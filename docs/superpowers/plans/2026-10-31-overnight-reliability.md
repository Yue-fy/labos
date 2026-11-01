# LabOS Overnight Reliability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the demonstrated LabOS workflow diagnosable, budget-aware and safely maintainable before the next onsite session.

**Architecture:** Preserve deterministic local physical execution and report-only LLM cooperation. Add bounded stage/I/O evidence, earlier illumination admission checks, complete verified central review, truthful lifecycle status and recoverable portable updates. No change is deployed to live laboratory workers tonight.

**Tech Stack:** Python 3.11+, existing Pydantic/httpx/SQLite/PyYAML, mocked VISA, PowerShell assets and pytest. No new dependency.

**Spec:** `docs/superpowers/specs/2026-10-31-overnight-reliability-design.md`

## Global Constraints

- All new product text, code comments, documentation and reports are English.
- No instrument I/O, physical tasks, remote PC activation, live configuration changes, production or lyr edits, or service restarts. Use injected device boundaries and disposable local test installations only.
- Preserve every existing numeric current, power, reference, excitation and duration limit; preserve exact diagnostic acknowledgments, fixed experiment scopes, local approval, exclusive ownership, durable no-replay and independent cleanup.
- A minimum SR830 excitation of 4 mV RMS is not OFF and is not a calibrated sample current. Numerical responses do not establish BVPE, nonlinear Hall or a current-voltage curve.
- Preserve compatibility with existing v0.2.8 profiles and raw artifacts. Additive diagnostics are optional on older artifacts. Never rewrite historical evidence.
- Never publish live experimental data, credentials, local station paths or private configuration. Test fixtures are synthetic.
- Isolate all changes from the deployed checkout. Publish reviewable source/package artifacts only after independent review and verification; installation and hardware validation wait for the onsite session.

## Review Focus

1. Slow or failed initialization must identify the stage while leaving unowned outputs untouched (Tasks 1–2).
2. Deadline expiry/cancellation and observer/logging failure must never suppress either independent protection or close (Tasks 1–2,4).
3. Valid noncanonical artifacts, missing evidence and oversized nested diagnostics must not produce false checksum claims or unbounded model input (Task 3).
4. Stopped/failed workers and competing/custom profiles must not appear ready or lose another installation's startup entry (Tasks 4–5).
5. Interrupted update and rollback failure must preserve a durable unresolved journal and block further mutation until explicit recovery (Task 6).

## Execution order

Run Tasks 1, 2, 3, 4, 9, 5, 6, 10, 11, 12, 14, 16, 7, 15, 13, then 8. Tasks 9–13 were added after independent audits proved cross-profile replay, public session recovery and durable model-budget defects. Task 8 remains the final integration/delivery gate. All additions remain offline and keep the original safety envelope.

## Verification environment

Use the dedicated sibling optimization worktree and the existing development interpreter for dependencies only. Prefix every Python/pytest command with `PYTHONPATH=<optimization-worktree>/src`; the PowerShell-enabled suite additionally sets `LABOS_TEST_PWSH=<verified-pwsh-executable>`. The controller provides resolved local paths privately at dispatch. Full suite baseline: 484 passed. Imports must come from the optimization worktree, never the deployed checkout. No agent may spawn helpers. Controller serializes implementers and dispatches separate task reviewers.

---

### Task 1: Engine stage evidence and illumination budget admission

**Files:** Modify `src/labos/pilot.py`; create `src/labos/pilot_diagnostics.py` if needed; modify `tests/test_pilot.py` or add `tests/test_pilot_timing.py`.

**Interfaces:** Existing `PilotEngine(adapter, clock=..., sleep=...)` remains compatible; allow optional `observer` callback. Results add `timing` (stages, dropped count, total elapsed), `failure` (stage, phase, exception type and deadline classification), and `budget_checks`. Adapter optional `diagnostics()` data may be captured defensively as `device_diagnostics` before and after cleanup without replacing original failure. Do not require adapters to implement a new method. Event records use `stage`, `phase`, `started_elapsed_s`, `duration_s`, `outcome`; callback receives a copied bounded record.

- [ ] Add behavior tests: delayed open/preflight stage durations, failed configure/laser_on stage, deadline scope, cleanup/close failures, observer exception isolation and bounded events; assert preserved existing status/ownership semantics.
- [ ] Add slow baseline test where remaining illuminated time is less than settle + sample_count × maximum successful baseline-read duration + intersample intervals: laser_on is never called, accepted baseline remains, cleanup verified, budget evidence labels `observed_baseline_estimate`. Add affordable/zero-cost simulations that still finish.
- [ ] Run new tests RED and record real failure before changing production.
- [ ] Implement instrumentation around real engine stages and the admission check immediately before laser_on, with phase/run remaining minima. Do not change plan schema, accepted sample counts, sleep durations, hardware bounds or protection priority. Preserve BaseException propagation while cleanup still runs.
- [ ] Run focused tests, full pytest and ruff. Commit independently and write task report with RED/GREEN, files, exact commit(s), limitations.

### Task 2: Bounded adapter I/O trace and initialization deadlines

