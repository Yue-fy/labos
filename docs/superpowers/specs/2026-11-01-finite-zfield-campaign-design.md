# Finite LabOS z-field campaign

Status: implementation authorized after the operator reviewed the native-target-field revision and requested that testing begin. Experimental scope and low-level-driver reuse are authorized; physical dispatch still requires reviewed code and successful local commissioning.

## Purpose and accepted scope

Run one traceable, LabOS-native optical response sequence on CrSBr 1 at controller Z targets `[-0.5, -0.25, 0.0, 0.25, 0.5] T`, in that order, then return to `0 T`. Preserve the existing qualified temperature setpoint and control state. XX and XY denote the a-axis and 45-degree electrode directions; controller Z has not been mapped to the sample crystallographic axes.

Use `20 mA` laser current, corresponding previously to approximately `475 nW` at the PM pickoff. Record actual power; do not search for a target power or raise current. Preserve the `21.8 mA` controller current limit, `1 µW` PM ceiling, `4 mV RMS` excitation and `8 Hz` reference. Each field point uses the established native `photoresponse` plan: `3 dark + 3 illuminated` samples, `15 s` phase settling, `60 s` phase deadline and `180 s` optical point deadline. Magnetic transitions have separate bounded deadlines.

Do not scan gate voltage, temperature or motion, open AUX/chopper sessions, run a production measurement workflow, execute the reference Notebook, or apply staged `0.2.9rc1`. Preserve all existing configuration, source, portable runtimes and journals. The report worker remains available.

Success requires five accepted optical points, full raw field and optical records, verified independent protection, actual final zero-field qualification, resource closeout and delivery acknowledgments. A stopped or uncertain campaign remains a useful partial record, never a completed five-point result.

## Existing system and approaches

Core `0.2.8` can transport arbitrary authenticated correspondence, but its physical worker accepts only optical pilot tasks. Adding a magnetic target to an optical task's free-form context would not move or qualify the magnet. The production magnetic configuration contains broad ±3.6 T sweeps and cannot be used as campaign authority.

The operator selected reuse of the reviewed attoDRY low-level driver under LabOS orchestration. Reimplementing the SDK would duplicate ABI, float32, axis ordering and stability logic. Invoking the production scan procedure would violate the requested execution boundary.

The proposed implementation is a separately versioned, one-shot LabOS extension built from the deployed `0.2.8` baseline. It fetches exactly one central campaign message, verifies a locally pinned message/plan digest, executes once and exits. It does not replace the installed core, create a startup task or enable a resident physical worker. Matching central-side command-line helpers issue the typed task and reassemble/validate its artifacts using existing authenticated correspondence; they do not replace or restart the stock central service. Reusing the existing resident optical worker would require a broader uncommissioned protocol/core update; this finite extension avoids that change.

## Control and ownership

The central server issues one immutable `labos_magnetic_campaign_task` using a distinct `labos-magnetic-v1` protocol. The existing optical and report workers cannot execute it. The central task contains only typed values and identifiers; it cannot supply Python, shell commands, paths to execute or arbitrary SDK symbols.

The local Codex installs and commissions the reviewed extension without applying staged core updates. Local approval pins agent, sample, task ID, central message digest, source/DLL hashes, five targets, final zero and all limits. An authenticated HTTPS fetch must identify the expected central sender, agent and canonical digest before any instrument access. Missing or conflicting authority is a refusal.

Persist a task intent before device access. A task ID executes at most once, including when acquisition failed. A restarted process with an unresolved intent reports `UNKNOWN` and refuses further hardware actions. Delivery retries resend immutable artifacts only; they never repeat acquisition. A process-level single-instance lock excludes a second campaign locally.

Hold the existing optical station lease for the whole campaign. Acquire all identified magnetic station leases before opening the SDK, in a fixed order, without deleting or resetting locks. Check for known production acquisition/vendor sessions and all physical workers during local commissioning. These cooperative locks do not prove exclusion of arbitrary third-party vendor clients; retain that limitation and refuse known conflicts.

Keep optical and magnetic sessions open across all five points. Intermediate protective laser shutdown is required, but do not return to zero between points or release ownership between points. The ordered sweep is part of the scientific record.

## Reused magnetic boundary

Load only the reviewed low-level modules and their audited pure dependencies from a pinned source tree; do not import a production package initializer or any workflow. Verify the complete imported source closure and DLL hashes before loading. Reuse the actual 64-bit portable Python, COM5/device type 1 and the audited 64-bit DLL after fresh commissioning proves compatibility. Never ship the vendor DLL or production source in a public release.

Use the reviewed `AttoDryDriver` API: connect/read state, conditional field-control enable, `set_vector_field`, final-target `wait_for_field`, controlled `request_zero_field`, and close. Record SDK symbol, requested/returned monotonic time, return code, command ID, state and exception. All DLL return codes must be zero; a nonzero device fault also rejects the state. No Notebook partial-success fallback, cancel-popup API, error reset or guessed rate-setting API is allowed.

