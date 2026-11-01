"""Physical-worker simulation: real correspondence and SQLite, never hardware acceptance."""

import hashlib
import importlib
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from labos.central import create_app
from labos.config import AgentConfig
from labos.files import InstanceLock, json_bytes


def module():
    return importlib.import_module("labos.pilot_worker")


def configuration(tmp_path, **overrides):
    path = tmp_path / "pilot-connection.json"
    path.write_text(
        AgentConfig(
            agent_id="pc-a", token="A" * 40, server_url="http://localhost:8000", instruments=[]
        ).model_dump_json()
    )
    values = {
        "agent_id": "pc-a",
        "connection_config": path,
        "state_dir": tmp_path / "physical",
        **overrides,
    }
    return module().PilotWorkerConfig.model_validate(values)


def transport(api, *, drop_reply=False):
    dropped = False

    def request(req):
        nonlocal dropped
        response = api.request(req.method, str(req.url), content=req.content, headers=req.headers)
        if (
            drop_reply
            and req.method == "POST"
            and req.url.path.endswith("/messages")
            and not dropped
        ):
            dropped = True
            raise httpx.ReadTimeout("reply response lost after storage")
        return httpx.Response(response.status_code, content=response.content, headers=response.headers)

    return httpx.MockTransport(request)


def test_disabled_doctor_authenticates_without_constructing_adapter(tmp_path, central_config):
    # Opening a local adapter from Doctor would turn this simulated factory into an error.
    def forbidden(_):
        raise AssertionError("Doctor must not construct or open an instrument")

    with TestClient(create_app(central_config)) as api:
        worker = module().PilotWorker(configuration(tmp_path), transport(api), forbidden)
        result = worker.doctor()
        assert result["authenticated_correspondence"] is True
        assert result["physical_enabled"] is False
        assert result["hardware_access"] is False
        assert worker.status()["hardware_access"] is False


def plan(**overrides):
    return {
        "sample_id": "CrSBr 1",
        "mode": "combined",
        "laser_current_a": 0.0218,
        "power_limit_w": 5e-7,
        "reference_hz": 137.0,
        "samples_per_phase": 1,
        "interval_s": 0.0,
        "settle_s": 0.0,
        "phase_timeout_s": 5.0,
        "max_run_s": 20.0,
        **overrides,
    }


def approval(**overrides):
    return {
        "enabled": True,
        "sample_id": "CrSBr 1",
        "laser_current_max_a": 0.0218,
        "power_limit_max_w": 5e-7,
        "reference_hz": 137.0,
        "max_phase_s": 5.0,
        "max_run_s": 20.0,
        **overrides,
    }


def task(task_id="pilot_1", **overrides):
    return {
        "protocol": "labos-agent-v1",
        "document_type": "labos_pilot_task",
        "task_id": task_id,
        "instruction": "Run the approved finite pilot.",
        "context": {},
        "executable": False,
        "pilot_plan": plan(),
        "experiment_scope": "optical_transport",
        **overrides,
    }


def send(api, message_id, body):
    response = api.post(
        "/api/agents/pc-a/messages",
        headers={"Authorization": "Bearer " + "O" * 40},
        json={"id": message_id, "kind": "note", "body": body},
    )
    assert response.status_code == 200, response.text
    return response.json()["message"]


def commission_profile(api, config):
    from labos.pilot_authority import config_fingerprint
    response = api.post('/api/pilot-authority/pc-a/commission',
                        headers={'Authorization': 'Bearer ' + 'O' * 40}, json={
        'config_sha256': config_fingerprint(config),
        'experiment_scope': config.adapter_config.get('experiment_scope', 'optical_transport'),
        'note': 'Offline test fixture: legacy workers retired; physical states reconciled.',
        'legacy_workers_retired': True, 'physical_states_reconciled': True})
    assert response.status_code == 200, response.text


def messages(api):
    return api.get(
        "/api/agents/pc-a/messages", headers={"Authorization": "Bearer " + "O" * 40}
    ).json()["messages"]


@pytest.mark.parametrize(
    "local_approval,requested_plan",
    [
        (None, plan()),
        (approval(enabled=False), plan()),
        (approval(), plan(laser_current_a=0.0227)),
        (approval(), plan(sample_id="another sample")),
        (approval(), plan(reference_hz=138)),
    ],
)
def test_disabled_or_unapproved_request_returns_without_adapter_creation(
    tmp_path, central_config, local_approval, requested_plan
):
    def forbidden(_):
        raise AssertionError("unapproved input reached the adapter factory")

    with TestClient(create_app(central_config)) as api:
        send(api, "pilot_task", task(pilot_plan=requested_plan))
        worker = module().PilotWorker(
            configuration(tmp_path, approval=local_approval), transport(api), forbidden
        )
        worker.tick()
        received = messages(api)
        assert len(received) == 2
        body = received[-1]["body"]
        assert body["answer"]["status"] == "needs_input"
        assert body["backend"] == "pilot"
        assert body["model_attempts"] == 0
        assert worker.status()["physical_blocked"] is False


@pytest.mark.parametrize(
    "body",
    [
        {
            "protocol": "labos-agent-v1",
            "document_type": "labos_auto_task",
            "task_id": "report",
            "instruction": "Open hardware",
        },
        task(pilot_plan={**plan(), "adapter_id": "foreign"}),
        task(adapter_id="foreign"),
        task(pilot_plan=plan(excitation_v_rms=0.01)),
    ],
)
def test_only_bounded_pilot_tasks_can_reach_deterministic_responder(tmp_path, central_config, body):
    # Neither generic report tasks nor peer-supplied executable/adapter fields are physical authority.
    def forbidden(_):
        raise AssertionError("non-pilot or invalid input reached the adapter factory")

    with TestClient(create_app(central_config)) as api:
        send(api, "not_physical", body)
        worker = module().PilotWorker(
            configuration(tmp_path, approval=approval()), transport(api), forbidden
        )
        worker.tick()
        assert len(messages(api)) == 1
        assert sum(worker.status()["counts"].values()) == 1


