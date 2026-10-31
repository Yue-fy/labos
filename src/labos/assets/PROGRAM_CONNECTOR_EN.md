# Program-only PC connector

Use this profile on PCs with no Codex, no local LLM and no Tailscale client.
The PC makes outbound authenticated public HTTPS requests to the central
correspondence service. The central analyst can use Codex or an LLM; the PC
returns deterministic program results and approved source text. No inbound
PC port is required. This profile does not start the instrument Agent.

## Provision the PC

Use the existing portable Python package (or run `Install.ps1` to prepare the
package Python). Obtain a real central public HTTPS origin, PC identity and
unique bearer token through your deployment operator. The central endpoint
needs valid TLS and must forward `/health` and the authenticated
`/api/agents/<agent-id>/messages` API. A private Tailscale-only address cannot
serve a PC that has no Tailscale client. Do not disable certificate validation.
An explicitly provisioned `ca_file` and `proxy_url` in `agent.yaml` are supported.

Keep credentials only in the local provisioned `agent.yaml`, with an empty
`instruments` list for this profile. Do not send the file to the analyst.
Use a different state directory from the execution Agent and report worker.
Create `program-connector.yaml` alongside the scripts:

```yaml
agent_id: pc-a                  # must match the locally provisioned agent.yaml
connection_config: agent.yaml  # server_url must use public HTTPS
state_dir: data/program-connector
poll_s: 10
source_roots: {}                # optional local labels mapped to approved directories
programs: {}                    # no custom programs enabled by default
```

Run `Install-Program-Connector.ps1`. It runs connector diagnostics, creates
`LabOS-Program-Connector.lnk` in this Windows user's Startup folder, then
starts the connector. It does not install or log in to Codex. Windows sign-in
is required for Startup-folder launch. Keep the package directory in place.
`Start-Program-Connector.ps1` starts it manually. Inspect
`data/program-connector/status.json` and `program-connector.log`.
Run `Stop-Program-Connector.ps1 -DisableStartup` to request stop and remove
automatic startup. Stop waits for an active approved program's bounded call;
it is not an emergency hardware stop.

For manual diagnostics with the package Python:

```powershell
. .\Resolve-Python.ps1
$Python = Get-LabOSPython $PWD.Path
$env:PYTHONPATH = Join-Path $PWD.Path 'src'
& $Python -B -m labos.program_connector doctor --config program-connector.yaml
& $Python -B -m labos.program_connector once --config program-connector.yaml
```

## Central task contract

Send the following JSON body through the existing authenticated correspondence
API as a central message with a unique immutable message ID:

```json
{
  "protocol": "labos-agent-v1",
  "document_type": "labos_program_task",
  "task_id": "check-pc-a",
  "instruction": "Collect a deterministic runtime check.",
  "program_id": "runtime_check",
  "parameters": {},
  "context": {},
  "executable": false
}
```

`instruction` is a description for central review; it cannot select commands.
`executable:false` describes the correspondence document. Local approval of
`program_id` controls whether the connector runs a program. The reply uses
`labos_auto_result`, backend `program`, and a validated deterministic answer.
The central report worker may review the result against its original task.
The connector ignores `labos_auto_task` and review messages. No PC model runs.

Built-ins are `runtime_check` (Python version, no instrument initialization)
and `source_snapshot`. They accept no parameters. To use `source_snapshot`,
register a local source directory under `source_roots`, then include
`context.source_requests`, for example:

```json
{"source_requests": [{"root": "reference", "path": "acquire.py", "kind": "outline"}]}
```

The local host collects bounded `.py` / `.md` text or AST outlines and attaches
`source_evidence`. It does not import or execute the reference code. Source
paths must remain relative to a locally registered root. Register only approved
source trees, never credential/configuration directories. Sending source text
is a disclosure to the central analyst and should stay within local approval.

## Adding a local non-hardware program

The catalog below is an illustrative schema, not an installed acquisition
entry. A local operator must review and install a real program before enabling
it. The executable path must be absolute. Every argument is fixed locally;
peer parameters are validated, encoded as one JSON object and supplied through
stdin, never substituted into argv. Unknown parameters, wrong types, missing
required values, invalid choices and values outside local limits are rejected.

```yaml
programs:
  offline_check:
    enabled: false
    argv: ['C:\LabOS\python\python.exe', 'C:\Approved\offline_check.py']
    cwd: 'C:\Approved'
    timeout_s: 30
    max_output_bytes: 8192
    hardware: false
    parameters:
      sample:
        type: string
        required: true
        choices: [reference-a, reference-b]
      count:
        type: integer
        required: true
        minimum: 1
        maximum: 3
```

Supported parameter types are string, integer, number and boolean. Numeric
parameters require explicit minimum and maximum. Strings have a default
256-character maximum; `max_length` can reduce or extend that up to 4096.
Timeout is limited to 600 seconds and combined stdout/stderr to 16384 bytes.
The connector uses `shell=False` and rejects batch and PowerShell executable
entries. It does not execute a remotely supplied command, executable or path.

An approved program runs with the Windows user's permissions. The catalog is
an approval boundary, not an OS sandbox. Enabled code can affect devices or
start child processes; status therefore reports possible hardware access when
custom programs are enabled. Wrappers must implement safe cleanup and child
process management. Keep configuration and approved programs writable only by
trusted local operators. Programs must not print credentials.

No hardware program is configured or enabled here; `hardware:true` is rejected.
Integrating measurement code requires separate local commissioning, verified
model-specific stop behavior, explicit physical parameter limits and the
existing execution ownership rules. Do not mark acquisition code as an offline
check to bypass that work. This installation does not establish hardware
readiness or grant physical-control authority.

## Crash recovery and reconciliation

Preserve both `correspondence.sqlite` and `program-executions.sqlite` in the
state directory. The separate execution ledger keys each request by the
incoming immutable message ID. It commits `started` before program launch,
then persists the validated result as `finished` before attempting delivery.
Transport retries and restarts reuse finished results without rerunning code.

If the connector crashes after intent was committed but before a result was
saved, it cannot know whether the program launched or completed. A replay
returns `needs_input` for local reconciliation and does not launch it again.
Timeouts and output-limit stops also require reconciliation; a killed process
is not evidence that physical effects or child processes were undone.

Inspect local logs, program records and the actual device state under the
commissioned procedure. Keep the uncertain ledger record intact. Only after
local reconciliation may an operator authorize a new message ID for another
attempt. A new ID is a new execution request, even when task_id is unchanged;
central callers must retain the same message ID when retrying delivery. Never
delete journals or invent a new ID merely to force an uncertain action to run.