The SDK runs in a dedicated child process because a synchronous C call cannot reliably be interrupted by a Python deadline. The parent retains the independent VISA-based laser protection path. Child RPCs have unique IDs and finite response deadlines. A timed-out or malformed reply latches an unknown magnetic state, stops acquisition and triggers parent optical protection. Ignore late replies for progression; issue no further magnetic command through an uncertain connection. Do not force-kill a possibly active SDK call or claim that process termination stopped a magnet. Retain PID/intent/lease state for local reconciliation. If an overdue call returns, child guards prevent subsequent queued acquisition writes and attempt orderly SDK closure; this is not proof of zero field.

No new SDK read is allowed to indefinitely block laser shutdown. Illuminated-phase state RPCs have a `5 s` parent wait deadline; expiry immediately enters optical protection. At the commissioned `1 s` VISA transaction timeout, emission-OFF write/read verification gets a further `2 s` transaction budget, followed by the two zero-current transactions and existing excitation protection. Treat timeout or failed confirmation as unverified protection; these are software wait bounds, not a guaranteed physical response time. Connect/initialization has a separate `70 s` parent budget and is performed only with emission OFF. The test suite must exercise a stalled child while the optical parent owns an illuminated phase and prove the protection attempt is independent of the child's return.

This software protection survives an SDK-child stall; it does not promise laser shutdown after optical-parent death, OS failure or loss of instrument communication. No suitable independent hardware watchdog has been commissioned. Run this finite pilot under local Codex/operator supervision and retain unresolved-intent reconciliation after a parent crash. Hardware-watchdog commissioning would be a separate addition rather than an invented capability of this extension.

## Readiness and transition policy

Before deployment or physical dispatch, the read-only handoff must establish successful initialization, at least 12 complete states at roughly 1 Hz, raw call evidence, clear faults, live B/setpoint/control/T state, compatible Python/ABI and successful Disconnect/End. Refresh the disabled optical preflight and Doctor after releasing the SDK.

Use attoDRY's native target-field control with the controller's existing configured ramp behavior. The reviewed manufacturer-manual findings establish that magnetic field control manages the persistent-switch heater and current sweep; LabOS supplies a field target, not a magnet-current trajectory. Do not connect directly to APS100, program a sweep rate, bypass the native controller or infer a rate from a maximum setpoint step.

The selected SDK cannot query the current ramp-rate settings. Record them as `unknown/preserved_by_native_controller` if unavailable; their numeric value is not a required input or commissioning gate for this native target-field workflow. Historical factory charge tables are reference metadata, not values to program or proof of current settings. Actual field/status observations and the complete transition deadline determine whether a point is ready; do not predict arrival solely from a rate or replace qualification with a fixed sleep. Reconsider this boundary only if an implementation would need to change the ramp settings or bypass native field control; neither is in scope.

Before field control, verify owned optics, emission OFF, current setpoint zero and minimum excitation. Require starting actual and commanded X within the commissioned inactive-axis residual and Z inside the campaign envelope including readback tolerance. Refuse an unrelated large latent setpoint. Conditional field-control enable is allowed once only after the audited driver's clear-state, actual-versus-setpoint and vector-corner checks; no blind toggle is permitted.

Use controller `X=0` and requested Z, with an explicit direct transition policy for this scalar ordered sequence. Starting from this commissioning's verified zero field, the largest requested setpoint change is `0.5 T`; constrain the plan and the reviewed driver's maximum command step to that bound. Do not insert a separate manually generated 0.05 T staircase or additional measured points. Setpoint spacing is not a hardware ramp rate: each requested target is approached under native controller regulation. The driver must confirm the starting setpoint and register acknowledgment, and the executor must separately qualify the actual final field before optical acquisition. A changed initial field must be checked against this bound rather than silently introducing another path.

Retain the audited command-scoped readback policy and its float32 allowance: actual-field tolerance `0.0015 T`, setpoint ACK tolerance `0.0002 T`, stable peak-to-peak range `0.0005 T`, continuous dwell `10 s`, minimum 3 samples, poll `1 s`. At zero, validate both components and resultant magnitude. Manufacturer hard limits and narrow campaign target authority are separate checks; a ±0.5 T requested bound does not erase legitimate readback tolerance.

Proposed additional execution guards, explicitly engineering choices rather than historical settings: `900 s` for each complete field transition and qualification, `900 s` for final return/qualification, and an overall campaign budget that includes five transitions, five optical points and cleanup. These are finite wait ceilings, not requested ramp durations or rate estimates. SDK control/connect/read deadlines must be defined and exercised before commissioning; native DLL cancellation is not promised. No retry extends a budget. The optical `60/180 s` budgets remain unchanged.

Qualify the temperature baseline from the fresh read-only series. Proposed initial stability and in-run drift bound is ±`0.1 K` around that series' median sample temperature; preserve its observed temperature setpoint and control mode. If the series cannot meet this guard, hold the run rather than widen it. Report this engineering guard distinctly from a calibrated thermometry uncertainty.

## Optical points and advancement

Reuse the deployed `PilotEngine` and `CryostatAdapter` semantics instead of copying production acquisition. A point view borrows the campaign-owned optical session: its open/preflight/close contract must explicitly distinguish point-view release from final hardware closure. A point cannot report actual hardware closure while the campaign intentionally retains those resources.

