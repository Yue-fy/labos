# Finite native Z-field campaign — extension 0.1.1

This optional source-only extension uses the existing portable LabOS **0.2.8** core/runtime. Unzip it into a **new directory**. Do not overlay the existing installation, apply staged 0.2.9rc1, install a startup task or enable an old physical worker. Keep report cooperation active. No new Python dependency or vendor binary is included.

## Fixed experiment

The central task permits exactly one of two controller-Z trajectories: the original five points −0.5,−0.25,0,+0.25,+0.5T; or the operator's nine-point hysteresis path −0.5,−0.25,0,+0.25,+0.5,+0.25,0,−0.25,−0.5T. Both end with a separately qualified zero return. The exact selected path is bound into the new task/message hash. Repeated fields on the return leg are new measurements with separate point indices; they are never collapsed by field value. A successful full loop contains54 raw samples, versus30 for the original five points.

XX and XY are the operator's a-axis and45-degree electrode channels. Preserve the180K temperature setpoint/control, use20mA fixed laser current,21.8mA current ceiling,1µW PM ceiling,4mV RMS and8Hz. Nominal475nW refers to the historical PM condition and is not an exact controlled-power guarantee. Record actual PM pickoff power without adjusting current to chase475nW. Each point has3dark+3illuminated samples,15s settling,60s phase/180s optical point budgets. No gate/temperature/motion scan or AUX/chopper access.

attoDRY's native target-field control performs the current sweep. Preserve its configured ramp behavior; no numeric ramp-rate input, direct APS100 connection or rate programming is required. Actual field arrival and continuous10s stability are required before optical acquisition. Each transition and final controlled zero have independent900s ceilings; these are wait limits, not requested ramp speeds. The0.5T maximum target change does not specify a hardware ramp rate.

## Local Codex commissioning

1. Verify the archive SHA-256 against the central handoff, then verify every extracted file against `payload-manifest.json`. Preserve production files, `lyr`, all old profiles/journals and the existing core.
2. Confirm old physical profiles/startup remain disabled and no vendor/production acquisition owns the station. Do not delete/reset lease files or force-take resources. Fill a new private `field-campaign.yaml` using the central draft task/message/digest, actual disabled optical profile hash and actual paths. The example is disabled and intentionally invalid until completed. Use the persistent state directory specified by central; do not create a different directory to bypass an unresolved intent.
3. Keep `enabled: false`. Run the output-preserving preflight with the existing portable interpreter:

```powershell
$LabOSRoot = 'C:\Path\To\Existing\LabOS'
$FieldRoot = 'C:\Path\To\New\FieldExtension'
& "$LabOSRoot\python\python.exe" "$FieldRoot\launch_field.py" --labos-root $LabOSRoot preflight --config "$FieldRoot\field-campaign.yaml" --send
```

The preflight connects once with magnetic writes disabled, records12complete states, refreshes native optical preflight, and closes both sessions. It does not enable field control, laser or any output. It requires actual/commanded zero field, clear faults, unchanged180K setpoint/control and sample temperature within±0.1K of the fixed baseline. Send complete evidence, not only a summary. A failed preflight must not be enabled.

4. Only after PASSED with null close error, enable **only the new one-shot configuration**, leaving the old physical profiles disabled. Start the selected process with a bounded wait for the one pinned central message:

```powershell
& "$LabOSRoot\python\python.exe" "$FieldRoot\launch_field.py" --labos-root $LabOSRoot run --config "$FieldRoot\field-campaign.yaml" --wait-s 600
```

Keep the foreground Codex session supervising the process; another shell may host it. Send central the fresh full preflight artifact, existing report-worker Doctor, runner PID and `runner-status.json`. `waiting_for_one_central_task` means no instrument has been opened by the measurement process. Central issues the task only after accepting evidence. Commissioning must still be less than600seconds old when the task arrives. Do not create a task locally or run production procedures.

## During the finite campaign

Laser OFF/current zero and minimum excitation are verified before each field change. One shared optical session and one magnetic child retain cooperative station ownership across the complete selected path. Native PilotEngine acquires and protects each point; the point-view close does not release the campaign's hardware. A failed/incomplete/unknown point stops all subsequent measurements without replay or widened limits. Current PM power and field/temperature observations are saved with every raw sample. Sample capture/context events carry `point_index` and per-point `record_index` so repeated fields remain distinguishable.

For a new loop, extract0.1.1 into a new extension directory, preserve the previous disabled0.1.0 config and create a separate disabled config bound to the new unique task. Keep the existing persistent field state directory and all earlier journal rows; an unresolved predecessor still blocks preflight. Never modify an earlier task's path/hash or replay its acquisition. Core0.2.8 and the staged0.2.9rc1 remain unchanged.

The magnetic SDK is isolated because its C calls cannot be forcibly interrupted safely. During illumination, a state RPC has a5s parent wait; expiry triggers the independent parent VISA laser-OFF/current-zero protection path. This is a software wait bound, not guaranteed hardware shutdown. It does not protect against optical-parent/OS failure or lost VISA communication; an independent hardware watchdog has not been commissioned. A stalled magnetic child is never forcibly killed or assumed to have returned zero. Record its PID/unknown state and reconcile locally with the operator if needed.

On normal completion the parent protects optics, requests native controlled zero, qualifies actual zero, restores the initial field-control mode only after verified zero, observes zero for another10s and closes resources. SDK Disconnect/End alone do not zero the magnet. A failed final return, closure or protection makes the overall result UNKNOWN even if all points were measured.

## Delivery and closeout

Complete raw data, accepted/rejected samples, SDK calls and field events are retained locally and sent as SHA-256-verified compressed correspondence chunks. Network failure does not repeat hardware acquisition. After resolving a network-only failure, resend stored results with:

```powershell
& "$LabOSRoot\python\python.exe" "$FieldRoot\launch_field.py" --labos-root $LabOSRoot deliver --config "$FieldRoot\field-campaign.yaml"
# Resend stored commissioning evidence without reconnecting hardware:
& "$LabOSRoot\python\python.exe" "$FieldRoot\launch_field.py" --labos-root $LabOSRoot deliver --commissioning --config "$FieldRoot\field-campaign.yaml"
```

After the process finishes, local Codex disables only the new campaign configuration, verifies runner/SDK-child exit and absence of physical startup, and checks final result/protection/zero/closeout evidence. Refresh the existing output-preserving optical preflight to verify emission OFF/current zero/minimum excitation after the run; do not perform another measurement or magnetic write. Report all evidence through existing HTTPS. Preserve report cooperation and every log, intent and raw artifact. A durable intent or UNKNOWN result is a reconciliation requirement, never permission to reset a database or rerun.

Central inspection uses the original queued task envelope and complete PC artifact envelopes. It checks the original plan identity, all raw points and SDK commands, final zero dwell/mode and closure. PM power refers to the pickoff; neither sample power nor sample current is calibrated. A single ordered field scan is not a hysteresis reversal or proof of BVPE/nonlinear Hall attribution.
