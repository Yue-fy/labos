# Automatic central / PC assistant cooperation

The background worker receives explicit collaboration tasks, calls Codex and returns a report over the existing authenticated HTTPS channel. The central worker reviews the returned result automatically. Neither operator needs to announce each message.

The background runs are separate from interactive Codex chats. They receive the task and approved static context, not the private history of an IDE conversation. A worker is also separate from the PC execution Agent. Starting it does not register or control instruments.

## One-time PC setup

Use a verified complete portable package and separately provisioned PC identity,
credential and `cooperation.yaml`. Extract it into a permanent directory. Preserve
the production project, earlier packages and worker journals. Generic ZIPs contain
no live credential; no historical private bundle is required. Select the report
profile in [QUICKSTART_EN.md](QUICKSTART_EN.md) and validate the route using
[NETWORK_EN.md](NETWORK_EN.md).

1. Read `AGENTS.md` and this guide. An operator may run `Install.cmd`; a terminal assistant should use `powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\Install.ps1` to validate the portable Python runtime. No production Conda environment is needed.
2. Verify `cooperation.yaml` refers to this package's `config.yaml`, the actual PC ID, and the intended context snapshot. Preserve its empty instrument list.
3. Find the actual Codex executable and run `codex exec --help` and `codex login status` under the same Windows account that will run the worker. An IDE login alone may not establish CLI authentication. Configure `codex_command` as a YAML list containing the executable's full path. Prefer the native `codex.exe` over a `.cmd` shim. Paths containing spaces are supported.
4. The CLI must support `--ignore-user-config`, `--ephemeral` and `--output-schema`. If it does not, obtain a compatible CLI using the normal supported installation process. Do not bypass the worker's isolation flags to accommodate an old version.
5. Review the locally provisioned files listed in `context_files` (for example `LOCAL_CONTEXT_EN.md`). Correct only this static snapshot if needed, using the existing intake/review. Do not import production modules or open instruments to fill it. `context_files` is the explicit allowlist for material supplied to the model; maximum combined size is 32 KiB. Keep credentials out of it.
6. Run in PowerShell from the package directory:

```powershell
.\python\python.exe -B -m labos.cooperation_worker doctor --config cooperation.yaml
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\Install-Cooperation.ps1
```

The installer checks HTTPS authentication and CLI availability/login, adds a shortcut to the current user's Startup folder, and starts a hidden worker. This requires no administrator privileges. It starts after that user signs in, rather than before Windows login. Keep the directory in place. The PC needs to remain awake and connected to its configured approved route; Tailscale is needed only when that route requires it.

Read `data/cooperation/status.json` and `cooperation-worker.log` to verify startup. `phase: listening` with a recent timestamp means the last inbox check succeeded; it does not by itself prove Codex inference. No demonstration task is assumed to exist. After separate authorization, a new explicit report-only task and its matching result can check inference. A PC assistant can pull the central review once to inspect acceptance, but ongoing message handling needs no manual pulls.

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

Every generated report contains `status`, `summary`, `findings` and `questions`. Missing facts remain questions rather than invented device observations. This worker analyzes reports and supplied static code/context. It does not edit production code or initiate an experiment. A question needing operator input is returned in the report; it does not automatically authorize new work.

Malformed automation input and permanently rejected deliveries are quarantined in the local journal so later tasks can proceed. Transient delivery failures retain the cached reply and wait until the next poll interval. Oversized output produces a bounded failure report rather than disappearing. Use local diagnostics to investigate rejected jobs; do not delete the journal and blindly replay them.

## Recovery and model routing

Inbox cursors, jobs, backend invocation intents and generated replies are stored in `data/cooperation/correspondence.sqlite`. Each backend intent is committed before dispatch. A report has at most two backend invocations across Codex, local fallback, retries and restarts. The compatibility field `model_attempts` counts consumed backend reservations, including interrupted launches with uncertain outcomes; it does not count Codex's internal HTTP requests or prove provider computation occurred. A failed reservation permits no dispatch. Unclassified pending legacy rows with nonzero old attempts and no invocation ledger conservatively exhaust the allowance, since an old attempt could already have called both backends. Explicitly declared owned deterministic pilot/program responders preserve their old cycle counters and execution journals without inventing model invocations; any real backend intents already present remain counted. Deterministic pilot/program reports and source/capacity refusals spend no new invocation. Retryable evidence retrieval also spends none.

