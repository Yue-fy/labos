# Approved source context implementation plan

User request: let the cryostat assistant reference the existing `Integration-photonics/src` and `Integration-photonics/docs` directories. The automatic report worker is already commissioned, but 0.2.3 only accepts prewritten snapshots.

Implement a small 0.2.4 overlay for the existing LabOS package, without replacing credentials, journals, Python, production files or the `lyr` environment. The local commissioning assistant registers the two operator-specified roots once. Explicit tasks may request bounded text/AST outlines under those roots; host code reads text without importing production modules or giving Codex shell/device tools.

- [x] Add failing tests for allowlisted reading, AST outlines without execution, traversal/symlink/type rejection and bounded UTF-8 evidence.
- [x] Implement `source_context.py`, including a one-time CLI collector that can produce an automatic central-analysis task.
- [x] Add worker integration tests, then implement source-root configuration and source evidence in task/results. Preserve 0.2.3 message compatibility.
- [x] Ship an English guide, sample root registration, first PM100D source request and a small overlay. Stop the old worker before copying code; preserve its journal and identity.
- [x] Run full tests and lint; independently review source/profile boundaries; activate central compatibility. Physical PC collection remains pending until the overlay is applied.

Final verification:215 tests passed, Ruff passed for src/tests/scripts,12 PowerShell scripts parsed. Delivery legacy-argument tests ran on Linux PowerShell, not native Windows. Real public-route runtime smoke and central automatic review were observed; external PC and physical acquisition are not claimed.

Limits: `.py` and `.md` only; registered roots only; no imports, subprocesses or device sessions; at most six requests, 1 MiB per file, 12 KiB total returned source evidence. Include source hashes, line numbers and explicit truncation. The report model receives task data plus approved source text, and the result carries host-collected evidence. A first collector task can be sent immediately by the local assistant after registration, so the operator does not need to relay code snippets.


## Two deployment profiles and public ingress

The operator clarified that the no-LLM PC cannot join Tailscale. Extend the
implementation with a deterministic program connector and a separate public PC
gateway. Keep existing private443 and expose only gateway18081 via public8443.
Each physical PC has a unique identity/credential. No remote arbitrary commands
or hardware entries are enabled by the initial program-only catalog.

- [x] Implement and test fixed local program catalog, bounded JSON parameters,
  no-model built-ins, intent-before-launch journal and uncertain-outcome handling.
- [x] Implement and test exact public route/method and PC-credential boundaries.
- [x] Provision program-pc-01 and central review worker independently of cryostat.
- [x] Activate loopback gateway and public Funnel8443 with operator OS action;
  verify public DNS relay/TLS and scoped API access while preserving private443.
- [x] Complete a deterministic task/result/central-review server smoke over the
  public route; attribute it explicitly as server-only, not remote acceptance.
- [x] Prepare portable private bundles and source overlay; queue a separate task
  for the first real no-LLM PC, excluding the smoke cursor.
- [x] Fix independent review findings: handle-based source confinement and
  decoded-value credential exclusion; add leaf/parent race and escaped-token
  source/API/worker regressions.
- [ ] Observe actual no-Tailscale Windows installation separately.
- [ ] Observe cryostat source overlay and source/history reports separately.

## Physical acceptance steering

The operator now requires LabOS orchestration of a short730nm photoresponse and
dark2f Hall pilot, with prompt laser/excitation shutdown after every segment.
Do not run the old whole measurement application. Source/API/history evidence
is needed for a LabOS-owned executor and typed physical data. No numerical
physical limits or real device enable commands may be fabricated. SR830's
specified SINE minimum is not an excitation OFF mechanism. See
`subComputer/cryostat/LABOS_BVPE_NLH_PILOT_EN.md`.
