# LabOS cryostat physical pilot, version 0.2.5

This optional executor implements a fixed LabOS command path. It does not launch
the old measurement application or import production modules. The existing
Codex cooperation worker remains a report/source reader. Physical commands run
in a separate deterministic worker with a separate ledger and local profile.

## Established scope

- Sample: **CrSBr 1**. Preserve raw channel names XX, XY and AUX; contact axes are
  unverified and the operator accepts a workflow test with this limitation.
- 730 nm CLD1010LP: candidate current **21.8 mA**, never automatically increased.
  Historical pickoff power was approximately 0.483 µW at this current. The new
  measured-power ceiling is **1 µW at the PM pickoff before the sample**, not
  calibrated sample-plane power. Current alone does not guarantee optical power.
- SR830 XX is a voltage source with **4 mV RMS** at 8 Hz. There is no external
  series resistor. Sample current is uncalibrated. The operator explicitly accepts
  returning to this minimum after every segment; it is not zero or output OFF.
- Optical baseline, illuminated response, then dark transverse second harmonic.
  XX remains at 1f, XY changes from 1f to 2f for the dark segment, AUX remains 1f.
  Reference topology must already match the commissioned local configuration.
- Three readings per segment, 15 s settling, at most 60 s per segment and 180 s
  acquisition budget overall. Successful slow queries also consume the budget.
  Each device transaction is bounded; independent protection runs on exit even
  after acquisition cancellation or expiry. Network and model latency are outside
  this local control loop.
- Laser emission OFF and zero-current setpoint are independently read back after
  every segment and on errors. Excitation is independently returned to 4 mV RMS.
  Failed protection or an interrupted execution latches UNKNOWN and blocks replay.
- No gate sweep, temperature/magnetic-field change, motion, TEC setting change,
  fault reset, automatic source search or source-amplitude escalation.

The operator has authorized this finite test. Missing resource bindings or failed
device checks require factual local reconciliation, not a new general permission
request. Do not silently bypass a guard to obtain data.

## Apply the update on the cryostat PC

Use the existing working LabOS folder, preserving config.yaml, cooperation.yaml,
native Codex configuration, source-root registration, journals and logs. The
Integration-photonics production tree and its `lyr` environment are references
only and must remain unchanged.

1. Extract the **entire** physical update ZIP to a new directory.
2. From the existing LabOS folder, run Stop-Cooperation.ps1. Wait until its active
   model call finishes and data/cooperation/status.json reports stopped. If a
   physical worker already exists, stop it cooperatively and inspect its final
   protection evidence before updating. Do not kill an acquisition process.
3. Use the existing portable Python to apply the extracted update:

   ```powershell
   & '<existing LabOS>\python\python.exe' -B '<extracted update>\Apply-Pilot-Update.py' --target '<existing LabOS>'
   ```

   The updater verifies payload hashes and worker locks, backs up replaced files
   under data/pilot-update-backups, and copies only declared LabOS files and pure
   Python dependencies. It does not overwrite configuration or existing journals.
   If it reports an active worker, wait for the cooperative stop and rerun.
4. In the updated folder, run the file-based import check:

   ```powershell
   .\python\python.exe -B .\Check-Pilot-Runtime.py
   ```

   The portable runtime now includes PyVISA and pyserial. Keep the already working
   NI-VISA/GPIB driver installation; no production Python environment is changed.
5. Restart the report worker with Start-Cooperation.ps1 in a persistent terminal,
   or its existing sign-in shortcut. Avoid duplicate worker instances.

## Commission actual local bindings

Copy pilot-worker.example.yaml to **pilot-worker.yaml**. Keep approval.enabled
false while preparing and preflighting it. A supplied template is not a hardware
observation or proof of safe beam delivery.

Copy the actual full CLD and PM VISA strings, station configuration path and
chopper blade/reference/harmonic/output codes from the most recent local station
configuration. Do not invent USB vendor/product IDs, create another station lease,
use wildcard discovery, or import/instantiate production drivers. The station
path selects the exact existing `.hardware-owner.lock` convention.

