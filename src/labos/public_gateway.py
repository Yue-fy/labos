"""Restricted public PC API, forwarding only to the loopback central service.

Run separately from central and point an HTTPS terminator at its loopback port.
This module never configures Tailscale or exposes central's operator interface.
"""
from __future__ import annotations

import argparse
import asyncio
from contextlib import asynccontextmanager
import hmac
from pathlib import Path
import re

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response
import httpx
import yaml

from .config import CentralConfig, load_config

MAX_BODY_BYTES = 8 * 1024 * 1024
UPSTREAM_TIMEOUT_S = 15
_PC_PATH = re.compile(r"/api/agents/([A-Za-z0-9][A-Za-z0-9_-]{0,79})/([a-z-]+)\Z")
_METHODS = {
    "health": {"GET"},
    "messages": {"GET", "POST"},
    "register": {"POST"},
    "heartbeat": {"POST"},
    "poll": {"POST"},
    "results": {"POST"},
    "artifacts": {"POST"},
    "pilot-artifacts": {"POST"},
    "disconnect": {"POST"},
}
_SECURITY_HEADERS = {
    "Cache-Control": "no-store",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "X-Frame-Options": "DENY",
}


def create_app(config: CentralConfig, transport: httpx.AsyncBaseTransport | None = None):
    """Build the gateway; ``transport`` allows real ASGI central integration tests."""
    upstream_origin = httpx.URL(f"http://127.0.0.1:{config.port}")

    @asynccontextmanager
    async def lifespan(app):
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(10, connect=2, pool=2),
            follow_redirects=False,
            trust_env=False,
            transport=transport,
        ) as client:
            app.state.upstream = client
            yield

    app = FastAPI(title="LabOS public PC gateway", lifespan=lifespan,
                  docs_url=None, redoc_url=None, openapi_url=None, redirect_slashes=False)

    def error(status: int, detail: str):
        return JSONResponse({"detail": detail}, status_code=status, headers=_SECURITY_HEADERS)

    @app.middleware("http")
    async def security_headers(request, call_next):
        response = await call_next(request)
        response.headers.update(_SECURITY_HEADERS)
        return response

    @app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE",
                                           "HEAD", "OPTIONS", "TRACE", "CONNECT"])
    async def forward(request: Request, path: str):
        path = "/" + path
        agent_id = None
        if path == "/health":
            methods = {"GET"}
        else:
            match = _PC_PATH.fullmatch(path)
            if not match or match[2] not in _METHODS:
                return error(404, "not found")
            agent_id = match[1]
            methods = _METHODS[match[2]]
        if request.method not in methods:
            return error(405, "method not allowed")

        headers = {}
        if agent_id is not None:
            authorization = request.headers.getlist("authorization")
            if len(authorization) != 1 or not authorization[0].startswith("Bearer "):
                return error(401, "PC bearer credential required")
            token = authorization[0][7:].encode("utf-8")
            if hmac.compare_digest(token, config.admin_token.encode("utf-8")):
                return error(403, "PC credential required")
            identity = next((name for name, enrollment in config.agents.items()
                             if hmac.compare_digest(token, enrollment.token.encode("utf-8"))), None)
            if identity is None:
                return error(401, "invalid PC credential")
            if agent_id != identity:
                return error(403, "PC credential does not match this PC")
            headers["Authorization"] = "Bearer " + config.agents[identity].token

        lengths = request.headers.getlist("content-length")
        if lengths:
            if len(lengths) != 1 or not lengths[0].isascii() or not lengths[0].isdecimal():
                return error(400, "invalid content length")
            length = lengths[0].lstrip("0") or "0"
            maximum = str(MAX_BODY_BYTES)
            if len(length) > len(maximum) or (len(length) == len(maximum) and length > maximum):
                return error(413, "request body too large")
        content = bytearray()
        try:
            async with asyncio.timeout(UPSTREAM_TIMEOUT_S):
                async for chunk in request.stream():
                    if len(content) + len(chunk) > MAX_BODY_BYTES:
                        return error(413, "request body too large")
                    content.extend(chunk)
        except TimeoutError:
            return error(408, "request body timed out")

        # Never forward client-selected hosts, cookies, proxy credentials, or
        # forwarding headers. The upstream URL is built exclusively from config.
        for name in ("Content-Type", "X-Sha256", "X-Boot-Id"):
            if name in request.headers:
                headers[name] = request.headers[name]
        url = upstream_origin.copy_with(path=path, query=request.scope["query_string"])
        try:
            async with asyncio.timeout(UPSTREAM_TIMEOUT_S):
                result = await app.state.upstream.request(
                    request.method, url, headers=headers, content=bytes(content))
        except (httpx.HTTPError, TimeoutError):
            return error(503, "central service unavailable")
        if 300 <= result.status_code < 400:
            return error(502, "unexpected central redirect")
        if result.status_code >= 400:
            # Central validation errors may include submitted values. Do not
            # expose diagnostics, request bodies, or credentials publicly.
            return error(result.status_code, "central rejected the request")
        return Response(content=result.content, status_code=result.status_code,
                        media_type="application/json", headers=_SECURITY_HEADERS)

    return app


def main(argv=None):
    parser = argparse.ArgumentParser(description="Run the restricted LabOS public PC gateway")
    parser.add_argument("--config", type=Path, required=True, help="private central YAML configuration")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=18081)
    args = parser.parse_args(argv)
    try:
        config = load_config(args.config, CentralConfig)
    except (OSError, ValueError, yaml.YAMLError):
        # Validation exceptions can contain the entire private YAML input.
        parser.exit(2, "gateway configuration could not be loaded; check the private YAML file\n")
    import uvicorn

    # Access URLs can contain arbitrary query input; do not write them to logs.
    uvicorn.run(create_app(config), host=args.host, port=args.port, access_log=False)


if __name__ == "__main__":
    main()
