from __future__ import annotations

import ipaddress
from pathlib import Path
from urllib.parse import urlsplit

import yaml
from pydantic import Field, model_validator

from .models import Identifier, InstrumentSpec, Model, SetupProfile


class Enrollment(Model):
    token: str = Field(min_length=32, repr=False)
    instruments: list[InstrumentSpec]


class CentralConfig(Model):
    admin_token: str = Field(min_length=32, repr=False)
    agents: dict[Identifier, Enrollment]
    setups: list[SetupProfile] = Field(default_factory=lambda: [SetupProfile()])
    data_dir: Path = Path("runtime/central")
    host: str = "127.0.0.1"
    port: int = Field(default=8000, ge=1, le=65535)
    offline_after_s: float = Field(default=10, ge=1, le=120)
    command_timeout_s: float = Field(default=20, ge=1, le=300)
    openai_model: str | None = None

    @model_validator(mode="after")
    def unique_registry(self):
        tokens = [self.admin_token] + [a.token for a in self.agents.values()]
        ids = [d.id for a in self.agents.values() for d in a.instruments]
        if len(tokens) != len(set(tokens)) or len(ids) != len(set(ids)):
            raise ValueError("tokens and instrument IDs must be unique")
        if len({s.id for s in self.setups}) != len(self.setups):
            raise ValueError("setup IDs must be unique")
        registry = {d.id: d for a in self.agents.values() for d in a.instruments}
        for setup in self.setups:
            for role, instrument_id in setup.devices.items():
                if instrument_id not in registry or registry[instrument_id].kind != role:
                    raise ValueError("setup role does not match enrolled instrument")
        return self


class AgentConfig(Model):
    agent_id: Identifier
    token: str = Field(min_length=32, repr=False)
    server_url: str
    instruments: list[InstrumentSpec]
    data_dir: Path = Path("runtime/agent")
    heartbeat_s: float = Field(default=2, ge=0.1, le=30)
    poll_s: float = Field(default=0.3, ge=0.05, le=10)
    watchdog_s: float = Field(default=15, ge=1, le=120)
    request_timeout_s: float = Field(default=5, ge=0.1, le=30)
    allow_insecure_http: bool = False
    ca_file: Path | None = None
    proxy_url: str | None = None

    @model_validator(mode="after")
    def validate_connection(self):
        parsed = urlsplit(self.server_url)
        if (parsed.scheme not in {"https", "http"} or not parsed.hostname or parsed.username
                or parsed.password or parsed.query or parsed.fragment or parsed.path not in {"", "/"}):
            raise ValueError("server URL must be an http(s) origin without credentials or path")
        loopback = parsed.hostname == "localhost"
        try:
            loopback |= ipaddress.ip_address(parsed.hostname).is_loopback
        except ValueError:
            pass
        if parsed.scheme == "http" and not loopback and not self.allow_insecure_http:
            raise ValueError("HTTP requires explicit allow_insecure_http on trusted LAN/VPN")
        if self.watchdog_s <= self.heartbeat_s:
            raise ValueError("watchdog must exceed heartbeat interval")
        if len({d.id for d in self.instruments}) != len(self.instruments):
            raise ValueError("duplicate instrument IDs")
        self.server_url = self.server_url.rstrip("/")
        return self


def load_config(path: str | Path, cls):
    path = Path(path).resolve()
    values = yaml.safe_load(path.read_text(encoding="utf-8"))
    config = cls.model_validate(values)
    if not config.data_dir.is_absolute():
        config.data_dir = path.parent / config.data_dir
    if isinstance(config, AgentConfig) and config.ca_file and not config.ca_file.is_absolute():
        config.ca_file = path.parent / config.ca_file
    return config
