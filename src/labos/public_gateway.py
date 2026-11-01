"""Restricted public PC API, forwarding only to the loopback central service.

Run separately from central and point an HTTPS terminator at its loopback port.
This module never configures Tailscale or exposes central's operator interface.
"""
from __future__ import annotations

import argparse
import asyncio
from contextlib import asynccontextmanager
import hmac
import json
from pathlib import Path
import re

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response
import httpx
import yaml

from .config import CentralConfig, load_config

MAX_BODY_BYTES = 8 * 1024 * 1024
MAX_RESPONSE_BYTES = 8 * 1024 * 1024
MAX_ERROR_BYTES = 4096
UPSTREAM_TIMEOUT_S = 15
_REQUEST_LIMITS = {
    "messages": 65536,
    "artifacts": 2000000,
    "pilot-artifacts": 2000000,
    "pilot-claims": 4096,
}
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
    "pilot-claims": {"GET", "POST"},
    "disconnect": {"POST"},
}
_SECURITY_HEADERS = {
    "Cache-Control": "no-store",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "X-Frame-Options": "DENY",
}


def _length_status(lengths, maximum):
    if not lengths:
        return None
    if len(lengths) != 1 or not lengths[0].isascii() or not lengths[0].isdecimal():
        return 400
    length = lengths[0].lstrip("0") or "0"
    limit = str(maximum)
    if len(length) > len(limit) or (len(length) == len(limit) and length > limit):
        return 413
    return None


class _GatewayBoundary:
    """Bound whole HTTP handlers and keep raw ASGI disconnects visible."""

    def __init__(self, app, max_inflight):
        self.app = app
        self.maximum = max_inflight
        self.active = 0

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        async def secure_send(message):
            if message["type"] == "http.response.start":
                fixed = {key.lower().encode(): value.encode() for key, value in _SECURITY_HEADERS.items()}
                message["headers"] = [(key, value) for key, value in message["headers"] if key.lower() not in fixed]
                message["headers"].extend(fixed.items())
            await send(message)

        # No await between admission and increment. A full handler never
        # queues a body buffer, including while an earlier response is sent.
        if self.active >= self.maximum:
            response = JSONResponse({"detail": "gateway busy"}, status_code=503)
            return await response(scope, receive, secure_send)
        self.active += 1
        try:
            await self.app(scope, receive, secure_send)
        finally:
            self.active -= 1


