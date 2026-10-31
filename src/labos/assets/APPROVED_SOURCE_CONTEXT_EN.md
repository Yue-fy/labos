# Approved production source context

Version 0.2.4 can collect bounded `.py` and `.md` source excerpts from directories
registered by the local operator. It reads text and parses Python ASTs. It never
imports production modules, opens instruments or grants the report model shell
tools. Register approved source trees only; source text is disclosed to the
central analyst. Do not register home directories, credentials or configuration
trees. Filtering known provisioned credentials is not general secret detection.

For the cryostat PC, merge these entries into the existing `cooperation.yaml`,
preserving all other settings, especially the native Codex command and state:

```yaml
source_roots:
  production_src: 'C:/Users/LK_Setup/Yuanrong Li/Integration-photonics/src'
  production_docs: 'C:/Users/LK_Setup/Yuanrong Li/Integration-photonics/docs'
```

For a program-only PC, register its own approved paths in
`program-connector.yaml`. Do not assume the cryostat paths exist on other PCs.

Tasks can include `context.source_requests`, a list of at most six entries:

```json
{"root":"production_src","path":"attodry_control/pm100d.py","kind":"outline"}
```

Kinds are `outline` (Python imports/signatures/line ranges), `read` (at most 200
lines, optional `start_line`/`end_line`) and `index` (up to 250 `.py`/`.md` names).
Paths must be relative and remain inside a registered root. Directory symlinks
are not followed during indexing. Open file handles are checked for confinement
before reading, including a path change between resolution and opening. The
handle check supports Windows and Linux and fails closed on other platforms.
Evidence includes file SHA-256, requested
path, line ranges when applicable and a truncation flag. Limits: 1 MiB input per
file, 4096 content bytes per excerpt, 12 KiB total evidence. A returned excerpt
is not evidence that the whole file or driver was reviewed.

To send the first evidence for central automatic analysis, from the installed
LabOS directory in PowerShell:

```powershell
. .\Resolve-Python.ps1
$Python = Get-LabOSPython $PWD.Path
$env:PYTHONPATH = Join-Path $PWD.Path 'src'
& $Python -B -m labos.source_context --config cooperation.yaml --requests PM100D_SOURCE_REQUESTS.json --output handoff/pm100d-source-task.json --as-task
if ($LASTEXITCODE -ne 0) { throw 'Source collection failed; inspect roots and requested paths.' }
& $Python -B -m labos cooperate send --role pc --config config.yaml --kind note --input handoff/pm100d-source-task.json --output handoff/pm100d-source-receipt.json
```

For a program-only configuration, add `--profile program` to the collector and
use `--config program-connector.yaml`. Later central requests can use the
`source_snapshot` built-in. Source collection is deterministic in both profiles.
The server, not this profile, performs interpretation.

If the paths in the sample manifest differ from the actual checkout, inspect
the approved directory names and correct only relative paths. Do not run a
production import to discover APIs. Review PM100D open/read/status/close,
initialization writes, station/session ownership and hardware lease helpers
before proposing an acquisition wrapper.
