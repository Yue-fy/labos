# Cryostat physical pilot implementation plan

> For agentic workers: use superpowers:executing-plans or subagent-driven-development task by task, with TDD and an independent final review.

**Goal:** Implement a LabOS-owned finite 730nm photoresponse / dark transverse2f pilot with deterministic local protection and real typed data, without launching the existing complete procedure.

**Architecture:** A separate opt-in physical worker receives `labos_pilot_task` documents over existing scoped HTTPS correspondence. A local commissioned profile selects a fixed LabOS adapter; peers cannot select commands or production entry points. The physical engine owns finite phases and cleanup. Existing source is reviewed as driver evidence; its whole application is never launched. Report workers remain report-only.

**Tech stack:** Existing Python/Pydantic/httpx/SQLite. Windows vendor I/O runs in the commissioned local Python environment. No new external automation framework.

**Spec:** `subComputer/cryostat/LABOS_BVPE_NLH_PILOT_EN.md`, with the operator clarification below superseding its earlier excitation-isolation requirement.

## Current operator clarification

Sample label CrSBr 1. No external series resistor. Electrode mapping may remain unverified and raw channels XX/XY/AUX are acceptable. The operator explicitly permits reducing SR830 to its minimum4mV RMS after tests, preferring zero only if supported. Do not label minimum output as OFF or derive sample current from contact-resistance assumptions. Do not automatically increase excitation. Laser OFF is still required.

Historical 730nm records support21.8mA/approximately0.483uW PM-pickoff and22.7mA/approximately0.980uW; they are not sample-plane calibration or a current-source transport record. Conservative candidate pilot settings must remain within the commissioned local profile. Existing fault records, production files and lyr remain unchanged.

## Global constraints

- Keep product code, scripts and new reports English.
- Existing model/report workers never receive device tools.
- No gate/temperature/field/motion control. Check starting state without clearing faults or taking over another owner.
- No whole legacy CLI/notebook invocation, no remote arbitrary shell/Python/SCPI interface.
- Missing local commissioning facts keep physical execution disabled.
- Keep partial raw data, plan/config hashes, actual readbacks and independent cleanup outcomes.
- Use physical voltage/time/power units; no fabricated spectra, sample currents, device axes or physics claims.
- Output errors and unknown outcomes inhibit replay; a minimum-amplitude readback is not a physical OFF claim.

## Shared core interfaces

`src/labos/pilot.py` exports:
- `PilotPlan`: sample_id:str, mode:Literal['photoresponse','dark_hall','combined']; laser_current_a:float|None; power_limit_w:float|None; reference_hz:float; excitation_v_rms fixed0.004; samples_per_phase1..10; interval_s0..10; settle_s0..30; phase_timeout_s5..90; max_run_s5..300. Validate finite values and mode-specific requirements.
- `PilotApproval`: enabled:bool=False; sample_id:str; laser_current_max_a:float|None; power_limit_max_w:float|None; reference_hz:float; excitation_v_rms fixed0.004; max_phase_s; max_run_s. Exact sample/reference match and plan<=local limits; no physical defaults.
- `PilotEngine(adapter, clock=time.monotonic, sleep=time.sleep)`; `.run(plan, approval, cancel=None)->dict`. No subprocess/network/model code.
- Adapter methods: `open()`, `preflight()->dict`, `configure(phase,plan)`, `laser_on(current_a)`, `read_sample(phase)->dict`, `laser_off()->dict`, `protect_excitation()->dict`, `close()`.
- `preflight` returns `ready:True`, `laser_enabled:False`, and current identity/status evidence; engine refuses takeover otherwise. `laser_off` returns `laser_off_verified:bool`; `protect_excitation` returns `minimum_excitation_verified:bool` and `actual_v_rms`.
- Phases: photoresponse/combined=`dark_baseline`, `illuminated`; dark_hall/combined adds `dark_hall_2f`. Laser remains OFF outside illuminated. Protect excitation and turn laser OFF independently at each phase end and final exit. Failed protection prevents the next phase. Once owned, exceptions/cancellation/deadlines enter cleanup; preflight refusal must not shut off another owner's active output.
- Samples contain finite JSON, per-role raw channels, `power_w` for illuminated power guard, explicit phase and timestamps. Guard power before accepting a sample. Never assign spectrum or current metadata. Result dict includes status COMPLETED/FAILED/CANCELLED/UNKNOWN, samples, cleanup, error, acquisition_complete, protection_verified. UNKNOWN dominates unsuccessful protection. No true-OFF claim for excitation.

