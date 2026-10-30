# LabOS technical presentation — speaker notes

22 slides. Suggested talk length: 20–25 minutes.

## 01 | LabOS

This presentation explains LabOS through a concrete two-PC instrument scenario. It is a capability and architecture presentation, not a report of measured sample results. The central idea is to organize optical excitation, cryogenic environment, electrical transport and photovoltage or photocurrent readout into reproducible stages with shared evidence.

## 02 | Two response channels, one experimental context

The electrical branch tests transverse second-order response under AC current drive. The optical branch measures chopped-light photocurrent or photovoltage while changing power, polarization and excitation spectrum. Both share sample identity, wiring configuration and environmental readbacks. A common context enables comparisons without assuming a common microscopic mechanism.

## 03 | An evidence-driven hierarchy across two control PCs

The operator supplies a scientific objective, sample constraints and physical interventions. A central scientific agent combines planning, analysis and troubleshooting with a versioned evidence store. Proposed stages pass through deterministic schema, units, limits, resource-lock and command-ledger checks. Persistent workers on PC A and PC B own device sessions, execute bounded actions and retain local evidence. Commands flow down; measurements, observed states and faults flow back up. The small device panels identify resources; later figures expand their actual signal paths.

Reference: Architecture presentation inspired by QUANTA Fig. 1 [1]; original LabOS redraw for this instrument scenario.

## 04 | A PC agent is a persistent instrument service

A local worker is more than a remote shell. It keeps instrument connections, translates finite capability calls through adapters, manages one owner per device and records each command identity. Status monitoring and the watchdog run independently of a long scientific conversation. Raw measurements are written locally before an artifact outbox synchronizes them with checksums. An ambiguous dispatched action is reconciled, not blindly replayed.

## 05 | The complete two-PC instrument inventory

This inventory follows the supplied apparatus. PC A owns SuperK and the IR spectrometer. PC B owns attoDRY, two electrical transport lock-ins, a separate BVPE lock-in, a chopper, a power-monitoring photodiode, a 2400 gate source, the 730 nm laser and CLD1000 current controller, and a motorized polarization element. The electrical drive is a function of one transport lock-in, not a fourth lock-in.

## 06 | One sample connects the optical and electrical chains

The sample can receive light from PC A's SuperK or PC B's 730 nm source. A configured reference branch feeds the IR spectrometer; a power-monitoring branch supports sample-plane power calibration. PC B provides temperature, magnetic field, gate bias, electrical excitation and both transport and optical lock-in readout. Optical and electrical acquisitions are staged according to the selected wiring configuration. The cryostat drawing is an optical-access schematic, not a vendor CAD model.

## 07 | Orchestration travels over HTTP(S), not signal cables

PCs poll the central endpoint, return status through heartbeats and synchronize measurement artifacts. Central-to-PC arrows describe command payloads returned to these clients, not a requirement for inbound SSH access. An instrument resource is reserved for a run before dispatch. Command identity, boot session and ownership protect against accidental duplication or stale sessions. Local raw data are acknowledged separately from the command outcome.

## 08 | A point barrier links conditions before acquisition

At each experimental point, optical preparation on PC A and environmental preparation on PC B can proceed independently. Each worker reports the requested point identity, actual readback and readiness evidence. The coordinator releases acquisition only after the required participants are ready. Each trace records its own start and end time. The electrical reference fI and optical chopper reference fchop remain physical signals, independent of network latency. Hardware triggering can be added where the experiment requires strict simultaneous sampling.

## 09 | Translate the apparatus into a reproducible run setup

The setup manifest describes physical ownership, instrument interfaces, wiring and the calibration conventions relevant to a campaign. It distinguishes a device limit from a sample-specific authorized envelope and from settings already supported by prior data. The user can reuse the device setup while changing the objective, scan coordinates, reference tests or closure policy for a new experiment.

## 10 | Two transport lock-ins, with explicit drive and sense paths

The master transport lock-in both generates the sine wave and reads longitudinal voltage using its internal reference. Its oscillator reference is routed physically to the follower, which selects harmonic two for a transverse second-order measurement. The sample current is calibrated from the series-resistor voltage with an explicit RMS convention. The drive return is drawn separately from voltage sense leads. The transverse and longitudinal inputs may share a sample contact according to the selected differential wiring. The 2400 provides an independent gate voltage with leakage monitoring.

Reference: Circuit-level scenario based on the supplied apparatus; harmonic measurement rationale: [2,3].

## 11 | Change acquisition mode, preserve channel meaning

The first configuration reads Vxx at the fundamental and Vxy at the second harmonic. A subsequent baseline stage can select fundamental transverse voltage, and another stage can inspect longitudinal second-harmonic pickup. These are distinct acquisition stages for single-demodulator instruments; they are not presented as four simultaneous channels from two generic lock-ins. Every record includes the harmonic, phase reference, range and RMS convention.

