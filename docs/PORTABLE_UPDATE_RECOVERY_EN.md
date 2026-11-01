# Portable overlay maintenance and recovery

`Apply-Pilot-Update.py` updates a provisioned installation without starting a
worker, changing local physical approval, or replaying a task. Keep the update
folder, the existing interpreter, and every previous backup. A manifest checksum
checks package integrity; it is not independent authorization or a signature.
Use a reviewed update from a trusted source.

## Prepare a stopped installation

1. Stop every report worker, physical pilot and program connector through its
   existing local workflow. Confirm that the processes have exited. Stop any
   other process using the source or dependencies being replaced.
2. Freeze worker profiles, connection configuration and worker state locations
   throughout maintenance. Do not launch new workers or edit files concurrently.
   The updater holds the same advisory `instance.lock` protocol as workers, plus
   a per-installation updater lock. These locks do not prevent a person from
   creating a new profile and launching another process. There is no worker-import
   barrier or arbitrary-editor compare-and-swap guarantee.
3. Retain credentials, connection files, worker journals and historical evidence.
   The updater rejects payloads targeting actual discovered profiles, connection
   files and state directories. It never opens a correspondence/physical database.
4. Use the independently trusted existing Python interpreter and existing PyYAML
   installation. Apply parses configuration before any payload modification.
   Recovery uses only the Python standard library and recorded hashes/locks;
   neither operation imports installed or overlay LabOS modules, executes a
   configured program, or adds overlay source to the import path. The interpreter,
   standard library and parser are prerequisites, not recovery targets. If they
   cannot start, repair or provide a trusted independent interpreter first.
   Apply removes update-tree/current-directory aliases from parser import search,
   verifies the parser's package origin in the interpreter's base site-packages
   (or the known embedded-runtime site-packages) before execution, and restores
   the caller's search path. An arbitrary external yaml.py/package is refused.
   Payloads replacing PyYAML, its metadata/extensions, `.pth` startup hooks,
   `sitecustomize.py` or `usercustomize.py` refuse.

From the extracted update directory, using that interpreter:

```powershell
& 'C:\LabOS existing\python\python.exe' -I .\Apply-Pilot-Update.py --target 'C:\LabOS existing'
```

Substitute the installation's actual independently trusted interpreter. Always
launch updater/recovery commands with `-I` to exclude ambient PYTHONPATH and
user-site input. Isolation cannot repair a compromised interpreter or standard
library. The updater does not discover, install or repair an interpreter.

## Profile discovery and declarations

Discovery reads root-level `.yaml`, `.yml` and `.json` candidates as data. The
known stems `cooperation`, `pilot-worker`, `dark-a-worker`,
`optical-readback-worker` and `program-connector` identify their shipped worker
kinds. Custom maps with nonempty `agent_id` and `connection_config` and an explicit
`state_dir` are recognized even without `backend`. Omitted state directories need
an unambiguous kind: `backend: pilot` or pilot-specific keys; `programs` for a
program connector; `backend: codex/local` or report-specific keys; a known name;
or an explicit kind declaration. Conflicting kinds and ambiguous possible worker
maps refuse. Known/explicit profiles must parse and have valid identity/path
fields. Invalid syntax in any root candidate refuses rather than hiding a worker.
Unrelated parseable records, including ordinary Agent connection maps, are never
executed and are retained in the configuration inventory.

Defaults, relative to the profile's own parent directory, are:

| Kind | Default state directory |
| --- | --- |
| `pilot` | `data/physical-pilot` |
| `program` | `data/program-connector` |
| `report` | `data/cooperation` |

Both relative `state_dir` and `connection_config` use the profile's parent, even
for profiles outside the installation. Declare nested/external profiles and
ambiguous omitted-state profiles with repeated `--profile` options:

```powershell
& 'C:\LabOS existing\python\python.exe' -I .\Apply-Pilot-Update.py --target 'C:\LabOS existing' --profile 'program=C:\Station profiles\program.yaml' --profile 'C:\Station profiles\pilot.json'
```

For Python callers, `apply_update(update, target, profiles=None)` retains the
existing two-argument API; `profiles` accepts paths, `kind=path` strings, or
`(kind, path)` pairs. Profile paths supplied as relative declarations are relative
to the installation. Explicit profile aliases and state aliases resolve to
canonical paths; worker locks are canonical, deduplicated and sorted.
Root candidate symlinks and payload/control-path symlinks refuse.

Files ending `.example.yaml`, `.example.yml` or `.example.json` are templates,
not live profiles by convention; explicitly declare any template actually used
as a worker. The only YAML payload permitted is the disabled
`pilot-worker.example.yaml` with absent/null approval or `approval.enabled: false`. Shipped nonconfiguration
JSON records `CRYOSTAT_PILOT_PLAN.json`, `CRYOSTAT_PILOT_SOURCE_REQUESTS.json`,
`DARK_A_VOLTAGE_PLAN.json`, `OPTICAL_READBACK_PLAN.json`,
`PC_INTAKE_TEMPLATE.json`, `PM100D_SOURCE_REQUESTS.json` and
`SERVER_REPLY_TEMPLATE.json` are excluded from configuration candidates only
while they remain valid JSON without configuration identity keys. These records
may be payload-owned. Other root JSON is protected configuration inventory,
including unrelated JSON records. Do not use documentation filenames as live
configuration; identity keys turn them into candidates and prevent replacement.

## Transaction evidence

