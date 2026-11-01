# Shared Physical Execution Authority

## Problem and scope

The reliability audit found that two locally enabled physical profiles with separate state directories can sequentially execute the same central task. They also have independent UNKNOWN latches. A per-run hardware lease prevents simultaneous device access, but cannot prevent sequential replay. Profile-specific startup names must not make this worse. This design adds a conservative central authority to the upgraded physical path; no live server or PC will be changed during development.

All constraints in `2026-10-31-overnight-reliability-design.md` apply unchanged. This is at-most-one attempted execution with explicit reconciliation, not exactly-once completion. No time-based lease expiry permits physical replay.

## Selected approach

Keep existing profile-local inboxes, execution intents, immutable raw artifacts and state locks. Add central durable claims keyed by enrolled agent plus task/message identity, a per-agent active/uncertain gate, and one operator-selected canonical worker-config fingerprint. Configuration hashes are provenance/selection only, never a fresh deduplication namespace.

A shared local journal alone needs mandatory cross-installation/user paths and legacy migration. An ordinary central TTL lease can admit a partitioned old controller and is rejected. Central authority is chosen because it already owns the task identity and raw evidence. It cannot restrain old binaries that do not request grants; their retirement is an explicit deployment condition.

## Commissioning and compatibility

Authority tables are created uncommissioned. Neither server startup, missing tables, a new profile, an empty journal nor a cursor offset establishes clean history. Existing report/program/simulation APIs, old artifact downloads and profile loading remain compatible. Upgraded physical execution fails closed against an uncommissioned or older server/gateway. Disabled profiles and report-only workers remain usable without commissioning.

A new operator-only `labos pilot-authority commission` operation requires agent identity, selected enabled worker-config SHA256, exact experiment scope and an auditable note, plus explicit true acknowledgments that legacy workers/startup are retired and old physical states have been reconciled. This records attestations, not an independent verification of wiring or outputs. The operator performs this later at the onsite cutover. No test or release task may invoke it against the live server.

In one durable transaction, commissioning records the current correspondence sequence cutoff and retires task IDs from every historical central pilot task at or below that cutoff (including tasks without uploaded artifacts). New claims require a strictly post-cutoff central pilot message with a new task ID. Reusing an old task ID under a fresh message cannot bypass retirement. Recommissioning cannot erase consumed claims or clear an active/uncertain gate. Selected profile/scope may change only while no claim is active/uncertain; existing claim history remains. Missing/corrupt/restored authority requires explicit reconciliation; no automatic reset. One enrolled agent represents one physical station; multiple agent IDs for the same station are unsupported until centrally aliased by a reviewed design.

## Agent protocol

Use exact own-agent authentication for GET/POST `/api/agents/{agent_id}/pilot-claims`. GET exposes only bounded readiness/selected fingerprint/scope/cutoff/block status for Doctor. POST has a bounded schema containing original message ID, task ID, canonical plan hash, config hash, experiment scope and random attempt nonce. It is not an arbitrary control endpoint. Only these exact methods/routes are added to the restricted gateway. Operator credentials cannot obtain a PC execution grant.

Central validates the claim against the stored central-origin pilot task and its plan, the selected config/scope, cutoff, retired identities and active/uncertain gate. A future pilot task must include an explicit experiment scope; legacy scope-less messages are non-executable under the upgraded path. All checks and insertion occur in one BEGIN IMMEDIATE transaction. Unique constraints cover both agent/task and agent/message.

Grant execution only when this HTTP request newly commits the claim. Any existing claim, even with the same nonce, never regrants. Grant receipt binds all supplied identities. Persist the attempt nonce locally before the request. Freeze the validated worker-config snapshot used to compute the hash and pass that same snapshot to adapter construction; do not hash one mutable object and execute another. Referenced station-file contents remain subject to the existing local validation and must not be edited while enabled; the hash selects the worker configuration, not every referenced byte. Lost response, malformed receipt, old server, denied claim or authentication failure causes zero adapter constructions. The local intent remains committed; generic report retries must not request a new physical grant or execute. Sacrificing an unexecuted attempt is preferable to replay. No claim expires automatically.

The worker validates local approval and exact commissioned scope, then commits its local intent before requesting a claim and before constructing an adapter. A new verified grant permits that current process to invoke the adapter once. Existing local finished executions retain their exact result/artifact and retry delivery without requesting a new claim. Existing unresolved intents preserve their local latch. No code path falls back to local-only physical execution.

Doctor and runtime startup readiness compare the canonical config hash and scope with central selection, without importing drivers or opening instruments. Distinct roots/state paths produce different config fingerprints, so only the selected profile can become execution-ready. Duplicate processes with that same state remain excluded by InstanceLock. Central claims independently prevent same-task replay and overlapping distinct tasks. Do not infer current instrument output state from authority readiness.

## Completion and uncertainty

An indexed raw artifact, not a reply summary, resolves the active gate. Bind artifact task/message/plan/config identity to its claim. Atomically record terminal state with artifact indexing. COMPLETED/FAILED/CANCELLED with independently verified protection and successful close may release the gate for a different task; every consumed identity remains consumed. UNKNOWN, unverified protection, close failure, missing closure proof or malformed final evidence holds an uncertain gate. Absence of an uploaded artifact is never proof that execution did not happen.

A duplicate caller must not synthesize and upload a contradictory UNKNOWN artifact over another profile's valid claim. Return a bounded non-execution `needs_input`/authority-denied report, preserve its local intent as non-replayable, and leave original central evidence untouched. The local ledger must distinguish claim denial/no adapter from uncertain physical execution while never granting replay. Grant-receipt loss remains conservatively blocked pending review.

Existing historical artifacts without claims remain stored/readable and cannot clear a new active claim. Raw artifact routes retain operator-only reads. No own-agent raw download is added. Finalization is monotonic and claim-specific: retrying terminal artifact A while B is active cannot clear or alter B. Require an explicit null close_error plus a nonempty verified cleanup list including final-scope independent laser OFF/zero-setpoint and minimum-excitation proof; missing/malformed evidence retains uncertainty. Compare profile selection and scope inside the same durable claim transaction, and refuse reselection inside its transaction while a claim is active/uncertain. Definitive refusal is durably cached as needs_input without a pilot artifact; ambiguous receipt loss is durably latched and also creates no competing terminal artifact. Only an invocation with a newly validated grant that attempted adapter construction may submit claimed raw execution evidence.

Active/uncertain claims have no automatic reset operation in this release; an explicit reviewed reconciliation workflow is a future operation, and onsite activation must not proceed if such a gate already exists.

## Validation

Use temporary SQLite and TestClient/MockTransport only. Cover two separate profiles receiving the same task, different task IDs racing, profile mismatch, lost claim receipt, same nonce retry, restart after local intent, cross-profile UNKNOWN blocking, artifact upload retry, finished local recovery, old server/gateway, wrong-agent/admin credentials, oversized/malformed claims, missing commissioning, historical tasks with and without artifacts, task-ID reuse beyond cutoff, and profile switch preserving consumed history. Assert factory/physical-event counts and durable state, not merely HTTP codes. Preserve all approval, ownership, cleanup and numerical-limit tests.

## Delivery limits

The maintenance release can include this code and offline evidence, but cannot claim safe live cutover without the operator's onsite inventory, old-worker retirement and reconciliation. Backup restore or full loss of central and local history cannot retain unconditional at-most-once guarantees. Document this explicitly.
