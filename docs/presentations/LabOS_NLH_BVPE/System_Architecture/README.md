# LabOS System Architecture

A standalone English architecture figure showing **one central server, six instrument-host PCs, and one browser-only operator computer**. The figure expands the system beyond the two-PC measurement example while retaining that example's PC A/B ownership.

## Files

- [PDF](LabOS_System_Architecture_EN.pdf): searchable, embedded-font vector figure.
- [SVG](LabOS_System_Architecture_EN.svg): editable vector source, suitable for further figure editing.
- [PowerPoint](LabOS_System_Architecture_EN.pptx): one large slide with editable native shapes, text and connections.
- [High-resolution PNG](LabOS_System_Architecture_EN.png): 5120 × 3360 pixels.
- [Preview](Architecture_Preview.png): smaller image for quick review.
- [Complete bundle](LabOS_System_Architecture_EN_Bundle.zip): all deliverables, scene source and integrity files.

## What “agent” means

**Central AI agents** perform scientific reasoning. The main agent uses knowledge and memory and can delegate literature, planning, analysis, interpretation, troubleshooting and code-review tasks to specialist sub-agents. They are depicted inside the same central server.

**The server has a local LLM fallback.** A shared model router prefers the cloud model API and switches to the server's local model when the internet connection, API or invocation quota is unavailable. Experiment context and tool permissions carry across the switch. This affects model inference; deterministic coordination, command identity and local instrument ownership keep their existing roles. Cloud disconnection and loss of connectivity to an instrument PC are different events: changing model providers does not restore an unavailable instrument link.

**A local PC Agent is a persistent execution service.** It owns instrument connections, runs bounded driver operations, reports observed status, records commands and preserves raw data. It does not require a local LLM. One worker can manage several instruments on its PC. The existing implementation is in [src/labos/agent.py](../../../../src/labos/agent.py).

**A browser-only computer needs no instrument worker.** The operator can review objectives, plans and results through the central interface. Instrument-host PCs need the local execution service because they own USB, GPIB, serial and vendor-software sessions.

## Reading the diagram

| Flow | Meaning |
| --- | --- |
| Amber | Operator interaction and authorization |
| Purple | Scientific planning, specialist delegation and command payloads |
| Green | Knowledge retrieval, measurements, observed status and archived evidence |
| Teal | Deterministic coordination and persistent execution services |
| Blue | Physical device interfaces and the central server boundary |

Every instrument PC initiates its network connection to the server. Downward command arrows show command payloads returned to those clients, not inbound sessions into Windows PCs. The design supports HTTP(S) over a routed LAN or VPN and an accessible central HTTPS endpoint. SSH is an optional maintenance channel rather than a runtime dependency.

The coordinator checks units, limits, ownership, command identity and stage readiness. Local workers keep a command journal, watchdog and raw-data outbox. Acquisition artifacts and readbacks return to the server, enter quality assessment and become evidence for analysis and subsequent planning. Commands with ambiguous physical outcomes require reconciliation rather than blind replay.

PC A/B show the supplied SuperK/IR and sample-lab apparatus. PCs C, D, E and N are example additional resource hosts; they do not represent a claim that these extra instrument drivers have already been commissioned. Device-interface labels describe architectural connection options rather than model-specific confirmed wiring. Physical lock-in references and hardware triggers are separate from this HTTP(S) network.

## Design and reproduction

The layout places all central logical services and the local-model fallback inside one physical server boundary, with six visible monitor icons for the distributed execution hosts. A remote cloud-model service is shown outside the server. The operator computer is drawn separately to make the AI-agent / PC-worker distinction explicit. This is an original native-vector drawing using LabOS's existing figure renderer. No raster image is embedded in the PowerPoint.

From the parent directory, using the presentation dependencies and Poppler:

```bash
python3 build_system_architecture.py
```

The command generates all formats, checks text completeness and geometry, renders previews and validates the ZIP contents. PDF and PPTX use the same scene geometry; Microsoft PowerPoint rendering was not exercised. The figure documents the scalable system and the user's server-side model-failover arrangement; this artifact task does not change executable application code.
