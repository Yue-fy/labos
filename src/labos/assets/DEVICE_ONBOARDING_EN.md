# Device onboarding with or without existing code

Status: operational guidance for commissioning assistants. This document adds a source-selection and evidence workflow; it does not install a generic driver registry, discovery command or hardware executor. Check the installed runtime separately.

## 1. Select the source route

Existing laboratory code is one possible source. Its absence is not a reason to stop offline preparation.

| Available evidence | Prepare | Record before any live use |
| --- | --- | --- |
| Working site code or vendor SDK | A thin adapter around reviewed low-level operations; keep the production workflow separate | Source revision/hash, entry point, import/constructor/open/close effects, interpreter/bitness/DLL requirements, locally tested model and owner |
| Maintained open-source driver | A thin adapter around a pinned class/version and reviewed operation subset | Exact upstream source, supported versus physically tested models, dependency lock, initialization transcript, units and cleanup |
| Manufacturer programming manual only | An LLM-authored draft adapter and protocol fixtures | Model, document number/revision/hash/URL, printed page and PDF page for each command, parser/units, state effects, preconditions and limits |
| GUI-only or no reviewed automation interface | A manual device procedure with explicit operator steps and evidence fields | Expected observation, confirmation owner/time, permitted scope and how the workflow waits or stops |

Do not execute the production workflow, vendor demonstration or an unreviewed import to discover its interface. Review connection and initialization code as carefully as output operations. Keep raw SCPI/vendor calls inside the reviewed adapter; a handoff never authorizes arbitrary commands or code.

An LLM-derived output operation requires the appropriate local/operator review of its command mapping, limits and stopping procedure before hardware use. Reuse existing authorization where it covers the actual operation and installation; do not ask again for every already-authorized parameter within that scope. A manufacturer range is not a sample-specific safe range.

## 2. Inspect a candidate offline

Create a focused candidate folder outside production code. Include a source/provenance record, proposed typed operations, lifecycle effects, simulator/fixtures, expected result units, timeouts and device-specific stop/verification procedure. This is review material, not an installed executable plugin.

For every operation, distinguish observation, triggered acquisition, configuration, output and movement. A method called `read`, or a command ending in `?`, may trigger acquisition or alter state. Audit dependencies and defaults, including VISA clear/reset, range selection, autoranging, reference settings, serial RTS/DTR and connection-time writes.

Record a candidate as draft until its protocol and exception fixtures pass. Simulation proves the modeled contract; it does not prove physical identity, wiring, sample limits, settling, interlock operation or successful real shutdown.

## 3. Discover resources in two explicit stages

**Stage A: local inventory.** Inspect OS USB/serial metadata, installed vendor/VISA backends and already configured resource names. Do not open instrument sessions. Treat this as address evidence, not device identity. Review the selected backend before enumerating: a VISA discovery call may probe a bus/network even if it does not call `open_resource`. There is currently no general LabOS passive-discovery CLI to invoke.

**Stage B: reviewed identity observation.** Use the operator's established scope for one selected resource and a known model/transport identity procedure. GPIB or USBTMC equipment that documents `*IDN?` may use that reviewed query; USB RAW or an unfamiliar protocol is not automatically eligible. Do not broadcast identity queries, instantiate all candidate drivers, or send `*IDN?` to unknown serial ports. Serial opening itself can affect RTS/DTR. Report unanswered or malformed responses without guessing an identity or changing instrument settings to make discovery succeed.

Before any session, resolve instrument ownership and active acquisition. A new logical device name or configuration path does not make an already owned physical address available.

## 4. Qualify the installation

Keep these records separate:

- **Driver capability:** reviewed software/model support, typed operations, units, implementation/runtime/dependency hashes, native limits and stop implementation.
- **Station binding:** actual PC, canonical resource/serial identity, wiring, terminal role, calibration and current ownership.
- **Operating grant:** who authorized which operations, sample/setup bounds, expiry, prerequisites and evidence revision.
- **Live outcome:** fresh raw readbacks, errors, stop/close evidence and physical uncertainty.

