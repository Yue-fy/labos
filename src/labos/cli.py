from __future__ import annotations

import argparse
import asyncio
import json
import logging
import secrets
import ssl
import sys
from pathlib import Path

import httpx
import yaml

from .config import AgentConfig, CentralConfig, Enrollment, load_config
from .files import InstanceLock, atomic_write
from .models import InstrumentSpec, Plan


def save_private(path: Path, data: bytes):
    atomic_write(path, data)
    path.chmod(0o600)


def provision(directory: Path, server_url: str, allow_http=False, host="127.0.0.1", port=8000):
    directory = Path(directory).resolve()
    paths = {name: directory / name / "config.yaml" for name in ("central", "pc-a", "pc-b")}
    if any(p.exists() for p in paths.values()):
        raise FileExistsError("configuration already exists; refusing to overwrite credentials/data")
    devices = {"pc-a": [InstrumentSpec(id="superk_01", kind="laser")],
               "pc-b": [InstrumentSpec(id="rotator_01", kind="rotator"),
                        InstrumentSpec(id="spectrometer_01", kind="spectrometer")]}
    enrollments = {name: Enrollment(token=secrets.token_urlsafe(32), instruments=specs)
                   for name, specs in devices.items()}
    central = CentralConfig(admin_token=secrets.token_urlsafe(32), agents=enrollments,
                            data_dir=Path("data"), host=host, port=port)
    agent_configs = {
        name: AgentConfig(agent_id=name, token=enrollment.token, server_url=server_url,
                          allow_insecure_http=allow_http, instruments=enrollment.instruments,
                          data_dir=Path("data")) for name, enrollment in enrollments.items()}
    for name, config in {"central": central, **agent_configs}.items():
        save_private(paths[name], yaml.safe_dump(config.model_dump(mode="json"),
                                                allow_unicode=True, sort_keys=False).encode())
    save_private(directory / "central" / "operator.token", central.admin_token.encode() + b"\n")
    atomic_write(directory / "scan.json", json.dumps(Plan().model_dump(), indent=2).encode())
    return paths


def doctor(config: AgentConfig, transport=None):
    tls = ssl.create_default_context(cafile=str(config.ca_file)) if config.ca_file else True
    with httpx.Client(base_url=config.server_url, timeout=config.request_timeout_s, verify=tls,
                      transport=transport, trust_env=False, proxy=config.proxy_url) as client:
        health = client.get("/health")
        health.raise_for_status()
        if health.json().get("service") != "labos-central":
            raise ValueError("destination is not a LabOS central server")
        response = client.get(f"/api/agents/{config.agent_id}/health",
                              headers={"Authorization": f"Bearer {config.token}"})
        response.raise_for_status()
        return {"server_url": config.server_url, "agent_id": config.agent_id,
                "authenticated": True, "enrolled": response.json()["enrolled"],
                "transport": "HTTPS" if config.server_url.startswith("https:") else "explicit HTTP",
                "ssh_required": False}


def operator_client(config_path, server_url):
    config = load_config(config_path, CentralConfig)
    url = server_url or f"http://127.0.0.1:{config.port}"
    return httpx.Client(base_url=url, headers={"Authorization": f"Bearer {config.admin_token}"},
                        timeout=30, trust_env=False)


def configure_logging(directory):
    directory.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        handlers=[logging.StreamHandler(), logging.FileHandler(directory / "service.log", encoding="utf-8")])


