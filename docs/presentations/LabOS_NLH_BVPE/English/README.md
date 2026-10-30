# LabOS: Distributed Nonlinear Hall and BVPE Experiments

An English technical presentation explaining how LabOS coordinates instruments across two laboratory PCs. The 22-slide deck combines system architecture, instrument ownership, physical signal paths, execution timing, calibration, campaign logic and data provenance. All diagrams are original LabOS drawings; QUANTA supplies architectural context rather than apparatus content.

## Deliverables

- [PowerPoint](LabOS_Technical_Overview_EN.pptx): editable native text, shapes and connections, with English speaker notes on every slide.
- [PDF](LabOS_Technical_Overview_EN.pdf): matching scene layout, embedded fonts, searchable text and clickable references.
- [Speaker notes](Speaker_Notes_EN.md): a complete English narration, organized by slide.
- [Slide overview](Slide_Overview_EN.png): a contact sheet of all 22 slides.
- [Figures](Figures/): six standalone diagrams, each provided as editable SVG and vector PDF.
- [QA report](QA_Report_EN.json) and [checksums](SHA256SUMS): document checks and delivery integrity.
- [Complete bundle](LabOS_Technical_Overview_EN_Bundle.zip): the presentation, PDF, notes, previews, figures and validation files in one package.

## Technical coverage

1. Central scientific agent: planning, analysis, troubleshooting and evidence retrieval.
2. Deterministic coordinator: units, limits, resource ownership, stage state, command ledger and qualification.
3. Persistent PC agents: instrument sessions, bounded drivers, command journal, watchdog, local raw-data cache and retryable artifact delivery.
4. Complete apparatus: PC A owns SuperK and the IR spectrometer; PC B owns attoDRY, two transport lock-ins, the chopper and BVPE lock-in, PD, 2400, 730 nm laser, CLD1000 and motorized polarization optics.
5. Nonlinear Hall circuit: sine output, series resistor, separate drive and differential sense leads, gate connection, physical reference and staged harmonic acquisition.
6. BVPE optical and readout path: configured excitation source, chopping, polarization, power-monitor pickoff, optical-access sample, gate and referenced photoresponse.
7. Cross-PC operation: shared point identities, readiness barriers, recorded acquisition windows and physical phase references.
8. Scientific workflow: preparation manifests, power calibration, controls, return references, joint campaigns, provenance and quality decisions.

The deck presents a complete application scenario using the supplied instrument inventory. It contains no fabricated measured curves. Instrument roles and experiment configuration are distinct from manufacturer specifications. Vxx/Vxy identify spatial channels; each lock-in's X/Y identify phase components. Network coordination and physical lock-in references are drawn separately.

## Standalone figures

| Figure | Contents |
| --- | --- |
| `01_System_Architecture` | Researcher, scientific agent, evidence, coordinator and both PC workers |
| `02_Experiment_Topology` | Complete optical, electrical, gate and reference relationships |
| `03_Timing_and_References` | Ready barrier, acquisition stages and electrical/optical references |
| `04_Nonlinear_Hall_Circuit` | Excitation, series resistor, Hall bar, Vxx/Vxy leads, gate and oscillator reference |
| `05_BVPE_Optical_and_Readout` | Source branches, chopper, polarization, power monitor, sample and BVPE lock-in |
| `06_Execution_and_Quality` | Execution states, accepted/rejected evidence, unknown outcomes and closure |

## Rebuild

From the parent directory, install `requirements-presentation.txt` into a development environment. Poppler's `pdftoppm` is also required for raster previews. The shared renderer uses the system font paths declared in `build_presentation.py`.

```bash
python3 build_english_deck.py
python3 verify_english_deck.py
```

The verification command also creates the ZIP bundle and checks its contents against the generated files.

The PDF and PowerPoint are generated from one vector scene description. The PowerPoint uses Arial for Latin text; the PDF embeds DejaVu Sans. PowerPoint font substitution can slightly change glyph appearance. Validation checks both deliverables for complete text, page bounds, English-only slide content and notes, and text overlap candidates. Dense diagrams are also inspected visually. The PowerPoint was not rendered by Microsoft PowerPoint during this build.

The full sources remain in the repository: `build_english_deck.py`, `build_presentation.py`, `verify_english_deck.py` and `English/slides_scene_EN.json`.

References are listed on slide 22 and in the speaker notes, including QUANTA, Sodemann and Fu, Ma et al., and Osterhoudt et al.
