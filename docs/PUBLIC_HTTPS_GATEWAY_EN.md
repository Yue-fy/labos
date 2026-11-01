# Public HTTPS for PCs outside Tailscale

All example service hostnames below use the reserved `.example` domain. Replace them with your
own verified Serve/Funnel URL obtained from the server operator and checked
against `tailscale serve status` and `tailscale funnel status`. These examples
do not identify a running installation.

The public PC endpoint is separate from the private operator endpoint. A remote
PC needs ordinary DNS and **outbound HTTPS on TCP 8443**; it does not need to join
the tailnet, install Tailscale, accept inbound connections, or open a local port.
The server still runs Tailscale. A network that blocks outbound 8443 must permit
that destination before the PC can connect.

| Purpose | HTTPS origin / local destination | Access |
| --- | --- | --- |
| Operator dashboard and full central API | `https://labos-gateway.example` (443) → `127.0.0.1:18080` | Private Tailscale Serve |
| Restricted PC API | `https://labos-gateway.example:8443` → `127.0.0.1:18081` → central `127.0.0.1:18080` | Public HTTPS after Funnel activation |
| Optional local model service | Local port 8000 | Private; unrelated to this gateway |

Funnel supports public ports 443, 8443, and 10000. A port cannot simultaneously
be private Serve and public Funnel, so use **8443** for this gateway and retain
the existing private configuration on 443. Funnel requires MagicDNS, HTTPS,
and permission in the tailnet policy. See [Tailscale Funnel requirements](https://tailscale.com/docs/features/tailscale-funnel)
and the [Funnel CLI reference](https://tailscale.com/docs/reference/tailscale-cli/funnel).

## Prepare and check locally

From the LabOS checkout, with the central optional dependencies installed:

```bash
.venv/bin/python -m pytest tests/test_public_gateway.py -q
.venv/bin/ruff check src/labos/public_gateway.py tests/test_public_gateway.py
```

Run the gateway as a separate supervised process using the **same private central
configuration** as the running central service. The config's `port` must be
18080 for the example below. The gateway derives its upstream exclusively from
`http://127.0.0.1:<config.port>`; it does not start another central instance or
open central's database.

```bash
.venv/bin/python -m labos.public_gateway \
  --config /path/to/private-central.yaml \
  --host 127.0.0.1 --port 18081 --max-inflight 32
```

The defaults are `--host 127.0.0.1 --port 18081 --max-inflight 32`.
Choose `--max-inflight` from 1 through 256 for the deployment; excess concurrent
requests receive a fixed 503 before their body is read. The limit applies per
gateway process, including health requests, and bounds upstream connections.
Size it for agent foreground/heartbeat and correspondence traffic together.
Keep the central configuration and all its credentials on the server. Restart this gateway when enrollments or
credentials change so its credential snapshot matches central.

In another terminal, check the local boundary before exposing it:

```bash
curl --fail --silent --show-error http://127.0.0.1:18081/health
curl --silent --show-error -o /dev/null -w '%{http_code}\n' http://127.0.0.1:18081/
curl --silent --show-error -o /dev/null -w '%{http_code}\n' http://127.0.0.1:18081/api/status
```

Expected: `/health` returns the real central health document with
`"service":"labos-central"`; `/` and `/api/status` return 404. If central is
unreachable, health returns 503 with a generic JSON error instead of claiming
that central is healthy.

## Activate the public endpoint after preparation

Only after tests pass and the local gateway is ready, the server operator can
publish **the gateway port** with this exact command:

```bash
sudo tailscale funnel --bg --https=8443 --yes http://127.0.0.1:18081
```

The operating system may require operator `sudo` rights to change Tailscale
configuration. Tailnet policy may also require an administrator to enable
Funnel. The code and tests do not run this command or change networking.

Inspect the resulting listeners, including the existing private listener:

```bash
tailscale funnel status
tailscale serve status
curl --fail --silent --show-error https://labos-gateway.example:8443/health
```

Verify that 8443 points to `127.0.0.1:18081` and private 443 retains its existing
central target. Test public health from a PC outside the tailnet; a successful
local check alone does not establish public DNS or remote firewall reachability.

To stop this public listener later while preserving the private listener:

```bash
sudo tailscale funnel --https=8443 off
```

## Remote PC configuration

Provision each PC with its own enrollment credential and set its `server_url` to:

```yaml
server_url: https://labos-gateway.example:8443
```

Use the normal system certificate trust and the PC's existing `agent_id` and
credential. Keep credentials in the private PC configuration; avoid putting them
in URLs, shell history, screenshots, or reports. The central operator credential
belongs only on the server and is rejected by the public PC API.

Run Doctor with this configuration, then the usual PC `cooperate send/pull`
commands or cooperation worker. Correspondence uses the same envelopes and
cursor queries as private central. The operator continues reading reports and
posting central replies through the private service or server-local connection.
Public HTTPS connectivity does not commission hardware or establish instrument
readiness.

## Public API contract

`GET /health` is public and forwards central's health document. All routes below
require `Authorization: Bearer <that PC's token>` and an exact matching enrolled
`agent_id`:

| Route | Allowed methods |
| --- | --- |
| `/api/agents/{agent_id}/health` | GET |
| `/api/agents/{agent_id}/messages` | GET, POST |
| `/api/agents/{agent_id}/register` | POST |
| `/api/agents/{agent_id}/heartbeat` | POST |
| `/api/agents/{agent_id}/poll` | POST |
| `/api/agents/{agent_id}/results` | POST |
| `/api/agents/{agent_id}/artifacts` | POST |
| `/api/agents/{agent_id}/pilot-artifacts` | POST |
| `/api/agents/{agent_id}/pilot-claims` | GET, POST |
| `/api/agents/{agent_id}/disconnect` | POST |

Other paths return 404; other methods on the listed paths return 405. The
gateway has no dashboard, operator APIs, evidence, planner, model endpoint,
OpenAPI schema, or interactive documentation. Operator credentials, another
PC's credential, duplicate authorization headers, unknown tokens, and missing
credentials cannot access the authenticated PC routes.

Authenticated bodies are capped before forwarding, including requests without
Content-Length: generic requests allow 8,388,608 bytes; message POSTs allow
65,536 bytes; artifact and pilot-artifact POSTs allow 2,000,000 bytes; pilot-claim
POSTs allow 4,096 bytes. A receive deadline of 15 seconds covers the whole body
and returns a fixed 408 on timeout. Central retains its established limits
on private upload routes. Request query strings, including message cursors,
are preserved. Only authorization,
content type, artifact hash, and boot ID headers are passed to the fixed
loopback upstream. Proxy environment settings and request-supplied host,
forwarding, cookie, or proxy authorization headers cannot select another
upstream. Redirects are rejected and credentials are never followed elsewhere.

Errors are JSON, responses carry `Cache-Control: no-store`, and upstream
operations have a 15-second total deadline including sending, headers, and the
complete response body. Transfer timeouts and transport failures return a fixed
503. The gateway never retries an upstream POST. Public error responses omit
upstream diagnostics and validation inputs; ordinary successful correspondence responses
still contain the messages requested by the authenticated PC. The standalone
server disables access URL logging and does not print private configuration
validation details. Keep any additional process supervisor or reverse proxy
logging free of credentials and request bodies.

Every successful upstream response has an 8,388,608-byte ceiling. The gateway
requests identity encoding, rejects unexpected encodings and redirects, checks
each raw chunk before retaining it, and returns a fixed 502 when the response
exceeds the ceiling. It closes the upstream stream on success, rejection,
timeout, cancellation, and downstream disconnect. Redirect bodies and ordinary
error bodies are not drained; only a 409 may be inspected, under a separate
4,096-byte ceiling. Only the exact known invalid-session object is reconstructed
as `{"detail":"invalid agent session","code":"invalid_agent_session"}` so an
Agent can re-register using its existing boot ID. Other errors stay sanitized.

The response ceiling admits maximum-size correspondence receipts and pages of
100 maximum-size messages without changing message cursors. It is an explicit
resource contract, not a guarantee that historically unbounded heartbeat
cancellation lists, configuration inventories, or open status dictionaries
always fit. An oversized heartbeat fails explicitly with 502; cancellation IDs
are never silently truncated. Operators must resolve such an oversized response
through the private service rather than treating an error as an empty stop list.