Tag every optical sample with qualified target, actual magnetic/temperature states before and after its acquisition, timestamps and command lineage. Guard these reads through the bounded child RPC. A state that violates field/setpoint/fault/control/temperature checks rejects the point; retain the optical reading and invalid magnetic evidence rather than discarding them. Cached SDK getters lack a device sequence number or acquisition timestamp: label that freshness limitation even when host queries succeed.

For each point, require `COMPLETED`, exactly three accepted dark and three accepted illuminated raw samples, no rejected samples, finite PM/XX/XY values, independently verified laser/current/excitation protection and a null point-close error. Any failed, timed-out, incomplete, cancelled or unknown point stops the remaining sequence without replay. A parent crash also latches the entire campaign; no automatic continuation at a later point.

## Ordered cleanup and final acceptance

Use fresh independent cleanup budgets; acquisition expiry/cancellation must not suppress protective actions. First attempt and verify laser emission OFF, current setpoint zero and existing minimum excitation. Then, only through the still-known owned, clear, responsive magnet session, perform controlled zero return and complete actual-field zero qualification. A device fault, lost ownership, disabled control of uncertain origin or SDK timeout prohibits a blind zero write. Report the failed return and need for local intervention rather than claim safety.

SDK `close()` is Disconnect/End, not a zero command. Record zero qualification and actual closure separately. For this commissioning's initially disabled field control, restore control OFF only after successful actual-zero qualification, then verify control OFF, zero setpoint and a further 10 s zero-field observation window. Disabling control pauses regulation; it is not the zero-return mechanism. If a future commissioning starts with control ON, retain that initial mode instead. Do not perform a blind control toggle after failed zero qualification. Attempt all owned resource releases and retain every cleanup error. A final return, mode-restoration or closure error makes the overall result `UNKNOWN`, even if the five optical points succeeded. No new measured field point is taken during return.

Final local Codex closeout confirms the one-shot process and magnetic child have exited, the new campaign approval is disabled, no physical startup was added, all previous physical profiles remain disabled, and the report backend and logs remain. Unresolved child/PID/ownership state requires a truthful unresolved report.

## Raw data, transport and figures

Persist append-only field/command events and complete optical samples before summaries. Preserve accepted and rejected readings, stale/late responses, exception details, all hashes, baseline, user scope, versions and task intent. Retain PM pickoff power as measured; do not relabel it sample power.

The existing optical artifact endpoint accepts only optical task schemas and cannot be reused by pretending this is an old task. Send the new campaign's canonical raw JSON as immutable bounded correspondence chunks plus a manifest. Each chunk carries task/artifact ID, index/count, byte count and hash; the manifest contains whole-artifact hash and total size. Check credentials before encoding. Central reassembly rejects duplicates with changed content, missing chunks, noncanonical data, size-limit violations and hash mismatch. A delivery retry cannot access instruments.

Local measurement completion, artifact delivery and central acceptance are separate states. Central accepts completion only after reassembling and validating full evidence, five ordered points and final cleanup. Retain partial artifacts after a stopped run. Do not use chunk arrival or a summary assertion as evidence of a successful field point.

Plot XX and XY dark-subtracted X/Y voltage response against measured Z field, with actual PM power and temperature recorded for every point. Retain dark/illuminated samples and scatter/quality flags; show uneven power instead of silently assuming constant 475 nW. Explain that one ordered sweep lacks hysteresis reversal and transport-current/power calibration, and does not establish BVPE or nonlinear Hall attribution.

## Implementation and verification boundaries

Use an isolated branch from live `0.2.8`; baseline observed: 473 tests passed, 11 skipped. Do not alter the live central process or installed PC during development. Add the extension's own version and compatibility evidence; do not claim it is stock `0.2.8` or promote `0.2.9rc1` implicitly.

Before any field write: implement strict schema/authority tests, hash/import rejection, exclusive ownership, task replay/crash latch, simulated five-point integration, injected SDK/optical faults and delayed RPCs, temperature/field qualification failure, final-zero failure, full artifact round-trip and closeout checks. Run the existing suite and obtain a fresh independent review of the full change. Then commission the extension with writes disabled, obtain local full evidence and issue one new uniquely identified central task only after acceptance.

Public delivery contains source and English instructions, not private credentials, station configuration, measurements, vendor binaries or production code. Configuration examples start disabled. Local installation requires an explicit reviewed handoff; a report-only agent cannot install or start the executor by receiving a note.

## Decisions remaining before activation

1. Read-only preflight evidence has been centrally verified. Current numeric ramp-rate metadata is unavailable, but does not block use of the native target-field interface with its ramp configuration preserved. The new field-aware executor still needs implementation, review and local commissioning before any physical dispatch.
2. The operator instructed that testing proceed after the native-target-field correction. Implement and verify the extension, then commission it locally; no additional experiment authorization is required within this scope.
3. Exact module names, RPC framing/library, storage layout and delivery packaging are builder decisions, provided all observable requirements above hold. The implementation plan must settle them before code is written.
