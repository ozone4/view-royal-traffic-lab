# Development boundaries

This is a public, experimental synthetic traffic sandbox. Never commit credentials, private observations, footage, local environments or generated runs. Do not change unrelated projects or system configuration.

Keep simulation behavior separate from claims about real traffic. Preserve matched demand, requested/completed/active/uninserted/removed accounting, fail-closed diagnostics and provenance. The viewer replays sampled engine positions; it must not fabricate motion or recompute outcomes.

Use the pinned isolated environment. Write failing regressions before behavioral changes, then run focused and full warning-strict pytest, real-engine artifact auditing and browser checks as appropriate. Retain non-sticky mobile navigation. Review final changes independently before committing; do not expand scope silently.
