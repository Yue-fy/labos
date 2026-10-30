# QUANTA-inspired evidence and qualification design

Source: [Autonomous Quantum Measurement with Agentic AI](https://arxiv.org/abs/2610.38850), especially Supplementary §§2, 4, 6–7. This is an engineering adaptation to LabOS's simulated optical workflow, not a reproduction of the paper's transport experiments.

## Outcome and boundaries

The operator prepares a scan and its quality policy, optionally consults reviewed local protocols or existing hardware-test code, runs deterministic preflight, and explicitly starts it. PC workers remain persistent outbound HTTP(S) clients with exclusive local instrument ownership. SSH is not required. Only simulated drivers are currently implemented.

Adopt three linked capabilities: qualify every synchronized spectrum before counting it as a successful point; retrieve versioned evidence without letting its contents authorize commands; close runs with structured observations, limitations, verified shutdown evidence and proposed follow-up. Keep raw rejected spectra. A command completing is distinct from a scientifically usable observation.

## Quality and provenance

Plan carries a quality policy with an optional positive maximum count. Instrument enrollment may declare a positive detector ceiling. A detector overload flag or a count reaching either ceiling rejects the spectrum. There is no universal SNR/stationarity threshold: this release does not infer those from one spectrum. Validity checks are operational checks, not proof of precision or physical attribution.

New acquisition artifacts include detector flags and immutable plan/setup+instrument-configuration hashes copied from their command. The central server verifies provenance and recomputes qualification from its stored plan, rather than trusting a worker's acceptance claim. Quality results live beside the immutable original bytes, never rewriting raw evidence. Historical artifacts without checks are visibly unassessed, not silently qualified.

A rejected reading stops the current scan, requests source-off and verifies the resulting readback through the existing cleanup path. No automatic retry, replay of UNKNOWN commands or change of an experimental envelope. Follow-up is a new draft which requires preflight and explicit Start. HDF5 `raw` contains qualified spectra only; `audit` retains every synchronized artifact and qualification result, including rejected and legacy unassessed data. Existing SQLite databases remain readable.

## Evidence and decisions

An authenticated operator can add bounded UTF-8 text with title, source URI/path, category (manual, protocol, code, paper, run), tags and reviewed flag. Store SHA-256 and immutable content; a changed document is a new version. Built-in lexical retrieval includes ASCII identifiers and Chinese text, returns bounded excerpts with source IDs/hashes, and defaults to reviewed evidence. Nothing executes imported code or fetches a supplied URL. Importing existing test code is supported as evidence; real adapters still require the model, connection, SDK and device-safe review.

AI planning gets at most five reviewed excerpts as untrusted reference data, returns their source IDs/hashes, and logs retrieval IDs without credentials. Evidence cannot change enrollment, driver allowlists or authorize execution. No API key/model is needed for local retrieval, quality checks or deterministic run review.

A review reports run status separately from data qualification; qualified/rejected/unassessed counts and explicit measurement IDs; plan/config hashes; successful source-off readbacks with timestamps, or unconfirmed closure; supported observations, interpretation limits and next actions. Rejected or unassessed spectra do not support summary signal metrics. Review snapshots are immutable and digest-addressed; rerunning after late data/closure evidence creates another version. Completing an optical scan never claims a physical mechanism, real-hardware validation or proof of sample safety.

## User experience and delivery

Dashboard adds quality threshold preparation, evidence search/import, qualification counts, a structured run-review display, raw-data export even for zero qualified points, and an explicit historical label on offline telemetry. Plot qualified spectra only and clear stale plots. Preserve manual control buttons.

Ship v0.2.0 role ZIPs, source wheel and updated Chinese operating instructions with no embedded credentials. Reuse the existing Windows runtime without adding dependencies. Linux tests/package execution do not constitute Windows or physical-instrument acceptance.