Generated output is committed before sending. Ambiguous network sends retry with the same ID and cached body, so cached reports are delivered unchanged without another generation, including legacy cached reports. If interrupted before caching an answer, already reserved invocations remain consumed. A pending report with one Codex intent resumes directly with configured local fallback in its final slot. Other retryable provider failures wait 60 seconds between polling cycles while slots remain; exhausted reports produce a terminal failure. The worker handles one pending message per polling cycle.

Successful HTTP responses are validated as complete pages before inbox or cursor
changes. A page must contain at most 100 messages, matching agent/sender identities,
ascending unique signed SQLite sequences and a cursor equal to its last sequence
(or unchanged for an empty page). Invalid JSON, HTML responses and malformed or
nonprogressing pages produce `phase: protocol_unavailable`. The durable inbox and
cursor are preserved, no provider is called for that tick, and a later valid page
can resume normal processing. Invalid task bodies within a valid envelope still
follow ordinary per-item rejection.

Original-task retrieval keeps an own-message cache and scan cursor in the same
correspondence database. Each lookup advances through at most two pages per tick;
`phase: preparing` means the scan remains incomplete, not that the parent is
missing. Progress survives restart, and previously scanned messages are available
from the cache. Only an empty validated page establishes a missing parent.
Preparation and retrieval spend no model reservations and share the current
operation's stop/deadline guard. Source scans also have independent entry,
directory and AST bounds; see [approved source context](APPROVED_SOURCE_CONTEXT_EN.md).
SQLite connections owned by the report, physical and program workers close after
their existing commit/rollback boundary, including early returns and exceptions.
Execution intent ordering and physical/program journals retain their existing
semantics.

The default poll interval is 10 seconds. Empty checks require no model call. On the central server, a configured loopback OpenAI-compatible model endpoint may serve as fallback when Codex fails, including authentication, quota or upstream network failure. Results record `codex`, `local`, `local_fallback` or `unavailable`. A failed request does not prove that its cause was quota exhaustion. A valid structured answer with `status: failed` or `needs_input` is a completed response and does not trigger fallback. This fallback belongs to the cooperation worker; it does not add failover to every LabOS feature.

One monotonic `model_timeout_s` deadline (180 seconds by default) starts before preparation and covers the active cloud/fallback cycle. When both backends and both slots are available, cloud receives a fixed half of the time remaining after preparation. An ordinary cloud failure or that cloud attempt deadline permits local only after owned-process cleanup and a fresh cancellation/deadline check. Local gets the actual remainder, never a fresh timeout. Without fallback, the sole backend gets the full remainder. Aggregate expiry, stop, reservation failure or exhausted slots cannot start fallback. A new preparation cycle after restart gets a new operation deadline, but never resets the durable two-invocation allowance. Local model loading or cloud cleanup can consume the remainder, so fallback completion is not guaranteed.

Before reserving either backend, the worker checks the exact rendered Codex prompt and every configured local request body against 131,072 UTF-8 bytes each. This includes policy, message, original task, supplied source/review evidence, approved static context, JSON escaping and local protocol/model metadata. It sends the checked local bytes unchanged. Oversize input returns a bounded `needs_input` report with zero new invocations; material evidence is never silently shortened to fit. Existing individual message/source/context limits still apply. Codex stdout/stderr are discarded; its dedicated answer file is ingested through a bounded read of at most 1 MiB plus one overflow-detection byte. This is an ingestion bound, not a producer disk quota. The local HTTP envelope is streamed and limited to 2 MiB before JSON parsing; unsupported content encodings are refused.