## Task 1: finite engine and limits

Files: `src/labos/pilot.py`, `tests/test_pilot.py`.
- [ ] Write failing tests for local authorization/limits before device I/O, phase sequencing and no auto-amplitude escalation.
- [ ] Implement models and engine using exact interface above.
- [ ] Test over-power, malformed samples, backend failures, cancellation/timeouts, independent cleanup attempts and failed protection preventing further phases. Preflight laser-ON refusal performs no takeover.
- [ ] Verify meaningful artifact content and safe terminal state using an explicit stateful simulated test bench; label tests as simulation, not hardware acceptance.

## Task 2: durable physical worker

Files: `src/labos/pilot_worker.py`, `tests/test_pilot_worker.py`.
- [ ] Use a separate local config/state and deterministic responder, no model.
- [ ] Accept only `labos_pilot_task` with validated `pilot_plan`. Local adapter is injected for tests; CLI defaults physical-disabled and fixed adapter ID, never peer-selected executable.
- [ ] Commit execution intent before adapter creation, preserve finished result on delivery retry, refuse unknown execution replay.
- [ ] Save report JSON atomically with SHA256 before delivery; attach bounded `pilot_result` to `labos_auto_result`, backend pilot, model_attempts0. Preserve result on network failure. Unknown physical outcomes latch a local block.
- [ ] Doctor only validates runtime/config/authentication and does not open an instrument. Stop must signal active engine cancellation; never silently kill physical I/O as an emergency-stop claim.

Main integrates central Task/Result schemas, zero-model attempt accounting and matching automatic review for pilot results, with actual API tests.

## Task 3: reviewed cryostat adapter and deployment

Main-owned files: `src/labos/cryostat_pilot.py`, `tests/test_cryostat_pilot.py`, Windows scripts/English guides, private commissioned configuration.
- [ ] Collect and review actual CLD backend/interlocks, PM100D, SR830/SR865A, station lease and resource bindings through registered source roots.
- [ ] Implement a fixed LabOS adapter with model/serial verification, lease compatibility and per-I/O bounds; no legacy whole-procedure import or invocation.
- [ ] Keep physical profile disabled until actual SDK/resource binding and local ownership are established; missing facts cannot be guessed.
- [ ] Test against replay resources at the vendor-I/O boundary and perform no output enable on this central server.
- [ ] Prepare a small commissioning bundle with a read-only preflight phase and explicit physical enable configuration; retain original report-worker identity/cursor and production environment.

## Review focus

- Partial initialization and active foreign output must not become automatic takeover.
- Cleanup failures must attempt all independent protections and persist UNKNOWN, not completed.
- Process death/network replay must never repeat a possibly executed physical run.
- Configuration/schema mistakes must fail before opening drivers; numerical values stay finite and locally bounded.
- Tests with replay backends and successful networking never constitute real hardware acceptance.

Actual physical pilot and new Windows worker acceptance remain pending until returned device evidence and commissioning satisfy the local profile. The operator has already authorized this finite test within conservative settings; do not ask for repeated general permission.

## Task 4: explicit two-SR830 profile after real commissioning feedback

The actual PC installed0.2.5 and verified211 overlay files, but its output-preserving
preflight timed out on AUX *IDN? before status qualification. No physical worker
was enabled. The returned commissioning report relays the operator's current
instruction to exclude AUX for this pilot. Four earlier identities succeeded;
neither current laser OFF nor gate OFF has yet been established by that attempt.

