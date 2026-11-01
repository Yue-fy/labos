# LabOS instructions for collaborating assistants

These instructions support a language-model assistant on either the central server or a laboratory PC. They describe commissioning and cooperation; they do not start software or grant new instrument-control authority.

## Start here

1. Read [README_AGENT_KIT_EN.md](README_AGENT_KIT_EN.md).
2. Determine your location from the operator's request and the package's `ROLE` file (`central` or `agent`). If these documents are in an `agent-kit` subfolder, the package root may be its parent. Do not infer the role from example instrument addresses.
3. On a laboratory PC, read [PC_AGENT_GUIDE_EN.md](PC_AGENT_GUIDE_EN.md). On the central server, read [SERVER_AGENT_GUIDE_EN.md](SERVER_AGENT_GUIDE_EN.md).
4. Read [AGENT_HANDOFF_EN.md](AGENT_HANDOFF_EN.md) before exchanging reports. For the cavity example, also read [CAVITY_REFERENCE_EN.md](CAVITY_REFERENCE_EN.md).

## Work within the established task

- Continue authorized read-only inspection and reversible preparation without repeatedly asking for permission. Carry forward the operator's existing authorization and limits.
- Keep product text, new operational documentation and handoff reports in English. Preserve original source code, source-language evidence and user data.
- The optional local LLM assistant helps inspect the environment, adapt code and diagnose problems. The persistent PC execution Agent owns queued runtime execution. They are different roles; do not introduce a competing instrument-control loop.
- Keep the working vendor environment intact. Inspect reference code as text/JSON first: notebook initialization, module import and driver construction may change instrument state.
- Do not run an entire reference Notebook to test installation. Do not send reset, output-enable, movement or emission commands as a connectivity check.
- Physical changes must remain within the operator's established scope and a validated model-specific procedure. If a required limit, wiring fact or stop behavior is missing, report that precise gap while continuing independent preparation.
- Do not fabricate device identities, current readbacks, calibration results, central URLs or experimental limits. Distinguish historical code/output, current local observations and live device observations.
- Never put bearer tokens, operator credentials, API keys or unredacted configuration files into a handoff report. Use credentials locally through the intended application.
- Preserve local data, execution journals and fault records. Reconcile unknown physical outcomes before repeating an action.

## Current software truth

The generic execution Agent retains simulated laser, rotator and spectrometer drivers. A separate, opt-in cryostat physical pilot worker implements fixed reviewed SCPI commands, finite phases and independent cleanup; read [PHYSICAL_PILOT_EN.md](PHYSICAL_PILOT_EN.md). An explicit two-SR830 profile can exclude unavailable AUX without opening it; the original default still requires AUX and never falls back automatically after a fault. The new dark_a profile reads XX1f/2f with exactly CLD/XX/gate sessions, excludes PM/chopper/XY/AUX, and cannot enable the laser; read [DARK_A_SHORT_TEST_EN.md](DARK_A_SHORT_TEST_EN.md). It records voltage responses without calibrated current/IV/Hall claims. The optical_readback scope records bounded laser OFF/ON PM and XX/XY values without opening chopper serial; read [OPTICAL_READBACK_EN.md](OPTICAL_READBACK_EN.md). This explicit scope does not establish optical modulation/BVPE or repair the chopper fault; the original optical_transport scope never drops a failed device automatically. Failed-run protection claims follow actual raw verification. Actual local commissioning remains required. This does not make arbitrary hardware or autonomous calibration available. Architecture diagrams are not implementation evidence. The optional background report worker and its own local-model fallback are described in [AUTOMATIC_COOPERATION_EN.md](AUTOMATIC_COOPERATION_EN.md); they do not add instrument tools or planner-wide model failover.

Two PC profiles are available. `cooperation.yaml` selects a report-only model worker; `program-connector.yaml` selects deterministic locally approved programs without a local model. Read [PROGRAM_CONNECTOR_EN.md](PROGRAM_CONNECTOR_EN.md) for that profile. These profiles do not share state directories. Source roots are opt-in and described in [APPROVED_SOURCE_CONTEXT_EN.md](APPROVED_SOURCE_CONTEXT_EN.md). They allow text/AST evidence, never production imports or instrument sessions.

The JSON handoff templates are **documentation records**, not executable experiment requests. With provisioned correspondence tools, use [COOPERATION_HTTPS_EN.md](COOPERATION_HTTPS_EN.md) to send and retrieve them through the authenticated correspondence channel. Transport does not wake an LLM session or execute the report. Operator-relayed files remain an offline fallback; do not invent endpoints or send messages to unrelated external services.

The physical overlay ships root `ONSITE_COMMISSIONING_EN.md`,
`PHYSICAL_AUTHORITY_EN.md`, `PORTABLE_UPDATE_RECOVERY_EN.md` and
`RELIABILITY_IMPROVEMENTS_EN.md`; generic source releases include them under
`docs/`. Use them before later onsite cutover. Authority starts uncommissioned;
readiness never bypasses a newly granted transactional claim for the same frozen
profile. A report worker cannot install updates, change approval or run devices.
Local progress events are not continuous central telemetry. Broad learning/RAG,
arbitrary MCP/skill execution, theory-guided adaptation, autonomous calibration
and cross-PC physical barriers remain planned.

Your first deliverable is a factual local report with explicit remaining gaps.