def create_app(config: CentralConfig, transport: httpx.AsyncBaseTransport | None = None,
               *, max_inflight: int = 32):
    """Build the gateway; ``transport`` allows real ASGI central integration tests."""
    upstream_origin = httpx.URL(f"http://127.0.0.1:{config.port}")
    if type(max_inflight) is not int or not 1 <= max_inflight <= 256:
        raise ValueError("max_inflight must be an integer from 1 to 256")

    @asynccontextmanager
    async def lifespan(app):
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(10, connect=2, pool=2),
            follow_redirects=False,
            trust_env=False,
            transport=transport,
            limits=httpx.Limits(max_connections=max_inflight, max_keepalive_connections=max_inflight),
        ) as client:
            app.state.upstream = client
            yield

    app = FastAPI(title="LabOS public PC gateway", lifespan=lifespan,
                  docs_url=None, redoc_url=None, openapi_url=None, redirect_slashes=False)

    def error(status: int, detail: str):
        return JSONResponse({"detail": detail}, status_code=status, headers=_SECURITY_HEADERS)

    app.add_middleware(_GatewayBoundary, max_inflight=max_inflight)

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

        maximum = MAX_BODY_BYTES
        if agent_id and request.method == "POST":
            maximum = _REQUEST_LIMITS.get(match[2], maximum)
        length_status = _length_status(request.headers.getlist("content-length"), maximum)
        if length_status:
            return error(length_status, "invalid content length" if length_status == 400 else "request body too large")
        content = bytearray()
        try:
            async with asyncio.timeout(UPSTREAM_TIMEOUT_S):
                async for chunk in request.stream():
                    if len(content) + len(chunk) > maximum:
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
        headers["Accept-Encoding"] = "identity"

        async def exchange():
            try:
                # This deadline includes headers, send, and every body chunk.
                async with asyncio.timeout(UPSTREAM_TIMEOUT_S):
                    async with app.state.upstream.stream(
                            request.method, url, headers=headers, content=bytes(content)) as result:
                        if 300 <= result.status_code < 400:
                            return error(502, "unexpected central redirect")
                        encodings = result.headers.get_list("content-encoding")
                        if encodings and (len(encodings) != 1 or encodings[0].strip().lower() != "identity"):
                            return error(502, "unexpected central encoding")
                        length_status = _length_status(result.headers.get_list("content-length"), MAX_RESPONSE_BYTES)
                        if length_status:
                            return error(502, "central response too large" if length_status == 413 else "invalid central response")
                        # Inspect only the closed session contract; arbitrary
                        # error diagnostics and redirect bodies are never drained.
                        if result.status_code >= 400 and result.status_code != 409:
                            return error(result.status_code, "central rejected the request")
                        maximum = MAX_ERROR_BYTES if result.status_code == 409 else MAX_RESPONSE_BYTES
                        body = bytearray()
                        # Preloaded transports already hold their content;
                        # network responses always use raw, undecoded chunks.
                        chunks = result.aiter_bytes() if result.is_stream_consumed else result.aiter_raw()
                        async for chunk in chunks:
                            if len(body) + len(chunk) > maximum:
                                return error(502, "central response too large")
                            body.extend(chunk)
                        if result.status_code == 409:
                            # Compare parsed pairs rather than accepting extra
                            # fields, duplicate keys, code-only, or loose values.
                            try:
                                pairs = json.loads(body, object_pairs_hook=lambda pairs: pairs)
                            except (ValueError, UnicodeError, RecursionError):
                                pairs = None
                            if pairs == [("detail", "invalid agent session")]:
                                return JSONResponse({"detail": "invalid agent session", "code": "invalid_agent_session"},
                                                    status_code=409, headers=_SECURITY_HEADERS)
                            return error(409, "central rejected the request")
                        return Response(content=bytes(body), status_code=result.status_code,
                                        media_type="application/json", headers=_SECURITY_HEADERS)
            except (httpx.HTTPError, TimeoutError):
                return error(503, "central service unavailable")

        async def disconnected():
            while (await request.receive())["type"] != "http.disconnect":
                pass

        operation = asyncio.create_task(exchange())
        disconnect = asyncio.create_task(disconnected())
        try:
            done, _ = await asyncio.wait((operation, disconnect), return_when=asyncio.FIRST_COMPLETED)
            if disconnect in done:
                raise asyncio.CancelledError
            return operation.result()
        finally:
            for task in (operation, disconnect):
                if not task.done():
                    task.cancel()
            await asyncio.gather(operation, disconnect, return_exceptions=True)

    return app


def main(argv=None):
    parser = argparse.ArgumentParser(description="Run the restricted LabOS public PC gateway")
    parser.add_argument("--config", type=Path, required=True, help="private central YAML configuration")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=18081)
    parser.add_argument("--max-inflight", type=int, choices=range(1, 257), default=32,
                        metavar="1..256", help="maximum active requests (default: 32)")
    args = parser.parse_args(argv)
    try:
        config = load_config(args.config, CentralConfig)
    except (OSError, ValueError, yaml.YAMLError):
        # Validation exceptions can contain the entire private YAML input.
        parser.exit(2, "gateway configuration could not be loaded; check the private YAML file\n")
    import uvicorn

    # Access URLs can contain arbitrary query input; do not write them to logs.
    uvicorn.run(create_app(config, max_inflight=args.max_inflight), host=args.host, port=args.port, access_log=False)


if __name__ == "__main__":
    main()