**Files:** Modify `src/labos/cryostat_pilot.py`; optional shared diagnostics helper from Task 1; tests `tests/test_cryostat_pilot.py`, `tests/test_dark_a_pilot.py`.

**Interfaces:** Produce optional `CryostatAdapter.diagnostics() -> dict` containing at most 128 latest I/O/open events, dropped count, immutable first acquisition fault and last acquisition I/O, separate from later cleanup. Engine Task 1 consumes this optional interface. Existing `last_io` stays compatible.

- [ ] RED tests with injected/mocked monotonic clock and VISA manager: cancellation/deadline between opens; open timeout clipped to remaining time; manager construction measured and checked after return; partial open closes only its resources without output takeover.
- [ ] RED tests distinguish native timeout within budget from native timeout at exhausted deadline while preserving exception type/message; failing configure and laser_on still expose their original failing I/O after cleanup. Include trace bounds/truncated response and protection independence.
- [ ] Implement guarded per-open checks and clipped timeout, finite bounded trace events for manager/open/query/write, failure capture. Keep strict decoder, fixed commands and no automatic retries.
- [ ] Move standalone preflight CLI's existing 60-second guard before open, include diagnostics even on failure, no additional instrument queries.
- [ ] Run focused/full pytest and ruff; commit and report.

### Task 3: Complete bounded evidence and resilient retrieval

**Files:** Modify `src/labos/pilot_artifacts.py`, `src/labos/central.py`, `src/labos/cooperation_worker.py`; tests `tests/test_pilot_artifacts.py`, `tests/test_cooperation_worker.py`, `tests/test_pilot_worker.py`.

**Interfaces:** `review_snapshot(artifact, digest)` remains callable, projection is finite JSON <=32768 UTF-8 bytes, reports `snapshot_truncated` and omitted fields/counts. Include actual laser current/emission per phase, elapsed timing, rejected reasons and partial state/last-I/O, close_error, and optional Task1/2 diagnostics. Historical artifacts missing these remain valid.

- [ ] RED: synthetic ON actual-current + rejected PM READ? + close_error survive projection; oversized/deep nested preflight/trace remains <=32768 bytes with explicit omission markers and retains status/protection/hash.
- [ ] RED: central fetch of valid whitespace/noncanonical UTF-8 JSON verifies exact response bytes, mismatched bytes never reach responder. Transient HTTP evidence failure followed by success invokes model once and preserves generation-attempt budget; no result replay.
- [ ] Preserve exact stored bytes in the existing operator-only raw artifact GET route (add a verified byte accessor while keeping the object accessor compatible); verify exact HTTP content hash before JSON parse and task/plan binding; use bounded field projection rather than passing arbitrary raw dicts to model. Split temporary evidence retrieval retry handling from provider failure attempts; never weaken integrity/auth checks.
- [ ] Run focused/full pytest and ruff; commit and report.

### Task 4: Truthful worker lifecycle and bounded event journal

**Files:** Modify `src/labos/pilot_worker.py`; create focused `src/labos/pilot_events.py` if needed; modify tests `tests/test_pilot_worker.py`; only minimal base-worker changes if justified and reported.

**Interfaces:** Task1 `observer` receives bounded engine stage records. Status separates `configured_approval_enabled`, `profile_validated`, `physical_blocked`, lifecycle phase and `physical_enabled`; stopped/stopping/failed are never enabled. Cached status includes `snapshot_only`, UTC updated time, PID, generated `instance_id`, canonical `config_sha256`, and optional `launch_id` from environment `LABOS_PILOT_LAUNCH_ID` validated as exactly32 lowercase hex characters; it never claims current instrument output state. Add private per-state `events.jsonl` bounded to 1 MiB active plus one rotated file; credentials never appear in events.

- [ ] RED tests for clean stop, crash/failure, pending stop, active intent and cached status inspection without factory creation or state latch; preserve Doctor lock behavior.
- [ ] RED tests for begin/progress/failure/end journal events, credential-bearing exception redaction, rotation and logging failure during owned run; failed logging cannot skip protection or close.
- [ ] Add lifecycle state and event sink, connect engine observer, record original failure class and exit status without sensitive text. Status CLI is read-only and explicitly snapshot-only; no process liveness guarantee from cached PID alone.
- [ ] Ensure failure/interrupt exit writes a truthful terminal snapshot where possible, preserves active-intent no-replay and does not silently clear unresolved state.
- [ ] Run focused/full pytest and ruff; commit and report.

### Task 5: Windows startup ownership and launch verification

**Dependency:** Complete Task 9 shared physical authority first. Startup readiness is bound to the operator-selected canonical config fingerprint; per-profile names never authorize multiple controllers.

**Files:** Modify `src/labos/assets/Install-Pilot.ps1`, `Start-Pilot.ps1`, `Stop-Pilot.ps1`; create small shared PowerShell helper if needed; relevant tests in `tests/test_windows_scripts.py` or existing PowerShell test file discovered via rg.

