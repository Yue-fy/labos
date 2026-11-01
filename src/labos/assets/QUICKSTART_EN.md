# LabOS Windows Agent — Quick start

The interface, controls, runtime messages and installation tools use English.

Choose the provisioned role before starting a component. Generic release ZIPs
contain no live credentials; obtain PC-specific configuration through the
operator. A **program-only** profile uses `Install-Program-Connector.cmd` without
a local model. An **agent-assisted report** profile uses `Install-Cooperation.ps1`
after runtime setup and requires authenticated Codex and its configured network.
`Start-Agent.cmd` starts the separate generic simulated execution Agent only.
See [NETWORK_EN.md](NETWORK_EN.md) for connectivity checks. A station-specific
handoff may supplement these directions; no historical private bundle is required.

## Install on the laboratory PC

1. Extract the entire ZIP to a folder such as `C:\LabOS\cavity-pc`.
2. Double-click **Install.cmd**. Keep the `python`, `src`, scripts and `ROLE` file together.
3. The portable package checks its bundled runtime without downloading dependencies or accessing instruments. A successful check prints `LabOS agent runtime OK`, followed by exit code `0`.
4. Installation details are saved in **install.log** in the same folder.

You do not need to install another Python, an SSH server or a local language model. Preserve the laboratory PC's existing instrument environment; vendor drivers may require a separate compatible Python or SDK.

## Connect to the central server

The generic ZIP does **not** contain `config.yaml` or live credentials. Obtain a personalized configuration or PC bundle from the central server first. It specifies the central URL, PC identity, credential and registered devices. Do not use another PC's configuration or copy the central operator credential to this PC.

Once configuration is available, open PowerShell in the extracted folder and run:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\Doctor.ps1
```

Doctor checks the central connection and PC authentication; it does not access instruments. For a provisioned generic execution Agent, double-click **Start-Agent.cmd** after this check. Report/program profiles use their own startup workflow. The Agent initiates HTTP(S) requests to the central server; SSH and inbound PC ports are not required.

## Current device support

The generic execution Agent supports simulated laser/rotator/spectrometer devices.
A separate opt-in physical pilot supports only fixed reviewed, locally commissioned
finite scopes; see [PHYSICAL_PILOT_EN.md](PHYSICAL_PILOT_EN.md),
[DARK_A_SHORT_TEST_EN.md](DARK_A_SHORT_TEST_EN.md) and
[OPTICAL_READBACK_EN.md](OPTICAL_READBACK_EN.md). Identified devices are not
automatically implemented drivers. The physical overlay includes root
`ONSITE_COMMISSIONING_EN.md`, `PHYSICAL_AUTHORITY_EN.md`,
`PORTABLE_UPDATE_RECOVERY_EN.md` and `RELIABILITY_IMPROVEMENTS_EN.md`; generic
source releases include those guides under `docs/`. Wiring inspection, separate
commissioning and a separately authorized new finite task are still required.
Do not execute a reference Notebook as an installation or connection check.

## If this PC has a language-model assistant

Ask it to read [AGENTS.md](AGENTS.md) and [README_AGENT_KIT_EN.md](README_AGENT_KIT_EN.md). The cooperation kit explains local inspection, reference-code review and coordination. A provisioned installation with the correspondence tools supports [HTTPS report send/receive](COOPERATION_HTTPS_EN.md); this does not require installing an LLM and does not automatically invoke one.

## Repair an existing 0.2.0 installation

If Install reports `SyntaxError: '(' was never closed`, apply the small **LabOS-Windows-Install-Fix-0.2.1.zip** to the existing Agent folder. Replace its four root files: `Install.cmd`, `Install.ps1`, `Check-Runtime.py` and `Doctor.ps1`. Then run **Install.cmd** again. The patch does not replace configuration, data or application code.
