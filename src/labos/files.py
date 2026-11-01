from __future__ import annotations

import json
import os
import uuid
from contextlib import AbstractContextManager
from pathlib import Path

from pydantic import AwareDatetime, Field, model_validator

from .models import DetectorFlags, Finite, Identifier, Model


def json_bytes(value: dict) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def contains_credential(value, credentials) -> bool:
    """Check decoded strings and wire JSON, including numeric credentials."""
    def decoded(item):
        if isinstance(item, str):
            return any(secret in item for secret in credentials)
        if isinstance(item, dict):
            return any(decoded(k) or decoded(v) for k, v in item.items())
        if isinstance(item, (list, tuple)):
            return any(decoded(v) for v in item)
        return False

    if decoded(value):
        return True
    wire = json_bytes(value)
    return any(secret.encode("utf-8") in wire for secret in credentials)


def atomic_write(path: Path, content: bytes):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        with temporary.open("xb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        if os.name != "nt":
            fd = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
    finally:
        temporary.unlink(missing_ok=True)


class InstanceLock(AbstractContextManager):
    def __init__(self, directory: Path):
        directory.mkdir(parents=True, exist_ok=True)
        self.path = directory / "instance.lock"
        self.handle = None

    def __enter__(self):
        self.handle = self.path.open("a+b")
        try:
            if os.name == "nt":
                import msvcrt
                self.handle.seek(0)
                self.handle.write(b"0")
                self.handle.flush()
                self.handle.seek(0)
                msvcrt.locking(self.handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            self.handle.close()
            raise RuntimeError("another LabOS process owns this data directory") from exc
        return self

    def __exit__(self, *args):
        if self.handle:
            self.handle.close()


class Measurement(Model):
    schema_version: int = 1
    measurement_id: Identifier
    command_id: Identifier
    experiment_id: Identifier
    point_index: int = Field(ge=0, le=4999)
    instrument_id: Identifier
    agent_id: Identifier
    timestamp: AwareDatetime
    sample_id: Identifier
    wavelength_nm: Finite
    angle_deg: Finite
    power_percent: Finite
    exposure_ms: Finite
    readbacks: dict
    spectrum_axis_nm: list[Finite] = Field(min_length=1, max_length=4096)
    counts: list[Finite] = Field(min_length=1, max_length=4096)
    driver_version: str
    workflow_version: str
    simulated: bool
    detector_flags: DetectorFlags | None = None
    provenance: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def consistent(self):
        if self.schema_version != 1 or self.measurement_id != self.command_id:
            raise ValueError("invalid measurement identity/version")
        if len(self.spectrum_axis_nm) != len(self.counts):
            raise ValueError("spectrum dimensions differ")
        if any(a >= b for a, b in zip(self.spectrum_axis_nm, self.spectrum_axis_nm[1:])):
            raise ValueError("spectrum axis must increase")
        # Also checks nested readback values; json dumps refuses nonfinite floats.
        json_bytes(self.readbacks)
        return self


def export_hdf5(store, run_id: str) -> Path:
    import h5py
    import numpy as np

    run, artifacts = store.export_snapshot(run_id)
    all_measurements = [a["measurement"] for a in artifacts]
    measurements = [a["measurement"] for a in artifacts if a["quality"]["status"] == "accepted"]
    if not all_measurements:
        raise ValueError("no synchronized measurements to export")
    path = store.root / "exports" / f"{run_id}.h5"
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{run_id}.{uuid.uuid4().hex}.tmp")
    try:
        with h5py.File(temporary, "w") as h5:
            h5.attrs["experiment_id"] = run_id
            h5.attrs["status_at_export"] = run["status"]
            h5.attrs["simulated"] = all(m["simulated"] for m in all_measurements)
            h5.attrs["workflow_version"] = "polarization-0.2.0"
            h5.attrs["data_selection"] = "raw: qualified only; audit: all synchronized artifacts"
            raw = h5.create_group("raw")
            for name in ("wavelength_nm", "angle_deg", "power_percent", "exposure_ms",
                         "point_index"):
                raw.create_dataset(name, data=[m[name] for m in measurements])
            axes = [m["spectrum_axis_nm"] for m in measurements]
            # Empty qualified sets still export the complete rejected-data audit trail.
            width = len(all_measurements[0]["counts"])
            raw.create_dataset("spectrum_axis_nm", data=np.array(axes).reshape((-1, width)))
            raw.create_dataset("counts", data=np.array([m["counts"] for m in measurements]).reshape((-1, width)))
            text_type = h5py.string_dtype("utf-8")
            metadata = h5.create_group("metadata")
            for name in ("plan", "setup", "preflight"):
                metadata.create_dataset(name, data=json.dumps(run[name], ensure_ascii=False),
                                        dtype=text_type)
            metadata.create_dataset("measurements_json", data=[json.dumps(m, ensure_ascii=False)
                                                               for m in measurements],
                                    dtype=text_type)
            audit = h5.create_group("audit")
            audit.create_dataset("measurements_json", data=[json.dumps(m, ensure_ascii=False)
                                                            for m in all_measurements], dtype=text_type)
            audit.create_dataset("qualifications_json", data=[json.dumps(a["quality"], ensure_ascii=False)
                                                               for a in artifacts], dtype=text_type)
            audit.create_dataset("artifact_sha256", data=[a["sha256"] for a in artifacts], dtype=text_type)
            h5.flush()
        # Windows requires a writable handle to flush the completed HDF5 file.
        with temporary.open("r+b") as handle:
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    return path
