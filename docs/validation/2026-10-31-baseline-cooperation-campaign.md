# Isolated Cooperation Baseline Campaign

This is software transport and journal evidence, not a hardware or model-provider acceptance result. The campaign used in-process ASGI and HTTPX MockTransport, temporary SQLite databases, synthetic identities and deterministic report responders. It opened no sockets, instrument sessions or real model backends and accessed no running laboratory service.

## Recorded result

| Item | Observation |
| --- | --- |
| Start, UTC | 2026-10-31 22:02:59 |
| Finish, UTC | 2026-10-31 22:19:24 |
| Total elapsed | 985.16 seconds |
| Task generation window | 900 seconds |
| Simulated stations / worker objects | 4 / 8 |
| Tasks submitted / final reviews stored | 828 / 828 |
| Synthetic responder invocations | 1,656 |
| Duplicate responder invocations | 0 |
| Stored correspondence messages | 2,484 |
| Injected GET timeouts | 2,329 |
| Injected POST receipt losses after storage | 373 |
| Worker object recreation with reopened durable state | 22 |
| Maximum observed task-to-review latency | 180.48 seconds |
| Final invariant result | PASS |

The oracle required one PC response and one central review per submitted task, exactly three stored correspondence records per task, and no duplicate responder invocation after retries or worker recreation. Transport faults continued during this baseline's drain period. The final task completed within the harness's 90-second drain allowance.

## Scope and interpretation

This baseline ran the already loaded code from local audit checkpoint `7d24b83`, before the later authority, gateway, durable invocation budget and resumable-history changes. Concurrent source edits did not replace that process's loaded modules. It is not the final integrated candidate's acceptance run.

The result demonstrates eventual correspondence delivery and cached-response reuse in this synthetic workload. The high maximum latency also shows why retry preparation and historical parent lookup need further work. It does not establish a hard delivery deadline under continuing faults.

Worker recreation is not an operating-system crash, power-loss test or forced termination during inference. The responders performed no inference, so this campaign cannot prove token consumption or cancellation of an already accepted remote request. No TCP, HTTPS certificate, Tailscale, native Windows, device-driver, calibration, output-protection or scientific-effect claim follows from this result. Those boundaries require their own tests and later onsite verification.

The private evidence retains the source hashes, deterministic fault seed, counters, temporary journals and timestamped result. Provisioned laboratory configuration and raw measurement data were not used or published.
