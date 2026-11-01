# Dark a-axis voltage short test — LabOS 0.2.7

This is the operator-approved replacement for the next measurement, not a replay
of the failed optical task. Sample: **CrSBr 1**. The operator identifies XX as the
a-axis pickup, XY as45degrees and AUX as b. This task acquires **XX only**.

## Finite scope and terminal state

- XX SR830 terminal excitation stays at **0.004 V RMS**, internal reference near
  **8 Hz**. There is no source-amplitude sweep and no frequency write.
- Sequential XX detection at1f then2f, three raw X/Y readings per phase,15s
  settling per phase,30s phase and90s total acquisition budgets. Existing time
  constant must be at most1s and local settling policy must be satisfied.
- Exactly three VISA sessions: CLD1010LP (identity/OFF/interlocks/protection),
  XX SR830 (voltage readout/excitation) and Keithley2400 (identity and output-OFF
  status only). No gate voltage/current measurement or gate setting/write.
- PM100D, chopper, XY and AUX are excluded from all sessions and queries. Their
  absence is not a claim that the earlier chopper communication fault is fixed.
- No laser enable path. Emission OFF and zero-current setpoint are independently
  read back during cleanup. TEC settings and the exact local connection-diagnostic
  acknowledgment are preserved; a changed fault never receives automatic reset.
- After each phase and on final exit, restore minimum4mV RMS and XX1f, with
  amplitude/harmonic/fundamental-frequency readback.4mV is **not zero/OFF**.
  Protection remains local and independent of network/model availability.
- This records lock-in voltage responses. There is no calibrated sample current,
  IV curve, resistance, contact polarity, calibrated sample voltage, or established
  nonlinear Hall effect. Terminal excitation is not the measured XX voltage.

Harmonic selection changes detection, not SINE OUT frequency. See the official
[SR830 manual](https://www.thinksrs.com/downloads/PDFs/Manuals/SR830m.pdf),3-8 and5-5.
The executor checks actual frequency and amplitude rather than relying on this alone.

## One local update using the public release

Use the existing provisioned LabOS runtime and its portable Python. Keep its
config.yaml, cooperation.yaml, old pilot-worker.yaml, source roots, secrets,
journals, failed-task ledger and raw artifacts. Keep Integration-photonics and
lyr unchanged. Do not run its measurement programs or import its drivers.

1. Fetch **v0.2.7** from https://github.com/Yue-fy/labos/releases/tag/v0.2.7.
   Download LabOS-Cryostat-Physical-Update-0.2.7.zip and SHA256SUMS, verify SHA256,
   and extract completely to a new directory. No GitHub login is required.
2. Cooperatively stop report cooperation and any physical workers. Confirm stopped
   status and final protection evidence; do not kill a running acquisition. The
   previous optical worker is expected disabled/stopped. If dark-a-worker.yaml
   already exists, preserve it and its state and review before proceeding.
3. Apply the verified overlay using the existing portable Python:

   ```powershell
   & '<existing LabOS>\python\python.exe' -I '<extracted update>\Apply-Pilot-Update.py' --target '<existing LabOS>'
   ```

   The updater checks report/original/dark-a worker locks and backs up replaced
   code. It preserves live YAML and all journals. Source git pull alone does not
   update a separate portable runtime.
4. From the existing runtime folder, set PYTHONPATH and prepare a **new disabled**
   local profile. Use **80** as the central cursor floor for this specific handoff;
   the failed optical task was sequence64 and must never run in the new ledger.

   ```powershell
   $env:PYTHONPATH = Join-Path (Get-Location).Path 'src'
   .\python\python.exe -B .\Check-Pilot-Runtime.py
   .\python\python.exe -B -m labos.dark_a --source .\pilot-worker.yaml --output .\dark-a-worker.yaml --start-after 80
   ```

   Preparation performs no instrument access and refuses overwrite or an existing
   dark-a state directory. It copies the actual CLD/XX/gate bindings, exact station
   config/lease path, temperature and diagnostic acknowledgment. It disables
   optical authorization, uses data/dark-a-pilot and limits30s/90s. It never edits
   the original profile. Do not replace working bindings with repository examples.
5. Run the **output-preserving preflight**, then the no-instrument Doctor:

   ```powershell
   .\python\python.exe -B -m labos.cryostat_pilot preflight --config .\dark-a-worker.yaml --output .\dark-a-preflight.json
   .\python\python.exe -B -m labos.pilot_worker doctor --config .\dark-a-worker.yaml
   ```

   Require PASSED, exact identities, laserOFF, inactive gate, existing4mV/8Hz,
   ready XX voltage input/reference/time constant and clean closure. A failure
   requires factual local reconciliation; no guard bypass or automatic retry run.
6. Restart normal report cooperation, send sanitized preflight plus installation
   evidence to central over existing authenticated HTTPS. Report software
   version, payload hashes, preserved-file checks and actual excluded devices.
   Never send secrets or publish operational evidence to GitHub.
7. Only after the local preflight PASSES within the exact limits above, the
   trusted local Codex may enable **only** dark-a-worker.yaml approval.enabled
   and start the worker to await central review and a new task:

   ```powershell
   .\Install-Pilot.ps1 -Config .\dark-a-worker.yaml
   ```

   Send its Doctor/start status. Central checks the preflight before queuing
   any physical task. The separate worker receives one new central
   labos_pilot_task. Do not create a task locally, replay the old task, or start
   legacy procedures. No new general experiment authorization is needed: the
   operator already approved this exact short test. The report-only background
   Codex cannot perform this local installation/activation step.
8. After the single task returns, verify raw artifact/independent protection
   results, disable approval, cooperatively stop this worker and remove its
   startup shortcut using Stop-Pilot.ps1 -Config .\dark-a-worker.yaml -DisableStartup.
   Preserve all journals, including failed or UNKNOWN outcomes. Report cooperation
   can remain running. No retry or amplitude escalation is implied by weak/zero data.

Central must use a new unique task ID. Network delivery retries resend the saved
artifact; they must never repeat physical acquisition. An unresolved execution or
failed cleanup blocks further physical runs until actual local reconciliation.
