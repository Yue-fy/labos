# LabOS Reliability and Commissioning Readiness

## Intent

Improve the existing LabOS implementation after real commissioning exposed long unobservable initialization, an exhausted acquisition budget, incomplete automatic review evidence and misleading stopped-worker status. The user requested at least three hours of optimization with multiple agents and postponed further physical experiments until an onsite wiring inspection. This work prepares a reviewable maintenance release; it does not deploy or run that release on laboratory hardware.

## Constraints

- All new product text, code comments, documentation and reports are English.
- No instrument I/O, physical tasks, remote PC activation, live configuration changes, production or lyr edits, or service restarts. Use injected device boundaries and disposable local test installations only.
- Preserve every existing numeric current, power, reference, excitation and duration limit; preserve exact diagnostic acknowledgments, fixed experiment scopes, local approval, exclusive ownership, durable no-replay and independent cleanup.
- A minimum SR830 excitation of 4 mV RMS is not OFF and is not a calibrated sample current. Numerical responses do not establish BVPE, nonlinear Hall or a current-voltage curve.
- Preserve compatibility with existing v0.2.8 profiles and raw artifacts. Additive diagnostics are optional on older artifacts. Never rewrite historical evidence.
- Never publish live experimental data, credentials, local station paths or private configuration. Test fixtures are synthetic.
- Isolate all changes from the deployed checkout. Publish reviewable source/package artifacts only after independent review and verification; installation and hardware validation wait for the onsite session.

## Approaches

1. Increase timeouts and expand remote Agent privileges. This would conceal latency and weaken the existing execution boundary; it is rejected.
2. Rewrite orchestration and instrument drivers. This is too broad for a maintenance window and risks previously demonstrated safety behavior; it is deferred.
3. Add bounded observability, earlier budget refusal, complete verified evidence, truthful lifecycle status and recoverable delivery. This is the selected engineering approach, chosen by the controller under the user's delegated optimization request. It preserves the architecture and makes the next onsite failure diagnosable.

## Components and contracts

### Engine timing and budget gate

Record monotonic elapsed and duration for open, preflight, each phase configuration, laser enable, settling, sample acquisition, independent protections and close. Bound the event list to 256 records and include explicit dropped count. Failure metadata identifies stage, phase, exception type, and whether the run or phase deadline is exhausted. A lightweight injected observation callback may receive already-bounded events; observer failure must never skip output protection or close.

Before enabling illumination, compare the remaining phase/run budget with settling, remaining sample intervals and the maximum observed successful dark sample duration times the requested illuminated sample count. If the measured estimate cannot fit, refuse before laser enable, retain dark data and run normal cleanup. Label this as an observation-based estimate, not a timing guarantee or a calibration. Do not extend any deadline. Zero-duration simulated reads remain valid; there is always a dark baseline before illumination.

### Adapter I/O diagnostics

Check acquisition cancellation/deadlines between individual session opens and clamp per-open timeout to the remaining run budget. Vendor ResourceManager construction cannot necessarily be interrupted; measure it and check immediately after return. Record a bounded ring of resource-open/query/write timing records with role, fixed command, effective timeout, outcome and bounded exception details. Do not add commands, retries, driver imports during Doctor, or chopper access to the readback-only scope.

Preserve the native exception while distinguishing an I/O timeout occurring with an exhausted acquisition deadline from a device failure occurring within budget. Capture the original failing transaction before cleanup overwrites last-I/O state. All protection transactions remain independent of exhausted acquisition guards.

### Verified automatic-review evidence

Verify fetched artifact checksums against exact response bytes, not a reserialized JSON object. Keep artifact/task/plan identity checks. Build a bounded model-facing projection with actual laser-current and emission readbacks by phase, accepted timing, rejected-sample phase/index/reason/last-I/O and bounded partial readbacks, close_error and timing/failure diagnostics. Explicitly report omitted/truncated data; link full immutable raw evidence by hash. Cap the entire projection at 32 KiB using finite JSON and deterministic reduction. Historical artifacts missing new fields remain supported.

Temporary artifact-fetch network errors retry as evidence retrieval without consuming model-generation attempts; authentication, integrity and schema failures must not feed unverified evidence to the model. Preserve reply identity and no-replay behavior.

### Worker lifecycle and event journal

Distinguish configured approval, profile validation, running/listening state and durable blocking. A stopped or stop-requested worker never reports physical_enabled=true. Cached status is explicitly a snapshot, with UTC update time and process identity; status inspection must not construct adapters, claim hardware state or latch an active intent. Lifecycle and finite acquisition progress are recorded as bounded credential-scrubbed JSONL events with rotation. Record exceptions and exit state without exposing credentials. Logs are engineering evidence, not an emergency stop or a guarantee that blocked vendor I/O has returned.

### Recoverable portable updates

Before changing shared source/dependencies, discover and lock all supported worker profiles in the installation, including custom profile filenames and program connectors. Refuse ambiguous/malformed worker profiles before mutation. Preserve credentials, all live configuration, journals and production files. Verify payload inventory and hashes first. Prepare a durable update journal and backups of replaced files plus inventory of newly added files. A handled write failure restores original bytes and removes only newly added update files. An interrupted/unresolved transaction blocks subsequent update attempts and provides a documented explicit recovery operation that holds the same worker locks. Never enable approval or start a worker as part of update/recovery.

## Validation and delivery

Start from the clean baseline and use meaningful RED/GREEN tests at injected clocks, mocked VISA, HTTP transport and temporary portable-installation boundaries. Exercise slow initialization, cancellation, phase/run expiry, cleanup failure, corrupt/missing evidence, lost replies, stopped status, custom worker locks, partial update failure and recovery. Run full Python and available PowerShell verification after integration. Build a versioned review package and inspect its manifest, portable layouts and absence of live data/secrets. Document exact improvements and limitations; no simulated check is hardware acceptance.

Provide an English onsite checklist covering electrode/source/reference topology, safe output readbacks, optical power plane, driver identity and a finite OFF/ON continuation. The first onsite action is observation and confirmation; no saved failed task is replayed automatically.

## Builder discretion

The builder may choose small helper modules, internal event names and backup/journal layout consistent with existing patterns. Add no dependencies, arbitrary shell execution, unattended maintenance privileges or automatic measurement retries. Any discovered issue outside this maintenance scope goes into the engineering backlog with evidence and risk.


## Delivery and native-validation extension

A later independent synthetic audit demonstrated unsafe Windows runtime ZIP names, credential-bearing partial personalized archives, overwritable versioned outputs and stale dependency wheels. The maintenance scope therefore includes shared portable archive validation, private no-replace staging, fresh per-build wheel resolution and immutable output publication. No previous release file is overwritten. POSIX0600 checks do not claim Windows ACL guarantees; credential bundles belong in a private user-controlled destination.

Add read-only GitHub Actions validation for Linux and native Windows, with immutable official action revisions and no production configuration or inference credentials. Native smoke builds the pinned embedded Python runtime and tests the current generic package in a path with spaces/non-ASCII using Windows PowerShell5.1; missing configuration must prevent Agent/server/instrument startup. Linux PowerShell checks remain useful but are not described as native Windows acceptance. No automated deployment or activation is added.

Primary filename rules: https://learn.microsoft.com/en-us/windows/win32/fileio/naming-a-file. Official action usage: https://github.com/actions/checkout, https://github.com/actions/setup-python, https://github.com/actions/upload-artifact (verified2026-10-31).
