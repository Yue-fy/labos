# Cavity reference: what the Notebook establishes

Source supplied by the operator: `subComputer/cavity/Fe-JFET optoelectronic test_Shuang_2.ipynb` on the central project. Its actual production path on the cavity PC must be identified locally.

The following facts come from static code inspection and saved output. They are **reference facts**, not new instrument queries or confirmation of the current wiring.

| Reference device/role | Address or connection in the code | Evidence basis |
| --- | --- | --- |
| Source-drain SMU: Keithley 2401 | `GPIB0::1::INSTR` | Initialization code and saved identity output |
| Gate SMU: Keithley 2400 | `GPIB0::2::INSTR` | Initialization code and saved identity output |
| Lock-in: SRS SR830 | `GPIB0::8::INSTR` | Initialization code and saved identity output |
| Chopper: SRS SR540 | SR830 AUX OUT channel 1 to chopper control-voltage input; chopper `f` reference to SR830 REF IN | Code comments/configuration; physical cables need local inspection |
| Notebook kernel | `.venv_old (3.11.7)` | Notebook metadata; actual interpreter/bitness still to inspect |

The reference imports the `Keithley2400` wrapper for the two SMUs, including the device identified historically as a 2401. Reusing that wrapper requires model-specific compatibility review; the import name is not the instrument identity.

Other code covers NKT laser control, a Thorlabs power meter, Kinesis motion/shutter/polarization hardware and an AWG. These are not automatically part of the first four-device pilot. Inventory actual devices before expanding the scope.

## Initialization has physical side effects

The Notebook's initialization cell contains SMU `*RST`/reset operations and NKT register writes enabling emission and setting power. It also configures other instrument and motion/shutter state. Do not execute this cell or the entire Notebook merely to test Python, network connectivity or device presence.

Historical chopper frequency-versus-voltage coefficients are stored in the code. Treat them as a recorded calibration associated with that setup; do not infer they remain valid after changing the chopper range, blade, wiring or controller. A software setting is distinct from an observed frequency.

In this reference, chopper actuation and lock-in measurements share the SR830 control resource. An integration must serialize access through the same owner/session rather than creating competing controllers for the two logical functions. Verify the AUX channel assignment locally before using it.

## What the PC assistant should verify next

1. Locate the working environment and relevant source without executing hardware initialization.
2. Record the actually connected device models/addresses and identify which facts come only from this reference.
3. Identify any active controller or Notebook kernel that owns the devices.
4. Map the read functions, set functions, dependencies, timeout handling and stop sequence into separate proposed adapter operations.
5. Obtain the actual sample/terminal wiring, allowed ranges and operating scope before a corresponding output test.
6. Return a sanitized intake report with current observations and unresolved items.

Do not substitute these historical setpoints or addresses for a current setup definition. Start with offline inspection; live tests follow the reviewed model-specific procedure and established operator scope.
