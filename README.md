# LabOS MVP

Central planning, local execution and traceable experimental data. The current software supports a central server, outbound Windows/Linux components,
generic simulated instruments and a separate opt-in finite physical pilot.
Report cooperation, approved-program execution, the generic Agent and physical
pilot have separate startup, state and authority boundaries.

The product interface, controls, installation tools, diagnostics and runtime messages use **English**. Existing Chinese deployment guides and bilingual presentation materials remain available.

Implemented: independent PC credentials, session isolation, preflight checks, exclusive device ownership, scans, pause/resume/stop, UNKNOWN outcome handling, local watchdogs, cached data upload, HDF5 export, an operator console and optional OpenAI plan drafts.

Version 0.2 adds acquisition quality checks, retained rejected data, plan/configuration fingerprints, reviewed references and existing test-code retrieval, source-linked drafts and versioned run reviews. See the [reliability guide](docs/RELIABILITY_IMPROVEMENTS_EN.md).

Version **0.2.1** fixes Windows PowerShell installation quoting, saves installation logs, checks actual Agent/CLI imports and provides an English console and quick start. [Installation repair](docs/WINDOWS_INSTALL_FIX_EN.md).

Version **0.2.2** adds durable, authenticated assistant correspondence with `labos cooperate send/pull`. Reports use the central HTTPS origin and per-PC credentials; they never execute hardware. See [HTTPS cooperation](src/labos/assets/COOPERATION_HTTPS_EN.md).

Version **0.2.3** adds background cooperation workers: explicit tasks trigger report-only Codex runs, results return automatically, and the central worker reviews them once. A configured central loopback model can serve as fallback. See [automatic cooperation](src/labos/assets/AUTOMATIC_COOPERATION_EN.md).

Version **0.2.4** adds two PC profiles: agent-assisted cooperation and a deterministic program connector requiring no local LLM. A separate restricted public HTTPS gateway supports PCs outside Tailscale. Registered `.py`/`.md` source excerpts help central review existing production drivers without importing them. See [PC profiles](docs/PC_PROFILES_EN.md), [program connector](src/labos/assets/PROGRAM_CONNECTOR_EN.md) and [public gateway](docs/PUBLIC_HTTPS_GATEWAY_EN.md).

Version **0.2.5** adds a separate, locally commissioned cryostat physical pilot: finite 730 nm photoresponse and dark second-harmonic acquisition with fixed reviewed instrument commands, per-transaction deadlines, independent cleanup, durable raw artifacts and replay inhibition. It does not run the complete legacy measurement application. See the [physical pilot guide](docs/PHYSICAL_PILOT_EN.md).

Version **0.2.7** adds an isolated dark a-axis voltage short test: XX1f/2f at4mV RMS and8Hz, with no PM/chopper/XY/AUX sessions, no laser enable, and independently verified cleanup. See the [dark a-axis guide](docs/DARK_A_SHORT_TEST_EN.md). This voltage workflow does not establish calibrated current, an IV curve or nonlinear Hall attribution.

Version **0.2.8** adds an explicitly commissioned laser OFF/ON readback scope using CLD/PM/XX/XY/gate without opening chopper serial. All laser/power/electrical guards remain, with a power ceiling in the dark baseline too. Modulation/BVPE is unverified; the old optical scope retains mandatory chopper checks. Failed-run summaries now follow actual protection status. See the [readback guide](docs/OPTICAL_READBACK_EN.md).

Version **0.2.9rc1** is a maintenance **candidate**, tag **v0.2.9-rc.1**,
pending onsite commissioning and hardware checks. It adds durable physical
claim authority, bounded evidence/model processing, transactional update
recovery and offline/native validation. Stable **v0.2.8** remains the older
release. See the [candidate release notes](docs/RELEASE_0.2.9rc1_EN.md),
[integrated validation](docs/validation/2026-11-01-0.2.9rc1-integrated.md) and
[staged update instructions](docs/GITHUB_DELIVERY_EN.md). Installing the
candidate never enables measurement.

The original execution Agent still supports simulated devices only. The optional physical pilot requires exact local bindings, current output-preserving preflight and a locally enabled profile. It is not evidence of completed hardware acceptance or BVPE/nonlinear Hall attribution.

Version **0.2.6** adds an explicit two-SR830 cryostat profile for a locally excluded
SR865A AUX. It never opens the excluded instrument and records its absence in
preflight/raw data. Existing profiles still require AUX unless explicitly changed;
an instrument timeout does not silently change the measurement configuration.

## Get code and PC updates from GitHub

