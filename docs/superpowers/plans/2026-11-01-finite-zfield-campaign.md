# Finite Z-field Campaign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver and commission a one-shot LabOS-native five-point Z-field optical campaign, preserving native controller ramp settings and verifying final zero.

**Architecture:** A separately versioned `labos_field` package uses deployed LabOS 0.2.8 optical acquisition and correspondence. A guarded child process owns the audited magnetic driver; the parent owns optical protection, durable campaign identity and ordered execution. Central helpers use existing HTTPS correspondence without changing the live service.

**Tech Stack:** Python 3.11+, existing pydantic/httpx/PyYAML, SQLite, multiprocessing spawn, native 0.2.8 PilotEngine/CryostatAdapter; no new runtime dependency.

**Spec:** `docs/superpowers/specs/2026-11-01-finite-zfield-campaign-design.md`, revised following the operator's native-target-field correction and instruction to begin testing.

## Global Constraints

- Targets exactly −0.5, −0.25, 0, +0.25, +0.5 T, final zero; controller X=0; existing native ramp configuration preserved, numeric rate metadata optional.
- CrSBr 1; 20 mA request,21.8 mA limit,1 µW PM ceiling,4 mV RMS,8 Hz; 3 dark+3 illuminated,15 s settle,60 s phase,180 s optical point.
- Field tolerance1.5 mT,ACK0.2 mT,p-p0.5 mT,dwell10 s,poll1 s; initial180 K, unchanged setpoint/control,±0.1 K sample-temperature guard.
- No production measurement workflows, Notebook execution, AUX/chopper/motion/gate/temperature scan, core replacement, staged0.2.9rc1 update or startup entry.
- One unique central task, immutable plan/local approval, no replay after intent, no progression after an unsuccessful point; final zero and actual closeout are separate requirements.

## Review Focus

- A delayed or blocked magnetic child must not keep the parent from attempting laser protection; Task2/3 timeout integration test.
- An ambiguous previous run or changed task/config must never reopen hardware; Task1/4 durable replay tests.
- Rejected optical data and SDK failure evidence must survive errors and artifact delivery; Task3/4 fault and artifact round-trip tests.
- Native controlled zero and restored initial control mode must be observed rather than inferred from disconnect; Task2/3 zero/mode/close-failure tests.
- Stock0.2.8 correspondence must store new tasks/chunks without executing them or accepting incomplete evidence; Task1/4 actual central-store integration test.

### Task 1: Strict authority, journal and full artifact transport

**Files:** Create `src/labos_field/{__init__,models,records,channel}.py`; tests `tests/test_field_records.py`.

**Interfaces:** `CampaignTask`, `LocalConfig`; `digest(value) -> str`; `Journal.begin(task_id,message_sha,config_sha)`, `Journal.finish(task_id,result)`; `artifact_messages(task_id,result) -> list[dict]`, `reassemble(messages) -> dict`; `Channel.fetch(config,message_id)`, `.send(message)`.

- [ ] Write tests rejecting changed target order/limits/nonfinite values, disabled or changed authority and duplicate/unresolved intents; test lossless bounded chunk round-trip and missing/tampered chunks.
- [ ] Run the new tests and observe import/behavior failure before implementation.
- [ ] Implement fixed campaign schema, canonical hashing, SQLite intent latch, TLS-verified paginated correspondence and compressed bounded raw artifacts. Network retries never invoke hardware.
- [ ] Run Task1 tests successfully and commit the independently testable boundary.

### Task 2: Audited magnetic driver and bounded child process

**Files:** Create `src/labos_field/{magnet,rpc}.py`; tests `tests/test_field_magnet.py`.

**Interfaces:** `MagnetSession(config,events)` with `open(writes=False)`, `read()`, `move(z)`, `zero()`, `close()`; `MagnetProcess(config,state_dir)` with matching RPC methods, `.healthy`, `.pid`; all methods return JSON evidence.

- [ ] Write tests for source/DLL hash refusal before loading, out-of-envelope/temperature/fault rejection, native direct target and final qualification, zero plus initial-mode restoration, closure errors and real process timeout/late-reply refusal.
- [ ] Observe RED, then implement namespace-isolated imports, fixed SDK allowlist/call audit, reviewed low-level methods, explicit guards and spawn/Pipe RPC. No forced SDK termination or rate writes.
- [ ] Prove GREEN and commit. Record the software deadline and parent-crash limitations in English instructions.

### Task 3: Finite native campaign and local commissioning CLI

**Files:** Create `src/labos_field/{engine,__main__}.py`, `field_extension/launch_field.py`; tests `tests/test_field_engine.py`.

**Interfaces:** `CampaignEngine(optical,magnet,clock,sleep).run(task,approval,event_sink) -> dict`; CLI `preflight`, `run`, `deliver`, `inspect`, with `--config` and no task code execution. Local config references existing optical profile and connection configuration, keeps its own state directory and binds exact message/task/digest.

- [ ] Write tests for exactly five ordered points/30 complete samples, borrowed-session lifecycle, field evidence around samples, stop-on-first-failure, independent optical protection on SDK stall, protected final zero and truthful failed/unknown outcomes.
- [ ] Observe RED; implement shared optical session with native PilotEngine point views, per-stage and total deadlines, independent cleanup, intent-before-open, fresh disabled commissioning evidence and a bounded wait for one pinned central message.
- [ ] Verify GREEN and commit. Persist partial evidence during execution; delivery is a separate no-hardware action.

### Task 4: Delivery, central validation and full integration

**Files:** Create `scripts/build_field_extension.py`, `docs/FIELD_CAMPAIGN_EN.md`, `field_extension/field-campaign.example.yaml`, tests `tests/test_field_integration.py`.

**Interfaces:** ZIP containing only extension/launcher/English instructions/disabled example plus a file manifest; central `inspect` reconstructs artifacts and verifies exact targets, raw sample count, point protection, final actual zero/mode and closure.

- [ ] Write a central-store integration test, packaged-launcher subprocess smoke test and no-replay delivery test; observe RED before needed implementation.
- [ ] Implement the minimal package/inspection pieces, run targeted and full tests/ruff, commit; obtain a fresh whole-branch review and fix important findings with RED→GREEN tests.
- [ ] Build and verify the public source-only delivery. Send local Codex one concrete deployment/preflight/start handoff with the fixed draft task identity; no measurement locally. Accept full evidence before posting the one central task.
- [ ] Monitor the finite campaign without replay, reassemble full raw data, independently validate each point and final zero/closure, plot data with actual field/power/temperature and retain quality flags. Request local closeout verification and preserve report cooperation/logs.
