# LabOS deployable MVP design

User-authorized workspace: `/home/fangy4/work/projects/LabOS`. Implement the previously discussed central planning/local execution architecture and PC delivery packages. Original reference: `GoogleDrive/LabOS/md/LabOS_MVP_Implementation_Spec.md`.

## Scope and acceptance
Python 3.11+, Windows/Linux agents; one central service and two outbound polling agents. Three simulated instruments complete an inclusive wavelength × angle scan. Provide preparation profiles, explicit Start, authenticated commands, finite limits, local watchdog, durable command journal, local-first JSON spectra, checked central synchronization and HDF5 export. Provide browser dashboard, CLI, packaged source/wheel, installation/start scripts and network troubleshooting. Optional OpenAI draft planning must never start experiments. No cloud account or paid API calls are required to test or run the simulated demo.

Real hardware is disabled in this release until model/SDK details, reviewed adapter, limits and physical setup validation are supplied. No software interlock claims physical fail-safe behavior on PC power loss. AI driver generation, arbitrary Python/SCPI, general YAML interpreter and fast synchronization are out of scope.

## Runtime contracts
Agents initiate HTTPS or explicit trusted-LAN/VPN HTTP connections to central. Each has a unique token and configured instrument identities; the operator token is separate. Central accepts no instrument ownership changes from an agent. Agent session IDs fence old process traffic; duplicate live sessions fail registration. A single-process file lock prevents multiple coordinators sharing a data directory.

Central SQLite persists runs, commands, measurements and audit events. Agent SQLite persists command payload, STARTED/COMPLETED/FAILED/UNKNOWN and results. A dispatched command is not requeued automatically. Timeout yields UNKNOWN; started commands after an agent restart become UNKNOWN. Duplicate IDs with changed payloads fail. Device resources are reserved atomically. Central restart marks active runs INTERRUPTED and queued commands cancelled; operator reconciliation executes safe shutdown before releasing resources. No automatic replay of interrupted physical steps.

SetupProfile binds role→instrument and records physical context and calibration notes. Plan defines sample, inclusive wavelength/angle grids, finite exposure/power and sample limits. Preflight checks fresh identity, simulated/real mode, capabilities and local limits; saves a timestamped snapshot. Pauses occur between complete measurement points; stop cancels remaining normal commands and requests local safe state. Unsafe/unknown cleanup retains resource locks until explicit successful reconciliation.

Each point has a unique run/point identity and explicit commanded values and observed readbacks. Capture writes an atomic local JSON file before command success. The agent keeps it and retries upload, including after restart. Central validates ownership, hash, size, finite arrays and command provenance before committing a measurement. Data is not deleted automatically. One HDF5 file is atomically assembled from confirmed central measurements; partial runs can also be exported.

## Deliveries
Build reproducible role packages without embedded credentials. Provision generates secrets locally, stores central config with restrictive permissions, and prepares separate per-agent ZIPs containing only that agent credential. Installer accepts wheelhouse for offline installations. No firewall, VPN or external account configuration is mutated automatically. Provide LAN, routed VPN and HTTPS reverse-proxy configurations, authenticated connectivity doctor and a three-process loopback acceptance test.

## Validation
Tests cover invalid units/numbers/ranges, cross-agent authorization, duplicate command/reply handling, stale session rejection, timeout/restart ambiguity, exclusive resources, watchdog safe state, upload idempotency/integrity and complete/partial HDF5. Actual subprocess demo must run central and two agents over TCP and verify points and export. Extracted delivery packages must also run the demo. Windows scripts are inspected and syntax-checked if PowerShell exists; physical PCs and real drivers require deployment acceptance outside this environment.