Codex runs in a temporary directory with read-only sandbox, disabled shell/execution, sub-agent, application, plugin, browser and device tools, and without inherited user configuration. Only explicitly allowlisted static snapshots and the task are supplied. The local backend receives no tool definitions. HTTP credentials remain in the transport configuration. Existing instrument leases, fault records, sessions and shutdown procedures remain outside this report worker.

## Stop or disable

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\Stop-Cooperation.ps1
# Also remove automatic startup:
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\Stop-Cooperation.ps1 -DisableStartup
```

Stopping cancels and joins the owned native async HTTP request, closes its resources, and prevents subsequent backend dispatch. Codex receives the exact checked prompt once through an owned private temporary input file (created with mode 0600 on POSIX), then uses a polled owned process and explicit terminate/kill/reap cleanup: up to two seconds for termination and two more for forced kill/reaping, without extending inference time. The file avoids Windows synchronous pipe writes that can block before `communicate` checks its timeout; no input is resent during polling. Input and schema preparation finish before the cloud reservation, and the parent closes the input handle after process teardown, before removing the private directory. A cleanup failure is terminal and cannot trigger fallback. The report CLI closes its correspondence client on every exit after construction.

These are cooperative operation limits, not a hard synchronous-return or worker-exit deadline. OS filesystem/resolver calls, runtime finalization and scheduling can delay completion. In particular, hostname resolution (including `localhost`) can leave an executor resolver job that `asyncio.run` waits for after cancellation of the HTTP task. Numeric loopback avoids that resolver path when already supported by deployment configuration; the worker preserves configured hostnames, TLS verification and certificate semantics. It never abandons a synchronous HTTP request in a background thread. Process cleanup owns the launched native Codex process; it cannot prove descendant work or already accepted provider computation has stopped. Legacy injected Python responders reserve once per call, but arbitrary synchronous injected code is not forcibly cancellable. Do not delete worker state to restart; doing so replays eligible old tasks from `start_after`. To run in a visible terminal for diagnosis:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\Start-Cooperation.ps1
```

Only one worker may own a given state directory. If a worker is already running, another launch exits instead of creating a competing consumer. The CLI `status` action prints the last recorded state and timestamp; a stale file is not proof that a process is alive.

Codex CLI's non-interactive invocation is described in the [official documentation](https://learn.chatgpt.com/docs/non-interactive-mode). Worker Doctor also checks the installed CLI directly; this package does not assume that an IDE extension provides an authenticated CLI on PATH.

## Evidence delivery capacity

The physical pilot keeps the complete immutable local raw JSON and its SHA-256, and records the execution as finished, even when the aggregate raw artifact exceeds the central 2,000,000-byte limit. The result then records `artifact.availability: local_only` and `evidence_delivery.status: blocked` with `raw_artifact_exceeds_capacity`, the actual local byte count and the unchanged cap. No upload is attempted for that known local refusal. An observed HTTP 413 is recorded separately as `remote_capacity_refusal`; it does not establish the remote server's actual capacity. Its raw availability is `unknown`, because an earlier upload may have been indexed before its receipt was lost. Both diagnoses are cached before correspondence delivery, so polling or restarting does not retry the refused raw upload or repeat physical execution. Transient transport failures retain the ordinary cached delivery retry path.

The complete correspondence envelope is checked against the unchanged 65,536-byte limit after source/pilot metadata is attached and again after delivery preparation. If reducing the answer is insufficient, the worker emits a bounded failure containing task and available plan/configuration/raw hash references, with explicit raw availability (`unknown` when no acknowledged indexing state is available). Oversized attached metadata is omitted from that failure envelope; immutable raw evidence is never shortened or rewritten. Existing central-indexed availability remains distinct from local-only evidence.

Central handles an explicit local-only or unknown-availability blocked result without fetching raw evidence reported unavailable or unconfirmed centrally, and without attempting model inference. This is a delivery diagnosis, not central raw verification or physical reconciliation. The outstanding physical claim remains blocked until the existing final raw-artifact verification and indexing requirements are satisfied; a summary or diagnosis cannot release it. Legacy raw artifacts and ordinary correspondence remain supported.
