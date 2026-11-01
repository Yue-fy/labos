# Field extension 0.1.1 — validation and execution decisions

## Hysteresis amendment

The operator corrected the requested experiment to the exact nine-point return path in `2026-11-01-zfield-hysteresis.md`. Version0.1.1 adds this path while retaining the earlier five-point authority and inspection compatibility. The native SDK control, current/power/temperature limits, deadlines, independent optical protection, persistent no-replay journal and zero/closure procedure are unchanged. Every repeated-field visit has its own indexed point and raw sample events. Central acceptance validates all nine ordered raw target writes and54 samples; forward observations cannot stand in for return-leg evidence.

The earlier0.1.0 experiment completed five points/30 physical samples and final native0T at core0.2.8. That evidence is retained privately; it does not commission a new task or prove a hysteresis mechanism. Actual PM pickoff in that scan was449.4–463.1nW, rather than an exactly controlled475nW.

The extension is separate from the portable LabOS0.2.8 core. No staged0.2.9rc1 update, production procedure or vendor binary is part of this delivery. The approved flow is native target field → actual-field qualification → native optical pilot → verified protection → next target → final controlled zero.

## Software evidence

- Full Linux suite: **513 passed,11 Windows-specific checks skipped**; no failure, one upstream Starlette/httpx deprecation warning. Ruff and package/launcher checks pass. Windows DLL/live station commissioning for the new extension remains required.
- Exact five-point/nine-point authority, message/config digest binding, durable no-replay intent and unresolved-run latch are covered. New tests preserve54 indexed samples, reject incomplete/altered return paths, stop on the first descending-transition failure and reject borrowed forward-leg getter proofs. The0.1.1 central inspector also accepted the actual complete five-point0.1.0 artifact without changing it.
- Stock central correspondence stores the new typed task and complete data parts without executing a legacy task or enqueuing arbitrary commands.
- A complete synthetic SDK-wire fixture passes central inspection. Removing complete getter pairs, state/dwell records or mode-restoration commands, or contradicting raw pointer values, fails inspection.
- SDK calls have contiguous indices and unique IDs. Field/temperature/control observations reference ten complete getter returns, with original pointer storage bytes. Qualification and sample context reference those observations; summaries alone cannot pass.
- Operator interruption retains immediately captured per-sample data and its partial point record. Failed/unknown campaigns preserve raw data without claiming successful acquisition.
- An actually delayed spawned child during an illuminated optical phase leaves the parent able to protect/close optics before the child returns.

## Independent review

One fresh whole-branch review identified three Important findings: incomplete central raw-evidence validation, loss of partial samples on KeyboardInterrupt, and preflight bypassing unresolved execution state. Each has a reproducing RED→GREEN regression test and was repaired before delivery. The complete suite was rerun afterward. The two cited verification gaps now have tests; no minor findings are deferred.

## Execution decisions and their limits

1. Implement inline with one independent whole-branch review. This preserves the active execution workflow; an author-only error remains possible, so tests and local commissioning are required.
2. Preserve native controller ramp settings and do not require a numeric rate input or add a software staircase. The manufacturer controller owns the current sweep; a later implementation that bypasses it would require a different safety analysis.
3. Separate software acceptance from live operational continuation. This permits review before any physical dispatch; commissioning and the requested real measurement remain outstanding until their evidence is accepted.
4. Treat the real-child/optical integration test as Important despite the review's Minor label. Omitting it would leave the independent protection boundary unverified.
5. Require actual Windows/SDK commissioning rather than infer target-host support from Linux tests. Skipping it risks an incompatible or incorrectly bound live deployment.
6. Do not claim an independent hardware watchdog or force-interrupt a native C call. Local supervision and unresolved-state reconciliation are required for parent/OS/device failure.
7. Deliver a separately versioned extension release from its branch under the existing GitHub delivery authorization. Do not merge or replace the live core/candidate; the tradeoff is one explicit additional deployment.

Software success does not establish actual field arrival, optical signal quality, device shutdown or final zero on a real instrument. Those are checked in the finite task's raw artifacts and final local closeout. PM pickoff power/sample current calibration and scientific mechanism attribution remain distinct from workflow validation.
