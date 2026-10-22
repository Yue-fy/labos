# Simulated Adaptive Loop Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Deliver a repeatable, data-dependent coarse-to-fine simulation through the existing LabOS runtime and Agents.

**Architecture:** Add a bounded adaptive option to Plan, a pure peak/refinement policy and an optional simulated excitation response. Runtime executes each round under one reservation and exports the decision history with the raw HDF5 data.

**Tech Stack:** Python 3.11+, existing Pydantic, FastAPI, httpx, SQLite, h5py and pytest.

**Spec:** `docs/superpowers/specs/2026-10-22-sim-adaptive-loop-design.md`

## Global Constraints

- No physical drivers, device discovery or external instrument connections.
- Explicit simulation approval; default 500–800 nm / 20 nm, then 5 nm and 1 nm.
- At most five rounds and 5000 total points; fixed polarization.
- Reuse preflight, resource reservation, command journal, watchdog and HDF5.
- No OpenAI key or LLM call required; policy is deterministic.

## Review Focus

- Missing/false approval or mutated non-simulation status must fail before commands.
- Flat, boundary, ambiguous, nonfinite or incomplete spectra must halt safely.
- Exhausted budgets and misaligned/narrow clipped windows must not queue unsafe scans.
- A stop/offline/failure between rounds must preserve earlier data and prevent continuation.
- Repeated coordinates and long command logs must retain every round's provenance.

### Task 1: Validated policy and simulated resonance

**Files:** `src/labos/models.py`, `src/labos/drivers.py`, new `src/labos/adaptive.py`, `tests/test_adaptive.py`.

**Interfaces:** `AdaptiveScan` and `SimulationResponse` models; `analyze_peak(plan, measurements, min_contrast) -> dict`; `refine_plan(plan, peak_nm, step_nm) -> Plan`. Plan has optional `adaptive`; InstrumentSpec has optional `simulation_response`.

- [x] Write tests for approval, bounds, rounds, invalid steps, data rejection, clipped grids, seeded response and a moved resonance.
- [x] Run `.venv/bin/python -m pytest tests/test_adaptive.py -q`; observe missing-feature failures.
- [x] Implement validated models and pure policy; retain the old simulator when no response is configured.
- [x] Run policy tests and full pytest suite; commit when green.

### Task 2: Closed-loop execution and provenance

**Files:** `src/labos/runtime.py`, `src/labos/store.py`, `src/labos/files.py`, `src/labos/central.py`, new `tests/test_adaptive_runtime.py`.

**Interfaces:** Consume Task 1 policy; extract `Runtime.scan(run_id, plan, point_offset=0)`; add `Store.adaptive_history(run_id) -> list[dict]` and authenticated `/api/runs/{run_id}/adaptive`.

- [x] Add failing real Agent/Store pump tests for a full loop, no peak, budget, stop, offline recheck, watchdog, and approval rejection.
- [x] Run runtime tests and verify failures before implementing.
- [x] Execute rounds with persistent reservations and sequential point indices; audit approval, analysis and decisions; export complete adaptive history to HDF5.
- [x] Run full pytest and Ruff; commit when green.

### Task 3: Runnable TCP demo and automated acceptance

**Files:** `src/labos/demo.py`, `src/labos/cli.py`, new `scripts/adaptive_acceptance.py`, `.github/workflows/tests.yml`, documentation and CLI tests.

**Interfaces:** Extend `acceptance(directory, ..., adaptive=False, resonance_nm=635, seed=0)`; expose `labos adaptive-demo --directory PATH --resonance-nm FLOAT --seed INT`.

- [x] Add a failing CLI/demo test and run it.
- [x] Reuse existing subprocess orchestration; verify measured round plans, peak, safe state, local caches, HDF5 and approval metadata.
- [x] Automate two identical seeded runs plus a moved resonance; compare measurements/decisions ignoring IDs and timestamps.
- [x] Run full pytest, Ruff, TCP adaptive acceptance and existing fixed-scan/fault acceptance as applicable.
- [x] Document commands, measured results, automatic decisions and manual approval boundaries; commit and deliver the independent GitHub branch.
