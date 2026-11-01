# Native Z-field hysteresis amendment

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Execute the operator's explicit nine-point return-path scan as a new, uniquely bound LabOS task and verify final native zero.

**Architecture:** Extend the already commissioned optional field extension with a second exact allowed trajectory. Keep the five-point trajectory backward compatible, preserve every measurement by point index and validate raw SDK writes against the task's exact trajectory. Deploy a separate source-only extension0.1.1; retain core0.2.8 and staged0.2.9rc1.

**Tech Stack:** Existing Python/Pydantic native engine, isolated attoDRY SDK child and authenticated correspondence; no new dependency.

**Spec:** `docs/superpowers/specs/2026-11-01-finite-zfield-campaign-design.md`, amended by the operator's direct instruction: −0.5,−0.25,0,+0.25,+0.5,+0.25,0,−0.25,−0.5T, then0T. This is a precise trajectory correction to the approved native execution design, not a new architecture choice.

## Global constraints

- Keep 20mA fixed current,21.8mA current ceiling,1µW PM ceiling,4mV RMS,8Hz,180K setpoint/control.
- Retain3dark+3illuminated readings per point,15s settling,60s phase/180s optical-point budgets and all existing magnetic/total deadlines.
- Actual PM power is recorded, not chased; the previous fixed-current run measured mean454–458nW rather than exactly475nW.
- No production workflow/Notebook, gate/temperature/motion scan, AUX/chopper session, core/candidate update, task replay or journal reset.
- New task/config identity; reuse the persistent state directory so earlier unresolved intents cannot be bypassed.
- Local disabled commissioning, Doctor and waiting-runner evidence precede dispatch. Supervise to closed/disabled; keep report backend.

## Review focus

1. Repeated B values must retain separate point/sample/event identities, not collapse into a field-keyed dictionary.
2. A failed first descending transition must stop the remainder, preserve the forward data and attempt protected native zero only with a healthy owned SDK.
3. Five-point results remain inspectable; nine-point acceptance requires54 samples and all nine raw target writes in order.
4. Deleting/reusing reverse-leg data or changing trajectory without rebinding the message must fail validation.
5. Package version/manifest must match0.1.1 while core remains0.2.8; numerical guards are unchanged.

### Task 1: Exact trajectory, indexed records and validation

**Files:** `src/labos_field/models.py`, `engine.py`, `__init__.py`; `tests/test_field_records.py`, `test_field_engine.py`, `test_field_evidence.py`, `test_field_integration.py`.

**Interfaces:** Preserve `CampaignTask`, `CampaignEngine.run` and `validate_campaign`; add the explicit `HYSTERESIS_TARGETS` constant, retain existing `TARGETS` as default. Central validation derives exact ordered path/count from the authorized task. Point raw events also carry `point_index`.

- [ ] Add rejecting/accepting trajectory tests and run RED.
- [ ] Add nine-point/54-sample, duplicate-field record identity, descending-failure stop and complete raw-wire evidence tests; run RED.
- [ ] Add the second allowed path and task-derived central counts/order; retain native hardware calls and all guards. Add point indices to sample events.
- [ ] Run targeted tests, then full `pytest` and Ruff.

### Task 2: Verified delivery and supervised experiment

**Files:** `scripts/build_field_extension.py`, `docs/FIELD_CAMPAIGN_EN.md`, `docs/FIELD_EXTENSION_VALIDATION_EN.md`; private central campaign record directory, kept out of GitHub.

- [ ] Build manifest version from extension constants; verify archive/launcher compatibility and update English instructions with both paths and repeated-point semantics.
- [ ] Obtain one fresh whole-change review; fix Important/Critical findings with regression checks; record rulings.
- [ ] Publish source-only field-v0.1.1 and verify downloaded archive digest.
- [ ] Allocate a new nine-point task, bind a separate disabled config, hand off local commissioning/supervision, and dispatch only after fresh acceptance.
- [ ] Require complete54-sample/SDK/zero/closure evidence; stop on failure without replay. Plot ascending/descending traces from point indices with shared turning-point display, not an extra measurement.
- [ ] Accept local disabled/process-exit/output closeout and preserve all data/report cooperation.
