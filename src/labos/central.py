from __future__ import annotations

import hmac
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse

from . import __version__
from .config import CentralConfig
from .evidence import EvidenceDocument, EvidenceStore
from .files import InstanceLock, export_hdf5
from .models import Identifier, Model, Plan
from .runtime import Runtime
from .store import Store


class Session(Model):
    boot_id: Identifier


class Heartbeat(Session):
    instruments: dict[Identifier, dict]


class Result(Session):
    command_id: Identifier
    state: str
    result: dict


class DraftRequest(Model):
    prompt: str


def create_app(config: CentralConfig):
    store = Store(config.data_dir)
    for agent_id, enrollment in config.agents.items():
        store.enroll(agent_id, enrollment.instruments)
    runtime = Runtime(config, store)
    evidence = EvidenceStore(config.data_dir)

    @asynccontextmanager
    async def lifespan(app):
        with InstanceLock(config.data_dir):
            store.recover()
            yield
            await runtime.close()

    app = FastAPI(title="LabOS MVP", version=__version__, lifespan=lifespan,
                  docs_url=None, redoc_url=None, openapi_url=None)
    app.state.store, app.state.runtime = store, runtime

    def principal(authorization: str | None = Header(default=None)):
        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(401, "bearer credential required")
        token = authorization[7:]
        if hmac.compare_digest(token, config.admin_token):
            return ("operator", None)
        for agent_id, enrollment in config.agents.items():
            if hmac.compare_digest(token, enrollment.token):
                return ("agent", agent_id)
        raise HTTPException(401, "invalid credential")

    def operator(identity=Depends(principal)):
        if identity != ("operator", None):
            raise HTTPException(403, "operator credential required")

    def agent(agent_id: str, identity=Depends(principal)):
        if agent_id not in config.agents or identity != ("agent", agent_id):
            raise HTTPException(403, "agent credential does not match this PC")

    def checked(function, *args, **kwargs):
        try:
            return function(*args, **kwargs)
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc

    @app.middleware("http")
    async def security_headers(request, call_next):
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Frame-Options"] = "DENY"
        return response

    @app.get("/health")
    def health():
        return {"status": "ok", "service": "labos-central", "version": __version__}

    @app.get("/", response_class=HTMLResponse)
    def dashboard():
        path = Path(__file__).parent / "static" / "index.html"
        return path.read_text(encoding="utf-8") if path.exists() else "LabOS dashboard being installed"

    @app.get("/api/status", dependencies=[Depends(operator)])
    def status():
        return {**store.registry(config.offline_after_s), "runs": store.runs(),
                "quality": {r["id"]: store.measurement_summary(r["id"]) for r in store.runs()},
                "setups": [s.model_dump() for s in config.setups], "simulated": True}

    @app.post("/api/preflight", dependencies=[Depends(operator)])
    def preflight(plan: Plan):
        return checked(runtime.preflight, plan)

    @app.post("/api/plan", dependencies=[Depends(operator)])
    async def ai_plan(body: DraftRequest):
        from .planner import draft_plan
        if not body.prompt.strip() or len(body.prompt) > 8000:
            raise HTTPException(422, "prompt must contain 1–8000 characters")
        try:
            references = evidence.search(body.prompt[:500])
            store.event("EVIDENCE_RETRIEVED", {"purpose": "draft_plan", "citations": [
                {k: d[k] for k in ("id", "sha256", "source", "version")} for d in references]})
            return await draft_plan(body.prompt, config, evidence=references)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        except Exception as exc:
            raise HTTPException(502, "AI provider request failed; no experiment was started") from exc

    @app.post("/api/evidence", dependencies=[Depends(operator)])
    def add_evidence(document: EvidenceDocument):
        return checked(evidence.add, document)

    @app.get("/api/evidence", dependencies=[Depends(operator)])
    def search_evidence(q: str = Query(default="", max_length=500), reviewed_only: bool = True):
        return checked(evidence.search, q, reviewed_only=reviewed_only)

    @app.post("/api/runs", dependencies=[Depends(operator)])
    async def start(plan: Plan):
        return checked(runtime.start, plan)

    @app.get("/api/runs/{run_id}", dependencies=[Depends(operator)])
    def run(run_id: str):
        return checked(store.run, run_id)

    @app.post("/api/runs/{run_id}/review", dependencies=[Depends(operator)])
    def create_review(run_id: str):
        return checked(runtime.review, run_id)

    @app.get("/api/runs/{run_id}/review", dependencies=[Depends(operator)])
    def latest_review(run_id: str):
        checked(store.run, run_id)
        return store.latest_review(run_id)

    @app.get("/api/runs/{run_id}/reviews", dependencies=[Depends(operator)])
    def review_history(run_id: str):
        checked(store.run, run_id)
        return store.reviews(run_id)

    @app.post("/api/runs/{run_id}/{action}", dependencies=[Depends(operator)])
    async def control(run_id: str, action: str):
        checked(runtime.control, run_id, action)
        return checked(store.run, run_id)

    @app.get("/api/runs/{run_id}/measurements", dependencies=[Depends(operator)])
    def measurements(run_id: str, qualified_only: bool = False):
        checked(store.run, run_id)
        return store.measurements(run_id, qualified_only=qualified_only)

    @app.get("/api/runs/{run_id}/export", dependencies=[Depends(operator)])
    def export(run_id: str):
        path = checked(export_hdf5, store, run_id)
        return FileResponse(path, filename=path.name, media_type="application/x-hdf5")

    @app.get("/api/events", dependencies=[Depends(operator)])
    def events(run_id: str | None = None):
        return store.events(run_id)

    @app.post("/api/agents/{agent_id}/register", dependencies=[Depends(agent)])
    def register(agent_id: str, session: Session):
        checked(store.register, agent_id, session.boot_id, offline_after=config.offline_after_s)
        return {"registered": True, "simulated": True}

    @app.get("/api/agents/{agent_id}/health", dependencies=[Depends(agent)])
    def agent_health(agent_id: str):
        return {"agent_id": agent_id, "enrolled": True,
                "instrument_ids": [d.id for d in config.agents[agent_id].instruments]}

    @app.post("/api/agents/{agent_id}/heartbeat", dependencies=[Depends(agent)])
    def heartbeat(agent_id: str, body: Heartbeat):
        checked(store.heartbeat, agent_id, body.boot_id, body.instruments)
        return {"cancel_runs": store.cancelled_runs(agent_id)}

    @app.post("/api/agents/{agent_id}/poll", dependencies=[Depends(agent)])
    def poll(agent_id: str, session: Session):
        command = checked(store.claim, agent_id, session.boot_id)
        if command:
            command["remaining_s"] = max(0, command["created"] + config.command_timeout_s - time.time())
        return {"command": command}

    @app.post("/api/agents/{agent_id}/results", dependencies=[Depends(agent)])
    def results(agent_id: str, result: Result):
        checked(store.complete_command, agent_id, result.boot_id, result.command_id,
                result.state, result.result)
        return {"accepted": True}

    @app.post("/api/agents/{agent_id}/artifacts", dependencies=[Depends(agent)])
    async def artifacts(agent_id: str, request: Request,
                        x_sha256: str = Header(), x_boot_id: str = Header()):
        # Fence uploads without refreshing stale device status.
        with store.transaction() as db:
            checked(store.session, db, agent_id, x_boot_id)
        content = bytearray()
        async for chunk in request.stream():
            content.extend(chunk)
            if len(content) > 2_000_000:
                raise HTTPException(413, "artifact too large")
        try:
            measurement_id = store.accept_artifact(agent_id, bytes(content), x_sha256)
        except (ValueError, KeyError) as exc:
            raise HTTPException(400, str(exc)) from exc
        return {"accepted": True, "measurement_id": measurement_id}

    @app.post("/api/agents/{agent_id}/disconnect", dependencies=[Depends(agent)])
    def disconnect(agent_id: str, session: Session):
        checked(store.disconnect, agent_id, session.boot_id)
        return {"disconnected": True}

    return app
