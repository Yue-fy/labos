# Physical execution authority

This release adds **at-most-one attempted execution**, not guaranteed completion. One enrolled agent represents one physical station. Multiple agent IDs controlling the same station are unsupported. Central authority selects one worker configuration and scope and retains consumed task/message identities across profile changes. Each physical attempt requires a newly committed grant; even the same nonce never receives a second grant.

The tables start **uncommissioned**. Startup, a new state directory, missing history, and a correspondence cursor do not establish a safe physical state. Upgraded workers fail closed against missing/old endpoints, an uncommissioned authority, authentication failures, profile mismatches, or ambiguous receipts. Existing report/program workers and historical artifact downloads remain usable.

## Onsite cutover, performed later by the operator

No commissioning or instrument access is part of release verification. Before enabling authority onsite:

1. Inventory and retire all legacy physical workers, cached launchers, scheduled tasks and startup registrations, including copied installations and other accounts. Old binaries can bypass this protocol and must be stopped.
2. Reconcile every old physical execution and unresolved local state using the onsite procedure and independent instrument readbacks. Authority status does not prove current output state.
3. Select the exact enabled physical profile on the intended host. Run its Doctor without instrument access and record `config_sha256` and experiment scope. Referenced station and connection files must remain fixed while enabled; the worker hash covers the validated worker configuration and paths, not every referenced file's bytes.
4. From the private operator interface, attest retirement and reconciliation with an auditable note:

```text
labos pilot-authority commission --config CENTRAL_CONFIG --agent-id pc-a --config-sha256 SHA_FROM_PC_DOCTOR --experiment-scope optical_transport --note "Onsite inventory and reconciliation reference" --legacy-workers-retired --physical-states-reconciled
labos pilot-authority status --config CENTRAL_CONFIG --agent-id pc-a
```

`--worker-config PATH` can replace the hash and scope when that file resolves to the exact selected host paths; the CLI requires its approval to be enabled and its agent identity to match. A copied configuration resolving to different paths is a different profile. The API records operator attestations; it does not independently verify retirement, wiring or outputs.

Commissioning atomically records the correspondence cutoff and retires **every historical pilot task ID**, including tasks with no uploaded artifact. Only new post-cutoff messages with new task IDs may claim execution. Reusing an old task ID in a new message remains refused. New physical tasks must explicitly include `experiment_scope` (`optical_transport`, `optical_readback`, or `dark_a`); legacy scope-less tasks cannot execute.

Profile selection uses the same commission operation, and requires the same explicit acknowledgments. It takes a new cutoff and preserves consumed history. A selection change and a claim serialize in the same durable transaction: either selection wins and rejects the old profile, or the claim wins and prevents selection. Active or uncertain claims cannot be cleared or changed by recommissioning. This release has no timeout, reset, unblock or reconciliation API. Do not activate a station with an existing active/uncertain gate; a reviewed reconciliation workflow is deferred.

## Execution and evidence

The worker freezes the validated configuration for both its fingerprint and adapter settings/approval. It commits a local intent and random nonce before requesting authority and before constructing an adapter. Only the current invocation receiving an exact, newly committed grant may construct its adapter once. A lost or malformed receipt sacrifices the attempt and preserves uncertainty; retrying correspondence never requests a new grant. Definitive refusals are cached as `needs_input`, without a physical artifact. Unresolved local intents likewise do not invent competing UNKNOWN artifacts. Existing finished executions resend their original result and artifact unchanged.

An active/uncertain claim blocks other tasks and profiles for the same agent. Indexed raw evidence must match task, original message, plan, configuration, scope and nonce. Only COMPLETED/FAILED/CANCELLED with explicit `close_error: null` and nonempty independently verified final cleanup can release the gate. Cleanup requires laser emission OFF, zero current setpoint and measured 0.004 V RMS minimum excitation. Minimum excitation is not OFF. UNKNOWN, missing/malformed protection evidence or failed close retains the block. Artifact indexing and the claim transition are atomic. Retrying terminal artifact A after task B starts cannot clear B. Historical unclaimed artifacts remain readable and cannot clear any claim.

Doctor reports `authority_ready` only when central selection exactly matches the frozen configuration and scope, local approval/profile validation succeeds, and neither central blocking nor a local unresolved intent/latch exists. Doctor always reports `physical_enabled: false` and performs no adapter construction or instrument I/O. Readiness is diagnostic; the transactional claim remains the execution decision. InstanceLock still excludes duplicate local processes using one state directory. Profile selection is not a global process-liveness guarantee.

Only the enrolled agent's own credential can GET/POST its exact `/api/agents/{agent_id}/pilot-claims` route. Operator credentials cannot acquire execution grants. Commission/status remains private and operator-only; raw artifact downloads remain operator-only.

## Failure and backup limitations

Never delete or reset central or local history to unblock a station. A crash after claim commit, response loss, factory failure, or unavailable evidence can intentionally leave it blocked indefinitely. There is no automatic expiry. Preserve the central database and local execution journals/artifacts together and protect them from rollback.

Restoring a stale backup, losing both central and local history, or allowing a legacy binary to run invalidates unconditional at-most-once guarantees. Restored/missing/corrupt authority requires explicit onsite reconciliation and legacy retirement before any future activation. An empty database is not proof of clean history. This release cannot independently detect every stale restore and does not claim safe live cutover without those operator actions.