class SimulatedBench:
    """Explicit stateful voltage/power bench; this is not a hardware acceptance fixture."""

    def __init__(self, *, protection_ok=True):
        self.opened = False
        self.laser_enabled = False
        self.excitation_v_rms = 0.004
        self.protection_ok = protection_ok
        self.events = []

    def open(self):
        self.events.append("open")
        self.opened = True

    def preflight(self):
        return {
            "ready": True,
            "laser_enabled": False,
            "simulated": True,
            "identity": "SIMULATED CRYOSTAT",
        }

    def configure(self, phase, requested):
        assert self.opened
        self.events.append(phase)
        self.excitation_v_rms = requested.excitation_v_rms

    def laser_on(self, current_a):
        assert current_a <= 0.0218
        self.laser_enabled = True
        self.events.append("laser_on")

    def read_sample(self, phase):
        assert self.opened
        return {
            "channels": {"XX": {"x_v": 1e-6, "y_v": 2e-7}, "XY": {"x_v": 3e-7, "y_v": 4e-8}},
            "power_w": 4e-7 if self.laser_enabled else 0.0,
            "simulated": True,
        }

    def laser_off(self):
        self.laser_enabled = False
        self.events.append("laser_off")
        return {"laser_off_verified": True, "emission_off_readback": True,
                "zero_current_setpoint_verified": True}

    def protect_excitation(self):
        self.excitation_v_rms = 0.004
        self.events.append("minimum_excitation")
        return {"minimum_excitation_verified": self.protection_ok, "actual_v_rms": 0.004}

    def close(self):
        self.opened = False
        self.events.append("close")


def artifact(worker, body):
    details = body["pilot_result"]["artifact"]
    content = (worker.config.state_dir / details["path"]).read_bytes()
    assert hashlib.sha256(content).hexdigest() == details["sha256"]
    return json.loads(content)


def test_intent_precedes_factory_and_real_data_is_persisted_before_delivery(
    tmp_path, central_config
):
    import sqlite3

    bench = SimulatedBench()
    config = configuration(tmp_path, approval=approval())

    def commissioned_factory(settings):
        assert settings == {}
        with sqlite3.connect(config.state_dir / "physical.sqlite") as db:
            assert db.execute(
                "SELECT state FROM executions WHERE task_id='pilot_1'"
            ).fetchone() == ("intent",)
        return bench

    with TestClient(create_app(central_config)) as api:
        commission_profile(api, config)
        send(api, "pilot_task", task())
        worker = module().PilotWorker(config, transport(api), commissioned_factory)
        worker.tick()
        body = messages(api)[-1]["body"]
        assert body["document_type"] == "labos_auto_result"
        assert body["backend"] == "pilot"
        assert body["model_attempts"] == 0
        assert body["pilot_result"]["status"] == "COMPLETED"
        assert body["pilot_result"]["sample_count"] == 3
        saved = artifact(worker, body)
        assert saved["message_id"] == "pilot_task"
        report = saved["report"]
        assert report["samples"][0]["channels"]["XX"]["x_v"] == 1e-6
        assert [sample["phase"] for sample in report["samples"]] == [
            "dark_baseline",
            "illuminated",
            "dark_hall_2f",
        ]
        assert report["plan"]["excitation_v_rms"] == 0.004
        assert report["config_sha256"] == body["pilot_result"]["config_sha256"]
        assert report["protection_verified"] is True
        assert "verified laser OFF" in " ".join(body["answer"]["findings"])
        assert body["answer"]["questions"] == []
        assert bench.events.count("open") == 1
        assert not bench.laser_enabled
        assert bench.excitation_v_rms == 0.004
        assert worker.status()["counts"] == {"sent": 1}
        assert len(json_bytes(body["pilot_result"])) < 4096
        uploaded = api.get(
            "/api/pilot-artifacts/pc-a/pilot_task", headers={"Authorization": "Bearer " + "O" * 40}
        )
        assert uploaded.status_code == 200
        assert uploaded.json() == saved


def test_lost_reply_response_uses_finished_artifact_and_never_repeats_io(tmp_path, central_config):
    bench = SimulatedBench()
    config = configuration(tmp_path, approval=approval())
    with TestClient(create_app(central_config)) as api:
        commission_profile(api, config)
        send(api, "pilot_task", task())
        worker = module().PilotWorker(config, transport(api, drop_reply=True), lambda _: bench)
        worker.tick()
        original = messages(api)[-1]["body"]
        saved = artifact(worker, original)
        assert worker.status()["counts"] == {"ready": 1}

        def forbidden(_):
            raise AssertionError("delivery retry must not create another physical adapter")

        restarted = module().PilotWorker(config, transport(api), forbidden)
        with restarted.db() as db:
            db.execute("UPDATE inbox SET retry_at=0")
        restarted.tick()
        assert len(messages(api)) == 2
        assert artifact(restarted, messages(api)[-1]["body"]) == saved
        assert restarted.status()["counts"] == {"sent": 1}
        assert bench.events.count("open") == 1


