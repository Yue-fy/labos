# LabOS Transport Loop

A companion to the [system architecture](../System_Architecture/README.md), explaining instrument communication, autonomous calibration, live acquisition feedback and planned coupling to server-local numerical physics.

## Files

- [Bilingual presentation and technical guide](LabOS_Transport_Workflow_ZH_EN.md): Chinese and English narration, communication layers, calibration protocol, feedback/action table, transport example and planned numerical-physics interface.
- [PDF workflow](LabOS_Transport_Closed_Loop_EN.pdf): one searchable vector figure.
- [Editable PowerPoint](LabOS_Transport_Closed_Loop_EN.pptx): native text, shapes and connections with English speaker notes.
- [SVG](LabOS_Transport_Closed_Loop_EN.svg): editable vector artwork.
- [High-resolution PNG](LabOS_Transport_Closed_Loop_EN.png): 6000 × 4000 pixels.
- [Preview](Workflow_Preview.png): smaller raster image.
- [Complete bundle](LabOS_Transport_Closed_Loop_EN_Bundle.zip), [QA report](QA_Report.json) and [checksums](SHA256SUMS).

## Reading the figure

The left column distinguishes central bounded requests, PC-initiated HTTP(S), local driver APIs, instrument buses and physical reference wiring. PC i…PC N represents an arbitrary instrument-host fleet rather than dedicated scientific roles.

The center shows a six-stage loop: campaign definition, calibration, preparation/acquisition, qualification, scientific feedback and validation of a revised stage. Recoverable qualification problems can return to calibration. Faults and uncertain physical commands require pause and reconciliation.

The dashed panel marks the **planned server-local theory/compute module**. It receives versioned qualified-data snapshots, executes defined numerical models, compares predictions and returns ranked candidate measurements. These suggestions pass through the same execution authority. Numerical solvers and the server's local LLM have distinct roles.

The lower strip distinguishes device/local response, central point/chunk feedback and asynchronous theory jobs. No network hard real-time or software-only phase-lock guarantee is implied.

## Rebuild

From the parent presentation directory, using the existing presentation dependencies and Poppler:

```bash
python3 build_transport_closed_loop.py
```

The script exports native vectors, validates text and geometry, renders previews and packages the files with integrity checks. PDF and PPTX share scene geometry; Microsoft PowerPoint rendering was not exercised.

The figure and guide describe a transport workflow design. No executable device-control code is changed, no sample results are fabricated, and the existing optical-simulation acceptance is not presented as physical transport validation. Primary sources and prototype context are linked in the bilingual guide.
