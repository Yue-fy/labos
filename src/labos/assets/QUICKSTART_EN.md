# LabOS Windows Agent — Quick start

The interface, controls, runtime messages and installation tools use English.

First follow your personalized bundle's `START_HERE_EN.md`. A **program-only**
bundle uses `Install-Program-Connector.cmd` and requires no model or Tailscale.
An **agent-assisted** bundle uses `Install-Cooperation.ps1` after runtime setup
and requires authenticated Codex plus its configured network. The generic
execution-Agent instructions below apply only when that component is intended.

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

Doctor checks the central connection and PC authentication; it does not access instruments. After a successful check, double-click **Start-Agent.cmd**. The Agent initiates HTTP(S) requests to the central server; SSH and inbound PC ports are not required.

## Current device support

This release enables simulated instruments only. Real SMUs, lock-ins, choppers and vendor SDKs require model-specific integration and validation. Do not execute an entire reference Notebook as an installation or connection check.

## If this PC has a language-model assistant

Ask it to read [AGENTS.md](AGENTS.md) and [README_AGENT_KIT_EN.md](README_AGENT_KIT_EN.md). The cooperation kit explains local inspection, reference-code review and coordination. A provisioned 0.2.2 package supports [HTTPS report send/receive](COOPERATION_HTTPS_EN.md); this does not require installing an LLM and does not automatically invoke one.

## Repair an existing 0.2.0 installation

If Install reports `SyntaxError: '(' was never closed`, apply the small **LabOS-Windows-Install-Fix-0.2.1.zip** to the existing Agent folder. Replace its four root files: `Install.cmd`, `Install.ps1`, `Check-Runtime.py` and `Doctor.ps1`. Then run **Install.cmd** again. The patch does not replace configuration, data or application code.
