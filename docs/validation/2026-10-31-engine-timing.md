# Engine Timing and Admission Verification

Implementation: `2aaacc4` (2026-10-31). Independent task review: spec compliant, quality approved. All devices/clocks were simulated. No laboratory service, configuration or physical output was accessed.

## Changes

- Bounded stage timing with callback-only start events, first-fault metadata and optional copied adapter diagnostics.
- Illumination admission checks use the maximum observed accepted dark-baseline read duration, settling and remaining sample intervals. Exact-fit estimates are refused under the existing strict deadline rule.
- Observer/diagnostic exceptions cannot suppress independent cleanup or close. Existing constructor calls and adapters remain compatible.

## Evidence

RED tests demonstrated missing timing/failure fields and actual laser-enable dispatch despite insufficient measured budget. Follow-up RED cases covered expired ready preflight, observer-consumed budget and final protection proof. No existing assertion was weakened.

The final focused engine run passed177 cases, including32 new cases. The full Python suite with available PowerShell checks passed516 cases in36.43s. Supported lint (`ruff check src tests scripts`) and diff whitespace checks passed. One pre-existing Starlette/httpx deprecation warning remained. Historical presentation-generator lint findings were outside this maintenance scope.

## Limits

The estimate is observational, not a guarantee for future reads, emission startup or cleanup duration. Existing per-I/O/deadline checks remain authoritative. Synchronous observation callbacks must return; in-memory events alone are not crash-durable. Hardware acceptance remains an onsite task.
