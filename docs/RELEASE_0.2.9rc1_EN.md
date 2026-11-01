# LabOS 0.2.9rc1 maintenance candidate

Package version: **0.2.9rc1**. Candidate tag: **v0.2.9-rc.1**.
This is a reviewable maintenance candidate pending onsite commissioning and
hardware checks. Stable **v0.2.8** is the older release. This candidate does not
promote stable, merge into main, deploy a service or authorize a measurement.

## Software changes

- Finite-engine evidence now retains stage timing, first failure, partial and
  rejected observations, actual readbacks, and independent protection/close
  outcomes. Startup/configuration consume the budget; observed baseline read
  cost informs refusal before illumination when the remaining work cannot fit.
- Central physical authority starts uncommissioned. Each new, explicitly scoped
  task requires a newly committed exact grant for the selected frozen profile.
  Ambiguous grants and unresolved cleanup preserve a blocking state; there is
  no automatic expiry, reset or unblock API.
- Durable correspondence separates evidence retrieval from backend inference,
  verifies stored raw bytes, bounds review input and delivery envelopes, and
  retains cached replies across retries. Each message permits at most two
  durable backend invocation intents across fallback/retries/restarts. A
  reservation does not prove provider inference occurred.
- Report processing bounds preparation, source lookup, provider input/output
  and owned cancellation cleanup. Worker lifecycle/status, journal rotation,
  SQLite connection closure and Windows startup ownership aid diagnosis.
- Portable overlays retain verified originals and transactional recovery
  evidence, discover and lock declared worker profiles, and preserve local
  configuration/state. Delivery builders validate archive paths and refuse
  output overwrite. New examples carry no inherited station commissioning facts.
- CI adds Ubuntu/Windows Python 3.11/3.14 checks and actual Windows PowerShell
  5.1 embedded-delivery checks, including the real `Install.cmd`, source-byte
  identity and portable shell line endings. Native failures led to a writable
  HDF5 sync handle and explicit encoding/newline/malformed-ZIP test fixtures;
  existing failure-preservation and unsafe-archive checks remain enforced.

## Acceptance evidence

The latest local integrated suite at runtime checkpoint `d37b937` reports
**1048 passed, one inherited Starlette/httpx warning, 208.88 seconds**. Lint
passed. The warning remains visible; dependencies were neither upgraded nor
suppressed for it. The four synthetic commissioning rehearsal scenarios at the
earlier checkpoint `7776aee` produced COMPLETED, FAILED, FAILED and UNKNOWN as
expected; these are software outcomes, not hardware acceptance.

The runtime checkpoint also passed all five native workflow jobs in
[run 41257339465](https://github.com/Yue-fy/labos/actions/runs/41257339465):
Ubuntu Python 3.11/3.14 each 1048 passed with zero skips, Windows Python
3.11/3.14 each 1002 passed with 46 existing platform skips, and actual Windows
PowerShell 5.1 embedded-delivery/source-byte/`Install.cmd` smoke succeeded.

The 1800-second synthetic campaign completed 1680 tasks/reviews, 3360 synthetic
calls/reservations and 5040 messages, with zero repeated `(role, input-message-id)`
calls. Read-only posthoc v2 verified all message chains and one persisted PC plus
one central reservation per task, with byte-identical before/after files and no
waiver. Worker object recreation is not OS crash coverage; no actual inference,
sockets, live service or hardware was exercised. The original v1 verifier's
file-presence check failed and remains preserved; v2's separate evidence and
limitations are recorded in the
[integrated report](https://github.com/Yue-fy/labos/blob/v0.2.9-rc.1/docs/validation/2026-11-01-0.2.9rc1-integrated.md).

Final documentation-source CI, package QA, whole-branch review and publication
remain release acceptance requirements. Their actual disposition and immutable
final commit/run/archive identities belong in external `QA_Report.json`.
Checkpoint acceptance does not establish final release acceptance.

## Candidate assets and identity

The candidate publication is intended to contain:

| Asset | Purpose |
| --- | --- |
| `LabOS-Agent-0.2.9rc1.zip` | Generic Agent source/install kit |
| `LabOS-Agent-Windows-x64-0.2.9rc1.zip` | Generic Windows kit with embedded runtime |
| `LabOS-Central-0.2.9rc1.zip` | Generic central source/install kit |
| `LabOS-Cryostat-Physical-Update-0.2.9rc1.zip` | Overlay for an existing provisioned physical installation |
| `SHA256SUMS` | Combined hashes for all four shipped ZIPs |
| `QA_Report.json` | External final package/source/run/review acceptance evidence |

Publish the exact three generic ZIPs retained by the final successful native
workflow. Build the physical overlay from the identical final reviewed tree
using the existing pinned physical wheels. Preserve the native builder's
three-package checksum file separately; the combined release manifest covers
all four ZIPs. Keep QA JSON external to the payload to avoid a self-hash cycle.
External `QA_Report.json` must identify the tested Windows ZIP by its actual
hash. A local rebuild or matching version string alone does not establish
identity with the native-tested ZIP. Old released files remain untouched.

## Later update and onsite continuation

Use [GitHub delivery and PC updates](GITHUB_DELIVERY_EN.md) for verified download
and staging. Upgrade central and selected PC software in a coordinated later
cutover; an old 0.2.8 central cannot provide this candidate's authority protocol.
Keep physical workers stopped. Preserve configuration, credentials, approval,
history, raw artifacts, vendor environments and prior backups.

Before any later activation, follow the [onsite checklist](ONSITE_COMMISSIONING_EN.md),
[authority guide](PHYSICAL_AUTHORITY_EN.md) and
[recovery guide](PORTABLE_UPDATE_RECOVERY_EN.md). Retire legacy physical workers
and all old pilot task IDs, reconcile unknown states, inspect current wiring,
freeze the enabled profile and referenced configuration, complete scope-specific
preflight, then perform explicit operator commissioning. Installing the
candidate never enables measurement or queues a physical task.

## Limits and planned work

Native session construction may block beyond a cooperative cancellation request;
software timing is not a hard real-time or hardware protection guarantee.
Local stage/status evidence is not a deployed continuous central telemetry
service. Generic instrument drivers remain simulated; fixed commissioned pilot
adapters do not support every inventoried device.

SR830 **4 mV RMS remains excitation**, not OFF or calibrated sample current.
No calibration, I-V curve, BVPE or nonlinear Hall attribution is established.
The strict chopper byte/communication fault is not repaired; `optical_readback`
excludes chopper serial and proves no modulation/reference locking. Preserve all
existing numeric limits, strict diagnostics, approval, ownership and protection.

Theory/residual coupling, autonomous calibration, broad learning memory/RAG,
arbitrary MCP/skill execution and coordinated cross-PC physical barriers remain
**Planned**. Read the [reliability guide](RELIABILITY_IMPROVEMENTS_EN.md) for
implemented boundaries and their limits.