def test_interrupted_intent_latches_unknown_across_distinct_task_ids(tmp_path, central_config):
    config = configuration(tmp_path, approval=approval())

    def process_dies_after_committed_intent(_):
        raise KeyboardInterrupt

    def forbidden(_):
        raise AssertionError("an unresolved physical outcome must never replay")

    with TestClient(create_app(central_config)) as api:
        commission_profile(api, config)
        send(api, "pilot_task", task())
        worker = module().PilotWorker(config, transport(api), process_dies_after_committed_intent)
        with pytest.raises(KeyboardInterrupt):
            worker.tick()
        with worker.physical_db() as db:
            original_config_hash = db.execute("SELECT config_sha256 FROM executions").fetchone()[0]
        send(api, "next_task", task("pilot_2"))
        # Editing a local profile does not reconcile the old physical outcome or rewrite its provenance.
        config.adapter_config = {"commissioning_note": "changed after interruption"}
        restarted = module().PilotWorker(config, transport(api), forbidden)
        assert restarted.status()["physical_blocked"] is True
        restarted.tick()
        restarted.tick()
        results = [
            m["body"] for m in messages(api) if m["body"]["document_type"] == "labos_auto_result"
        ]
        assert len(results) == 2
        assert all(r["answer"]["status"] == "needs_input" and "pilot_result" not in r for r in results)
        assert all(r["model_attempts"] == 0 for r in results)
        with restarted.physical_db() as db:
            assert db.execute("SELECT config_sha256 FROM executions").fetchone()[0] == original_config_hash
        assert restarted.status()["physical_blocked"] is True
        again = module().PilotWorker(config, transport(api), forbidden)
        assert again.status()["physical_blocked"] is True


def test_failed_physical_protection_preserves_partial_data_and_blocks_next_task(
    tmp_path, central_config
):
    bench = SimulatedBench(protection_ok=False)
    with TestClient(create_app(central_config)) as api:
        commission_profile(api, configuration(tmp_path, approval=approval()))
        send(api, "pilot_task", task())
        send(api, "next_task", task("pilot_2"))
        worker = module().PilotWorker(
            configuration(tmp_path, approval=approval()), transport(api), lambda _: bench
        )
        worker.tick()
        first = messages(api)[-1]["body"]
        assert first["pilot_result"]["status"] == "UNKNOWN"
        assert artifact(worker, first)["report"]["samples"]
        assert worker.status()["physical_blocked"] is True
        worker.tick()
        assert messages(api)[-1]["body"]["answer"]["status"] == "needs_input"
        assert "pilot_result" not in messages(api)[-1]["body"]
        assert bench.events.count("open") == 1


@pytest.mark.parametrize(
    "failure",
    ["unavailable", "lost_receipt", "wrong_receipt", "malformed_receipt", "nonobject_receipt"],
)
def test_artifact_delivery_failure_retains_finished_report_without_reply_or_rerun(
    tmp_path, central_config, failure
):
    bench = SimulatedBench()
    config = configuration(tmp_path, approval=approval())
    with TestClient(create_app(central_config)) as api:
        commission_profile(api, config)
        send(api, "pilot_task", task())

        def failed_upload(req):
            if req.method == "POST" and req.url.path.endswith("/pilot-artifacts"):
                if failure == "unavailable":
                    return httpx.Response(503, json={"detail": "temporarily unavailable"})
                response = api.request(
                    req.method, str(req.url), content=req.content, headers=req.headers
                )
                assert response.status_code == 200
                if failure == "lost_receipt":
                    raise httpx.ReadTimeout("artifact receipt lost after durable storage")
                if failure == "malformed_receipt":
                    return httpx.Response(200, content=b"invalid-json")
                if failure == "nonobject_receipt":
                    return httpx.Response(200, json=[])
                return httpx.Response(
                    200, json={"accepted": True, "sha256": "0" * 64, "message_id": "pilot_task"}
                )
            response = api.request(
                req.method, str(req.url), content=req.content, headers=req.headers
            )
            return httpx.Response(response.status_code, content=response.content, headers=response.headers)

        worker = module().PilotWorker(config, httpx.MockTransport(failed_upload), lambda _: bench)
        worker.tick()
        assert len(messages(api)) == 1
        assert worker.status()["counts"] == {"ready": 1}
        with worker.db() as db:
            cached = json.loads(db.execute("SELECT response FROM inbox").fetchone()[0])
        saved = artifact(worker, cached["body"])
        assert saved["report"]["status"] == "COMPLETED"

        def forbidden(_):
            raise AssertionError("artifact delivery must not run instruments again")

        restarted = module().PilotWorker(config, transport(api), forbidden)
        with restarted.db() as db:
            db.execute("UPDATE inbox SET retry_at=0")
        restarted.tick()
        assert len(messages(api)) == 2
        assert artifact(restarted, messages(api)[-1]["body"]) == saved
        assert bench.events.count("open") == 1


def test_finished_execution_survives_crash_before_correspondence_cache(tmp_path, central_config):
    bench = SimulatedBench()
    config = configuration(tmp_path, approval=approval())
    with TestClient(create_app(central_config)) as api:
        commission_profile(api, config)
        envelope = send(api, "pilot_task", task())
        worker = module().PilotWorker(config, transport(api), lambda _: bench)
        # Execution finishes durably before the outer correspondence ready transition.
        worker.respond(envelope, "")
        assert len(messages(api)) == 1

        def forbidden(_):
            raise AssertionError(
                "finished physical result must be recovered from the physical ledger"
            )

        restarted = module().PilotWorker(config, transport(api), forbidden)
        restarted.tick()
        assert messages(api)[-1]["body"]["pilot_result"]["status"] == "COMPLETED"
        assert bench.events.count("open") == 1


def test_reused_task_identity_is_rejected_and_next_new_task_still_runs(tmp_path, central_config):
    benches = []

    def factory(_):
        bench = SimulatedBench()
        benches.append(bench)
        return bench

    with TestClient(create_app(central_config)) as api:
        commission_profile(api, configuration(tmp_path, approval=approval()))
        send(api, "pilot_task", task())
        send(api, "reused_task", task(pilot_plan=plan(laser_current_a=0.02)))
        send(api, "new_task", task("pilot_2"))
        worker = module().PilotWorker(
            configuration(tmp_path, approval=approval()), transport(api), factory
        )
        worker.tick()
        worker.tick()
        worker.tick()
        assert worker.status()["counts"] == {"sent": 2, "rejected": 1}
        assert len(benches) == 2


