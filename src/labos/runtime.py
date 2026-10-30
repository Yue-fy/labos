from __future__ import annotations

import asyncio
import time
import uuid
from datetime import datetime, timezone

from .config import CentralConfig
from .files import export_hdf5
from .models import Plan
from .store import Store


class RunStopped(Exception):
    pass


class Runtime:
    def __init__(self, config: CentralConfig, store: Store):
        self.config = config
        self.store = store
        self.tasks: dict[str, asyncio.Task] = {}

    def setup(self, setup_id):
        for setup in self.config.setups:
            if setup.id == setup_id:
                return setup
        raise ValueError("unknown setup")

    def preflight(self, plan: Plan, ignore_reservation=False, allow_faults=False):
        setup = self.setup(plan.setup_id)
        if not setup.operator_confirmed:
            raise ValueError("physical setup needs operator confirmation")
        registry = self.store.registry(self.config.offline_after_s)
        instruments = {i["id"]: i for i in registry["instruments"]}
        snapshot = {}
        for role, instrument_id in setup.devices.items():
            instrument = instruments.get(instrument_id)
            if not instrument or not instrument["online"]:
                raise ValueError(f"{instrument_id}: offline or no fresh instrument status")
            spec, status = instrument["spec"], instrument["status"]
            if status.get("instrument_id") != instrument_id or status.get("kind") != role:
                raise ValueError(f"{instrument_id}: identity mismatch")
            if status.get("mode") != "simulated" or status.get("driver_version") != spec["driver_version"]:
                raise ValueError(f"{instrument_id}: unapproved driver/mode")
            if not status.get("stable"):
                raise ValueError(f"{instrument_id}: not ready")
            if status.get("fault_latched") and not allow_faults:
                raise ValueError(f"{instrument_id}: local watchdog fault requires reconciliation")
            if instrument["lock_run"] and not ignore_reservation:
                raise ValueError(f"{instrument_id}: already reserved")
            if role == "laser":
                if not (spec["wavelength_min_nm"] <= plan.wavelength_start_nm
                        <= plan.wavelength_stop_nm <= spec["wavelength_max_nm"]):
                    raise ValueError("wavelength exceeds enrolled limits")
                if plan.power_percent > spec["power_max_percent"]:
                    raise ValueError("power exceeds enrolled limits")
            elif role == "rotator":
                if not (spec["angle_min_deg"] <= plan.angle_start_deg
                        <= plan.angle_stop_deg <= spec["angle_max_deg"]):
                    raise ValueError("angle exceeds enrolled limits")
            elif plan.exposure_ms > spec["exposure_max_ms"]:
                raise ValueError("exposure exceeds enrolled limits")
            snapshot[role] = {"instrument_id": instrument_id, "agent_id": instrument["agent_id"],
                              "seen": instrument["seen"], "spec": spec, "status": status}
        return {"checked_at": datetime.now(timezone.utc).isoformat(), "instruments": snapshot,
                "evidence": self.store.evidence_citations(plan.evidence_ids),
                "point_count": len(plan.points()), "simulated": True,
                "minimum_exposure_s": len(plan.points()) * plan.exposure_ms / 1000,
                "note": "Exposure-only lower bound; movement, network and storage add time."}

    def start(self, plan):
        snapshot = self.preflight(plan)
        run = self.store.create_run(plan, self.setup(plan.setup_id), snapshot)
        self.tasks[run["id"]] = asyncio.create_task(self.execute(run["id"]))
        return run

    def control(self, run_id, action):
        run = self.store.run(run_id)
        if action == "pause":
            self.store.transition(run_id, {"RUNNING"}, "PAUSING")
        elif action == "resume":
            if run_id not in self.tasks or self.tasks[run_id].done():
                raise ValueError("interrupted run cannot resume; reconcile and prepare a new run")
            self.preflight(Plan.model_validate(run["plan"]), ignore_reservation=True)
            self.store.transition(run_id, {"PAUSED"}, "RUNNING")
        elif action == "stop":
            self.store.transition(run_id, {"RUNNING", "PAUSING", "PAUSED"}, "STOPPING")
            self.store.cancel_queued(run_id)
        elif action == "reconcile":
            # Safe cleanup is independent of acquisition limits, old plan schemas
            # and superseded scientific references. Ownership is checked atomically
            # here; authenticated workers execute only local shutdown operations,
            # and reservations remain held unless shutdown readbacks are confirmed.
            self.store.begin_reconcile(run_id)
            self.tasks[run_id] = asyncio.create_task(self.reconcile(run_id))
        else:
            raise ValueError("unknown control action")

    async def call(self, run_id, key, instrument_id, op, parameters, cleanup=False):
        if not cleanup and self.store.run(run_id)["status"] == "STOPPING":
            raise RunStopped()
        command = self.store.new_command(run_id, key, instrument_id, op, parameters)
        deadline = time.monotonic() + self.config.command_timeout_s
        while time.monotonic() < deadline:
            if not cleanup and self.store.run(run_id)["status"] == "STOPPING":
                raise RunStopped()
            current = self.store.command(command["id"])
            if current["state"] == "COMPLETED":
                if op == "acquire_and_store" and current["result"].get("measurement_id") != command["id"]:
                    raise ValueError("acquisition result identity mismatch")
                return current["result"]
            if current["state"] in {"FAILED", "UNKNOWN", "CANCELLED"}:
                raise ValueError(f"{op}: {current['state']}; {current['result'].get('error', '')}")
            await asyncio.sleep(0.03)
        self.store.timeout_command(command["id"])
        raise ValueError(f"{op}: command timeout; outcome must be reconciled")

    async def safe_shutdown(self, run_id):
        run = self.store.run(run_id)
        nonce = uuid.uuid4().hex
        results = await asyncio.gather(*[
            self.call(run_id, f"safe-{nonce}-{role}", instrument_id, "safe_shutdown", {}, cleanup=True)
            for role, instrument_id in run["setup"]["devices"].items()
        ], return_exceptions=True)
        failures = [str(r) for r in results if isinstance(r, BaseException)]
        if failures:
            raise ValueError("safe state unconfirmed: " + "; ".join(failures))
        for role, result in zip(run["setup"]["devices"], results):
            if role == "laser" and (result.get("shutter_open") or result.get("power_percent") != 0):
                raise ValueError("laser safe state unconfirmed")
        self.store.event("SHUTDOWN_VERIFIED", {"readbacks": dict(zip(run["setup"]["devices"], results)),
                                               "scope": "Software readbacks; not physical inspection"}, run_id)

    async def prepare_light(self, run_id, devices, plan):
        nonce = uuid.uuid4().hex
        await self.call(run_id, f"power-{nonce}", devices["laser"], "set_power",
                        {"percent": plan.power_percent})
        await self.call(run_id, f"shutter-{nonce}", devices["laser"], "open_shutter", {})

    async def boundary(self, run_id, devices, plan):
        status = self.store.run(run_id)["status"]
        if status == "STOPPING":
            raise RunStopped()
        if status == "PAUSING":
            await self.call(run_id, f"pause-{uuid.uuid4().hex}", devices["laser"], "safe_shutdown", {})
            status = self.store.run(run_id)["status"]
            if status == "STOPPING":
                raise RunStopped()
            self.store.transition(run_id, {"PAUSING"}, "PAUSED")
            while self.store.run(run_id)["status"] == "PAUSED":
                await asyncio.sleep(0.03)
            if self.store.run(run_id)["status"] == "STOPPING":
                raise RunStopped()
            await self.prepare_light(run_id, devices, plan)

    async def execute(self, run_id):
        run = self.store.run(run_id)
        plan = Plan.model_validate(run["plan"])
        devices = run["setup"]["devices"]
        final, error = "COMPLETED", None
        try:
            await self.prepare_light(run_id, devices, plan)
            for point_index, (wavelength, angle) in enumerate(plan.points()):
                await self.boundary(run_id, devices, plan)
                laser = await self.call(run_id, f"{point_index}-wavelength", devices["laser"],
                                        "set_wavelength", {"nm": wavelength})
                rotator = await self.call(run_id, f"{point_index}-angle", devices["rotator"],
                                          "set_angle", {"angle_deg": angle})
                if (not laser.get("stable") or laser.get("actual_wavelength_nm") != wavelength
                        or laser.get("power_percent") != plan.power_percent
                        or laser.get("shutter_open") is not True
                        or not rotator.get("stable") or rotator.get("actual_angle_deg") != angle):
                    raise ValueError("position readback did not verify the requested point")
                result = await self.call(run_id, f"{point_index}-capture", devices["spectrometer"],
                                         "acquire_and_store", {
                    "point_index": point_index, "sample_id": plan.sample_id,
                    "wavelength_nm": wavelength, "angle_deg": angle,
                    "power_percent": plan.power_percent, "exposure_ms": plan.exposure_ms,
                    "readbacks": {"laser": laser, "rotator": rotator},
                    "provenance": self.store.provenance(run_id)})
                deadline = time.monotonic() + self.config.command_timeout_s
                while result.get("measurement_id") not in {m["measurement_id"] for m in self.store.measurements(run_id)}:
                    if self.store.run(run_id)["status"] == "STOPPING":
                        raise RunStopped()
                    if time.monotonic() >= deadline:
                        raise ValueError("capture saved locally but central synchronization timed out")
                    await asyncio.sleep(0.03)
                quality = self.store.qualification(result["measurement_id"])
                if not quality or quality["status"] != "accepted":
                    raise ValueError("measurement quality rejected or unassessed: " +
                                     ", ".join((quality or {}).get("reasons", ["missing assessment"])))
        except RunStopped:
            final, error = "ABORTED", "stopped by operator; synchronized data preserved"
        except asyncio.CancelledError:
            self.store.cancel_queued(run_id)
            self.store.set_run(run_id, "INTERRUPTED", "runtime stopped; local watchdog protects devices")
            raise
        except Exception as exc:
            final, error = "FAILED", str(exc)
        self.store.cancel_queued(run_id)
        try:
            await self.safe_shutdown(run_id)
            self.store.set_run(run_id, final, error, release=True)
        except Exception as exc:
            self.store.set_run(run_id, "FAILED", f"{error or final}; {exc}", release=False)
        # Persist closure before the optional asynchronous export can be cancelled.
        self.review(run_id)
        if self.store.measurements(run_id):
            try:
                await asyncio.to_thread(export_hdf5, self.store, run_id)
                self.store.event("HDF5_EXPORTED", {}, run_id)
            except Exception as exc:
                self.store.event("HDF5_EXPORT_FAILED", {"error": str(exc)}, run_id)
    def review(self, run_id):
        from .review import build_review
        return self.store.save_review(run_id, build_review(self.store, run_id))

    async def reconcile(self, run_id):
        self.store.cancel_queued(run_id)
        try:
            await self.safe_shutdown(run_id)
            self.store.set_run(run_id, "ABORTED", "operator reconciliation completed", release=True)
        except Exception as exc:
            self.store.set_run(run_id, "FAILED", str(exc))
        self.review(run_id)

    async def close(self):
        pending = [task for task in self.tasks.values() if not task.done()]
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
