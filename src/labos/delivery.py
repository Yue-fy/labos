from __future__ import annotations

import zipfile
from pathlib import Path

from . import __version__
from .config import AgentConfig, load_config

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
        if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc":
            package.write(path, "src/labos/" + path.relative_to(source).as_posix())
    package.writestr("pyproject.toml", PACKAGE_PROJECT)
    package.writestr("ROLE", role)
    assets = source / "assets"
    if assets.exists():
        for path in sorted(assets.iterdir()):
            if path.is_file():
                package.write(path, path.name)


def build_agent_bundle(config_path: Path, output: Path, runtime_archive: Path | None = None) -> Path:
    config = load_config(config_path, AgentConfig)
    # Paths must resolve on the destination PC, not the provisioning machine.
    values = config.model_dump(mode="json")
    values["data_dir"] = "data"
    if config.ca_file:
        values["ca_file"] = "central-ca.pem"
    import yaml
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        raise FileExistsError("delivery archive exists; choose a new output path")
    with zipfile.ZipFile(output, "x", compression=zipfile.ZIP_DEFLATED) as package:
        write_package(package, "agent")
        package.writestr("config.yaml", yaml.safe_dump(values, allow_unicode=True, sort_keys=False))
        if config.ca_file:
            package.write(config.ca_file, "central-ca.pem")
        if runtime_archive:
            with zipfile.ZipFile(runtime_archive) as runtime:
                for name in runtime.namelist():
                    if name.startswith("/") or ".." in name.split("/") or not name.startswith("python/"):
                        raise ValueError("unsafe runtime archive path")
                    package.writestr(name, runtime.read(name))
    output.chmod(0o600)
    return output