- Add strict local aux_enabled=False with exactly cld/pm/xx/xy/gate bindings;
  retain defaultTrue for existing profiles and reject inconsistent binding sets.
- No automatic fallback or excluded AUX session/query/write. Retain every other
  identity, lease, reference, settling, power and protection check.
- Both SR830 channels record raw optical baseline/light at1f, then XY2f in dark.
  Record absent AUX in preflight and data; do not invent an independent channel,
  zero-bias BVPE, sample current or contact-axis interpretation.
- Preserve failed preflight and attempted profile; re-preflight before enablement.
- Regression tests cover combined phases, no excluded resource access, retained
  mandatory guards, binding inconsistencies and required-AUX timeout behavior.
- Deliver0.2.6 through the existing private GitHub repository/release, keeping
  live configuration and data local. Keep experimental tasks/results on HTTPS.

## Task 5: operator-approved dark a-axis voltage short test

The first .6 physical task failed during the second dark-baseline sample with an
ASCII decoding exception localized to chopper readback. Cleanup independently
verified laser emission OFF, zero current setpoint and XX minimum4mV RMS. Preserve
that result and execution ledger; do not replay it. The operator now explicitly
approves a dark a-axis1f/2f voltage short test at4mV RMS and about8Hz, with no gate
sweep or optical measurement. XX=a, XY=45degrees, AUX=b are operator observations;
contact polarity/current calibration remain unknown. Public GitHub delivery is
explicitly authorized by the latest instruction.

- Add dark_a plan phases dark_a_1f/dark_a_2f and immutable artifact acceptance.
- Add strict local experiment_scope=dark_a with exactly cld/xx/gate bindings;
  exclude PM/chopper/XY/AUX from sessions and queries. Retain laser-OFF/TEC/identity,
  inactive gate, station lease, finite I/O, status, frequency and settling guards.
- Reject scope/plan mismatch before execution intent and adapter construction.
  Only4mV amplitude writes, no FREQ writes; harmonic selection changes detection
  only. Recheck source amplitude/frequency and restoreXX1f during cleanup.
- Derive a new disabled dark-a-worker.yaml from the actual local prior profile,
  preserving its diagnostics acknowledgment, bindings and station lock identity.
  Use separate state/cursor and no optical authorization; preserve old files.
- Tests first: engine phases, excluded hardware, raw voltage provenance, guard
  failures, scope mismatch, profile preparation and update locking.
- Publish .7 source and overlay with an English local update/preflight/enable guide;
  actual preflight and a new unique physical task are required for real acceptance.
- No I/V/resistance inference, excitation escalation or nonlinear Hall claim.

## Task 6: truthful failed-run reporting and optical fault localization

Real dark_a task completed with6samples and verified protection (rawSHA
edb16bda7d766a274d09731fb7d517d4d126baed933e52986ef65e942e198e21).
Fresh full optical preflight94 and startup95 passed, but the new authorized
photoresponse task96 failed before preflight completion: UnicodeDecodeError,
byte0xf2 atposition2, zero samples, preflightnull, cleanupempty and protectionfalse
(rawSHA57987585528e1d85ad7ab881338c64f0c88bb2d5cc6c9e0db9cdf18c93b6c372).
The worker emitted a hardcoded finding claiming independent protection even
though its raw result disproves this. Preserve that historical result unchanged.

- Correct the fixed finding using actual protection evidence; an unverified
  result must say so and request independent local readbacks before another run.
  Acquisition failure with verified cleanup must remain distinct.
- Write behavioral worker/API regressions first for preflight rejection, failed
  protection, successful cleanup after acquisition failure, and successful runs.
- Do not infer the decoder's source from its message alone. Foreground handoff99
  requests output reconciliation and a bounded, passive, read-only trace using
  existing0.2.7 code: exact failing command, traceback and exception bytes.
- No acquisition retry, decoder weakening, resets, output enable or limit increase
  during diagnosis. Production code/lyr, prior task identities and journals stay.
- A root-cause fix requires returned boundary evidence and a reproducing test;
  prepare/review/verify any change before a new version is locally deployed.
