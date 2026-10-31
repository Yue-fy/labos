# LabOS agent cooperation kit

Document revision: 2026-10-31. Software baseline: LabOS 0.2.4; verify the installed version separately.

An experimental PC may have its own language-model assistant. That assistant can inspect the local environment, understand working instrument code, prepare adapters and explain failures. The central assistant coordinates the experiment and deployment. The PC's persistent execution Agent handles the runtime queue and device ownership.

| Participant | Responsibility |
| --- | --- |
| Operator | Supplies the scientific objective, physical setup and operating scope |
| Central LLM assistant | Integrates reports, prepares deployment and experiment changes, explains results |
| Optional PC LLM assistant | Inspects its own PC, preserves working dependencies, prepares local integration evidence |
| Central runtime | Validates and coordinates supported tasks, tracks ownership and results |
| PC execution Agent | Executes supported bounded commands, records local outcomes and uploads data |

An LLM is not required on every PC. Having one does not automatically add a communication channel or new runtime capabilities.

## Files to read

| File | Purpose |
| --- | --- |
| [AGENTS.md](AGENTS.md) | Entry instructions for an assistant |
| [PC_AGENT_GUIDE_EN.md](PC_AGENT_GUIDE_EN.md) | Local inspection, installation, code adaptation and PC-side reporting |
| [SERVER_AGENT_GUIDE_EN.md](SERVER_AGENT_GUIDE_EN.md) | Central-side integration, provisioning and task coordination |
| [AGENT_HANDOFF_EN.md](AGENT_HANDOFF_EN.md) | Shared report format, ownership and exchange sequence |
| [COOPERATION_HTTPS_EN.md](COOPERATION_HTTPS_EN.md) | Implemented authenticated report send/receive tools |
| [AUTOMATIC_COOPERATION_EN.md](AUTOMATIC_COOPERATION_EN.md) | Background task reception, Codex reporting and automatic central review |
| [CAVITY_REFERENCE_EN.md](CAVITY_REFERENCE_EN.md) | Facts extracted from the cavity reference Notebook, with their limits |
| [PC_INTAKE_TEMPLATE.json](PC_INTAKE_TEMPLATE.json) | Blank PC report; copy and fill with observed facts |
| [SERVER_REPLY_TEMPLATE.json](SERVER_REPLY_TEMPLATE.json) | Blank central response; records the next agreed step |

## Put the documents on an existing PC

The refreshed full delivery packages include these documents at their root. For an already extracted package, unpack **LabOS-Agent-Cooperation-Docs-0.2.4.zip** into a new `agent-kit` subfolder, for example `C:\LabOS\cavity-pc\agent-kit`. This document-only ZIP does not replace scripts, configuration, data or drivers. Automatic processing requires the full 0.2.4 software and a separately started worker.

If a site already has an `AGENTS.md`, keep it and explicitly point the assistant to this kit. Automatic discovery of `AGENTS.md` depends on the assistant product; an explicit instruction works even when automatic discovery is unavailable.

## Copy this to a laboratory PC's assistant

```text
You are the local LabOS commissioning assistant on this Windows laboratory PC.
Read agent-kit/AGENTS.md, README_AGENT_KIT_EN.md, PC_AGENT_GUIDE_EN.md,
AGENT_HANDOFF_EN.md and COOPERATION_HTTPS_EN.md in that same folder.
If the kit is at the package root, use the root paths instead.
Use the actual station's intake/review; read CAVITY_REFERENCE_EN.md only
when the operator identifies that reference as relevant to this station.

First inspect the local package, existing control code and working environment
without opening instrument sessions or executing the reference Notebook.
Prepare handoff/pc-intake.json from PC_INTAKE_TEMPLATE.json and a short English
summary. Mark unknowns explicitly and distinguish reference facts from current
observations. With a provisioned 0.2.2 package, send the report over the
cooperation HTTPS channel. Do not include credentials. List missing information
the central assistant needs, and continue useful offline preparation.
```

With a provisioned 0.2.2 package, send the sanitized report through the cooperation HTTPS tools. Otherwise relay it through the operator. The full production environment can stay on the PC.

## Copy this to the central assistant

```text
Read SERVER_AGENT_GUIDE_EN.md and AGENT_HANDOFF_EN.md. Review the PC intake
report and referenced evidence. State which observations are verified, which
integration changes are needed, and the next bounded commissioning step.
Return a report based on SERVER_REPLY_TEMPLATE.json. Keep central credentials
on the server and distinguish proposed work from implemented runtime support.
```

Use the provisioned HTTPS correspondence channel when available; otherwise exchange files through the operator. The send/pull tools deliver reports; an assistant must read them explicitly. For unattended processing, install the full 0.2.4 software and configure its optional background worker as described in AUTOMATIC_COOPERATION_EN.md. The document-only kit does not install that worker, invoke an LLM or add arbitrary JSON task execution.
