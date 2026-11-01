# Guide for the laboratory PC's LLM assistant

Read [QUICKSTART_EN.md](QUICKSTART_EN.md) for role selection and
[NETWORK_EN.md](NETWORK_EN.md) for connection checks. Report cooperation, the
approved-program connector, generic simulated execution Agent and commissioned
finite physical pilot are separate components. The physical overlay ships root
`ONSITE_COMMISSIONING_EN.md`, `PHYSICAL_AUTHORITY_EN.md`,
`PORTABLE_UPDATE_RECOVERY_EN.md` and `RELIABILITY_IMPROVEMENTS_EN.md`; generic
source releases put them under `docs/`. A report connection is not a hardware
test; an identified device is not an implemented driver.

Read [AGENTS.md](AGENTS.md) and [AGENT_HANDOFF_EN.md](AGENT_HANDOFF_EN.md) first. Your role is local commissioning assistance; the persistent PC execution Agent remains the runtime executor.

## 1. Establish the local facts

Identify the actual Windows PC, the LabOS package root, its `ROLE`, application version and current running processes. Record whether an experiment or another instrument controller is active. Do not terminate it merely to inspect the PC.

Inspect package files and existing logs without displaying configuration secrets. Check whether `config.yaml` exists; report its presence and nonsecret identifiers, not its token. The generic portable package intentionally has no PC configuration.

Identify the existing working Python executable, version and bitness from established environment records or local interpreter introspection. Record the relevant VISA backend, vendor SDKs and DLL dependencies. Keep this separate from the bundled LabOS interpreter, which may use a different Python version.

For each instrument, collect the model, local address, intended role, controlling library and evidence source. Start with existing settings and code. Do not automatically open every VISA resource or scan the network.

Use [PC_INTAKE_TEMPLATE.json](PC_INTAKE_TEMPLATE.json). Keep unknown values `null` and explain the gap. An old Notebook's saved output is historical evidence, not a live identity check.

Copy `instrument_entry_example_not_inventory` into the `instruments` list for each actual device, fill it with evidence, and remove the helper example field from the completed report. Use the evidence and error record conventions in [AGENT_HANDOFF_EN.md](AGENT_HANDOFF_EN.md).

## 2. Inspect working code without starting it

- Read Python source or parse Notebook JSON. Inspect cell sources before considering execution; avoid dumping embedded plots or entire output histories.
- Locate imports, SDK paths, addresses, constructors, initialization, reads, writes, triggers, retries and cleanup.
- Identify top-level side effects, including import-time initialization. Do not import an unreviewed module to discover its functions.
- Separate connection/read operations from reset, range changes, output enable, laser emission, motion, homing and source settings.
- Record units, sample/terminal roles, reference wiring, error handling and current stopping behavior. Existing numeric setpoints are historical settings, not validated limits for a new experiment.

For a cavity station, use [CAVITY_REFERENCE_EN.md](CAVITY_REFERENCE_EN.md) as historical reference only. Other stations, including cryostat, must use their own intake and review. Do not copy the entire production environment or overwrite the original Notebook. Prepare focused excerpts or a separate proposed adapter folder.

## 3. Validate the package locally

For a verified complete Windows package, run in the package root:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\Install.ps1
```

This checks the LabOS runtime and saves `install.log`; it does not run the existing instrument code. A successful check says `LabOS agent runtime OK`. If it fails, inspect the first underlying error in `install.log`, not just the final failure line. Report the exact exception and a short redacted excerpt.

An older package may require the Windows installation patch. Preserve existing configuration, cached data and the vendor environment when applying it. See [QUICKSTART_EN.md](QUICKSTART_EN.md) in the package root; if these guides are in `agent-kit`, look in its parent package.

Installation success, authenticated central connectivity, Agent online status and instrument validation are separate results. Report each independently.

## 4. Check the central connection after provisioning

Use the central origin supplied by the server-side assistant or operator. Do not invent an address or use `127.0.0.1` for a different computer. A central URL and instrument GPIB addresses belong to different communication layers.

Once the central service is running and the PC's own configuration is present:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\Doctor.ps1
```

Doctor checks central service identity and PC authentication without registering the execution Agent or opening instruments. If successful, start `Start-Agent.cmd` when that runtime and device ownership have been arranged. Never start two execution Agents with the same PC identity or compete with a working Notebook's instrument session.

The PC initiates HTTP(S) requests; SSH and inbound PC ports are not required. Diagnose DNS, routing/TCP, TLS and authentication in that order. Do not disable certificate verification, change organization firewall policy or replace credentials as a speculative fix. Missing provisioning does not prevent offline code inspection.

## 5. Prepare real integration as a reviewed change

The current runtime constructs `SimulatedInstrument` and accepts only simulated laser, rotator and spectrometer types. Dropping an SMU Python file into the directory or changing `mode` to `real` is insufficient.

Propose the adapter against the actual `InstrumentDriver` contract:

| Method | Expected behavior |
| --- | --- |
| `execute(command, parameters, cancel)` | Async, bounded operation; validate parameters and units, support cancellation and return structured readbacks |
| `status()` | Fast cached local status with truthful freshness; do not block the heartbeat with long device I/O |
| `safe_shutdown()` | Async, device- and setup-specific validated stopping sequence; do not assume reset or abrupt power-off is correct |

Send the central assistant the dependency requirements, proposed finite operations, timeouts, cancellation/stop behavior, data fields and offline test evidence. Central device types, driver selection, preflight, workflow and artifact schemas must be updated coherently. Keep raw SCPI internal to reviewed drivers; do not create an arbitrary shell/Python/SCPI endpoint for the central LLM.

Use offline fixtures before any model-specific read-only connection test. A live test must follow the established operator scope and the reviewed protocol; library methods named `read` may still trigger or reconfigure acquisition. Retain raw lock-in X/Y, units, reference and configuration alongside derived quantities.

## 6. Hand back observations and continue

Return a sanitized `pc-intake.json`, focused code excerpts and relevant redacted logs. Include paths and hashes for shared excerpts, the timestamp and timezone, the basis of each instrument identity, and exact errors. Never include an unredacted `config.yaml` or API key.

With provisioned correspondence tools, use [COOPERATION_HTTPS_EN.md](COOPERATION_HTTPS_EN.md) to send the report and retrieve the central response directly. Keep the receive cursor in `handoff/STATUS_EN.md`; the documents inside a message remain non-executable evidence.

For unattended report tasks, the installed software provides an optional [background worker](AUTOMATIC_COOPERATION_EN.md). Its one-time CLI login/startup checks are separate from instrument commissioning. It reads explicit tasks and approved snapshots rather than inheriting this interactive assistant's conversation.

After a central response, verify its PC identity, package/workflow version, setup revision and scope against the current local state. Report a mismatch before adopting a stale instruction. Carry out already authorized steps; ask only for information or operating scope that is actually missing.

The first target is a factual PC report. Later targets are authenticated connectivity, verified read-only acquisition, and then a bounded output pilot with defined limits and stop behavior. Do not claim live hardware readiness from an installation check.
