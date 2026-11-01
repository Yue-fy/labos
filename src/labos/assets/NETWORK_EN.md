# Network setup and connection diagnosis

PC components initiate outbound authenticated HTTPS to the provisioned central
`server_url`. They need no inbound PC port or SSH server. A generic ZIP contains
no live URL, identity or credential; obtain configuration through the operator's
established channel. Reserved examples such as `https://central.example.org`
are placeholders, never deployment addresses.

Use an approved LAN/VPN/private route or a restricted public PC gateway. Confirm
the actual hostname, port, DNS, proxy and firewall policy with the operator.
Public gateways expose scoped PC routes, not operator or model administration.
An HTTP connection is permitted only for an explicitly configured trusted
simulation network. Keep TLS verification enabled; do not replace HTTPS with
HTTP or copy another machine's token to make a check pass.

From the complete Windows package root, after provisioning:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\Doctor.ps1
```

Doctor checks connectivity and authentication without instrument access.
For report cooperation or the program connector, use that component's doctor
and configuration as described in [AUTOMATIC_COOPERATION_EN.md](AUTOMATIC_COOPERATION_EN.md)
or [PROGRAM_CONNECTOR_EN.md](PROGRAM_CONNECTOR_EN.md). A successful report
connection does not prove an execution Agent is connected or a physical pilot
is commissioned. See [QUICKSTART_EN.md](QUICKSTART_EN.md) for role selection.

On failure, preserve the exception type, timestamp and sanitized diagnostic log.
Check the configured endpoint and local clock, then DNS/routing, proxy/firewall,
certificate trust and PC enrollment. An authentication refusal needs matching
PC provisioning, not relaxed authorization. A timeout alone does not identify
which network layer failed. Do not publish tokens, full configuration or raw
credential-bearing logs. Preserve cached results and correspondence journals;
connection retries must not replay physical operations.
