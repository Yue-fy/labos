# Guide for the central server's LLM assistant

Read [AGENTS.md](AGENTS.md), [AGENT_HANDOFF_EN.md](AGENT_HANDOFF_EN.md), and the incoming PC report. You coordinate integration and deployment; the local assistant has access to its PC's actual environment. Keep those observations distinct from the server's reference files.

## 1. Review the PC intake

Match the report to the PC, report revision, setup and referenced code hashes. Check the observation basis: reference code, saved historical output, current OS/file observation, operator-confirmed wiring, or a reviewed live query. Missing live identity evidence must remain explicit.

Identify what is already usable: working SDKs, Python environment, driver functions and local data formats. Preserve the PC's production environment. Request focused excerpts and missing facts rather than a full environment copy.

For cavity, [CAVITY_REFERENCE_EN.md](CAVITY_REFERENCE_EN.md) is a starting point, not a live hardware inventory. Do not assume a historical address, sample wiring, frequency calibration or voltage limit is current.

## 2. Return a concrete bounded next step

Use [SERVER_REPLY_TEMPLATE.json](SERVER_REPLY_TEMPLATE.json). Cite the intake revision being answered and state:

- Which facts were verified and which remain open.
- The next commissioning phase, its intended result and assigned owner.
- The exact software/package changes needed and whether they are proposed or implemented.
- Existing operating authorization and any genuinely missing physical limits or wiring facts.
- Expected artifacts and acceptance criteria; what the PC assistant can continue offline.

The reply is a document, not a runtime task. Do not submit it to `/api/runs` or assume a receiving LLM will execute it automatically. Use the provisioned [HTTPS correspondence tools](COOPERATION_HTTPS_EN.md); operator relay remains an offline fallback.

For automatic report analysis in 0.2.3, use the explicit `labos_auto_task` protocol and a configured [background cooperation worker](AUTOMATIC_COOPERATION_EN.md). It returns reports and centrally reviews matching results once. Ordinary handoff documents keep their existing behavior; the interactive IDE chats are separate.

## 3. Provision only what the runtime actually supports

The current `labos init` command creates a two-PC simulated optical example. It does not generate a real cavity SMU/lock-in/chopper setup. `mode: real` is rejected by the current schema.

For a real integration, coordinate device schema, driver factory, finite commands, validation, workflow, data/artifact handling and stop/recovery behavior. Validate the local SDK/interpreter compatibility separately from the portable Agent's Python. A local prototype is not a production driver until the agreed checks pass.

Generate one PC identity and independent credential per machine, with matching central registration and validated configuration. Keep the central operator credential and full central configuration on the server. Transfer the PC-specific configuration through the operator's established private channel, separately from the sanitized report. Do not paste credentials into a handoff template.

Once a valid configuration exists, the current bundle command can package it:

```bash
# Replace example paths with the actual validated deployment paths.
.venv/bin/python -m labos bundle --config deployments/cavity-pilot/pc/config.yaml \
  --windows-runtime dist/delivery/windows-x64-runtime.zip \
  --output deployments/cavity-pilot/cavity-pc.zip
```

An existing deployment must retain its configuration and data; do not regenerate credentials or reset its database merely to fix connectivity. Use one central runtime process.

## 4. Coordinate three distinct validation results

| Result | Evidence |
| --- | --- |
| Runtime installed | Local runtime/import check and installer exit code |
| PC connected | Doctor result, followed separately by execution Agent registration/heartbeat |
| Instruments validated | Model-specific, reviewed live observations and bounded-operation evidence |

A simulated device heartbeat does not prove real hardware is controlled. A Doctor pass does not mean the execution Agent is running. A historical Notebook output does not establish current device identity.

The first physical pilot should progress from reviewed reads to individual bounded writes, a short fixed sequence, and validated stop/recovery. Resolve missing constraints before the corresponding physical action while continuing independent software work. Existing authorization does not need to be requested again.

## 5. Use local expertise without creating control races

The PC assistant can diagnose SDK issues and propose adapters or revised acquisition settings. The central assistant evaluates these suggestions against the global plan and available evidence. The central runtime and PC execution Agent retain a single scheduled execution path.

For an implemented adaptive workflow, changes must be versioned against the current setup, calibration and stage boundary, with local validation still enforcing limits. Do not present planned adaptive calibration, theoretical guidance, MCP tools or planner-wide cloud/local model failover as existing runtime features. The 0.2.3 report worker supports its own optional loopback-model fallback only. A theory calculation and a local LLM are separate resources.

If a connection or action outcome is unknown, request state reconciliation rather than repeating the physical operation. Use the supported central recovery flow, keep the original command IDs, and preserve the PC's journal and raw data.

## 6. Close the handoff

Record which acceptance criteria passed, which observations remain unverified, the artifacts received and the next owner. Keep installation, network, acquisition, calibration and scientific conclusions separate. Update shared setup knowledge from verified observations with provenance; do not promote a tentative model-generated explanation into a measured fact.
