# LabOS: Scientific Skills, Connected Instruments

A redesigned English system-architecture figure showing **one central server and an arbitrary fleet of instrument-host PCs**. Three generic symbols—PC i, PC j, …, PC N—represent that fleet. No scientific function or instrument model is assigned to a particular PC in this system-level view.

## Deliverables

- [PDF](LabOS_System_Architecture_EN.pdf): searchable vector figure with embedded fonts.
- [PowerPoint](LabOS_System_Architecture_EN.pptx): one editable slide using native text, shapes and connections.
- [SVG](LabOS_System_Architecture_EN.svg): editable vector artwork.
- [High-resolution PNG](LabOS_System_Architecture_EN.png): 5120 × 3840 pixels.
- [Preview](Architecture_Preview.png): a smaller raster for quick review.
- [Chinese/English presentation script](LabOS_Architecture_Presentation_ZH_EN.md): one-minute introductions, full narration in each language, a Hall/BVPE walkthrough, Q&A and a bilingual glossary.
- [Complete ZIP](LabOS_System_Architecture_EN_Bundle.zip): all formats, scene source, documentation and integrity files.
- [QA report](QA_Report.json) and [checksums](SHA256SUMS).

## The architecture

The scientific agent runtime sits at the center of the server. It uses four kinds of support: knowledge and experiment memory; reusable scientific skills; a model runtime with cloud/local failover; and tools exposed through MCP clients and connectors. A capability/setup registry describes the resources actually available in the PC fleet. Instrument actions pass through a deterministic stage coordinator before reaching a local worker.

| Component | Responsibility |
| --- | --- |
| Control agent / task supervisor | Maintain the scientific objective, choose methods, delegate and review evidence |
| Specialist sub-agents | Perform planning, analysis and diagnostics for the current task |
| Knowledge and memory | Retrieve literature/manuals/code, preserve experiment history and retain attributable evidence |
| Skill library | Supply reusable procedures, references and supporting scripts, loaded when relevant |
| MCP host, clients and connectors | Discover tools, obtain resources and invoke capabilities through explicit interfaces |
| Model runtime | Prefer cloud inference and fall back to the server's local model on cloud/API/quota failure |
| Capability and setup registry | Bind PC identities to devices, available operations, parameters, units and shared resources |
| Execution coordinator | Validate actions, reserve resources, join readiness states and track outcomes and qualified artifacts |
| PC Agent | Own local instrument sessions, execute bounded operations and preserve local evidence |

The operator workspace is a browser client. An instrument-host PC runs a persistent execution service; it does not need its own LLM. One PC can manage several instruments, and device ownership is described by configuration rather than a permanent scientific role. The existing worker implementation is in [src/labos/agent.py](../../../../src/labos/agent.py).

## Skills and MCP have different roles

Agent Skills package task instructions and can include scripts, references and assets. Their metadata enables discovery, while the relevant instructions are loaded on demand. The proposed LabOS library includes brainstorming, experiment design, calibration/QC, instrument integration, analysis/reporting and troubleshooting. These are reusable methods for agents to follow. See the [Agent Skills overview](https://agentskills.io/home).

MCP provides the client/server protocol for tools, resources and prompts. The LabOS application is the MCP host, with client components connecting to software connector services. The figure groups examples into Knowledge MCP, Analysis MCP and LabOS Control MCP. These are proposed LabOS connector roles, not claims that particular third-party servers are installed. See the [official MCP architecture](https://modelcontextprotocol.io/docs/learn/architecture).

A skill can tell an agent how to design a calibration or evaluate a response. The agent can then use an analysis tool or request a controlled stage. Device actions exposed by LabOS Control MCP enter the same validated execution coordinator. The diagram therefore retains the existing outbound worker network; it does not require an MCP server or LLM on every laboratory PC.

GitHub REA was investigated as requested. [morluto/rea](https://github.com/morluto/rea) is relevant to inspecting existing applications, packaged software and runtime behavior. It can be an optional software-integration connector when that evidence is needed. Ordinary available source code can be inspected with normal repository tools. The main figure uses neutral extension points so that LabOS is not tied to this one project.

## One experiment through the system

1. The operator supplies an objective, setup and allowed operating envelope.
2. The control agent retrieves prior evidence and loads relevant scientific skills.
3. Specialist agents develop a plan or analysis; MCP tools provide retrieval, computation and controlled-stage requests.
4. The coordinator validates the stage, reserves device resources and dispatches bounded operations to the required PCs.
5. Local workers communicate through the configured vendor SDK, VISA, USB, serial or LAN interface, write local data and return artifacts and readbacks.
6. Qualification and analysis produce evidence for the next decision and update experiment memory.

PCs initiate HTTP(S) requests to the server over LAN, VPN or an accessible HTTPS endpoint. Downward arrows describe command payloads returned to those clients. SSH is not a runtime requirement. Physical trigger and lock-in reference wiring remain separate from this control network.

Cloud-model disconnection and instrument-PC disconnection are different events. The model router changes inference providers while preserving context and tool permissions; it does not restore an unavailable device link or replay an uncertain physical command.

## Layout and reproduction

The figure uses a central scientific runtime surrounded by knowledge, skills, model routing and a capability registry, followed by a shared tool and execution path. Its PC symbols are deliberately interchangeable. The layout is an original LabOS design rather than a reproduction of the supplied paper diagram.

From the parent directory, with the presentation requirements and Poppler installed:

```bash
python3 build_system_architecture.py
```

The command exports all formats, verifies text completeness and geometry, renders previews and validates the ZIP contents. PDF and PPTX share one scene geometry; Microsoft PowerPoint rendering was not exercised. This artifact update describes the architecture and extension points. It does not install skills, register MCP services or change executable instrument-control code.