The installation updater lock is acquired before inspecting earlier transactions.
Every nonterminal, missing or corrupt new-format journal blocks a new apply.
Strictly validated completed legacy archives are the exception described below.
Backups are versioned under `data/pilot-update-backups/TRANSACTION_ID/`; previous backups are
never overwritten. `transaction.json` binds the canonical installation, package
version, transaction ID, complete root candidate paths/hashes, explicit profiles,
canonical profile/connection hashes and state locks, and each payload path's old
hash (or absence) and new hash. Its integrity checksum detects changed journal
content; it is not authentication against someone deliberately rewriting it.

The updater publishes this inventory as `preparing` before writing backups.
Every required original is flushed, read back and checked before `prepared`.
Only then may `applying` replace payload files through same-directory atomic
writes. The single `committed` boundary follows verification of every final
payload hash. `preparing`, `prepared`, `applying` and `rolling_back` all remain
unresolved; only `committed` and `recovered` are terminal. The original files are
stored at the same relative paths beneath the transaction directory.

An ordinary failure after preparation attempts rollback: durably publish
`rolling_back`, restore exact original bytes, and remove only introduced payload
files with expected new hashes. It does not delete unrelated files or directories.
Successful rollback publishes `recovered`; backups remain. A failure to restore
or publish the rollback marker leaves identifiable evidence and reports the exact
transaction ID. A process interruption does not run automatic recovery. A crash
after the last replacement but before commit still requires explicit recovery.
A commit marker already published before a subsequent flush error is treated as
the commit boundary and is not silently rolled back.

## Retained backups from the previous updater

Successful older updates retained directories named
`YYYYMMDDTHHMMSSZ-<8 lowercase hex characters>`. The old updater copied
`applied-manifest.json` only after finishing every payload replacement. The new
updater recognizes this completed archival history without moving, rewriting or
deleting any retained bytes. Recognition requires a valid UTC timestamp/name,
the old builder's exact `version`/nonempty `files` manifest structure, SHA-256
digest syntax, safe portable old payload paths, and a regular-file/directory
inventory confined to the recorded originals and completion marker. Duplicate
keys, Windows path aliases, extra files/directories and symlinks refuse.

These manifest digests describe the **payload installed by that historical
update**, not its retained originals. Originals can be a subset of the manifest: newly introduced files had
no original to save. The old record contains neither original-file hashes nor
profile/configuration snapshots. Recognition trusts intact local completion
evidence; it cannot prove missing originals, authenticate a deliberately forged
record, or grant modern rollback guarantees. Current destination files need not
match that historical payload after subsequent legitimate updates.

`--recover` explicitly refuses legacy backup IDs: legacy rollback is unsupported.
It never invents missing hashes/profiles or restores legacy bytes. Missing,
malformed or ambiguous legacy completion evidence still blocks a new apply;
keep the entire archive and reconcile it through deliberate local maintenance
review. Ordinary recognized completed history requires no deletion or movement.
New-format transactions use a 32-hex suffix and always require their own valid
`transaction.json`; a legacy marker cannot replace that journal.

## Explicit recovery

Keep every worker stopped and all configuration frozen. Inspect the reported
transaction ID and retained evidence. Then run the independent updater from the
retained update folder:

```powershell
& 'C:\LabOS existing\python\python.exe' -I .\Apply-Pilot-Update.py --target 'C:\LabOS existing' --recover TRANSACTION_ID
```

Python callers can use `recover_update(target, transaction_id)`. Recovery uses
recorded profiles; do not pass `--profile`. It acquires the installation lock and
the recorded canonical worker locks. The complete root candidate inventory and
all recorded profile/connection hashes must still match: changed, missing or
newly added candidates refuse before payload restoration. This prevents a newly
introduced worker from escaping the recorded lock set. Restore the maintenance
configuration under local review before retrying; never delete evidence merely
to make an apply proceed.

Before any payload restoration, recovery checks **all** required backups and
all current destinations. Previously existing files must have their old or new
hash; introduced files must be absent or have their new hash. Missing originals,
unknown user edits, corrupt/missing backups, symlinks and path conflicts refuse
without partially restoring earlier entries. Preserve user edits separately and
reconcile them deliberately; recovery never overwrites unknown bytes. Each
file is checked again immediately before its restore/removal. Interrupted
recovery can be repeated with the same transaction ID and recognizes already
restored entries. Explicit recovery also permits reverting a committed update
while its recorded hashes/configuration still match.

An interruption during inventory/backup preparation can leave incomplete or
missing required evidence, even though no payload was changed. Recovery refuses
that transaction; it cannot manufacture missing backups or infer authorization
to clear it. Manual maintenance reconciliation is required before another apply.
Keep the complete transaction directory and review the original installation
and package independently. No automatic evidence deletion or journal repair is
provided.

## Limits and checks after maintenance

Files are flushed with `fsync`; replacement and directory flushing are used where
supported. These measures and the fault-injection tests support process-interruption
recovery with intact recorded evidence. They do not promise portable filesystem
or power-loss durability, Windows directory-fsync semantics, storage-controller
flush behavior, or exclusion against independent editors. Recovery restores file
bytes, not original ACLs, timestamps, already imported process modules, or an
interpreter that cannot run. Keep a separate installation backup when those
properties matter.

Inspect the terminal journal and locally review the resulting package before
using the existing startup procedures. Update/recovery never enables approval,
starts a process, clears physical no-replay records, reconciles a hardware outcome,
or constitutes hardware acceptance.
