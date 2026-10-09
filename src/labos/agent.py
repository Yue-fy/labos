from __future__ import annotations

import asyncio
import hashlib
import logging
import random
import ssl
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import httpx

from .config import AgentConfig
from .drivers import SimulatedInstrument
from .files import Measurement, atomic_write, json_bytes
from .journal import Journal

logger = logging.getLogger(__name__)


class Agent:
    def __init__(self, config: AgentConfig, transport=None):
        self.config = config
        self.boot_id = "boot_" + uuid.uuid4().hex
        self.devices = {spec.id: SimulatedInstrument(spec) for spec in config.instruments}
        self.journal = Journal(config.data_dir)
        self.cancel = asyncio.Event()
        self.shutdown = asyncio.Event()
        self.cancelled_runs: set[str] = set()
        self.current_run = None
        self.last_contact = time.monotonic()
        self.registered = False
        self.watchdog_tripped = bool(self.journal.device_faults())
        tls = ssl.create_default_context(cafile=str(config.ca_file)) if config.ca_file else True
        self.client = httpx.AsyncClient(base_url=config.server_url, timeout=config.request_timeout_s,
                                       headers={"Authorization": f"Bearer {config.token}"},
                                       verify=tls, transport=transport, trust_env=False,
                                       proxy=config.proxy_url, follow_redirects=False)
        # Recover a durable capture if the process died before recording its upload entry.
        for path in (config.data_dir / "cache").glob("*.json"):
            content = path.read_bytes()
            measurement = Measurement.model_validate_json(content)
            self.journal.add_artifact(measurement.command_id, path,
                                      hashlib.sha256(content).hexdigest())

    def statuses(self):
        faults = self.journal.device_faults()
        return {instrument_id: {**driver.status(), "fault_latched": instrument_id in faults,
                                "fault_reason": faults.get(instrument_id)}
                for instrument_id, driver in self.devices.items()}

    async def request(self, endpoint, **kwargs):
        response = await self.client.post(f"/api/agents/{self.config.agent_id}/{endpoint}", **kwargs)
        if response.status_code == 409 and response.json().get("detail") == "invalid agent session":
            self.registered = False
        response.raise_for_status()
        self.last_contact = time.monotonic()
        return response.json()

    async def register(self):
        await self.request("register", json={"boot_id": self.boot_id})
        self.registered = True
        await self.heartbeat()

    async def heartbeat(self):
        response = await self.request("heartbeat", json={"boot_id": self.boot_id,
                                                       "instruments": self.statuses()})
        self.cancelled_runs.update(response["cancel_runs"])
        if self.current_run in self.cancelled_runs:
            self.cancel.set()

    async def watchdog_once(self):
        if time.monotonic() - self.last_contact > self.config.watchdog_s:
            self.cancel.set()
            self.journal.latch_watchdog()
            for device in self.devices.values():
                await device.safe_shutdown()
            if not self.watchdog_tripped:
                logger.warning("watchdog entered local safe state; waiting for central connection")
            self.watchdog_tripped = True

    async def background(self):
        next_heartbeat = 0.0
        while not self.shutdown.is_set():
            if self.registered and time.monotonic() >= next_heartbeat:
                try:
                    await self.heartbeat()
                except (httpx.HTTPError, ValueError):
                    logger.warning("heartbeat unavailable; local watchdog remains active")
                next_heartbeat = time.monotonic() + self.config.heartbeat_s
            await asyncio.sleep(0.1)

    async def watchdog_loop(self):
        while not self.shutdown.is_set():
            await self.watchdog_once()
            await asyncio.sleep(0.1)

    async def execute(self, command):
        previous = self.journal.start(command)
        if previous:
            return {"state": previous["state"], "result": previous["result"]}
        self.current_run = command["run_id"]
        self.cancel = asyncio.Event()
        state, result = "FAILED", {"error": "command did not execute"}
        try:
            device = self.devices.get(command["instrument_id"])
            if not device:
                raise ValueError("instrument not configured on this PC")
            if command["op"] != "safe_shutdown" and command["instrument_id"] in self.journal.device_faults():
                raise ValueError("local watchdog fault is latched; explicit safe recovery required")
            if command["op"] != "safe_shutdown" and self.current_run in self.cancelled_runs:
                raise ValueError("run cancelled; stale command refused")
            if command.get("remaining_s", 1) <= 0:
                raise ValueError("expired command refused")
            if command["op"] != "safe_shutdown":
                self.journal.claim_device(command["instrument_id"], command["run_id"])
            result = await asyncio.wait_for(
                device.execute(command["op"], command["parameters"], self.cancel),
                timeout=command.get("remaining_s", 30))
            if command["op"] == "acquire_and_store":
                parameters = command["parameters"]
                measurement = Measurement(
                    measurement_id=command["id"], command_id=command["id"],
                    experiment_id=command["run_id"], point_index=parameters["point_index"],
                    instrument_id=command["instrument_id"], agent_id=self.config.agent_id,
                    timestamp=datetime.now(timezone.utc), sample_id=parameters["sample_id"],
                    wavelength_nm=parameters["wavelength_nm"], angle_deg=parameters["angle_deg"],
                    power_percent=parameters["power_percent"], exposure_ms=result["exposure_ms"],
                    readbacks=parameters["readbacks"], spectrum_axis_nm=result["spectrum_axis_nm"],
                    counts=result["counts"], driver_version=device.spec.driver_version,
                    workflow_version="polarization-0.1.0", simulated=True)
                content = json_bytes(measurement.model_dump(mode="json"))
                path = self.config.data_dir / "cache" / f"{command['id']}.json"
                atomic_write(path, content)
                sha = hashlib.sha256(content).hexdigest()
                self.journal.add_artifact(command["id"], path, sha)
                result = {"measurement_id": command["id"], "sha256": sha,
                          "locally_saved": True, "simulated": True}
            state = "COMPLETED"
            if command["op"] == "safe_shutdown":
                self.journal.clear_device(command["instrument_id"])
                self.watchdog_tripped = bool(self.journal.device_faults())
        except (asyncio.CancelledError, TimeoutError):
            for driver in self.devices.values():
                await driver.safe_shutdown()
            state, result = "UNKNOWN", {"error": "action interrupted; safe state requested; not replayed"}
        except Exception as exc:
            state, result = "FAILED", {"error": str(exc)}
        finally:
            self.current_run = None
        self.journal.finish(command["id"], state, result)
        return {"state": state, "result": result}

    async def synchronize(self):
        # Upload first: command success alone never implies central data durability.
        for item in self.journal.pending_artifacts():
            content = Path(item["path"]).read_bytes()
            try:
                await self.request("artifacts", content=content,
                                   headers={"Content-Type": "application/json", "X-SHA256": item["sha"],
                                            "X-Boot-ID": self.boot_id})
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code in {400, 403, 404, 422}:
                    logger.error("artifact %s rejected; local copy retained for inspection", item["id"])
                    continue
                raise
            self.journal.ack_artifact(item["id"])
        for item in self.journal.pending_results():
            try:
                await self.request("results", json={"boot_id": self.boot_id, "command_id": item["id"],
                                                    "state": item["state"], "result": item["result"]})
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code in {400, 404, 409, 422} and self.registered:
                    logger.error("result %s rejected; journal retained", item["id"])
                    continue
                raise
            self.journal.ack_result(item["id"])

    async def run(self):
        monitors = [asyncio.create_task(self.background()), asyncio.create_task(self.watchdog_loop())]
        backoff = 1.0
        try:
            while not self.shutdown.is_set():
                try:
                    if not self.registered:
                        await self.register()
                        logger.info("agent %s connected (%d SIMULATED instruments)",
                                    self.config.agent_id, len(self.devices))
                    await self.synchronize()
                    response = await self.request("poll", json={"boot_id": self.boot_id})
                    if response["command"]:
                        await self.execute(response["command"])
                    backoff = 1.0
                    await asyncio.sleep(self.config.poll_s)
                except (httpx.HTTPError, ValueError, OSError):
                    # Never log HTTP exception strings: proxy credentials may appear in URLs.
                    logger.warning("central unavailable or protocol rejected; reconnecting in %.1fs", backoff)
                    await asyncio.sleep(backoff + random.random() * 0.25)
                    backoff = min(backoff * 2, 15.0)
        finally:
            self.shutdown.set()
            for monitor in monitors:
                monitor.cancel()
            await asyncio.gather(*monitors, return_exceptions=True)
            self.cancel.set()
            for device in self.devices.values():
                await device.safe_shutdown()
            if self.registered:
                try:
                    await self.request("disconnect", json={"boot_id": self.boot_id})
                except httpx.HTTPError:
                    pass
            await self.close()

    async def close(self):
        await self.client.aclose()