Check that the sample/730 nm source and PM pickoff match that same recent setup,
no other measurement owns these devices, and the beam route uses the established
enclosed experimental path. The operator's latest statement is that the MC2000B
is running and displays Locked; retain its confirmation note. This is manual PLL
evidence, not a query-verified lock. A later changed/stopped setup needs a fresh
state check. The executor checks its running state, configuration and reference
frequencies; it never starts or configures the chopper.

Set adapter_config.commissioned and manual_route_confirmed true only after these
bindings and the existing optical route are established locally. These flags do
not enable acquisition while approval.enabled remains false.

If an existing CLD configuration contains a documented connection-diagnostic
acknowledgment, copy its **exact observed tuple and original explanation**. Never
invent an acknowledgment, clear an interlock, alter TEC modes or reset a fault.
The profile preserves 26 °C with ±0.05 °C measured tolerance; it refuses an
unmatched existing setpoint rather than changing it. Gate output must already
be OFF; historical actual_zero_unverified remains unverified, without a new
zero-voltage claim. Reference settings must already match and time constants
must be at most 1 s. Stop and report exact mismatches instead of adapting silently.

## Output-preserving preflight and handoff

```powershell
.\python\python.exe -B -m labos.cryostat_pilot preflight --config .\pilot-worker.yaml --output .\cryostat-preflight.json
.\python\python.exe -B -m labos.pilot_worker doctor --config .\pilot-worker.yaml
```

Preflight opens only the explicit, exclusively leased VISA resources and COM10.
It performs fixed identity/status queries without reset or output-enable writes.
The JSON contains PASSED/FAILED, exact failing device I/O, identities, observed
settings and closure failures. The read-only settings queries can consume status
latches; do not run during someone else's acquisition. Doctor does not open any
device. Linux replay tests do not establish Windows/backend acceptance.

Send a sanitized preflight and commissioning report over existing HTTPS:

```powershell
.\python\python.exe -B -m labos cooperate send --role pc --config .\config.yaml --input .\cryostat-commissioning-report.json
```

Use a normal cooperation note/report envelope with an English body. Include the
preflight JSON, runtime versions, actual source-config path/hash, channel mapping
status, operator confirmation note and worker-start status. Do not send bearer
tokens, full private configuration, or unredacted credential-bearing logs.

After a PASSED preflight within the established scope, set approval.enabled true
and run Install-Pilot.ps1. This adds a separate sign-in shortcut and hidden worker.
It does not enqueue a measurement. The central operator queues exactly one finite
pilot after checking the returned evidence; the local worker preflights again.
The report worker cannot promote a report or model output to a physical task.

## Pilot result and stop behavior

- Local physical state: data/physical-pilot; log: physical-pilot.log.
- Raw immutable JSON: data/physical-pilot/artifacts, including partial/rejected
  samples, plan/config hashes, status readbacks and independent cleanup results.
- Full raw file uploads through the PC-scoped HTTPS endpoint before the reply.
  Central verifies checksum/task/plan and loads stored raw data for automatic
  review. Network retries reuse the saved result and never repeat device I/O.
- Stop-Pilot.ps1 requests cancellation between device operations and during
  settling. It is not a hardware emergency stop. Inspect the cleanup readbacks.
  After the first pilot, disable approval and the pilot startup shortcut until
  another test is deliberately commissioned. Do not delete the ledger or faults.
- Software cannot shut an output down after loss of the controlling process,
  power or physical instrument link; retain existing local hardware protections.

The immediate scientific outputs are **730 nm chopper-referenced photoresponse**
and **dark raw XY second-harmonic voltage**. BVPE and nonlinear Hall attribution
require later power/current/polarization/symmetry and leakage/heating controls.
Weak or null response is valid pilot data. Do not fabricate current calibration,
electrode assignments, a Hall coefficient or a successful measurement.
