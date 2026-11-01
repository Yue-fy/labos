# Reliability behavior and its limits

This candidate adds inspectable software safeguards. Offline checks are not
final campaign/CI acceptance or proof of instrument commissioning. Follow
[ONSITE_COMMISSIONING_EN.md](ONSITE_COMMISSIONING_EN.md) before later physical
work, [PHYSICAL_AUTHORITY_EN.md](PHYSICAL_AUTHORITY_EN.md) for claim semantics,
and [PORTABLE_UPDATE_RECOVERY_EN.md](PORTABLE_UPDATE_RECOVERY_EN.md) for recovery.

Candidate **0.2.9rc1** (tag **v0.2.9-rc.1**) is separate from the older
stable **v0.2.8** release. See the [candidate release notes](https://github.com/Yue-fy/labos/blob/v0.2.9-rc.1/docs/RELEASE_0.2.9rc1_EN.md),
[integrated validation report](https://github.com/Yue-fy/labos/blob/v0.2.9-rc.1/docs/validation/2026-11-01-0.2.9rc1-integrated.md)
and [staged central/PC update instructions](https://github.com/Yue-fy/labos/blob/v0.2.9-rc.1/docs/GITHUB_DELIVERY_EN.md).

## Separate components and authority

Report cooperation, the deterministic approved-program connector, the generic
instrument Agent and the finite physical pilot are separate processes and
authority boundaries. Report-only Codex can analyze approved context; it cannot
install code, change approval or operate instruments. A report connection pass
is not an instrument test. Generic Agent drivers remain simulated. Fixed
commissioned pilot adapters do not make every inventoried USB device supported.

```mermaid
sequenceDiagram
    participant C as Central authority
    participant W as Selected local worker
    participant E as Finite engine
    participant D as Commissioned adapter
    C->>W: New post-cutoff task and explicit scope
    W->>W: Freeze validated profile; commit intent and nonce
    W->>C: Transactional claim for same profile hash
    C-->>W: Newly committed exact grant (at most one attempt)
    W->>E: Bounded validated plan and local approval
    E->>D: Finite acquisition
    E->>D: Independent protection and close
    E-->>W: Partial/full raw evidence and actual cleanup status
    W->>W: Persist raw artifact; UNKNOWN latches block
    W->>C: Raw artifact and bounded result
    C->>C: Index matching evidence; review
```

Authority starts uncommissioned. Legacy retirement, physical reconciliation,
same frozen enabled profile hash/scope, new cutoff and later operator onsite
commissioning are mandatory. All old pilot task IDs retire, even without an
artifact; old scope-less/failed tasks never replay. Readiness is a recent
observation and never bypasses the claim. Lost/ambiguous receipts consume the
attempt conservatively. There is no reset, automatic expiry or unblock API.
Only matching independently verified terminal evidence can release a gate.

## Timing, protection and delivery

The engine records bounded stage timing, first failure metadata, partial samples,
budget decisions and independent cleanup/close evidence. Startup and configure
costs consume the budget. Illumination admission estimates the remaining work
from accepted baseline read cost; it refuses before ON when that estimate cannot
fit. Observed cost is not a bound on future reads. Native device-manager/session
construction can still block, and timing identifies its duration only after
return. Cooperative cancellation is not hard real-time interruption.

Local progress events, rotated journals and status snapshots aid diagnosis.
Final raw artifacts/results return centrally; this is not a deployed continuous
central telemetry stream or live dashboard. UNKNOWN cleanup blocks later tasks
even after restart. Laser OFF, zero current setpoint, measured 4 mV RMS minimum
excitation and session close are separate evidence. Minimum excitation is not
OFF or calibrated sample current. Preserve strict decoder/diagnostic acknowledgments,
all existing numeric limits, ownership/approval checks and independent cleanup.

Durable correspondence and execution journals retain cached replies and
uncertain intents instead of blindly repeating work. Raw evidence capacity
refusals and pending delivery do not authorize acquisition retries. Registered
read-only source context returns bounded text/AST evidence without production
imports. Transactional updates lock declared workers, retain verified originals
and require valid recorded evidence for recovery; unknown edits are preserved.

The canonical source rehearsal is `scripts/rehearse_commissioning.py`; the
physical overlay installs identical bytes as root `rehearse_commissioning.py`
and includes its hash plus all four guides in the payload manifest. It produces
synthetic, source-versioned JSON in a new directory only. Exact commands and
the four scenario expectations are in the onsite checklist. The UNKNOWN worker
integration uses temporary state, TestClient/MockTransport and the real engine.
No physical measurement, native driver or provider invocation is acceptance
evidence from that rehearsal.

## Planned theory and coordination

**Planned:** versioned theory predictions/residuals could help propose a next
bounded plan after wiring and physical calibration are established. Broad
self-learning memory/RAG, arbitrary MCP/skill execution, adaptive autonomous
calibration and coordinated cross-PC physical barriers remain future work.
Deterministic local validation, claim authority and protection must remain
outside model discretion. Optical OFF/ON alone does not identify BVPE; dark
harmonic voltage alone does not establish nonlinear Hall transport or an I-V
curve. The readback scope excludes the chopper with failed strict serial
diagnostics and establishes no modulation/reference locking or fault repair.