Copying a driver or manifest transfers no installation/output authority. A changed implementation, dependency, SDK, binding or protection policy invalidates affected qualification; changes to plan data within an already qualified envelope should not require a new driver release. The current fixed physical pilots do not yet implement this general envelope mechanism.

Review and simulate stopping before the first limited write. The first bounded live write also validates its actual stop/readback path. Do not wait until a high authorization rank to think about stopping. UNKNOWN is a recovery/ownership condition, not a higher commissioning level; preserve the journal and reconcile before retrying.

A manual device remains manual in execution records. Software completion cannot substitute for the operator's required confirmation.

## 5. Return a concrete handoff

Use `PC_INTAKE_TEMPLATE.json` and `AGENT_HANDOFF_EN.md`. Include source route/revision, model evidence, proposed operations, initialization effects, dependencies, offline fixtures, physical ownership, missing binding/limit facts and the next bounded commissioning step. Mark unavailable facts `null`. Attach focused excerpts and hashes, not credentials or the entire production environment.

Central and local assistants should continue offline preparation while a live prerequisite is missing. The local persistent executor remains the only runtime controller. Do not turn the report-only worker into an instrument controller or launch a second measurement loop.

## Primary-source checks, 2026-11-01

| Candidate | Verified scope and connection caveat |
| --- | --- |
| QCoDeS SR830 | Version0.62.0 provides the SR830 driver; its VISA base can clear the device and initialization performs queries. [Driver](https://github.com/microsoft/Qcodes/blob/v0.62.0/src/qcodes/instrument_drivers/stanford_research/SR830.py), [VISA lifecycle](https://github.com/microsoft/Qcodes/blob/v0.62.0/src/qcodes/instrument/visa.py) |
| QCoDeS Keithley2400 | Version0.62.0 construction writes trigger/data-format settings. [Source](https://github.com/microsoft/Qcodes/blob/v0.62.0/src/qcodes/instrument_drivers/Keithley/Keithley_2400.py) |
| PyMeasure SR830 / Keithley2400 | Version0.16.0 provides both. Its VISA adapter opens the resource; Keithley2400 also sets data format during construction. [SR830](https://github.com/pymeasure/pymeasure/blob/v0.16.0/pymeasure/instruments/srs/sr830.py), [2400](https://github.com/pymeasure/pymeasure/blob/v0.16.0/pymeasure/instruments/keithley/keithley2400.py), [VISA adapter](https://github.com/pymeasure/pymeasure/blob/v0.16.0/pymeasure/adapters/visa.py) |
| PyMeasure Thorlabs | The current documented class names PM100USB. Do not infer PM100D qualification from the historical phrase PM100. [API](https://pymeasure.readthedocs.io/en/latest/api/instruments/thorlabs/thorlabspm100usb.html) |
| pylablib Thorlabs | Documentation says the class was tested on PM160. Its GenericPM constructor sends `INIT`; family similarity is not a PM100D physical test. [Documentation](https://pylablib.readthedocs.io/en/latest/devices/Thorlabs_pm.html), [Version1.4.5 source](https://github.com/AlexShkarin/pyLabLib/blob/v1.4.5/pylablib/devices/Thorlabs/misc.py) |
| Thorlabs vendor SDK | Official product list includes PM100D and PM160. Review each example before adapting it; examples can initialize and set wavelength. [Official repository](https://github.com/Thorlabs/Light_Analysis_Examples/blob/main/README.md) |
| pyvisa-sim | Use a pinned version and test the exact fixture. Version0.7.0 has a documented no-response-dialogue regression; a main-branch fix is not proof of a released package fix. YAML contract simulation needs additional explicit blocking/disconnect/physical-recovery tests. [Definitions](https://pyvisa.readthedocs.io/projects/pyvisa-sim/en/latest/definitions.html), [Issue167](https://github.com/pyvisa/pyvisa-sim/issues/167) |

Additional transport references: [PyVISA query/discovery semantics](https://pyvisa.readthedocs.io/en/latest/introduction/communication.html), [pySerial opening effects](https://pyserial.readthedocs.io/en/latest/pyserial_api.html#serial.Serial.open).