def test_cli_stop_signals_engine_while_vendor_io_is_blocked(tmp_path, central_config, capsys):
    import threading

    entered = threading.Event()
    release = threading.Event()
    errors = []

    class BlockingSimulation(SimulatedBench):
        def read_sample(self, phase):
            entered.set()
            assert release.wait(3), "test did not release simulated I/O"
            return super().read_sample(phase)

    bench = BlockingSimulation()
    config = configuration(tmp_path, approval=approval())
    path = tmp_path / "pilot.json"
    path.write_text(config.model_dump_json())
    with TestClient(create_app(central_config)) as api:
        commission_profile(api, config)
        send(api, "pilot_task", task())
        worker = module().PilotWorker(config, transport(api), lambda _: bench)

        def run():
            try:
                worker.tick()
            except BaseException as exc:
                errors.append(exc)

        thread = threading.Thread(target=run)
        thread.start()
        try:
            assert entered.wait(2)
            assert module().main(["stop", "--config", str(path)]) == 0
            assert worker._cancel.wait(1)
            assert (
                thread.is_alive()
            )  # Cooperative cancellation cannot interrupt blocked vendor I/O.
            assert "emergency" in capsys.readouterr().out.lower()
        finally:
            release.set()
            thread.join(3)
        assert not errors
        assert not thread.is_alive()
        assert messages(api)[-1]["body"]["pilot_result"]["status"] == "CANCELLED"
        assert not bench.laser_enabled
        assert bench.excitation_v_rms == 0.004


def test_config_loading_keeps_local_paths_and_rejects_remote_executable_selection(tmp_path):
    path = tmp_path / "physical.yml"
    path.write_text("agent_id: pc-a\nconnection_config: pc.yml\nstate_dir: physical\n")
    config = module().load_pilot_worker_config(path)
    assert config.connection_config == tmp_path / "pc.yml"
    assert config.state_dir == tmp_path / "physical"
    assert config.approval is None
    for field, value in [
        ("adapter_id", "peer.python:main"),
        ("backend", "codex"),
        ("role", "central"),
        ("codex_command", ["sh", "-c", "echo unexpected"]),
    ]:
        with pytest.raises(ValueError):
            module().PilotWorkerConfig.model_validate({**config.model_dump(), field: value})


def test_physical_worker_refuses_report_worker_state_without_changing_its_cursor(
    tmp_path, central_config
):
    from labos.cooperation_worker import Worker, WorkerConfig

    config = configuration(tmp_path, approval=approval())
    with TestClient(create_app(central_config)) as api:
        send(api, "ordinary_report_message", {"content": "Report-worker correspondence"})
        report_config = WorkerConfig(
            role="pc",
            agent_id="pc-a",
            connection_config=config.connection_config,
            state_dir=config.state_dir,
        )
        report_worker = Worker(report_config, transport(api), responder=object())
        report_worker.tick()
        before = report_worker.status()
        with pytest.raises(ValueError, match="separate"):
            module().PilotWorker(config, transport(api), lambda _: SimulatedBench())
        assert report_worker.status()["cursor"] == before["cursor"]
        assert report_worker.status()["counts"] == before["counts"]


def test_adapter_construction_failure_becomes_unknown_and_blocks_other_task_ids(
    tmp_path, central_config
):
    def fails(_):
        raise RuntimeError("partial driver initialization might have occurred")

    with TestClient(create_app(central_config)) as api:
        commission_profile(api, configuration(tmp_path, approval=approval()))
        send(api, "pilot_task", task())
        worker = module().PilotWorker(
            configuration(tmp_path, approval=approval()), transport(api), fails
        )
        worker.tick()
        body = messages(api)[-1]["body"]
        assert body["pilot_result"]["status"] == "UNKNOWN"
        assert body["model_attempts"] == 0
        assert worker.status()["physical_blocked"] is True


@pytest.mark.parametrize("enable", [True, False])
def test_doctor_validates_default_profile_without_constructing_adapter(
    tmp_path, central_config, monkeypatch, enable
):
    import sys
    import types

    fake = types.ModuleType("labos.cryostat_pilot")

    def forbidden(_):
        raise AssertionError("Doctor imported or constructed the default instrument adapter")

    fake.create_adapter = forbidden
    fake.validate_adapter_config = lambda settings: settings
    monkeypatch.setitem(sys.modules, "labos.cryostat_pilot", fake)
    with TestClient(create_app(central_config)) as api:
        worker = module().PilotWorker(
            configuration(tmp_path, approval=approval(enabled=enable)), transport(api)
        )
        assert worker.doctor()["physical_enabled"] is False
        assert worker.doctor()["configured_approval_enabled"] is enable
        assert worker.doctor()["profile_ready"] is enable
        checks = worker.doctor()
        assert checks["instrument_access_performed"] is False
        assert checks["hardware_access"] == ("possible_when_commissioned" if enable else False)


def test_missing_commissioning_fails_before_intent_or_default_factory(
    tmp_path, central_config, monkeypatch
):
    import sys
    import types

    fake = types.ModuleType("labos.cryostat_pilot")

    def invalid_profile(settings):
        raise ValueError("local commissioning facts are missing")

    def forbidden(_):
        raise AssertionError("an uncommissioned profile reached adapter construction")

    fake.validate_adapter_config = invalid_profile
    fake.create_adapter = forbidden
    monkeypatch.setitem(sys.modules, "labos.cryostat_pilot", fake)
    with TestClient(create_app(central_config)) as api:
        send(api, "pilot_task", task())
        worker = module().PilotWorker(configuration(tmp_path, approval=approval()), transport(api))
        worker.tick()
        body = messages(api)[-1]["body"]
        assert body["answer"]["status"] == "needs_input"
        with worker.physical_db() as db:
            assert db.execute("SELECT COUNT(*) FROM executions").fetchone()[0] == 0
        assert worker.status()["physical_blocked"] is False
        with pytest.raises(ValueError, match="commissioning"):
            worker.doctor()