**Interfaces:** Derive stable startup identity from resolved installation + profile path. Per-profile startup entry/log target; continue recognizing legacy `LabOS-Physical-Pilot.lnk` only if its target/arguments belong to the requested installation/profile. Never remove another profile's entry. No worker approval changes.

Verified physical Start/Install require the supplied embedded `python/python.exe`. Refuse the `.venv/Scripts/python.exe` redirector before worker launch and before startup registration, while retaining it for Doctor, metadata, cooperative Stop and other existing scripts. CPython's Windows venv launcher creates a separate interpreter process, so its launcher PID cannot satisfy this candidate's direct-child handshake. See the [primary launcher source](https://github.com/python/cpython/blob/3.14/PC/venvlauncher.c). A timeout or failed handshake after an actual launch can leave that child running; it must never be described as verified process exit or output protection.

- [ ] RED mocked PowerShell integration cases: two profiles/installs do not overwrite/remove each other; requested startup disable still attempts removal if runtime or config resolution fails; unrelated legacy shortcut retained. Use real script execution with mocked OS shell/child boundaries, not text-search tests.
- [ ] Add bounded child launch readiness check using Task4 status identity/update time and process result; failure returns nonzero with useful diagnostics, no forced kill or hardware state claims. Duplicate existing worker launch must be reported clearly without enabling another loop.
- [ ] Keep standalone portable paths/spaces and Windows PowerShell 5.1 compatibility; run PowerShell parse checks and available cross-platform script tests.
- [ ] Run focused/full pytest and ruff; commit and report limits of Linux-hosted Windows tests.

### Task 6: Transactional portable overlay with explicit recovery

**Files:** Modify `src/labos/assets/Apply-Pilot-Update.py`; create bounded internal helper only if packaging includes it; modify `tests/test_pilot_update.py`; add English recovery docs in `docs/PORTABLE_UPDATE_RECOVERY_EN.md`.

**Interfaces:** Keep `apply_update(update, target)` compatible, optional explicit config/profile list for nonstandard locations. Discover top-level recognized worker YAML/JSON profiles without executing commands; include default/custom pilot, cooperation and program connectors. Explicit `recover_update(target, transaction_id)` and CLI recovery option use recorded verified inventory, same locks, no approval or startup changes.

**Frozen builder contract:** The standalone updater/recovery must not import overlay or installed LabOS code. Recovery uses only the standard library and recorded profile hashes/state locks; apply may use the existing trusted base PyYAML before mutation, and this updater refuses payloads replacing that parser. The base interpreter/parser itself is a prerequisite, not a recovery target. Known filenames map to shipped defaults; custom parsed maps with agent/connection identity and explicit state paths are recognized. Omitted state paths require an unambiguous pilot/program/report discriminator or explicit kind declaration; ambiguous possible profiles refuse rather than guess. Malformed known or explicitly declared profiles refuse. Record the complete root configuration-candidate inventory and explicit profile paths/hashes; recovery refuses changed/missing/added candidates before payload mutation, so a newly introduced worker cannot escape recorded locks. Templates and payload-owned nonconfiguration JSON are explicitly excluded by the documented policy. Acquire a per-installation updater lock before checking unresolved transactions, and deterministic worker locks before any payload mutation. Journal `preparing/prepared/applying/rolling_back` are unresolved; only durable `committed/recovered` are terminal. All backups and inventory precede the first payload write. Recovery preflights every old/new/absent hash and backup first, refuses all user-edit conflicts without partial mutation, then rechecks each destination before restoration. File fsync/rename is not a portable power-loss or arbitrary-editor compare-and-swap guarantee.

Explicit profile declarations may resolve symlink aliases canonically; automatic root candidate symlinks may refuse. External declared state directories can be locked, while backup/control metadata must remain confined to the selected installation. Reject `.pth`, `sitecustomize.py` and `usercustomize.py` payload startup hooks as well as parser replacement, so a later interpreter invocation cannot execute newly inserted startup code before independent recovery.

- [ ] RED: active custom-named pilot and program connector block all mutation; malformed recognized profile fails closed; source/config/journals unchanged.
- [ ] RED: mid-write fault restores all replaced bytes and removes only introduced payload files; backup inventory records old/new hashes. Simulated interruption leaves journal unresolved and next apply refuses; explicit recovery restores bytes under worker locks. Rollback failure remains unresolved with exact recovery evidence.
- [ ] Verify all payload paths/hashes and profile identity before mutation, stage backups + durable journal, apply with per-file atomic writes, finalize journal only after success. Reject protected paths and symlink escapes, preserve prior backups and unrelated files. Do not auto-run recovery from an ambiguous partial state.
- [ ] Document stopped-worker/recovery workflow and unsupported platform hard-crash guarantees honestly.
- [ ] Run focused/full pytest and ruff; commit and report.

### Task 7: Offline commissioning rehearsal and onsite handoff

**Files:** Create `scripts/rehearse_commissioning.py`, `tests/test_commissioning_rehearsal.py`, `docs/ONSITE_COMMISSIONING_EN.md`, `docs/RELIABILITY_IMPROVEMENTS_EN.md`; update relevant README/agent guides with links and `scripts/build_pilot_update.py` with verified English guide inclusion.

**Interfaces:** A no-network CLI generates a clearly marked synthetic JSON rehearsal report in an explicitly chosen new output directory. Use real PilotEngine and fake-clock adapter, no driver imports. Scenarios: finite success; slow initialization/budget refusal before ON; I/O fault with partial evidence; failed cleanup blocks future execution in integration test. Include source version and limitations. No live production paths or credentials.

- [ ] Add RED tests for real engine scenario statuses, bounded evidence and zero vendor imports/network attempts; output paths cannot silently replace an existing evidence report.
- [ ] Implement minimal offline rehearsal and English checklist separating demonstrated software behavior from onsite wiring/calibration/driver checks. Checklist records electrode axes, source/current path, lock-in reference/input mode, optical power plane, chopper state and independent OFF/minimum readbacks.
- [ ] Include exact repeatable software acceptance commands, observed-estimate limitations, status/log paths, update rollback and tomorrow's finite-test entry criteria without pre-authorizing a new hardware task.
- [ ] Ship the actual new authority, update-recovery, onsite and reliability guides plus the canonical offline rehearsal script in the physical overlay payload/manifest, so recipients need no separate checkout or broken command paths. Generic builders already include root docs; keep a single canonical source for each guide/script and test overlay inclusion. Distinguish source-checkout commands from the script path actually shipped to a PC.
- [ ] Make generic PC/source onboarding documentation deployment-independent: replace personal production-source paths with reserved examples, remove assertions about already queued private demonstration tasks or private deployment bundles, and link the shipped physical/onsite guides. Preserve actual provisioned configuration and historical evidence untouched.
- [ ] Make active onboarding consistently English: add a canonical shipped NETWORK_EN.md, switch the CLI network-error help link to it, and refresh Quickstart/agent-kit/automatic-cooperation/role guides and active README links so they describe the actual separate report, generic execution and commissioned finite physical components. Remove old private-bundle-only installation assertions; historical version support is not proof of a currently provisioned installation. Preserve archived Chinese/bilingual repository reports; Task14 omits archived Chinese guides from new delivery ZIPs instead of rewriting them.
- [ ] Run script + focused/full tests + lint; commit and report.

### Task 8: Integrated verification, maintenance package and final review

**Files:** Verify the 0.2.9rc1 candidate version prepared in Task15 and update remaining delivery text, release notes and package QA metadata. This is a reviewable maintenance candidate, pending onsite commissioning and hardware checks. Do not modify old released packages.

- [ ] Run full suite with PowerShell and lint from isolated worktree; inspect failure-injection coverage and actual import paths.
- [ ] Build generic and physical overlay deliverables from committed source using existing pinned runtime/wheels in the main checkout; immutable new output filenames only.
- [ ] Verify manifest hashes, runtime extraction, protected-file preservation, all expected English guides/scripts, no live credentials/data; run portable smoke using isolated local temporary directories only.
- [ ] Controller dispatches whole-branch independent review of all implementation commits and resolves its single fix wave. Re-run only affected checks after fixes and full integration when warranted.
- [ ] Preserve user-requested >=3h active optimization window with timestamped work record; if further time remains, deepen concrete uncovered failure cases and explicitly record scope extensions before implementation. Deliver source branch, review bundle, QA evidence, remaining hardware limitations and onsite continuation.


### Task 9: Central at-most-one physical authority (before Task 5)

**Spec:** `docs/superpowers/specs/2026-10-31-physical-authority-design.md` (read this task-specific spec in full).

**Files:** Create `src/labos/pilot_authority.py`; modify `src/labos/central.py`, `pilot_artifacts.py`, `pilot_worker.py`, `public_gateway.py`, `cli.py` as required; tests `tests/test_pilot_authority.py`, `tests/test_pilot_worker.py`, `tests/test_public_gateway.py`; English `docs/PHYSICAL_AUTHORITY_EN.md`.

**Interfaces:** Own-agent GET/POST `/api/agents/{agent_id}/pilot-claims`; operator-only commission/status API and `labos pilot-authority` CLI. Authority begins uncommissioned. Canonical config hash comes from a frozen validated execution snapshot. New pilot tasks carry explicit `experiment_scope`; legacy scope-less tasks cannot execute. Existing profile loads/artifact history/report/program APIs remain compatible.

- [ ] RED synthetic two-profile sequential duplicate and cross-profile UNKNOWN cases; factory count <=1, unrelated task blocked while active/uncertain.
- [ ] RED lost-receipt, same nonce replay, restart after intent and definitive denial sequences; no competing synthetic UNKNOWN artifact and no second factory.
- [ ] RED historical cutoff seeding including no-artifact task IDs; reused retired task IDs remain refused after new message. Missing commissioning/old endpoint/auth mismatch/oversized claim never reaches factory.
- [ ] RED terminal A receipt-loss retry while B active: A retry is idempotent and cannot clear B; malformed/missing cleanup/close proof cannot release any gate. Selection vs claim transactions serialize safely.
- [ ] Implement durable transactional claims, selected profile/scope, active/uncertain gate, exact grant verification and claim-bound artifact transition, retaining every existing local safety layer. Add disabled/no-I/O Doctor readiness. No live commissioning.
- [ ] Document one-time onsite retirement/reconciliation attestations, selected profile changes, at-most-one semantics and failure/restore limitations. No automatic timeout/recovery/unblock.
- [ ] Run focused/full tests and lint; commit/report.

### Task 10: Public gateway streaming limits and session recovery

**Files:** Modify `src/labos/public_gateway.py`, `src/labos/central.py` for existing streamed upload checks, `src/labos/agent.py` only if necessary for a stable safe error signal; tests `tests/test_public_gateway.py`, `tests/test_agent.py`; English network guide.

**Interfaces:** Retain generic request8,388,608bytes and15s receive/upstream envelopes. Apply the existing central route-specific limits to messages65,536bytes, pilot artifacts2,000,000bytes and Task9 claims4,096bytes before buffering/forwarding. Stream upstream under8,388,608-byte response cap, close on all outcomes, sanitized502 for oversize. Known invalid-session409 propagates only through a closed safe signal allowlist; all other details remain sanitized. No internal POST retry. Legal100-message pages/maximum receipts must pass. Expose a bounded deployment concurrency option (default32 active handlers, CLI --max-inflight, valid1..256) with sanitized503 before reading overload bodies; no unbounded queued body buffers.

- [ ] RED streamed actual AsyncByteStream limit-1/limit/limit+1, unbounded fast chunks, oversized error/redirect, timeout/cancellation/closure, malformed length and unexpected encoding cases. Avoid ASGITransport-only false streaming proof.
- [ ] RED central-session loss through real gateway+Agent request causes re-registration; unrelated409 and malformed/untrusted errors do not. Never leak credential/body/private exception/Location headers.
- [ ] Implement bounded receive/streaming with the same total upstream deadline, fixed origin and per-PC auth/method whitelist. Check len(buffer)+len(chunk) before extending existing private central message/artifact loops too. Tighten existing route-specific message/artifact request caps only to their established central values; retain generic bounds elsewhere.
- [ ] Document response ceiling as explicit resource contract; do not claim every historically unbounded heartbeat/config dictionary always fits or silently truncate cancellation IDs.
- [ ] Use reserved example endpoints in the public network guide rather than publish this installation's actual host identity. Operators obtain their own verified Serve/Funnel URL; live server/client configuration stays unchanged.
- [ ] Run focused/full suite+lint; commit/report.

### Task 11: Oversized evidence and final-envelope delivery diagnosis

**Files:** Modify `src/labos/pilot_worker.py`, `src/labos/cooperation_worker.py`, possibly focused helper; tests `tests/test_pilot_worker.py`, `tests/test_cooperation_worker.py`; English reliability notes.

**Interfaces:** Keep2,000,000-byte central raw cap and65,536-byte correspondence cap. Preserve full local raw artifact and finished execution even if too large to upload. Emit an explicit bounded durable local-only/evidence-delivery-blocked report without claiming central raw verification. Central skips fetching nonexistent raw evidence and does not consume model attempts to diagnose known size refusal. Central physical claim remains blocked without verified final artifact.

- [ ] RED individually valid large synthetic samples whose aggregate exceeds2MB: local bytes/hash/finished execution persist, no repeated I/O on polling/restart, central receives truthful bounded delivery diagnosis and no oversize upload loop.
- [ ] RED oversized source_evidence/pilot_result fields after answer reduction still produce a complete valid<=65,536-byte failure envelope; original local evidence remains unchanged. Include multibyte/escaped text.
- [ ] Implement deterministic full-envelope check after all fields, safe minimal fallback with task/hash references only and explicit evidence availability; distinguish hard capacity refusal from transient transport. No truncation of immutable raw data and no cap increases.
- [ ] Run focused/full tests+lint; commit/report.

### Task 12: Durable model-attempt budget and bounded fallback

**Files:** Modify `src/labos/cooperation_models.py`, `src/labos/cooperation_worker.py`; tests `tests/test_cooperation_worker.py`, new focused responder-budget tests; English automatic cooperation guide.

**Interfaces:** Persist each model/backend invocation intent before dispatch. At most2 actual backend invocations total across Codex/local fallback/restarts for one report; label count as backend invocations rather than claiming internal model HTTP calls. Deterministic pilot/program/source paths retain0. Retryable evidence retrieval spends0. One aggregate configured model timeout covers cloud+fallback; a fresh fallback cannot reset the entire timeout. Report-only isolation flags remain verbatim.

**Frozen builder contract:** An optional focused `cooperation_budget.py` may hold the shared operation guard. Production responders expose a budget-aware entry point; legacy two-argument injected responders use an explicit one-reservation adapter, never retry-on-TypeError. Deterministic pilot/program/source classification occurs before dispatch (minimal explicit markers in their owned responders are allowed). Pending legacy rows with nonzero attempts but no new invocation ledger conservatively exhaust the allowance; cached replies still deliver unchanged. One operation guard starts before preparation; Task16 propagates it through bounded preparation. Use native async HTTP behind the synchronous CLI entry point, streamed inside one total cancel/deadline scope; do not abandon a synchronous request thread. Own/poll Codex Popen with bounded communicate/terminate/kill/reap, stdin supplied once, stdout/stderr discarded, isolation flags preserved. Require the exact rendered Codex prompt and exact serialized local request body each <=131072 UTF-8 bytes before the first reservation; compile/check every configured fallback representation too and send those exact checked bytes. Bound ingested Codex answer to1MiB and local decoded HTTP envelope to2MiB before parse. Reject unsupported content encodings rather than allow unbounded expansion. Guarantees cover owned client tasks/processes plus a stated finite cleanup allowance; they cannot prove provider-side computation already accepted has ceased.

**Fallback allocation:** When local fallback and two invocation slots remain, fix the first cloud attempt deadline to half the actual remaining aggregate time after preparation. Ordinary cloud failure or that attempt deadline permits local only after owned-process cleanup and a fresh aggregate/cancellation check; local receives the actual remainder. Aggregate expiry/cancellation, failed durable reservation or exhausted slots never starts fallback. A pending report with one persisted Codex intent and configured fallback resumes directly with local in its remaining slot. Without fallback, cloud or direct local receives the full remaining allowance. A valid structured failed/needs_input answer is a completed result, not a provider outage. The aggregate monotonic deadline covers one active preparation/dispatch cycle; the two-invocation cap persists across cycles/restarts. Cleanup may use its finite teardown allowance but never extends inference time. Preserve backend labels and state these limits honestly.

**Platform limit:** Cancel and join the owned native async HTTP task and forbid any subsequent dispatch after aggregate expiry/cancellation. Do not claim a hard synchronous-return or worker-exit deadline for OS hostname resolution/runtime finalization: asyncio executor shutdown can wait for a resolver after the awaiting task is cancelled (including localhost; numeric loopback avoids this resolver path). Preserve hostname compatibility and TLS; do not add a helper-process architecture in this task. The finite cleanup allowance describes explicit client/process teardown, not preemption of arbitrary OS resolver work. Document this limitation rather than silently abandoning a synchronous request thread.

Process teardown is limited to the owned direct native Codex Popen process, with bounded terminate/kill/reap. Do not introduce Windows Job Objects, ctypes, process-group or tree-killing architecture without a demonstrated supported native-client defect. State that descendants and already accepted provider computation are outside this teardown guarantee; preserve the existing native-path requirement and isolation flags.

Supply the exact checked Codex prompt once through an owned private temporary input file used as stdin, then poll communicate without a PIPE input write. CPython's Windows communicate writes stdin synchronously before its timed waits, so a stalled child could otherwise block the parent outside the timeout. Use one cross-platform path, POSIX0600 before writing, guards around preparation, reservation before launch and parent-owned handle cleanup after process teardown. Preserve all arguments/isolation flags. Filesystem calls retain the documented OS scheduling limitation.

The conservative legacy nonzero-attempt migration applies to unclassified/model-capable pending rows. Explicitly owned deterministic pilot/program responders and validated source/capacity paths that cannot invoke a model may retain zero new model reservations despite old responder-cycle attempts. Preserve the old attempt history, execution journals and any already recorded backend reservations; arbitrary backend strings or unclassified injected responders are not proof of determinism.

- [ ] RED simulated process termination immediately after invocation begin: restarts cannot reset invocation count. Cloud failure+local fallback counts2 and cannot run another cloud/local pair.
- [ ] RED fake monotonic delays demonstrate fallback receives remaining aggregate budget and no invocation starts after deadline/stop. Provider calls/subprocess launches are mocked; no live inference.
- [ ] RED assembled parent+source+snapshot+static input has an explicit finite UTF-8 byte budget; exceeding it returns a deterministic bounded needs_input report without inference and without silently dropping material evidence. Input cap131,072bytes for the serialized policy+message+static-context prompt (including UTF-8/JSON escaping); preserve all existing per-source/message limits.
- [ ] Bound/discard subprocess diagnostics since structured result is written to its dedicated file; bound file/HTTP result before parsing. Do not introduce tools, broaden filesystem/network privileges or disable TLS.
- [ ] Add final client close on report-worker exit. Task16 separately owns polling validation, resumable parent lookup and bounded source preparation; expose a callable operation guard that it can consume without changing model-invocation accounting.
- [ ] Run focused/full tests+lint; commit/report.

### Task 13: Sustained isolated durability/fault campaign

**Files:** Private acceptance harness/report under `.superpowers/overnight-20261031/` (never commit scratch or test data); public method/results may be summarized in `docs/RELIABILITY_IMPROVEMENTS_EN.md`.

- [ ] Run a sustained report-only transport/journal campaign on the reviewed integrated commit with disposable databases, synthetic identities/evidence, injected transient fetch/delivery failures, lost receipts and repeated worker restarts. No real PC, service, credentials or provider inference.
- [ ] Record elapsed UTC/monotonic duration, workload, injected faults, final idempotency/completeness checks, peak retained data/resource limits and source commit. Stop immediately on invariant violation, preserve evidence, fix via reviewed task before a new campaign.
- [ ] Use deterministic reproducible seeds and bounded rates/data; duration should observe long-running retry/status behavior, not merely repeat identical unit tests. Keep user informed while the campaign runs.
- [ ] Finalize after the user-requested >=3h optimization window and all required task/review/check work is complete.


### Task 14: Safe immutable delivery and fresh runtime dependencies

**Files:** Modify `src/labos/delivery.py`, `scripts/build_delivery.py`, `scripts/build_windows_runtime.py`; create focused portable archive/publication helper if useful; tests `tests/test_delivery.py` and new runtime-builder tests.

**Interfaces:** Shared platform-independent archive validation rejects Windows traversal, backslash/drive/ADS, invalid/reserved component/trailing-dot-space names, case aliases, duplicate files and file/directory conflicts. Read ZipInfo objects directly. Ordinary directory entries supported. Personalized bundles remain exclusive and private before writing credentials; failed calls leave no credential-bearing final/staging file. Generic release/runtime outputs never overwrite prior bytes. Fresh per-invocation wheels only.

- [ ] RED synthetic ZIPs demonstrate backslash escape, ADS, exact duplicate/case alias and remapped-wheel collision refusal before publication in both builders. Normal runtime directory entries still pass.
- [ ] RED personalized failure after configuration serialization leaves no final/private staging file; POSIX mode inspected during writing is0600 under umask022; existing output remains unchanged. Do not claim chmod is a Windows ACL guarantee.
- [ ] RED each versioned output/SHA256SUMS collision preserves every existing file; invalid runtime or late publication failure yields no mixed new release.
- [ ] RED stale historical wheel cache plus freshly selected new version packages only the fresh version and no duplicate destinations; failed build preserves prior runtime.
- [ ] Implement preflight+private temporary staging and no-replace publication, fail cleanup without touching existing unrelated files. Runtime wheel download uses a new temporary destination; cache only verified upstream Python separately. Verify destinations after wheel .data remapping as well as before. No dependency/version changes.
- [ ] Omit archived LabOS *_ZH.md guides from newly built package roots, embedded LabOS assets and generic root-doc copies while retaining historical repository files unchanged. Existing English quickstart remains; Task7 supplies the canonical English network guide/help link and updates active onboarding. This also prevents the old ACCEPTANCE_ZH.md absolute workstation path from being recopied into a new generic delivery. Do not filter third-party dependency content by language.
- [ ] Run focused/full tests/lint; commit/report.

### Task 15: Native Windows and Linux continuous validation

**Files:** Create `.github/workflows/validation.yml` and checkout line-ending policy `.gitattributes`; update `scripts/verify_windows_delivery.ps1` for explicit retained log output if needed; English validation guide. Prepare the 0.2.9rc1 candidate metadata in `pyproject.toml` and `src/labos/__init__.py` before triggering native CI; Task8 completes release QA afterward. No production runtime behavior change.

**Interfaces:** Public GitHub Actions read-only contents permission, push/pull_request/workflow_dispatch triggers (never pull_request_target). Use immutable verified official action SHAs; checkout persist-credentials:false. No production config/token/provider secret/hardware or live endpoint in any job.

- [ ] Ubuntu and Windows Python3.11/3.14 unit/lint matrix; preserve intentional platform skips with honest reporting. Add a native Windows job building the actual pinned embedded runtime and current generic Windows package, parsing all shipped PowerShell assets with Windows PowerShell5.1, then running existing verify_windows_delivery.ps1 through Windows PowerShell5.1 against the exact new ZIP. It must run embedded python/python.exe and reject absent config without starting Agent/server/instruments.
- [ ] Pin verified official refs: checkout3d3c42e5aac5ba805825da76410c181273ba90b1(v7), setup-python6d4fd22b20465ccc0f7354476588e8df7c9ca0e0(v7), upload-artifactcf430e030ddbb5b0abf93d22962f4752f3646cd9(v7). No arbitrary action version guesses. Sources https://github.com/actions/checkout and https://github.com/actions/setup-python verified2026-10-31.
- [ ] Retain generic checksum/install/test logs on failure, never personalized bundles. Use finite job timeouts/concurrency cancellation and no auto deploy/release/physical activation.
- [ ] Verify a native-built central ZIP retains LF shell shebangs and canonical Python source bytes, even with Windows Git defaults; enforce a portable checkout policy rather than treating OS-dependent archive bytes as identical.
- [ ] Validate YAML and PowerShell parse locally. After controller pushes the reviewed feature branch under existing authorization, inspect actual Actions results; fix real portability failures through reviewed scoped work. Do not claim native success before observing it.
- [ ] Commit workflow/docs/report; no artificial unit tests mirroring YAML.


### Task 16: Bounded preparation and resumable correspondence lookup

**Files:** Modify `src/labos/cooperation_worker.py`, `src/labos/source_context.py`; create focused page validator helper if useful; tests `tests/test_cooperation_worker.py`, `tests/test_source_context.py`; English cooperation/source guide. A small shared `src/labos/sqlite_state.py` transaction helper and focused tests may also replace worker/physical/program SQLite context ownership without changing journal schemas or transaction ordering.

**Interfaces:** Explicit successful-page validator for messages array, agent/sender identity, ascending unique SQLite-signed sequence0..9,223,372,036,854,775,807, and next_cursor matching last returned record (or unchanged after empty page). Malformed page has a fixed protocol-unavailable status and no inbox/cursor mutation. Invalid task bodies still use ordinary per-item rejection after valid page ingestion.

- [ ] RED200HTML/missing/wrong fields/stalled-backward/out-of-range cursor cases followed by a valid page: unattended tick survives, previous durable cursor unchanged until valid response, no model or physical replay.
- [ ] RED old parent beyond several pages: durable own-message cache + resumable scan advances at most2 pages per lookup/tick, survives restart/stop, eventually finds valid parent without archiving it as missing. Distinguish incomplete scan from confirmed missing and reject nonprogressing pages. Evidence preparation spends0 model attempts.
- [ ] RED source index with >10,000 entries or >1,000 directories and few matches terminates with explicit truncation/scan metadata; cancellation/deadline checks between filesystem operations. Avoid os.walk collecting an unbounded directory before the counter runs; use bounded scandir iteration and sorted retained results. Preserve <=250 matches, <=1MiB file read, <=4096-byte excerpt and <=12KiB evidence limits.
- [ ] Add optional guard callback to ReadOnlySources.collect/one and propagate Task12 operation guard. Standalone source CLI retains bounded scan counts even without a callback. A blocked OS filesystem call is not a hard real-time guarantee; state that limit.
- [ ] Bound AST outline traversal/retained definitions so large allowed source files do not render every node before final truncation. Preserve handle-verified confinement, no symlink/production import, exact source hashes and explicit truncation.
- [ ] Close report, physical and program worker SQLite connections deterministically after commit/rollback, including constructor marker checks. A disposable200-transaction reproduction grew descriptors from4 to204 when garbage collection was disabled, returning to4 after collection; current connection contexts commit but do not close. Preserve BEGIN IMMEDIATE/FULL settings and durable intent ordering. Add real commit/rollback/closed-connection tests independent of garbage collection, including early return and exceptions; do not redesign journals or close a caller's live transaction early.
- [ ] Run focused/full tests+lint; commit/report.


### Task 17: Fresh physical commissioning template observations

**Files:** `src/labos/assets/pilot-worker.example.yaml`; focused delivery/update tests if needed; English commissioning guide note.

**Interfaces:** New-package examples are uncommissioned defaults, never transferred evidence of a past physical observation. Existing operator-owned configuration and history stay byte-preserved during update.

- [ ] Remove the real sample label and inherited dated chopper Locked affirmation from the canonical example: generic sample label, manual confirmation false and empty note. Preserve all numerical physical limits, fixed driver/identity contracts, approval disabled, commissioned false and route confirmation false. No actual lab config/history edits.
- [ ] Check other shipped example templates only for inherited affirmative physical observations; do not broaden driver authority or rewrite historical evidence.
- [ ] Verify actual newly built generic/physical template payloads have fresh defaults; confirm updater preservation of an existing stopped operator configuration remains covered. Focused regression and lint; integrated full suite remains Task8.
- [ ] Document current onsite observation/preflight as required; no device/network/model calls or local activation.


### Task 18: Observed Windows unit/runtime portability failures

**Files:** `src/labos/files.py`; `tests/test_pilot_update.py`, `tests/test_source_context.py`, `tests/test_windows_runtime_builder.py`; narrowly affected export tests only if additional meaningful coverage is needed.

**Evidence:** Actual initial Actions run41256130299 Windows Python3.11 unit result:94 failed,905 passed,46 skipped. JUnit identifies86 updater fixture byte/newline failures,3 source fixture encoding/hash failures,4 real HDF5 export failures with EBADF, and1 unsafe wheel-path fixture whose backslash is normalized by the Windows ZIP writer before validation. Inspect the3.14 JUnit too before assuming identical causes. Linux cells and native Windows installer job passed; none supersedes these failures.

- [ ] Fix the actual Windows HDF5 temporary-file flush failure using a valid owned handle without changing snapshot selection, raw/audit data, atomic replacement or failure preservation. Existing native failing export integration tests are RED evidence; verify native GREEN after publication.
- [ ] Make synthetic fixture encodings/newline bytes explicit where tests assert exact bytes. Preserve the production source collector's hash of actual original bytes, updater's exact-byte preservation and all transaction/lock/authority assertions. Never normalize protected production files to satisfy tests.
- [ ] Ensure unsafe wheel-path fixtures serialize the intended raw backslash member on Windows as well as Linux; constructing ZipInfo on Windows otherwise normalizes it before validation. Keep rejection coverage and production validation unchanged rather than silently skipping it. Existing distinct-version duplicate-distribution fixtures remain intact.
- [ ] Run focused affected tests and lint; run full suite once for any runtime code fix. Independently review; controller will observe actual Windows3.11/3.14 and native jobs on the updated candidate. No broad dependency changes, hidden blanket skips, hardware/provider/live config/service access or measurement.
