"""Build a source-only optional extension; no core overlay or vendor binary."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def build(output):
    output = Path(output)
    files = {
        f"src/labos_field/{p.name}": p.read_bytes()
        for p in sorted((ROOT / "src/labos_field").glob("*.py"))
    }
    files.update(
        {
            "launch_field.py": (ROOT / "field_extension/launch_field.py").read_bytes(),
            "field-campaign.example.yaml": (
                ROOT / "field_extension/field-campaign.example.yaml"
            ).read_bytes(),
            "START_HERE_FIELD_EN.md": (ROOT / "docs/FIELD_CAMPAIGN_EN.md").read_bytes(),
        }
    )
    files["payload-manifest.json"] = (
        json.dumps(
            {
                "extension_version": "0.1.0",
                "core_version": "0.2.8",
                "files": {
                    name: hashlib.sha256(value).hexdigest() for name, value in sorted(files.items())
                },
            },
            indent=2,
        )
        + "\n"
    ).encode()
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "x", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, value in sorted(files.items()):
            archive.writestr(name, value)
    return output


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    print(build(parser.parse_args().output))
