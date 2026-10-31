"""Exercise update integrity, backup and worker-lock checks without device access."""

import hashlib
import json
from pathlib import Path
import runpy

import pytest

from labos.files import InstanceLock

APPLY = Path(__file__).parents[1] / "src/labos/assets/Apply-Pilot-Update.py"


def fixture(tmp_path):
    update = tmp_path / "update"
    update.mkdir()
    target = tmp_path / "LabOS (existing)"
    target.mkdir()
    (target / "config.yaml").write_text("preserved-connection")
    (target / "cooperation.yaml").write_text(
        "role: pc\nagent_id: pc-a\nconnection_config: config.yaml\n"
    )
    payload = update / "overlay"
    payload.mkdir()
    (payload / "Check-Pilot-Runtime.py").write_text("# new runtime check\n")
    (target / "Check-Pilot-Runtime.py").write_text("# previous runtime check\n")
    (update / "payload-manifest.json").write_text(
        json.dumps(
            {
                "files": {
                    "Check-Pilot-Runtime.py": hashlib.sha256(
                        (payload / "Check-Pilot-Runtime.py").read_bytes()
                    ).hexdigest()
                }
            }
        )
    )
    return update, target


def test_update_preserves_connection_and_journal_and_backs_up_replaced_files(tmp_path):
    update, target = fixture(tmp_path)
    journal = target / "data/cooperation/journal.sqlite"
    journal.parent.mkdir(parents=True)
    journal.write_bytes(b"preserved-journal")
    apply_update = runpy.run_path(str(APPLY))["apply_update"]
    backup = apply_update(update, target)
    assert (target / "Check-Pilot-Runtime.py").read_text() == "# new runtime check\n"
    assert (backup / "Check-Pilot-Runtime.py").read_text() == "# previous runtime check\n"
    assert (target / "config.yaml").read_text() == "preserved-connection"
    assert journal.read_bytes() == b"preserved-journal"


@pytest.mark.parametrize("fault", ["checksum", "active_worker", "protected_path", "escape"])
def test_update_refuses_before_mutation_on_bad_payload_or_active_worker(tmp_path, fault):
    from contextlib import nullcontext

    update, target = fixture(tmp_path)
    manifest = update / "payload-manifest.json"
    if fault == "checksum":
        (update / "overlay/Check-Pilot-Runtime.py").write_text("# tampered\n")
    elif fault in ("protected_path", "escape"):
        entry = "config.yaml" if fault == "protected_path" else "../escaped.py"
        manifest.write_text(json.dumps({"files": {entry: "0" * 64}}))
    lock = InstanceLock(target / "data/cooperation") if fault == "active_worker" else nullcontext()
    with lock, pytest.raises((ValueError, RuntimeError)):
        runpy.run_path(str(APPLY))["apply_update"](update, target)
    assert (target / "Check-Pilot-Runtime.py").read_text() == "# previous runtime check\n"
    assert (target / "config.yaml").read_text() == "preserved-connection"
