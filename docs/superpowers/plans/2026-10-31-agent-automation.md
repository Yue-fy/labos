# Automatic Assistant Correspondence Implementation Plan

> **For agentic workers:** Execute inline with superpowers:executing-plans. User requested implementation; do not add another design approval round.

**Goal:** Deliver and activate durable automatic report cooperation between central and cryostat PC assistants.

**Architecture:** Poll the existing HTTPS correspondence API, persist jobs and responses in a separate SQLite journal, invoke a bounded report-only backend, and deliver stable replies. Requests produce results; central result review is terminal. Use Codex and an optional loopback model fallback.

**Tech Stack:** Python, Pydantic, httpx, SQLite, Codex CLI, Windows PowerShell, systemd user services.

**Spec:** `docs/superpowers/specs/2026-10-31-agent-automation-design.md`.

## Global Constraints

- Preserve production software, hardware ownership, instrument state and existing credentials.
- Protocol `labos-agent-v1`; 10-second default polling; two model attempts with 60-second retry delay.
- Persist output before sending; never invoke the model for ordinary messages or terminal reviews.
- All new delivery content is English. Work in the operator-designated project; preserve existing uncommitted changes.

## Review Focus

- A dropped POST response must not duplicate a reply or repeat inference after restart.
- A bad task or failed backend must not block all later messages.
- A result for another task must not trigger an automatic review.
- Windows executable paths with spaces must remain a single argument; messages travel on stdin.
- Missing CLI/auth or model quota must produce truthful diagnostics and bounded retry/fallback.

## Task 1: Persistent worker and providers

**Files:** Create `src/labos/cooperation_worker.py`, `src/labos/cooperation_models.py`, `tests/test_cooperation_worker.py`.

**Interfaces:** `WorkerConfig`, `Answer`, `Responder(config).respond(message, context)`, `Worker(config, transport=None, responder=None).tick()`; module CLI `doctor`, `run`, `once`, `status`, `stop`.

- [x] Write API integration tests for a task/result/review round trip, ordinary-message suppression, restart, wrong result reference, ambiguous send and bounded model failure.
- [x] Observe the missing-feature failure, implement the journal/worker, and pass the tests.
- [x] Test provider process argv/stdin and local-model HTTP boundaries, observe failures, implement providers and verify.

## Task 2: Delivery and startup

**Files:** Add English automation guide and PowerShell start/install/stop scripts under `src/labos/assets`; update package version and cooperation-kit entry points.

- [x] Implement worker doctor and Windows startup without replacing production environments.
- [x] Parse PowerShell and run packaged Python entry points; verify archive source/doc parity and checksums.
- [x] Build generic 0.2.3 and private cryostat 0.2.3 packages, with a ready-to-copy English prompt.

## Task 3: Central activation and acceptance

**Files:** Private deployment worker configuration, systemd user service, English network/automation acceptance records.

- [x] Run the full test suite, Ruff and diff whitespace checks.
- [x] Exercise the real local model and HTTPS correspondence with an attributed central-side test.
- [x] Start central worker, queue an explicitly bounded PC demonstration task, and preserve receipt IDs.
- [x] Review the final change and report separately what was proven centrally and what still requires the PC to start its worker.

Acceptance: `subComputer/cryostat/reviewMD/AUTOMATION_ACCEPTANCE_EN.md`. Remote installation and the actual remote automatic response are pending the one-time operator package transfer; the central-only smoke is explicitly attributed.