## 12 | Turn a nonlinear signal into a controlled comparison

A campaign starts from a low-drive dark reference, then tests excitation-amplitude dependence and returns to a reference setting. Frequency and harmonic controls help separate a reproducible second-order response from thermal effects, contact nonlinearities and pickup. Field symmetry must be interpreted for the chosen physical model rather than imposed using a universal linear-Hall rule. The diagrams describe measurement logic, not measured sample curves.

## 13 | Optical drive, power and referenced readout

SuperK provides a configured spectral excitation state, while the 730 nm diode branch is controlled through CLD1000 drive current. A selected beam path passes through the chopper and polarization element to an optical-access sample mount. The reference spectrum and PD power monitor characterize the optical condition; a calibration transfer links the monitor to power at the sample plane. The BVPE lock-in measures photovoltage directly or photocurrent through its configured current input or current preamplifier. Its physical reference comes from the chopper, not from the network.

Reference: Optical / photocurrent scenario for LabOS; BVPE experimental context: Osterhoudt et al. [4].

## 14 | Describe the optical state at the sample plane

CLD1000 sets diode drive current; it does not by itself measure optical power at the sample. The PD reading is converted through detector response, monitor electronics and an optical transfer calibration. This calibration can depend on wavelength and the configured optical path, including window transmission and polarization elements. A photocurrent channel also needs its amplifier gain and the modulation-amplitude convention. These definitions are stored with each acquisition rather than inferred after the experiment.

## 15 | Combine spectrum, power, polarization and environment

A BVPE campaign includes dark and reference acquisitions, optical-power characterization, polarization scans and environmental sweeps. The 730 nm branch is useful for fixed-wavelength power and polarization measurements. The SuperK branch is configured as a selected excitation band or a measured broadband illumination state. The IR spectrometer operates within its configured response band; the power monitor and optical transfer calibration provide the power context. The current or voltage response can then be compared under common sample-state coordinates.

## 16 | A shared coordinate links dark and illuminated stages

A joint campaign can prepare an environmental state, acquire dark transport, characterize the optical condition, acquire BVPE and then repeat a dark or power reference. PC A and PC B participate only where their capabilities are needed. Source or wiring changes are explicit stage transitions and may include operator actions. The campaign graph keeps branches and return references distinct instead of flattening them into one undifferentiated curve.

## 17 | A measurement is more than a scalar value

A complete measurement record joins identity, requested setpoints and observed conditions without conflating them. The raw electrical and optical channels carry harmonic and reference definitions. Detector readings, spectrum and calibration identifiers explain the optical state. Quality assessment is separately versioned so that rejected data remain available for audit. Hashes link immutable plans, setup versions, artifacts and analysis products. The schema shown here is a capability-level record model rather than a claim that all fields share one instrument sampling clock.

## 18 | Explicit state transitions govern the next action

The coordinator moves a point through preparation, readiness, acquisition, synchronization and qualification. Rejected evidence is retained and can motivate a diagnostic plan. Unknown dispatch outcomes require ownership and state reconciliation instead of replay. Safe closure records observed output states; stopping electrical or optical excitation does not implicitly ramp a magnet or gate to zero. Physical rewiring or sample changes are explicit operator steps.

## 19 | Start from the research objective, not a remote desktop

The operator can describe a scientific task in natural language and review the resulting stages before execution. The example asks for dark nonlinear Hall and polarization-dependent BVPE at matched environmental coordinates. The PC-side configuration identifies resources, connections, drivers, data paths and local policies. The experiment-side configuration identifies the sample, scientific question, wiring, coordinate sequence and controls. The interface provides live state, data-quality feedback and an attributable run review.

## 20 | Reuse local code. Compose shared capabilities.

Existing test scripts are valuable starting points for finite capability adapters: connect, read status, set, settle, acquire, save and stop with verification. Drivers keep manufacturer dependencies and physical connections local. The central resource graph can include more PCs while preserving resource locks, shared physical paths and local ownership. Code and protocols also become versioned evidence for planning, which is different from executing arbitrary retrieved code.

## 21 | Connected instruments. Attributable science.

LabOS connects a distributed set of laboratory resources around a scientific objective. In this scenario, it joins two PCs, two excitation paths, environmental and gate control, harmonic transport, and chopped-light readout. Deterministic execution and local ownership support dependable operation, while shared identities, calibrations, timestamps and quality records support scientific interpretation. The central agent can then propose the next useful comparison from the evidence.

## 22 | Scientific context and diagram provenance

The instrument inventory and drive method were supplied and confirmed by the user. QUANTA is the framework reference for separating scientific reasoning, deterministic execution and persistent hardware ownership. The nonlinear Hall papers motivate fundamental and second-harmonic readout and the need for controls. The BVPE paper provides optical-response context. These sources are not used as measured data from this apparatus. The cryostat and front-panel illustrations are conceptual, with roles and interfaces expressed through experiment configuration.
