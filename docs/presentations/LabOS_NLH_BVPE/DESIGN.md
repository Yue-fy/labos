# LabOS × Nonlinear Hall / BVPE presentation brief

Deliver an editable Chinese PowerPoint and a visually matching, searchable PDF for a laboratory group meeting, approximately 18 slides, 16:9. The subject is LabOS's cross-PC orchestration and the user's proposed optical/transport apparatus. Redraw original vector diagrams, borrowing the hierarchy of QUANTA Fig. 1 rather than reproducing its figure or hardware.

Confirmed by user: PC A owns SuperK and an IR spectrometer. PC B owns attoDRY (T/B), two transport lock-ins for spatial Vxx/Vxy, chopper, a BVPE lock-in referenced to the chopper, a PD measuring optical power, a 2400 gate-voltage source, a 730 nm laser, CLD1000 laser-current controller, and motorized polarizer or quarter-wave plate. Electrical excitation is a lock-in sine output with series resistor.

The slides must separate command/data networking, actual optical/electrical paths, and physical phase reference. Use a typical first transport pass Vxx at 1f and Vxy at 2f, with other harmonics in separate passes unless multi-demodulation capability is verified. Do not equate a lock-in's X/Y phase components with spatial Vxx/Vxy. BVPE optical nonlinearity is not a requirement to demodulate at twice the chopper frequency.

User steering: this is a system-capability presentation, not a readiness audit. Do not write “待确认” or lists of incomplete integration. Describe wavelength selection, optical-source selection, PD readout/calibration, current readout, optical window and spectrometer bands as configurable parts of the complete scenario. Do not invent numerical ratings, named SDKs or a fitted switching matrix. A nonlinearly scaling transverse signal or modulated photocurrent alone does not establish a microscopic mechanism.

Frame the apparatus as an application scenario and explain system capabilities without pretending this is a measured Hall/BVPE results report. Keep development/acceptance status out of the main narrative. Existing code can be reviewed and wrapped by finite driver operations; importing it as evidence does not execute it.

Design choice by the author: white academic pages, navy headings, purple reasoning layer, teal execution/PC layer, amber operator/physical reference, red rejected data. Use large editable diagrams and short text. Include speaker notes, a complete script and source references. Use a shared vector scene to generate native PowerPoint shapes and an embedded-font PDF, with matching line breaks and geometry.

Execution: verify scientific primary sources and project state; compose the shared scene; render both outputs; inspect a contact sheet and dense pages; check page count, missing glyphs, out-of-bounds objects and text geometry. Artifact work is reversible and authorized by the user; continue without an additional design-approval gate.
