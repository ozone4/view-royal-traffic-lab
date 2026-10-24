# Contributing

Small, testable improvements are welcome. Open an issue before proposing major geometry, calibration, sensing or hosted-service changes.

1. Use a source checkout and `uv sync --locked --extra test`.
2. Add a failing regression before changing simulation or accounting behavior.
3. Run `.venv/bin/python -m pytest -q -W error`.
4. Generate a real demo, audit `bundle.json`, and run browser checks for viewer/export changes. See the README.
5. Preserve source/evidence labels, matched demand, all vehicle cohorts and diagnostic failures. Do not replace failed simulations with invented outputs.
6. Keep generated runs, environments, credentials, footage and private observations out of Git and issue attachments.

CI checks Linux/macOS runtime behavior and Linux browser acceptance. Full repeated/sensitivity experiments can be run with `traffic-lab study`; they are not run on every pull request.

Changing a time step, horizon or demand process can change outcomes. Document those changes and their validation rather than treating software tests as real-world calibration or safety evidence.

Contributions to original project material are submitted under the repository's MIT licence. Identify third-party code/data and retain applicable notices. AI-assisted contributions need the same source review, licensing checks and executable evidence as other contributions.
