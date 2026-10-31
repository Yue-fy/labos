# Automatic central / PC assistant cooperation — LabOS 0.2.3

The background worker receives explicit collaboration tasks, calls Codex and returns a report over the existing authenticated HTTPS channel. The central worker reviews the returned result automatically. Neither operator needs to announce each message.

The background runs are separate from interactive Codex chats. They receive the task and approved static context, not the private history of an IDE conversation. A worker is also separate from the PC execution Agent. Starting it does not register or control instruments.

## One-time PC setup

Use the personalized **LabOS-Cryostat-PC-0.2.3.zip** for cryostat. Extract it completely into a new, permanent directory. Keep earlier packages and the production project unchanged. The generic package has no PC credential.

1. Read `AGENTS.md` and this guide. An operator may run `Install.cmd`; a terminal assistant should use `powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\Install.ps1` to validate the portable Python runtime. No production Conda environment is needed.
2. Verify `cooperation.yaml` refers to this package's `config.yaml`, the actual PC ID, and the intended context snapshot. Preserve its empty instrument list.
3. Find the actual Codex executable and run `codex exec --help` and `codex login status` under the same Windows account that will run the worker. An IDE login alone may not establish CLI authentication. Configure `codex_command` as a YAML list containing the executable's full path. Prefer the native `codex.exe` over a `.cmd` shim. Paths containing spaces are supported.
4. The CLI must support `--ignore-user-config`, `--ephemeral` and `--output-schema`. If it does not, obtain a compatible CLI using the normal supported installation process. Do not bypass the worker's isolation flags to accommodate an old version.
5. Review `LOCAL_CONTEXT_EN.md` in the personalized package. Correct only this static snapshot if needed, using the existing intake/review. Do not import production modules or open instruments to fill it. `context_files` is the explicit allowlist for material supplied to the model; maximum combined size is 32 KiB. Keep credentials out of it.
6. Run in PowerShell from the package directory:

```powershell
.\python\python.exe -B -m labos.cooperation_worker doctor --config cooperation.yaml
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\Install-Cooperation.ps1
```

The installer checks HTTPS authentication and CLI availability/login, adds a shortcut to the current user's Startup folder, and starts a hidden worker. This requires no administrator privileges. It starts after that user signs in, rather than before Windows login. Keep the directory in place. The PC needs to remain awake and connected to Tailscale.

Read `data/cooperation/status.json` and `cooperation-worker.log` to verify startup. `phase: listening` with a recent timestamp means the last inbox check succeeded; it does not by itself prove Codex inference. The central demonstration task is already queued; a successful result is the inference check. A PC assistant can pull the central review once to inspect acceptance, but ongoing message handling needs no manual pulls.

## Task protocol

Send this JSON through the existing `labos cooperate send --kind note` tool. Assign a new task ID and message ID for a new task.

```json
{
  "protocol": "labos-agent-v1",
  "document_type": "labos_auto_task",
  "task_id": "connection-review-001",
  "instruction": "Summarize the supplied network evidence and list the remaining software integration gaps.",
  "context": {"network_round_trip": "accepted", "execution_heartbeat": "not_tested"},
  "executable": false
}
```

A task yields `labos_auto_result` replying to its envelope ID. The central worker reviews a matching result and sends terminal `labos_auto_review`. A review does not cause another model call. Ordinary notes, installation reports, intake documents and acknowledgments are archived without invoking a model. This prevents endless reply loops. Use explicit tasks when automatic analysis is wanted; an arbitrary chat message is not an executable command.

Every generated report contains `status`, `summary`, `findings` and `questions`. Missing facts remain questions rather than invented device observations. This version analyzes reports and supplied static code/context. It does not edit production code or initiate an experiment. A question needing operator input is returned in the report; it does not automatically authorize new work.

Malformed automation input and permanently rejected deliveries are quarantined in the local journal so later tasks can proceed. Transient delivery failures retain the cached reply and wait until the next poll interval. Oversized output produces a bounded failure report rather than disappearing. Use local diagnostics to investigate rejected jobs; do not delete the journal and blindly replay them.

## Recovery and model routing

Inbox cursors, jobs and generated replies are stored in `data/cooperation/correspondence.sqlite`. Generated output is committed before sending. Ambiguous network sends retry with the same ID and cached body, so a restart does not repeat that generation. An abrupt interruption before committing a generated answer can repeat inference. Failed inference gets at most two attempts, separated by 60 seconds; failure then produces a terminal report. The worker handles one pending message per polling cycle.

The default poll interval is 10 seconds. Empty checks require no model call. On the central server, a configured loopback OpenAI-compatible model endpoint may serve as fallback when Codex fails, including authentication, quota or upstream network failure. Results record `codex`, `local`, `local_fallback` or `unavailable`. A failed request does not prove that its cause was quota exhaustion. This fallback belongs to the cooperation worker; it does not add failover to every LabOS feature.

Codex runs in a temporary directory with read-only sandbox, disabled shell/execution, sub-agent, application, plugin, browser and device tools, and without inherited user configuration. Only explicitly allowlisted static snapshots and the task are supplied. The local backend receives no tool definitions. HTTP credentials remain in the transport configuration. Existing instrument leases, fault records, sessions and shutdown procedures remain outside this report worker.

## Stop or disable

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\Stop-Cooperation.ps1
# Also remove automatic startup:
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\Stop-Cooperation.ps1 -DisableStartup
```

Stopping waits for an active model call to finish or time out. Do not delete worker state to restart; doing so replays eligible old tasks from `start_after`. To run in a visible terminal for diagnosis:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\Start-Cooperation.ps1
```

Only one worker may own a given state directory. If a worker is already running, another launch exits instead of creating a competing consumer. The CLI `status` action prints the last recorded state and timestamp; a stale file is not proof that a process is alive.

Codex CLI's non-interactive invocation is described in the [official documentation](https://learn.chatgpt.com/docs/non-interactive-mode). Worker Doctor also checks the installed CLI directly; this package does not assume that an IDE extension provides an authenticated CLI on PATH.
