# LabOS 0.2.1 — Windows installation repair

Date: 2026-10-31 (Europe/Helsinki).

The 0.2.0 installer passed Python code containing embedded double quotes through `python -c`. Legacy PowerShell argument handling removed the quotes, truncating the code at `print(Portable` and producing `SyntaxError: '(' was never closed`.

See [Microsoft's native argument parsing documentation](https://learn.microsoft.com/en-us/powershell/module/microsoft.powershell.core/about/about_parsing#passing-arguments-that-contain-quote-characters) for the distinction between Legacy and Standard argument handling.

The repaired installer executes **Check-Runtime.py** instead. It checks the actual Agent and CLI imports, required dependencies and in-memory SQLite without reading configuration or accessing a server or instruments. It saves **install.log**, preserves the installer's exit code, and explains when PC provisioning is still required.

## Already extracted 0.2.0

1. Copy **LabOS-Windows-Install-Fix-0.2.1.zip** to the Windows laboratory PC.
2. Extract its four scripts into the existing Agent folder, replacing the matching files. They must sit beside `ROLE`, `python` and `src`.
3. Double-click **Install.cmd**.
4. Expect **LabOS agent runtime OK** and exit code **0**.
5. Without `config.yaml`, the provisioning message is expected. Obtain the PC's configuration before running Doctor or Agent.

The small patch changes installation scripts only. Existing application code and its interface remain at their previous version. For the English interface and all updated application files, use the complete **0.2.1** release; upgrade the central server as well as the required PC package.

The patch does not replace configuration, data, vendor drivers or the existing Python runtime. If installation still fails, retain the window and inspect **install.log**.

## Fresh deployment

Use **LabOS-Agent-Windows-x64-0.2.1.zip**, extract the entire archive, and follow **QUICKSTART_EN.md**. The generic package has no live PC credentials. Actual SMU, lock-in and chopper integrations are separate from this installation repair.

## Verification scope

The installer regression tests execute the real PowerShell scripts and Python check under Legacy argument handling, including a path with spaces, parentheses and Chinese characters. On Linux, only the Windows Python executable is substituted with the test host's Python. This is not Windows hardware acceptance.

For native Windows package validation, run the repository's `scripts/verify_windows_delivery.ps1` with the full ZIP path. It verifies installation, the packaged CLI and missing-configuration handling without starting an Agent or accessing instruments.
