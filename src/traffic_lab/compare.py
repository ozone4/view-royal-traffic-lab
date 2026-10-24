"""Fail-closed guardrails before presenting matched runs side-by-side."""
from __future__ import annotations
from typing import Any


class ComparisonError(ValueError):
    pass


MATCHED = (
    'seed', 'demand_sha256', 'scenario_sha256', 'demand_scale',
    'horizon_seconds', 'step_seconds', 'warmup_seconds', 'frame_interval_seconds',
    'arrival_window_seconds', 'engine_version', 'geometry_status',
    'demand_status', 'control_status', 'model_status', 'modes', 'units',
)


def assert_comparable(runs: list[dict[str, Any]]) -> None:
    if not runs:
        raise ComparisonError('no runs to compare')
    reference = runs[0].get('metadata', {})
    for run in runs:
        diagnostics = run.get('diagnostics', {})
        if diagnostics.get('valid') is not True or any(
            diagnostics.get(key) != 0 for key in ('collisions', 'teleports', 'unexpected_removals')
        ):
            raise ComparisonError('run diagnostics invalidate comparison')
        if run.get('metrics', {}).get('removed', 0) != 0:
            raise ComparisonError('removed vehicles invalidate comparison')
        if run.get('variant') not in {'baseline', 'rebalanced', 'constrained'}:
            raise ComparisonError('unknown variant')
        metadata = run.get('metadata', {})
        for key in (*MATCHED, 'network_sha256'):
            if key not in metadata or metadata[key] is None or metadata[key] == '':
                raise ComparisonError(f'missing required {key}')
        for key in MATCHED:
            if metadata[key] != reference.get(key):
                raise ComparisonError(f'mismatched {key}')
        # Compiled XML includes control changes as well as network settings.
        # Different hashes are allowed only when the variant declares its changes.
        if metadata['network_sha256'] != reference.get('network_sha256') and not run.get('changes'):
            raise ComparisonError('different network requires declared changes')
