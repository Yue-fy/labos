# Pure simulation adaptive resonance scan

## Goal and authority

Implement the user's requested runnable QMAT demonstration on top of main
`e80aecf373ce5146895930fb4e4313d7e50641ff`, using the supplied implementation
specification's section 44 as the starting point. This change is authorized to
implement and verify the simulation, without connecting physical instruments.
The meeting date and final demonstration roster are outside this deliverable.

## Behavior

- Explicitly approved simulation only; initial scan defaults to 500–800 nm in
  20 nm steps, one fixed polarization, 1 ms exposure.
- A deterministic, configurable simulated excitation resonance is installed on
  the spectrometer. The policy sees acquired spectra, never the simulator's peak
  setting. The existing simulator remains the default for fixed scans.
- Analyze the integrated, background-subtracted spectral signal versus excitation
  wavelength. Select a unique interior maximum with sufficient contrast.
- Refine around the measured maximum by two previous steps on either side,
  clipped to the previous interval. Snap endpoints inward to the new inclusive
  grid. Default refinement steps are 5 and 1 nm. Analyze the final scan too.
- Reject flat/no-contrast data, boundary maxima, comparable distinct maxima,
  corrupt/nonfinite data, unsupported multidimensional scans and invalid budgets.
  This is a deterministic single-resonance policy, not LLM scientific reasoning.

## Integration and safety

Use one Runtime run and one resource reservation, the existing Agent command
path, local watchdog, cache/upload, SHA-256 checks, SQLite audit and HDF5 export.
Global point indices identify repeated coordinates across rounds. Each round is
prechecked; all ranges stay inside the original approved envelope and no round
may exceed the total budget (at most 5000 points; at most five rounds).

Analysis/validation failure follows existing safe shutdown. Unknown outcomes are
not replayed; incomplete cleanup retains reservations for operator reconciliation.
Pause, stop and process interruption apply to the whole adaptive run. A central
restart interrupts rather than autonomously resumes the experiment.

The API requires `adaptive.simulation_approved: true`. The local demo command is
the user's explicit simulation approval, binds loopback, provisions fresh isolated
simulation configs and runs three OS processes. It cannot accept an external
instrument configuration or hardware mode. Production/real experiment approval
rules and the existing fixed-scan Start operation remain intact.

## Evidence and deliverables

Persist approval, round start/end, observed peak, decision, next plan, point
offsets and policy version as audit events. Export complete adaptive history in
HDF5 without the UI log's 200-event truncation. Provide a CLI demo, an automatic
acceptance script and CI checks. Acceptance must run actual loopback TCP with two
Agents, verify each HDF5 round against measurements, repeat a seeded experiment,
and move the hidden simulated peak to prove data-dependent decisions.

## Implementation choices

An additive adaptive setting on Plan and a small deterministic policy module
reuse the trusted executor. A separate toy executor would bypass existing safety
and storage; an LLM policy would add nondeterminism and an API dependency. Neither
is needed for this simulation demonstration. No new runtime dependency is needed.