Use the public [Yue-fy/labos repository](https://github.com/Yue-fy/labos) and its
[versioned releases](https://github.com/Yue-fy/labos/releases). See
[GitHub delivery and PC updates](docs/GITHUB_DELIVERY_EN.md) for anonymous reads,
clone/pull, verified package download and commissioning. Live credentials and
device journals are not stored in GitHub. Pulling source does not enable outputs
or modify a running installation.

## Install and connect a Windows PC

For the older stable release, download `LabOS-Agent-Windows-x64-0.2.8.zip`, extract the entire archive, and double-click **Install.cmd**. For candidate `0.2.9rc1`, use the exact candidate ZIP and coordinated staged update instructions above; keep physical workers stopped until separate onsite commissioning. The portable package includes Python. See [QUICKSTART_EN.md](src/labos/assets/QUICKSTART_EN.md). Existing cryostat installations should use the smaller physical-update overlay and its dedicated guide.

The generic package has no `config.yaml` or live credentials. First obtain the PC-specific configuration from the central server, run **Doctor.ps1**, and then double-click **Start-Agent.cmd**. Doctor checks connectivity and authentication; it does not access instruments. SSH is not a runtime dependency.

For later physical cutover, follow the [onsite checklist](docs/ONSITE_COMMISSIONING_EN.md),
[physical authority](docs/PHYSICAL_AUTHORITY_EN.md) and
[update recovery](docs/PORTABLE_UPDATE_RECOVERY_EN.md). Preserve working vendor
environments and journals. Wiring inspection and separate commissioning precede
any separately authorized new finite task; this maintenance authorizes none.

## Collaborate with a PC's language-model assistant

The optional local LLM assistant can inspect its PC, understand working instrument code and prepare integration evidence. The persistent PC execution Agent remains the runtime executor. Read the [English agent cooperation kit](src/labos/assets/README_AGENT_KIT_EN.md), with [PC-side instructions](src/labos/assets/PC_AGENT_GUIDE_EN.md), [central-side instructions](src/labos/assets/SERVER_AGENT_GUIDE_EN.md), [handoff conventions](src/labos/assets/AGENT_HANDOFF_EN.md), blank JSON reports and a cavity reference card.

Refreshed delivery bundles include `AGENTS.md` and the guides at their root. With provisioned correspondence tools, assistants can send and retrieve sanitized reports over HTTPS. Operator file relay remains a fallback. Report transport does not automatically wake a chat session or invoke an LLM.

For unattended report processing, use the verified installed software and start the optional [background worker](src/labos/assets/AUTOMATIC_COOPERATION_EN.md). One-time PC startup configuration is required; subsequent explicit tasks and replies need no operator relay. It does not resume the IDE's private conversation or operate instruments.

## Development and local acceptance

```bash
uv venv .venv
uv pip install --python .venv/bin/python -e '.[central,ai,dev]'
.venv/bin/python -m pytest -q
.venv/bin/python -m labos demo --directory runtime/demo-01
# Full 399-point simulation; use a fresh output directory.
.venv/bin/python -m labos demo --directory runtime/full-demo-01 --full
```

## Provisioning and deployment

Read the [PC profiles](docs/PC_PROFILES_EN.md),
[English network guide](src/labos/assets/NETWORK_EN.md) and
[onsite commissioning checklist](docs/ONSITE_COMMISSIONING_EN.md).
Archived Chinese guides and bilingual evidence remain in the repository.

For a simulation deployment on a trusted LAN/VPN, replace the example address with the central server's actual reachable address:

```bash
.venv/bin/python -m labos init --directory deployments/lab-01 \
  --server-url http://192.168.1.10:8000 --allow-http --host 0.0.0.0
.venv/bin/python -m labos bundle --config deployments/lab-01/pc-a/config.yaml \
  --windows-runtime dist/delivery/windows-x64-runtime.zip --output deployments/lab-01/pc-a.zip
.venv/bin/python -m labos bundle --config deployments/lab-01/pc-b/config.yaml \
  --windows-runtime dist/delivery/windows-x64-runtime.zip --output deployments/lab-01/pc-b.zip
.venv/bin/python -m labos central --config deployments/lab-01/central/config.yaml
```

Copy each PC its own ZIP. Keep `central/config.yaml` and `operator.token` on the central server. Open the central URL in a browser and enter the operator token. Review parameters, run preflight, and click **Start simulated run**.

PCs initiate HTTP(S) requests to the central server. Across VLANs or NAT, use an allowed route, a managed VPN or a reachable HTTPS central endpoint. Windows scheduled startup is available after manual validation.

## Build delivery packages

```bash
.venv/bin/python scripts/build_windows_runtime.py
.venv/bin/python scripts/build_delivery.py --output dist/candidate-0.2.9rc1-new-001 \
  --windows-runtime dist/delivery/windows-x64-runtime.zip
```

To validate a complete portable ZIP on Windows without starting an Agent or accessing instruments:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\verify_windows_delivery.ps1 -Archive C:\LabOS\LabOS-Agent-Windows-x64-0.2.9rc1.zip
```

## System presentations

- [English technical overview: PowerPoint](docs/presentations/LabOS_NLH_BVPE/English/LabOS_Technical_Overview_EN.pptx) · [PDF](docs/presentations/LabOS_NLH_BVPE/English/LabOS_Technical_Overview_EN.pdf) · [Figures and bundle](docs/presentations/LabOS_NLH_BVPE/English/README.md).
- [System architecture diagram](docs/presentations/LabOS_NLH_BVPE/System_Architecture/README.md): central server, knowledge/memory, scientific agents, skills, MCP, cloud/local model routing and a generic PC fleet.
- [Bilingual architecture presentation notes](docs/presentations/LabOS_NLH_BVPE/System_Architecture/LabOS_Architecture_Presentation_ZH_EN.md).
- [Transport closed-loop diagram and bilingual notes](docs/presentations/LabOS_NLH_BVPE/Transport_Closed_Loop/README.md): communication, calibration, quality feedback, stage updates and planned theory coupling.

The diagrams describe implemented components together with explicitly identified planned capabilities. They do not establish that transport drivers, autonomous calibration or MCP are enabled. The implemented model fallback is limited to the configured correspondence worker.

## Runtime boundaries

The SQLite coordinator runs as a single central process; do not use multiple workers or reload. Interrupted physical actions require reconciliation rather than blind retries. The local software watchdog does not replace hardware interlocks. This release has no general YAML executor, arbitrary Python/SCPI execution interface, automatic production-driver generation or hardware timing guarantee.

Optional AI drafts require `openai_model` in the central configuration and `OPENAI_API_KEY` on the central server. Drafts still require deterministic preflight and explicit Start. Tests and simulated experiments do not require an API key.
