# Deployable LabOS MVP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Deliver authenticated central/agent services and copyable Windows/Linux packages that complete a two-PC simulated scan and preserve data on failure.
**Architecture:** Central deterministic runtime owns runs/resources. Agents poll outbound, enforce local limits, journal commands and persist spectra before upload. UI/optional AI only prepare plans; explicit Start executes them.
**Tech Stack:** Python 3.11+, FastAPI, Pydantic, HTTPX, SQLite, PyYAML, h5py, optional OpenAI SDK.
**Spec:** `docs/superpowers/specs/2026-10-09-deployable-mvp-design.md`.

## Global Constraints
- Work in the user-requested independent project directory; no external deployment or firewall changes.
- No live AI call or real hardware operation; simulated mode is explicit everywhere.
- No automatic re-execution of a dispatched command; retain ambiguous resources until reconciliation.
- Agent packages must not contain operator or other agents' credentials.

## Review Focus
- Restart between device action and journal commit must surface UNKNOWN.
- Lost upload acknowledgements must not duplicate points.
- Agent-supplied status must not replace central ownership/limits.
- Stop/pause during a point must not start another point.
- Extracted packages and paths with spaces must work independently of source checkout.

### Task 1: Typed protocol and simulated devices
**Files:** `src/labos/models.py`, `src/labos/drivers.py`, `src/labos/config.py`, `tests/test_models.py`, `tests/test_drivers.py`.
**Interfaces:** `Plan.points()`, `SetupProfile.devices`, `SimulatedInstrument.execute(command, parameters, cancel)` and `safe_shutdown()`; finite values and local limits enforced before execution.
- [x] Write tests for inclusive 399-point grids, invalid/nonfinite values, empty limit intersections, unknown capabilities and cancellation-safe simulated devices.
- [x] Run `pytest tests/test_models.py tests/test_drivers.py` and observe missing-module failure.
- [x] Implement typed models/config and three simulated instrument adapters.
- [x] Run the same command; expected all PASS. Commit task.

### Task 2: Durable central/agent storage
**Files:** `src/labos/store.py`, `src/labos/journal.py`, `src/labos/files.py`, `tests/test_storage.py`.
**Interfaces:** `Store` exposes transactional registry/run/command/measurement operations; `Journal` de-duplicates commands and persists results; atomic JSON/HDF5 utilities.
- [x] Write tests for exclusive resources, conflicting duplicate payloads, interrupted commands/runs, hash-verified measurement deduplication and finite data rejection.
- [x] Run `pytest tests/test_storage.py`; expected missing-module FAIL.
- [x] Implement SQLite transactions and artifact validation; stale commands never requeue.
- [x] Run tests; expected PASS. Commit task.

### Task 3: Authenticated central API/runtime and outbound agents
**Files:** `src/labos/central.py`, `src/labos/runtime.py`, `src/labos/agent.py`, `tests/test_api.py`, `tests/test_runtime.py`, `tests/test_agent.py`.
**Interfaces:** `create_app(config)`, `Runtime`, `Agent.run()`; registered boot session, role-scoped bearer tokens, heartbeat/poll/result/upload, explicit Start/Pause/Resume/Stop/Reconcile.
- [x] Write tests for 401/403, instrument ownership, stale sessions, local-first capture and restart replay, run point counts, timeout UNKNOWN and safe reconciliation.
- [x] Run these tests; expected missing-module FAIL.
- [x] Implement worker lifecycle with bounded timeouts, agent watchdog/cancellation and persistent uploads.
- [x] Run tests; expected PASS. Commit task.

### Task 4: CLI, preparation dashboard and optional AI drafts
**Files:** `src/labos/cli.py`, `src/labos/planner.py`, `src/labos/static/index.html`, `tests/test_cli.py`, `tests/test_planner.py`.
**Interfaces:** `python -m labos init|central|agent|doctor|submit|export|demo`; optional planner returns only validated draft plans using configured model.
- [x] Write tests for provisioning secret isolation, unsupported real mode, authenticated doctor, draft-only planner and strict response handling.
- [x] Run tests; expected missing-module FAIL.
- [x] Implement CLI/UI and optional AI integration; no automatic execution.
- [x] Run tests; expected PASS. Commit task.

### Task 5: Delivery packages and deployment documentation
**Files:** `scripts/build_delivery.py`, Windows/Linux launch/install scripts, `docs/DEPLOYMENT_ZH.md`, `docs/NETWORK_ZH.md`, `docs/HARDWARE_ZH.md`, `tests/test_delivery.py`, `scripts/acceptance.py`.
**Interfaces:** Role ZIPs contain wheel/source, pinned requirements, instructions and executable scripts; per-agent bundles include only assigned token/config.
- [x] Write package tests for safe paths, no secrets, complete entrypoints and extractability.
- [x] Run tests; expected missing build module FAIL.
- [x] Build delivery ZIPs; provide LAN/VPN/TLS recipes, offline wheelhouse and startup troubleshooting.
- [x] Run full pytest, Ruff, three-process TCP acceptance and extracted-package acceptance; expected PASS and confirmed HDF5 point count. Commit task.
- [x] Fresh reviewer checks runtime/auth/storage/delivery; fix material findings with reproducing tests and rerun relevant acceptance.
