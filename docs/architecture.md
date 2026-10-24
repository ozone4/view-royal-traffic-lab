# Architecture

The application has two separate execution environments:

1. **Python and SUMO** generate simulations and recorded artifacts in a local source checkout.
2. **An offline HTML viewer** reads those artifacts embedded in its own file. It does not start an engine, contact a server or change simulation results.

## Simulation pipeline

`schema.py` validates the deliberately narrow synthetic scenario contract. `demand.py` generates finite, seeded arrival requests once for matched comparisons. `network.py` writes the fictional geometry and supported controls, then calls the pinned `netconvert` executable.

`runner.py` controls the pinned engine through TraCI with bounded execution and process cleanup. It keeps engine-derived departures, completed trip XML, active/uninserted accounting, sampled positions and every-step stopped-vehicle counts. Warning/error logs, collisions, teleports and unexpected removals invalidate results. A usable engine version is part of the recorded lifecycle; failure cannot silently become valid provenance.

`compare.py` requires matching canonical evidence, demand and time-window metadata, with only declared variant differences. `replay.py` applies that guard at the public export boundary, validates artifact accounting and writes a self-contained HTML file using exclusive creation.

## Fixed synthetic model

Four approaches have 250-metre inbound/outbound edges, one lane per direction and legal left/straight/right routes. A protected approach-by-approach sequence includes matching yellow and all-red stages. This is a supported nonconflicting sequence in a toy model, not a field signal-safety assessment.

The three bundled variants are baseline timing, rebalanced green allocation within the same cycle, and a deliberately restricted eastbound exit. Zero warmup and a finite arrival/observation window make unfinished demand particularly important.

## Evidence boundary

Input hashes identify frozen demand and normalized scenario content. Compiled network hashes may vary across executions because SUMO writes path-dependent comments; original generated files remain available locally.

Observed data, assumed demand, inferred demand and modelled outcomes must remain distinct in any future expansion. Local maps alone do not supply calibration. No sensing or private observations are part of this milestone.
