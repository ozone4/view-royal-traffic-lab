# Validation and limitations

The initial synthetic implementation was exercised with genuine SUMO 1.28.0 and independently reviewed before publication. The public source preserves that simulation, accounting and viewer implementation.

## Pre-publication evidence

- 137 tests passed with warnings treated as errors, including live-engine, cleanup, failed-provenance and racing-export regressions.
- A full study completed 52 simulations: five seeds, three demand levels and three variants, plus one-seed time-step/horizon sensitivity checks and one repeat.
- Raw demand, ledgers and XML outputs reconciled 34,320 requested records, 22,664 actual insertions and 16,888 completed trips. Completed/active/uninserted/removed partitions and per-approach totals were retained.
- Repeated baseline demand bytes, metrics and the vehicle ledger matched exactly.
- Desktop Chromium and mobile-sized Chromium/WebKit checks passed without page errors, external requests or horizontal overflow.
- Specification and final independent code-quality reviews passed after identified failure-path and output-integrity defects were corrected.

These are scoped software checks. They are not physical-device tests, calibrated predictions, numerical-convergence evidence or a traffic-safety assessment. Local raw runs, private planning notes and copied research documents are intentionally not included in the public repository.

## What the study showed

At base demand, 660 requests and a 900-second observation horizon, five-seed averages were:

| Variant | Completed | Active | Not inserted |
|---|---:|---:|---:|
| Baseline | 345.4 | 122.2 | 192.4 |
| Alternative timing | 345.0 | 122.4 | 192.6 |
| Restricted eastbound exit | 234.6 | 143.6 | 281.8 |

The alternative timing did not establish an overall improvement. The restricted exit reduced completed trips. Completed-only averages exclude unfinished demand, and seed ranges are descriptive rather than confidence intervals.

Sensitivity was material. At seed 11, baseline completion changed from 346 at the default step to 371 at half-step; with the original step and doubled observation horizon, it was 657. Cross-step/horizon results are sensitivity checks, not matched proposal comparisons.

## Known macOS startup limitation

During a fresh archived-checkout check, the first direct demo invocation hit the native `netconvert` startup timeout (30 seconds). Following the full README setup/test sequence in that checkout then passed all 137 tests and a three-scenario demo/audit. The cause of the initial delay remains undiagnosed; later success does not establish a fix. No timeout or simulation behavior was changed to obtain that result.

If a native-tool startup times out, retain the failed output directory and terminal error. Do not treat partial files as valid results or reuse that output path. Include your OS, architecture, Python/SUMO versions and redacted diagnostics when reporting it. The offline downloadable replay is unaffected because it does not start native tools.

## Reproduce the checks

Follow the README for the locked environment, tests, demo, serialized-artifact audit and browser checks. For the complete study:

```bash
.venv/bin/traffic-lab study --output runs/study
```

Read `runs/study/study.md`, `study.json` and individual run outputs. Output locations must be new. Preserve complete demand accounting when interpreting results.

GitHub CI is configured to exercise warning-strict tests, a genuine three-scenario demo and artifact auditing on Linux/macOS. Its Linux job also runs browser acceptance checks. The workflow status provides evidence for the public commit; historical local results are not a substitute for that run.
