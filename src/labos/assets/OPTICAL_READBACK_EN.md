# LabOS 0.2.8 — bounded laser OFF/ON readback

The operator wants real optical instrument/readback plots even when sample
response is weak or absent. This **explicit optical_readback scope** records PM100D
power and raw XX/XY voltages with laser emission OFF then ON. It is a separately
commissioned task, not a retry of either failed optical task.

The MC2000B COM10 query path produced corrupt command echoes. A 100 ms idle probe
also failed. This package does not claim to fix that fault. In this scope no
chopper port/session/query/write is created; its mechanical state is unchanged
and unverified here. Optical modulation, chopper phase correlation and BVPE are
not established by these readbacks. The original optical_transport scope retains
its strict chopper requirements with no automatic fault-driven fallback.

## Limits and output protection

- Sample CrSBr 1. Exact CLD1010LP/PM100D/XX SR830/XY SR830/gate2400 identities and
  bindings; AUX excluded. No wildcard discovery or legacy application/driver import.
- Nominal 730 nm source, at most 21.8 mA setpoint, PM pickoff ceiling 1 µW in both OFF
  and ON phases. These are the established limits; no increase to obtain a signal.
  PM wavelength correction stays 730 nm; power at the sample is not calibrated.
- XX terminal excitation stays 4 mV RMS near 8 Hz, no amplitude/frequency/gate sweep.
  Preserve voltage input, reference, time constant/status/harmonic checks. Gate
  is identity/OFF-status only, not a voltage/current measurement or setting.
- Preserve the actual station config/ownership lock, existing 26 °C TEC setpoint,
  temperature tolerance and exact documented CLD diagnostic acknowledgment.
  All interlock/mode/current/voltage/temperature checks remain; no fault resets.
- Three samples per phase, 15 s settling, 60 s phase and 180 s local acquisition budgets.
  Any power/communication/status fault stops acquisition. Independent cleanup
  attempts emission OFF, zero-current setpoint and minimum 4 mV RMS, including on
  cancellation/deadline. 4 mV is not zero/OFF. No automatic acquisition retry.
- Raw XX/XY values are voltage readbacks; sample current/polarity are uncalibrated.
  Do not label this an IV curve, nonlinear Hall or established BVPE measurement.

## Apply once on the existing Windows installation

1. Download the public v0.2.8 physical overlay and SHA256SUMS from
   https://github.com/Yue-fy/labos/releases/tag/v0.2.8. Verify the selected archive's
   SHA256 and fully extract into a new directory. No GitHub sign-in is required.
2. Cooperatively stop report cooperation and any physical workers before applying.
   Both existing physical profiles are expected disabled/stopped after diagnostic 102.
   Preserve all production files, lyr, live YAML, credentials, logs and ledgers.
   Keep the failed optical artifacts and completed dark data unchanged.
3. Apply with the existing portable Python:

   ```powershell
   & '<existing LabOS>\python\python.exe' -I '<extracted update>\Apply-Pilot-Update.py' --target '<existing LabOS>'
   ```

   The updater verifies all payload hashes and locks report/original/dark/readback
   worker states before replacing shared code. It backs up replaced files, retains
   live configuration and journals, and supplies the same pinned pure dependencies.
4. From the existing runtime folder, derive a NEW disabled profile:

   ```powershell
   $env:PYTHONPATH = Join-Path (Get-Location).Path 'src'
   .\python\python.exe -B .\Check-Pilot-Runtime.py
   .\python\python.exe -B -m labos.optical_readback --source .\pilot-worker.yaml --output .\optical-readback-worker.yaml --start-after 102
   ```

   Preparation does no device I/O, preserves original profiles/limits/bindings/
   acknowledgment, selects optical_readback and creates data/optical-readback-pilot.
   It refuses overwrite/existing state. Do not replace live values with examples or
   reset a ledger/cursor. Earlier tasks 64/89/96 precede the new cursor floor.
5. Run output-preserving preflight and no-instrument Doctor:

   ```powershell
   .\python\python.exe -B -m labos.cryostat_pilot preflight --config .\optical-readback-worker.yaml --output .\optical-readback-preflight.json
   .\python\python.exe -B -m labos.pilot_worker doctor --config .\optical-readback-worker.yaml
   ```

   Require a fresh PASSED result with the five exact identities, laser OFF, inactive gate,
   existing 4 mV / 8 Hz, qualified PM settings, XX/XY references and clean closure.
   Chopper must be explicitly out_of_scope. A failure does not authorize ignoring
   data, dropping another device or bypassing a protection. Report the exact fault.
6. Restart normal report cooperation. Send sanitized preflight/version/payload and
   preservation evidence through existing authenticated HTTPS. Only after PASSED
   within these exact limits, enable **only** optical-readback-worker.yaml approval
   and start its separate worker:

   ```powershell
   .\Install-Pilot.ps1 -Config .\optical-readback-worker.yaml
   ```

   Send Doctor and actual startup status. Keep other physical profiles disabled.
   Central reviews returned evidence and queues ONE NEW uniquely identified finite
   photoresponse task. Do not create/run a task locally or resubmit old tasks.
7. After its artifact and independent cleanup are verified, disable readback
   approval, cooperatively stop/remove its startup, preserving all results:

   ```powershell
   .\Stop-Pilot.ps1 -Config .\optical-readback-worker.yaml -DisableStartup
   ```

   Preserve failure/UNKNOWN outcomes. A network retry resends the same stored
   result without acquiring again. The report worker may remain running.

The background report-only Codex cannot install or activate this local executor;
a trusted local Codex/operator performs this one deployment step. Existing operator
permission already covers the bounded experiment; no new general authorization is
needed. Server will plot actual uploaded PM OFF/ON and XX/XY points. Weak/null
response is valid data; no synthetic curve or automatic power escalation is used.
