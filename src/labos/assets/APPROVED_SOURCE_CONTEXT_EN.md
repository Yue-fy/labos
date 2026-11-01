# Approved production source context

The source-context collector can collect bounded `.py` and `.md` source excerpts from directories
registered by the local operator. It reads text and parses Python ASTs. It never
imports production modules, opens instruments or grants the report model shell
tools. Register approved source trees only; source text is disclosed to the
central analyst. Do not register home directories, credentials or configuration
trees. Filtering known provisioned credentials is not general secret detection.

For an agent-assisted PC, register operator-approved paths in `cooperation.yaml`,
preserving other settings, the native Codex command and journals. These reserved
example paths are placeholders and must be replaced with inspected local roots:

```yaml
source_roots:
  production_src: 'C:/LabOS-approved/example-project/src'
  production_docs: 'C:/LabOS-approved/example-project/docs'
```

For a program-only PC, register its own approved paths in
`program-connector.yaml`. Do not assume these example paths exist.

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

Each index examines at most 10,000 directory entries and retains at most 1,000
directories, including the requested directory, before stopping. Entries are
iterated individually; only the bounded matching names are sorted. The `scan`
metadata records entries, retained directories, opened directories and the limit
that stopped the scan. Reaching a scan or 250-match limit sets `truncated: true`,
even if few supported files were found. A truncated index is not a complete
inventory. The standalone collector applies the same limits.

The main AST traversal visits at most 10,000 nodes, retains at most 250 definitions
and 80 imports, and stops when the excerpt content allowance is reached. Signatures and
imports exceeding 256 subtree nodes, 32 levels of depth or 4096 text characters
are explicitly omitted before rendering. Outline
`scan` metadata reports visited nodes, definitions and the stopping limit; file
hashes still describe the exact original bytes. The collector uses lazy AST
traversal rather than collecting all children before counting them.

During worker preparation, source collection checks the same cancellation and
monotonic deadline guard used for provider dispatch, between filesystem operations
and AST traversal steps. It closes active directory iterators on cancellation.
A blocked OS filesystem operation or Python parsing call cannot be interrupted by
these cooperative checks; this is not a hard real-time completion guarantee.

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