def test_credential_bearing_driver_error_stays_local_without_model_fallback(
    tmp_path, central_config
):
    class PrivateErrorSimulation(SimulatedBench):
        def configure(self, phase, requested):
            raise RuntimeError("driver diagnostic with " + "A" * 40)

    bench = PrivateErrorSimulation()
    with TestClient(create_app(central_config)) as api:
        commission_profile(api, configuration(tmp_path, approval=approval()))
        send(api, "pilot_task", task())
        worker = module().PilotWorker(
            configuration(tmp_path, approval=approval()), transport(api), lambda _: bench
        )
        worker.tick()
        assert worker.status()["counts"] == {"ready": 1}
        assert len(messages(api)) == 1  # Private raw data cannot be uploaded.
        with worker.db() as db:
            cached = json.loads(db.execute("SELECT response FROM inbox").fetchone()[0])
        assert cached["body"]["backend"] == "pilot"
        assert cached["body"]["model_attempts"] == 0
        assert "A" * 40 not in json.dumps(cached)
        assert "A" * 40 in json.dumps(artifact(worker, cached["body"]))
        assert bench.events.count("open") == 1


def test_cli_doctor_cannot_reclassify_active_worker_intent_as_unknown(tmp_path, central_config):
    config = configuration(tmp_path, approval=approval())
    path = tmp_path / "pilot.json"
    path.write_text(config.model_dump_json())
    with TestClient(create_app(central_config)) as api:
        worker = module().PilotWorker(config, transport(api), lambda _: SimulatedBench())
        with worker.physical_db() as db:
            db.execute(
                "INSERT INTO executions VALUES(?,?,?,?, 'intent',NULL)",
                ("active_task", "active_message", "0" * 64, "1" * 64),
            )
        with InstanceLock(config.state_dir):
            assert module().main(["doctor", "--config", str(path)]) == 1
        assert worker.status()["physical_blocked"] is False


def test_central_review_loads_uploaded_raw_data_and_stops_the_reply_cycle(tmp_path, central_config):
    from labos.cooperation_worker import Worker, WorkerConfig

    central_path = tmp_path / "central.json"
    central_path.write_text(central_config.model_dump_json())
    reviewed = []

    class Reviewer:
        def respond(self, message, context):
            evidence = message["stored_pilot_evidence"]
            reviewed.append(evidence)
            assert evidence["central_raw_artifact_verified"] is True
            assert evidence["preflight"]["simulated"] is True
            assert evidence["protection_verified"] is True
            assert evidence["phase_statistics"]["illuminated"]["power_w"]["mean"] == 4e-7
            assert (
                evidence["phase_statistics"]["dark_hall_2f"]["channels"]["XY"]["x_v"]["mean"]
                == 3e-7
            )
            assert evidence["cleanup"]
            return {
                "backend": "test",
                "answer": {
                    "status": "completed",
                    "summary": "Simulation raw data verified; no physics attribution.",
                    "findings": [],
                    "questions": [],
                },
            }

    with TestClient(create_app(central_config)) as api:
        commission_profile(api, configuration(tmp_path, approval=approval()))
        send(api, "pilot_task", task())
        pc = module().PilotWorker(
            configuration(tmp_path, approval=approval()), transport(api), lambda _: SimulatedBench()
        )
        central = Worker(
            WorkerConfig(
                role="central",
                agent_id="pc-a",
                connection_config=central_path,
                state_dir=tmp_path / "review",
            ),
            transport(api),
            Reviewer(),
        )
        pc.tick()
        central.tick()
        result = messages(api)
        assert len(result) == 3
        assert result[-1]["body"]["document_type"] == "labos_auto_review"
        assert result[-1]["body"]["answer"]["status"] == "completed"
        pc.tick()
        central.tick()
        assert len(messages(api)) == 3 and len(reviewed) == 1


@pytest.mark.parametrize('failure', ['preflight', 'cleanup'])
def test_unverified_protection_is_never_reported_as_verified(tmp_path, central_config, failure):
    class FailingBench(SimulatedBench):
        def preflight(self):
            if failure == 'preflight':
                raise UnicodeDecodeError('ascii', b'ab\xf2', 2, 3, 'ordinal not in range(128)')
            return super().preflight()
    bench = FailingBench(protection_ok=failure != 'cleanup')
    with TestClient(create_app(central_config)) as api:
        commission_profile(api, configuration(tmp_path, approval=approval()))
        send(api, 'pilot_task', task())
        worker = module().PilotWorker(configuration(tmp_path, approval=approval()),
                                      transport(api), lambda _: bench)
        worker.tick()
        result = messages(api)[-1]['body']
        saved = artifact(worker, result)['report']
        assert saved['protection_verified'] is False
        assert 'not independently verified' in ' '.join(result['answer']['findings'])
        assert result['answer']['questions']
        if failure == 'preflight':
            assert saved['cleanup'] == []
            assert '0xf2' in saved['error']
            assert bench.events == ['open', 'close']
        else:
            assert saved['status'] == 'UNKNOWN'
            assert worker.status()['physical_blocked']


