from __future__ import annotations

import zipfile
from contextlib import ExitStack
from pathlib import Path

from . import __version__
from .config import AgentConfig, load_config
from .portable_archive import preflight_outputs, private_stage, publish_outputs, validate_members

PACKAGE_PROJECT = f'''[build-system]
requires = ["setuptools>=75"]
build-backend = "setuptools.build_meta"
[project]
name = "labos-mvp"
version = "{__version__}"
requires-python = ">=3.11"
dependencies = ["pydantic>=2.10,<3", "httpx>=0.28,<1", "PyYAML>=6,<7"]
[project.optional-dependencies]
central = ["fastapi>=0.115,<1", "uvicorn>=0.34,<1", "h5py>=3.12,<4"]
ai = ["openai>=1.68,<3"]
physical = ["PyVISA==1.16.2", "pyserial==3.5"]
[project.scripts]
labos = "labos.cli:main"
[tool.setuptools.packages.find]
where = ["src"]
[tool.setuptools.package-data]
labos = ["static/*.html", "assets/*"]
'''


def write_package(package: zipfile.ZipFile, role: str):
    source = Path(__file__).parent
    for path in sorted(source.rglob("*")):
        if (path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc"
                and not path.name.endswith("_ZH.md")):
            package.write(path, "src/labos/" + path.relative_to(source).as_posix())
    package.writestr("pyproject.toml", PACKAGE_PROJECT)
    package.writestr("ROLE", role)
    assets = source / "assets"
    if assets.exists():
        for path in sorted(assets.iterdir()):
            if path.is_file() and not path.name.endswith("_ZH.md"):
                package.write(path, path.name)


def build_agent_bundle(config_path: Path, output: Path, runtime_archive: Path | None = None) -> Path:
    config = load_config(config_path, AgentConfig)
    # Paths must resolve on the destination PC, not the provisioning machine.
    values = config.model_dump(mode="json")
    values["data_dir"] = "data"
    if config.ca_file:
        values["ca_file"] = "central-ca.pem"
    import yaml
    preflight_outputs([output])
    # Read public inputs before opening a file that will contain credentials.
    ca_bytes = Path(config.ca_file).read_bytes() if config.ca_file else None

    with ExitStack() as stack:
        runtime = stack.enter_context(zipfile.ZipFile(runtime_archive)) if runtime_archive else None
        members = validate_members(runtime, prefix="python") if runtime else []
        with private_stage(output) as (staged, stream):
            with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as package:
                write_package(package, "agent")
                package.writestr("config.yaml", yaml.safe_dump(values, allow_unicode=True, sort_keys=False))
                if ca_bytes is not None:
                    package.writestr("central-ca.pem", ca_bytes)
                for member in members:
                    package.writestr(member, runtime.read(member))
            stream.close()
            publish_outputs([(staged, output)])
    return output
