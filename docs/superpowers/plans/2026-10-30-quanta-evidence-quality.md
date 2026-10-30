# Evidence and measurement qualification implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make LabOS's data qualification and evidence-to-decision chain inspectable.

**Architecture:** Deterministic quality checks beside immutable artifacts; an independent local evidence index; bounded evidence retrieval for draft-only planning and immutable deterministic run reviews. Existing outbound worker networking and safety ownership remain authoritative.

**Tech Stack:** Python 3.11+, Pydantic, SQLite, FastAPI, HDF5, plain browser JavaScript. No new runtime dependencies.

**Spec:** `docs/superpowers/specs/2026-10-30-quanta-evidence-quality.md`

## Global Constraints

- Only simulated drivers are currently implemented.
- No automatic retry, replay of UNKNOWN commands or change of an experimental envelope.
- Evidence cannot change enrollment, driver allowlists or authorize execution.
- Linux tests/package execution do not constitute Windows or physical-instrument acceptance.

## Review Focus

- Old databases and late uploads must remain readable without silently qualifying historical data.
- Threshold equality, overload flags and false worker acceptance must stop acquisition while retaining rejected raw data.
- A changed/missing provenance hash on a new command must be refused before synchronization.
- Imported code, malicious document instructions and agent credentials must not gain execution or operator access.
- A review/plot/export must distinguish rejected data and old telemetry from accepted/live evidence.

### Task 1: Qualification, provenance and fail-closed acquisition

**Files:** models.py, quality.py (new), files.py, drivers.py, agent.py, store.py, runtime.py; tests/test_quality.py (new), test_runtime.py, test_storage.py.

**Interfaces:** `QualityPolicy`, `assess(measurement, policy, detector_ceiling) -> dict`; `Store.qualification(id) -> dict|None`; `Store.measurements(run_id, qualified_only=False)`; `Store.provenance(run_id) -> dict`.

- [ ] Write failing tests for overload/count equality, accepted-only export, retained rejection, tampered hash and historical unassessed rows.
- [ ] Run `.venv/bin/python -m pytest tests/test_quality.py -q`; expect failures for missing quality functionality.
- [ ] Implement typed policy/flags, simulation ceiling, command-bound hashes, independent central qualification, qualified point counts and scan stop on rejection. Record cleanup evidence. Export all audit entries and qualified-only arrays.
- [ ] Run targeted tests then `.venv/bin/python -m pytest -q`; expect all passing.
- [ ] Commit `feat: qualify spectra and preserve rejected measurement evidence`.

### Task 2: Versioned local evidence and cited draft retrieval

**Files:** evidence.py (new), central.py, planner.py; tests/test_evidence.py (new), test_planner.py.

**Interfaces:** `EvidenceStore(root).add(EvidenceDocument)`, `.search(query, reviewed_only=True, limit=5)`; `draft_plan(..., evidence=None)` returns `evidence` citations; authenticated `/api/evidence` POST and GET query endpoints.

- [ ] Write failing tests for version/digest idempotency, reviewed-only English/Chinese/code retrieval, credential separation and planner citation provenance.
- [ ] Run targeted tests; expect missing evidence feature failures.
- [ ] Implement bounded immutable documents and deterministic lexical ranking; attach excerpts as untrusted data to planner, return/log source IDs and hashes. Never execute code or fetch links.
- [ ] Run evidence/planner/API tests and full suite; expect all passing.
- [ ] Commit `feat: retrieve reviewed protocols and code with source provenance`.

### Task 3: Review, dashboard, documentation and delivery

**Files:** review.py (new), central.py, runtime.py, static/index.html, docs/QUANTA_IMPROVEMENTS_ZH.md (new), README.md, assets/docs, version/build scripts; tests/test_review.py (new), delivery tests; scripts/quality_acceptance.py (new).

**Interfaces:** `build_review(store, run_id) -> dict`; `Store.save_review(run_id, body) -> dict`; GET/POST `/api/runs/{run_id}/review`; automatic closure snapshot for completed/failed/reconciled runs. POST review route must precede generic control route.

- [ ] Write failing review tests: no signal summary from rejected/unassessed data, shutdown evidence distinct from run status, immutable review versions, operator-only API.
- [ ] Run targeted tests; expect missing review functionality failures.
- [ ] Implement review and UI using textContent; show accepted/rejected counts and offline history, import/search evidence and download rejected-run audit. Publish Chinese instructions mapping paper ideas to concrete features and limits.
- [ ] Run full suite and TCP quality acceptance (overload -> retained rejection -> source-off -> separately preflighted lower-exposure success), existing network regression, browser check and role-package smoke check. Build v0.2.0 without credentials and record hashes.
- [ ] Commit `feat: close experiments with evidence reviews and deliver v0.2 packages`.
- [ ] Run independent whole-branch review and fix important issues with regression tests; report exact validation and remaining Windows/hardware limits.