def test_failed_acquisition_with_verified_cleanup_reports_protection_truthfully(tmp_path, central_config):
    class FailedReading(SimulatedBench):
        def read_sample(self, phase):
            raise ValueError('invalid reading')
    bench = FailedReading()
    with TestClient(create_app(central_config)) as api:
        commission_profile(api, configuration(tmp_path, approval=approval()))
        send(api, 'pilot_task', task())
        worker = module().PilotWorker(configuration(tmp_path, approval=approval()),
                                      transport(api), lambda _: bench)
        worker.tick()
        result = messages(api)[-1]['body']
        saved = artifact(worker, result)['report']
        assert saved['status'] == 'FAILED' and saved['protection_verified'] is True
        assert 'not independently verified' not in ' '.join(result['answer']['findings'])
        assert 'verified' in ' '.join(result['answer']['findings'])
        assert result['answer']['questions'] == []
        assert bench.events.count('laser_off') == 2
        assert bench.events.count('minimum_excitation') == 2


def test_readiness_and_terminal_snapshots_are_not_running(tmp_path):
    worker = module().PilotWorker(configuration(tmp_path, approval=approval()),
                                  adapter_factory=lambda _: SimulatedBench())
    try:
        status = worker.status()
        assert status['configured_approval_enabled'] is True
        assert status['profile_validated'] is True
        assert status['phase'] == 'ready'
        assert status['physical_enabled'] is False
        for phase in ('started', 'stopping', 'stopped', 'failed'):
            snapshot = worker.write_status(phase)
            assert snapshot['physical_enabled'] is False
            assert snapshot['authority_ready'] is False
            assert snapshot['snapshot_only'] is True
            assert snapshot['instrument_output_state'] == 'unknown'
            assert snapshot['updated_at_utc'].endswith('Z')
        assert len(status['instance_id']) == 32
        assert status['config_sha256'] == hashlib.sha256(json_bytes(worker.config.model_dump(mode='json'))).hexdigest()
    finally:
        worker.client.close()


@pytest.mark.parametrize('launch_id', ['abc', 'A' * 32, 'g' * 32, '0' * 33, ''])
def test_launch_id_rejects_invalid_handshake_before_state_creation(tmp_path, monkeypatch, launch_id):
    config = configuration(tmp_path)
    monkeypatch.setenv('LABOS_PILOT_LAUNCH_ID', launch_id)
    with pytest.raises(ValueError, match='launch'):
        module().PilotWorker(config)
    assert not config.state_dir.exists()


def test_launch_and_instance_identity_in_status_and_events(tmp_path, monkeypatch):
    monkeypatch.setenv('LABOS_PILOT_LAUNCH_ID', 'a' * 32)
    config = configuration(tmp_path)
    worker = module().PilotWorker(config)
    try:
        status = worker.write_status('started')
        worker.write_status('stopped')
        records = [json.loads(line) for line in (config.state_dir / 'events.jsonl').read_text().splitlines()]
        assert status['launch_id'] == 'a' * 32
        assert all(record['instance_id'] == status['instance_id'] for record in records)
        assert all(record['config_sha256'] == status['config_sha256'] for record in records)
        assert all(record['launch_id'] == status['launch_id'] for record in records)
    finally:
        worker.client.close()


def test_cached_status_is_read_only_and_does_not_claim_pid_liveness(tmp_path, monkeypatch, capsys):
    config = configuration(tmp_path)
    config.state_dir.mkdir()
    snapshot = {'phase': 'listening', 'physical_enabled': True, 'pid': 1234}
    path = config.state_dir / 'status.json'
    path.write_text(json.dumps(snapshot))
    config_path = tmp_path / 'pilot.json'
    config_path.write_text(config.model_dump_json())
    def forbidden(*args, **kwargs):
        raise AssertionError('cached status must not instantiate a worker')
    monkeypatch.setattr(module(), 'PilotWorker', forbidden)
    assert module().main(['status', '--config', str(config_path)]) == 0
    status = json.loads(capsys.readouterr().out)
    assert status['snapshot_only'] is True
    assert status['process_liveness'] == 'unknown'
    assert status['readiness_uncertain'] is True
    assert status['physical_enabled'] is False
    assert status['instrument_output_state'] == 'unknown'
    assert json.loads(path.read_text()) == snapshot
    assert not (config.state_dir / 'physical.sqlite').exists()
    assert not (config.state_dir / 'instance.lock').exists()


@pytest.mark.parametrize('failure,code,phase', [(None, 0, 'stopped'), (RuntimeError('A' * 40), 1, 'failed'),
                                             (KeyboardInterrupt(), 130, 'stopped')])
def test_owned_cli_terminal_snapshot_and_close_before_lock_release(tmp_path, central_config, monkeypatch, failure, code, phase):
    config = configuration(tmp_path, approval=approval())
    path = tmp_path / 'pilot.json'
    path.write_text(config.model_dump_json())
    with TestClient(create_app(central_config)) as api:
        worker = module().PilotWorker(config, transport(api), lambda _: SimulatedBench())
        monkeypatch.setattr(module(), 'PilotWorker', lambda _: worker)
        original = worker.write_status
        terminal_lock_checks = []
        def write_status(value):
            if value in {'stopped', 'failed'}:
                with pytest.raises(RuntimeError, match='another LabOS process'):
                    with InstanceLock(config.state_dir):
                        pass
                terminal_lock_checks.append(value)
            return original(value)
        monkeypatch.setattr(worker, 'write_status', write_status)
        def tick():
            if failure is not None:
                raise failure
            worker.request_stop()
        monkeypatch.setattr(worker, 'tick', tick)
        assert module().main(['run', '--config', str(path)]) == code
        status = json.loads((config.state_dir / 'status.json').read_text())
        assert status['phase'] == phase
        assert status['physical_enabled'] is False
        assert status['exit_status'] == code
        assert status['failure_class'] == (type(failure).__name__ if failure else None)
        assert terminal_lock_checks == [phase]
        assert worker.client.is_closed
        records = [json.loads(line) for line in (config.state_dir / 'events.jsonl').read_text().splitlines()]
        assert records[0]['event'] == 'begin'
        assert records[-1]['event'] == 'end'
        assert 'A' * 40 not in json.dumps(records)


