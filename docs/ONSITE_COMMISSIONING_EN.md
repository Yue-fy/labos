# Onsite commissioning checklist

All physical measurement is postponed until onsite wiring inspection. This
guide prepares a later cutover; it enqueues no task and grants no operating
permission. Software rehearsal results are synthetic. Use the independently
verified candidate and a trusted interpreter/runtime. Preserve the working
vendor environment, configuration, journals, raw artifacts and previous backups.

## Before any software or instrument action

1. Observe physical wiring and output displays first. Record time, operator and
   station identity in the local commissioning record. A stopped process is not
   evidence that outputs are protected.
2. Inventory and retire every legacy physical worker, copied installation,
   cached launcher, scheduled task and Startup registration, including other
   user accounts. Reconcile every old execution and unknown outcome using
   independent local readbacks. Do not delete journals or replay old tasks.
3. Stop and freeze every declared worker/profile, including report and program
   components, before updating code or dependencies. Never apply an overlay
   through an active report-only Agent or run the complete legacy procedure.
4. Follow [PORTABLE_UPDATE_RECOVERY_EN.md](PORTABLE_UPDATE_RECOVERY_EN.md).
   From the extracted update directory, an example isolated launch is:

   ```powershell
   & 'C:\LabOS\station\python\python.exe' -I .\Apply-Pilot-Update.py --target 'C:\LabOS\station'
   ```

   Substitute the actual independently trusted interpreter and target. `-I`
   excludes ambient Python path/user-site input; it cannot repair a compromised
   interpreter or standard library. Retain the update directory and transaction
   ID under `data/pilot-update-backups/`. Unknown edits or missing evidence
   require deliberate reconciliation; recovery never guesses or overwrites them.

## Record wiring and calibration facts

Complete these fields from inspection and supported model-specific checks;
unknown fields block the relevant physical scope. Do not invent readbacks.

The shipped `pilot-worker.example.yaml` is uncommissioned and attests no current
chopper state. Before enabling a local profile, supply the actual sample identity
and current onsite observations (including a recorded Locked observation where
the chosen scope requires chopper lock), and pass that scope's preflight.

| Field | Required local evidence |
| --- | --- |
| Device/session ownership | Actual identities, addresses, exclusive station ownership, fixed supported adapter scope |
| Electrode/crystal axes | Source and voltage contact pairs, polarity, crystal directions, injection and return path |
| Electrical excitation | Source settings/readbacks, gain, filter, time constant, reference source/frequency, harmonic and input mode |
| Current calibration | Independently established current path/calibration; high contact resistance alone is insufficient |
| Optical power | Measurement plane, attenuation/pickoff, calibration and the unchanged local power ceiling |
| Chopper/reference | Present state, actual reference topology, diagnostic outcome; no assumed locking |
| Independent protection | Emission OFF, zero laser-current setpoint, measured minimum excitation, all cleanup and close results |

XX/XY/AUX labels do not establish longitudinal/transverse geometry or Vxx/Vxy.
The earlier mapping describes crystal-axis directions; contact roles and
polarity still require inspection. SR830 minimum **4 mV RMS is still excitation**,
neither OFF nor calibrated sample current. This maintenance adds no voltage,
current or power range. Retain all existing numeric bounds, strict decoder and
diagnostic acknowledgments, approval and ownership checks and independent
cleanup. No timeout or failed device may silently remove a required channel.

An OFF/ON optical response alone does not identify BVPE. Dark harmonic voltage
is neither a calibrated I-V curve nor proof of nonlinear Hall transport. The
`optical_readback` scope deliberately excludes chopper serial after its strict
communication diagnostic failed. It does not repair that fault or establish
modulation/reference locking. Other identified devices (including attoDRY,
camera, spectrometer, motion and AUX) are not automatically implemented drivers.

## Repeatable software acceptance, without instruments

In a **source checkout** with the existing development dependencies, use a new
output directory for every rehearsal (substitute actual checkout/interpreter):

```bash
PYTHONPATH="$PWD/src" /path/to/trusted/python -m pytest tests/test_commissioning_rehearsal.py tests/test_pilot.py tests/test_pilot_worker.py tests/test_pilot_update.py -q
PYTHONPATH="$PWD/src" /path/to/trusted/python scripts/rehearse_commissioning.py --output-dir /tmp/labos-rehearsal-new-001
PYTHONPATH="$PWD/src" LABOS_TEST_PWSH=/path/to/pwsh /path/to/trusted/python -m pytest -q
PYTHONPATH="$PWD/src" /path/to/trusted/python -m ruff check src tests scripts
git diff --check
```

The physical overlay ships the same canonical script at the **PC package root**,
not `scripts/`. In PowerShell at that root, the trusted embedded runtime already
has its configured package source path:

```powershell
.\python\python.exe -B .\rehearse_commissioning.py --output-dir .\handoff\synthetic-rehearsal-new-001
```

It imports no vendor driver, constructs no native manager/session, calls no
model/provider and opens no network connection. The versioned JSON is explicitly
synthetic, includes the actual imported source version and refuses any existing
output directory. Four real-engine scenarios cover completion, slow startup
with observed-cost refusal before ON, partial I/O evidence, and UNKNOWN cleanup.
The worker integration test additionally proves UNKNOWN blocks a different
future task after restart using only temporary SQLite and in-process transport.
These checks do not certify native initialization or hardware protection.

## Later onsite cutover and new finite-test entry criteria

Upgrade central and the selected PC in a separate onsite cutover. Read
[PHYSICAL_AUTHORITY_EN.md](PHYSICAL_AUTHORITY_EN.md) before activation. Authority
starts uncommissioned. Record the enabled, frozen validated profile hash and
scope from the selected PC, retirement/reconciliation attestations and operator
commissioning. Keep referenced files fixed too: the hash binds validated worker
configuration/paths, not every referenced file's bytes.

Commissioning takes a new cutoff and retires **all historical pilot task IDs**,
including those without artifacts. Never replay a failed or scope-less task.
At most one attempted execution may obtain the transactional grant; readiness
is only a recent observation. Every attempt still needs a newly committed claim
for that same frozen hash and explicit scope. There is no automatic reset,
expiry or unblock; an uncertain/active gate cannot be cleared by recommissioning.

Only after wiring, calibration prerequisites, local protections, identity/scope,
legacy retirement, reconciliation and commissioning are evidenced may a
**separately authorized new finite task** be considered. This guide neither
creates that task nor pre-authorizes it. Preserve unchanged existing limits.

For the selected profile inspect its configured state directory: default
`data/physical-pilot/status.json`, `physical.sqlite`, `correspondence.sqlite`,
`events.jsonl` (and rotated files), and `artifacts/`. Launch logs are under
`logs/physical-pilot-<identity>/<launch-id>.stdout.log` and `.stderr.log`.
Status/stage events are local snapshots, not continuous central telemetry.
Archive raw acquisition, rejection, cleanup, close, claim and central-result
evidence together. Use the profile's cooperative stop/startup-disable workflow
as instructed; inspect independent output readbacks afterward. Blocking native
I/O can delay cancellation. Never delete evidence to unblock the next run.

## Implemented versus planned

Implemented software boundaries and evidence are described in
[RELIABILITY_IMPROVEMENTS_EN.md](RELIABILITY_IMPROVEMENTS_EN.md). Physics-guided
theory feedback, autonomous calibration, broad learning memory/RAG, arbitrary
MCP/skill execution and coordinated cross-PC physical barriers remain **Planned**.
None substitutes for the onsite facts above or deterministic local protection.