def main(argv=None):
    parser = argparse.ArgumentParser(description="LabOS: outbound lab agents; SIMULATED release")
    sub = parser.add_subparsers(dest="command", required=True)
    init = sub.add_parser("init", help="generate separate central and PC configurations")
    init.add_argument("--directory", type=Path, default=Path("deployments/demo"))
    init.add_argument("--server-url", default="http://127.0.0.1:8000")
    init.add_argument("--allow-http", action="store_true")
    init.add_argument("--host", default="127.0.0.1")
    init.add_argument("--port", type=int, default=8000)
    for name in ("central", "agent", "doctor"):
        command = sub.add_parser(name)
        command.add_argument("--config", type=Path, default=Path("config.yaml"))
    for name in ("status", "prepare", "submit", "export", "control"):
        command = sub.add_parser(name)
        command.add_argument("--config", type=Path, required=True)
        command.add_argument("--server-url")
        if name in {"prepare", "submit"}:
            command.add_argument("--plan", type=Path, required=True)
        if name in {"export", "control"}:
            command.add_argument("--run-id", required=True)
        if name == "export":
            command.add_argument("--output", type=Path, required=True)
        if name == "control":
            command.add_argument("action", choices=["pause", "resume", "stop", "reconcile"])
    authority = sub.add_parser("pilot-authority", help="inspect or commission physical authority")
    actions = authority.add_subparsers(dest="authority_action", required=True)
    for name in ("status", "commission"):
        command = actions.add_parser(name)
        command.add_argument("--config", type=Path, required=True)
        command.add_argument("--server-url")
        command.add_argument("--agent-id", required=True)
        if name == "commission":
            selection = command.add_mutually_exclusive_group(required=True)
            selection.add_argument("--worker-config", type=Path)
            selection.add_argument("--config-sha256")
            command.add_argument("--experiment-scope", choices=["optical_transport", "optical_readback", "dark_a"])
            command.add_argument("--note", required=True)
            command.add_argument("--legacy-workers-retired", action="store_true", required=True)
            command.add_argument("--physical-states-reconciled", action="store_true", required=True)
    bundle = sub.add_parser("bundle", help="create one PC ZIP with only that PC's credential")
    bundle.add_argument("--config", type=Path, required=True)
    bundle.add_argument("--output", type=Path, required=True)
    bundle.add_argument("--windows-runtime", type=Path)
    demo = sub.add_parser("demo", help="run central and two agents as separate TCP processes")
    demo.add_argument("--directory", type=Path, default=Path("runtime/acceptance"))
    demo.add_argument("--full", action="store_true", help="run 399-point scan")
    from .cooperation import add_parser, run as cooperate
    add_parser(sub)
    args = parser.parse_args(argv)
    try:
        if args.command == "cooperate":
            return cooperate(args)
        elif args.command == "pilot-authority":
            from .pilot_authority import Commission, config_fingerprint
            from .pilot_worker import load_pilot_worker_config
            with operator_client(args.config, args.server_url) as client:
                path = f"/api/pilot-authority/{args.agent_id}"
                if args.authority_action == "status":
                    response = client.get(path)
                else:
                    digest, scope = args.config_sha256, args.experiment_scope
                    if args.worker_config:
                        selected = load_pilot_worker_config(args.worker_config)
                        if selected.agent_id != args.agent_id or not (selected.approval and selected.approval.enabled):
                            raise ValueError("Select an enabled worker configuration for this agent")
                        digest = config_fingerprint(selected)
                        configured_scope = selected.adapter_config.get("experiment_scope", "optical_transport")
                        if scope is not None and scope != configured_scope:
                            raise ValueError("Scope differs from selected worker configuration")
                        scope = configured_scope
                    body = Commission(config_sha256=digest, experiment_scope=scope, note=args.note,
                                      legacy_workers_retired=args.legacy_workers_retired,
                                      physical_states_reconciled=args.physical_states_reconciled)
                    response = client.post(path + "/commission", json=body.model_dump())
                response.raise_for_status()
                print(json.dumps(response.json(), indent=2))
        elif args.command == "init":
            paths = provision(args.directory, args.server_url, args.allow_http, args.host, args.port)
            print(json.dumps({name: str(path) for name, path in paths.items()}, indent=2))
            print("SIMULATED configurations generated. Operator token is in central/operator.token.")
        elif args.command == "central":
            from .central import create_app
            import uvicorn
            config = load_config(args.config, CentralConfig)
            configure_logging(config.data_dir / "logs")
            uvicorn.run(create_app(config), host=config.host, port=config.port, workers=1,
                        access_log=False)
        elif args.command == "agent":
            from .agent import Agent
            config = load_config(args.config, AgentConfig)
            configure_logging(config.data_dir / "logs")
            with InstanceLock(config.data_dir):
                asyncio.run(Agent(config).run())
        elif args.command == "doctor":
            print(json.dumps(doctor(load_config(args.config, AgentConfig)), indent=2))
        elif args.command == "bundle":
            from .delivery import build_agent_bundle
            print(build_agent_bundle(args.config, args.output, args.windows_runtime))
        elif args.command == "demo":
            from .demo import acceptance
            print(json.dumps(acceptance(args.directory, full=args.full), indent=2))
        else:
            with operator_client(args.config, args.server_url) as client:
                if args.command == "status":
                    response = client.get("/api/status")
                elif args.command in {"prepare", "submit"}:
                    plan = Plan.model_validate_json(args.plan.read_bytes())
                    response = client.post("/api/preflight" if args.command == "prepare" else "/api/runs",
                                           json=plan.model_dump())
                elif args.command == "control":
                    response = client.post(f"/api/runs/{args.run_id}/{args.action}")
                else:
                    response = client.get(f"/api/runs/{args.run_id}/export")
                    response.raise_for_status()
                    atomic_write(args.output, response.content)
                    print(args.output)
                    return 0
                response.raise_for_status()
                print(json.dumps(response.json(), indent=2, ensure_ascii=False))
    except KeyboardInterrupt:
        return 130
    except (ValueError, OSError, RuntimeError, httpx.HTTPError) as exc:
        # HTTP exception text may contain credential-bearing proxy URLs.
        message = f"network request failed ({type(exc).__name__}); see NETWORK_EN.md" if isinstance(exc, httpx.HTTPError) else str(exc)
        print(f"LabOS: {message}", file=sys.stderr)
        return 1
    return 0