def test_journal_observes_stages_failure_and_end_without_sensitive_exception(tmp_path, central_config):
    class BrokenBench(SimulatedBench):
        def read_sample(self, phase):
            raise RuntimeError('secret=' + 'A' * 40)
    bench = BrokenBench()
    with TestClient(create_app(central_config)) as api:
        commission_profile(api, configuration(tmp_path, approval=approval()))
        worker = module().PilotWorker(configuration(tmp_path, approval=approval()), transport(api), lambda _: bench)
        send(api, 'journal_failure', task())
        worker.tick()
        records = [json.loads(line) for line in (worker.config.state_dir / 'events.jsonl').read_text().splitlines()]
        assert records[0]['event'] == 'begin'
        assert records[-1]['event'] == 'end'
        assert any(row['event'] == 'progress' and row['outcome'] == 'started' for row in records)
        assert any(row['event'] == 'failure' and row['failure_class'] == 'RuntimeError' for row in records)
        assert 'A' * 40 not in json.dumps(records)
        assert bench.events[-3:] == ['laser_off', 'minimum_excitation', 'close']


@pytest.mark.parametrize('error', [OSError('disk full'), KeyboardInterrupt()])
def test_journal_failure_during_owned_io_does_not_skip_protection_or_close(tmp_path, central_config, monkeypatch, error):
    events = importlib.import_module('labos.pilot_events')
    bench = SimulatedBench()
    with TestClient(create_app(central_config)) as api:
        commission_profile(api, configuration(tmp_path, approval=approval()))
        worker = module().PilotWorker(configuration(tmp_path, approval=approval()), transport(api), lambda _: bench)
        def broken(*args, **kwargs):
            raise error
        monkeypatch.setattr(events.EventJournal, 'append', broken)
        send(api, 'journal_full', task())
        worker.tick()
        assert bench.events[-3:] == ['laser_off', 'minimum_excitation', 'close']
        assert messages(api)[-1]['body']['pilot_result']['status'] == 'COMPLETED'
        assert worker.status()['journal_failures'] > 0


def test_event_journal_rotation_is_bounded_and_private(tmp_path):
    import os
    import stat
    events = importlib.import_module('labos.pilot_events')
    journal = events.EventJournal(tmp_path)
    for index in range(5000):
        journal.append({'event': 'progress', 'sequence': index, 'padding': 'x' * 500})
    active = tmp_path / 'events.jsonl'
    rotated = tmp_path / 'events.jsonl.1'
    assert rotated.exists()
    assert active.stat().st_size <= 1024 * 1024
    assert rotated.stat().st_size <= 1024 * 1024
    assert len(list(tmp_path.iterdir())) == 2
    for path in (active, rotated):
        assert all(isinstance(json.loads(line), dict) for line in path.read_text().splitlines())
        if os.name != 'nt':
            assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_pending_stop_and_active_intent_remain_visible(tmp_path):
    worker = module().PilotWorker(configuration(tmp_path, approval=approval()),
                                  adapter_factory=lambda _: SimulatedBench())
    try:
        with worker.physical_db() as db:
            db.execute("INSERT INTO executions VALUES(?,?,?,?, 'intent',NULL)",
                       ('active_task', 'active_message', '0' * 64, '1' * 64))
        worker.write_status('started')
        worker.request_stop()
        status = worker.status()
        assert status['phase'] == 'stopping'
        assert status['active_intent'] is True
        assert status['physical_enabled'] is False
        worker.write_status('failed')
        with worker.physical_db() as db:
            assert db.execute("SELECT state FROM executions").fetchone()[0] == 'intent'
        restarted = module().PilotWorker(worker.config, adapter_factory=lambda _: SimulatedBench())
        try:
            assert restarted.status()['physical_blocked'] is True
        finally:
            restarted.client.close()
    finally:
        worker.client.close()


def test_late_observer_cannot_overwrite_terminal_snapshot(tmp_path):
    worker = module().PilotWorker(configuration(tmp_path))
    try:
        worker.write_status('stopped')
        path = worker.config.state_dir / 'status.json'
        terminal = path.read_bytes()
        worker._observe_engine({'stage': 'close', 'phase': None, 'started_elapsed_s': 0,
                                'duration_s': 0, 'outcome': 'completed'})
        worker.request_stop()
        assert path.read_bytes() == terminal
    finally:
        worker.client.close()


def test_cli_once_finishes_with_stopped_snapshot(tmp_path, central_config, monkeypatch):
    config = configuration(tmp_path)
    path = tmp_path / 'pilot.json'
    path.write_text(config.model_dump_json())
    with TestClient(create_app(central_config)) as api:
        worker = module().PilotWorker(config, transport(api))
        monkeypatch.setattr(module(), 'PilotWorker', lambda _: worker)
        assert module().main(['once', '--config', str(path)]) == 0
        status = json.loads((config.state_dir / 'status.json').read_text())
        assert status['phase'] == 'stopped'
        assert status['exit_status'] == 0
        assert status['physical_enabled'] is False
        assert worker.client.is_closed


def test_terminal_snapshot_waits_for_inflight_stop_snapshot(tmp_path, monkeypatch):
    import threading
    worker = module().PilotWorker(configuration(tmp_path))
    entered = threading.Event()
    release = threading.Event()
    terminal_done = threading.Event()
    errors = []
    original = module().atomic_write
    def delayed(path, content):
        if path.name == 'status.json' and json.loads(content)['phase'] == 'stopping':
            entered.set()
            assert release.wait(3)
        return original(path, content)
    monkeypatch.setattr(module(), 'atomic_write', delayed)
    def write(phase):
        try:
            worker.write_status(phase)
        except BaseException as exc:
            errors.append(exc)
        finally:
            if phase == 'stopped':
                terminal_done.set()
    stop_thread = threading.Thread(target=write, args=('stopping',))
    terminal_thread = threading.Thread(target=write, args=('stopped',))
    try:
        stop_thread.start()
        assert entered.wait(2)
        terminal_thread.start()
        assert not terminal_done.wait(0.1)
    finally:
        release.set()
        stop_thread.join(3)
        if terminal_thread.ident:
            terminal_thread.join(3)
        worker.client.close()
    assert not errors
    assert json.loads((worker.config.state_dir / 'status.json').read_text())['phase'] == 'stopped'


@pytest.mark.parametrize('failure', [RuntimeError('private failure'), KeyboardInterrupt()])
def test_owned_exit_preserves_unresolved_intent(tmp_path, central_config, monkeypatch, failure):
    config = configuration(tmp_path, approval=approval())
    path = tmp_path / 'pilot.json'
    path.write_text(config.model_dump_json())
    with TestClient(create_app(central_config)) as api:
        worker = module().PilotWorker(config, transport(api), lambda _: SimulatedBench())
        monkeypatch.setattr(module(), 'PilotWorker', lambda _: worker)
        def tick():
            with worker.physical_db() as db:
                db.execute("INSERT INTO executions VALUES(?,?,?,?, 'intent',NULL)",
                           ('active_task', 'active_message', '0' * 64, '1' * 64))
            raise failure
        monkeypatch.setattr(worker, 'tick', tick)
        assert module().main(['run', '--config', str(path)]) in {1, 130}
        status = json.loads((config.state_dir / 'status.json').read_text())
        assert status['active_intent'] is True
        assert status['physical_enabled'] is False
        with worker.physical_db() as db:
            assert db.execute("SELECT state FROM executions").fetchone()[0] == 'intent'
        restarted = type(worker)(config, transport(api), lambda _: SimulatedBench())
        try:
            assert restarted.status()['physical_blocked'] is True
        finally:
            restarted.client.close()


@pytest.mark.parametrize('error', [OSError('status disk full'), KeyboardInterrupt()])
def test_status_logging_failure_after_ownership_cannot_skip_cleanup_or_client_close(tmp_path, central_config, monkeypatch, error):
    config = configuration(tmp_path, approval=approval())
    path = tmp_path / 'pilot.json'
    path.write_text(config.model_dump_json())
    original = module().atomic_write
    class StatusFailureBench(SimulatedBench):
        def configure(self, phase, requested):
            super().configure(phase, requested)
            def fail_status(destination, content):
                if destination.name == 'status.json':
                    raise error
                return original(destination, content)
            monkeypatch.setattr(module(), 'atomic_write', fail_status)
    bench = StatusFailureBench()
    with TestClient(create_app(central_config)) as api:
        commission_profile(api, config)
        worker = module().PilotWorker(config, transport(api), lambda _: bench)
        monkeypatch.setattr(module(), 'PilotWorker', lambda _: worker)
        send(api, 'status_logging_failure', task())
        assert module().main(['once', '--config', str(path)]) == 0
        assert bench.events[-3:] == ['laser_off', 'minimum_excitation', 'close']
        assert messages(api)[-1]['body']['pilot_result']['status'] == 'COMPLETED'
        assert worker.client.is_closed
        assert worker.status()['status_failures'] > 0


@pytest.mark.parametrize(
    'primary,close_failure,code,phase,failure_class',
    [
        (None, RuntimeError('private close failure'), 1, 'failed', 'RuntimeError'),
        (None, KeyboardInterrupt(), 130, 'stopped', 'KeyboardInterrupt'),
        (ValueError('private primary failure'), RuntimeError('private close failure'), 1, 'failed', 'ValueError'),
        (ValueError('private primary failure'), KeyboardInterrupt(), 1, 'failed', 'ValueError'),
        (KeyboardInterrupt(), RuntimeError('private close failure'), 130, 'stopped', 'KeyboardInterrupt'),
        (KeyboardInterrupt(), KeyboardInterrupt(), 130, 'stopped', 'KeyboardInterrupt'),
    ],
)
def test_client_close_failure_is_in_terminal_outcome_and_preserves_primary(
    tmp_path, central_config, monkeypatch, capsys, primary, close_failure, code, phase, failure_class
):
    config = configuration(tmp_path)
    path = tmp_path / 'pilot.json'
    path.write_text(config.model_dump_json())
    with TestClient(create_app(central_config)) as api:
        worker = module().PilotWorker(config, transport(api))
        monkeypatch.setattr(module(), 'PilotWorker', lambda _: worker)
        original_close = worker.client.close
        close_owned = []
        def close():
            try:
                with InstanceLock(config.state_dir):
                    close_owned.append(False)
            except RuntimeError:
                close_owned.append(True)
            if len(close_owned) == 1:
                raise close_failure
            original_close()
        monkeypatch.setattr(worker.client, 'close', close)
        def tick():
            if primary is not None:
                raise primary
            return worker.status()
        monkeypatch.setattr(worker, 'tick', tick)
        try:
            assert module().main(['once', '--config', str(path)]) == code
            snapshot = json.loads((config.state_dir / 'status.json').read_text())
            assert snapshot['phase'] == phase
            assert snapshot['exit_status'] == code
            assert snapshot['failure_class'] == failure_class
            assert snapshot['physical_enabled'] is False
            assert close_owned == [True]
            records = [json.loads(line) for line in (config.state_dir / 'events.jsonl').read_text().splitlines()]
            assert records[-1]['event'] == 'end'
            assert records[-1]['exit_status'] == code
            assert records[-1]['failure_class'] == failure_class
            assert 'private' not in json.dumps(records)
            output = capsys.readouterr().out
            if code == 1:
                assert f'failed ({failure_class})' in output
            assert 'private' not in output
        finally:
            original_close()
