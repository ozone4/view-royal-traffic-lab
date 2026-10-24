"""Independent checks of exported JSON, separate from engine implementation."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import pytest

ROOT = Path(__file__).resolve().parents[1]


def fixture_bundle():
    # Deliberately tiny test fixture, NOT an engine run or user-facing result.
    per = {a: dict(requested=0, completed=0, active=0, not_inserted=0, removed=0) for a in 'NESW'}
    per['N'].update(requested=3, completed=1, active=1, not_inserted=1)
    return {'runs': [{
        'variant': 'baseline',
        'metadata': {'horizon_seconds': 10, 'demand_sha256': 'fixture', 'seed': 42},
        'geometry': {'bounds': [0, 0, 10, 10]},
        'metrics': {'requested': 3, 'inserted': 2, 'completed': 1, 'active': 1, 'not_inserted': 1, 'removed': 0, 'per_approach': per},
        'diagnostics': {'valid': True, 'collisions': 0, 'teleports': 0, 'unexpected_removals': 0},
        'frames': [{'t': 10, 'vehicles': [{'id': 'fixture-active', 'x': 5, 'y': 5, 'approach': 'N'}]}],
    }]}


def run_audit(tmp_path, bundle):
    path = tmp_path / 'fixture.json'
    path.write_text(json.dumps(bundle))
    return subprocess.run([sys.executable, str(ROOT / 'scripts/audit_artifacts.py'), str(path)], text=True, capture_output=True, timeout=10)


def test_valid_fixture_passes_independent_audit(tmp_path):
    result = run_audit(tmp_path, fixture_bundle())
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)['status'] == 'PASS'


@pytest.mark.parametrize('defect', ['missing-demand', 'wrong-final-active', 'wrong-approach', 'bad-diagnostics', 'duplicate-vehicle', 'nonfinite-position', 'early-final-frame'])
def test_audit_rejects_bad_serialized_results(tmp_path, defect):
    bundle = fixture_bundle()
    run = bundle['runs'][0]
    if defect == 'missing-demand': run['metrics']['requested'] = 4
    elif defect == 'wrong-final-active': run['frames'][0]['vehicles'] = []
    elif defect == 'wrong-approach': run['metrics']['per_approach']['N']['completed'] = 0
    elif defect == 'bad-diagnostics': run['diagnostics']['collisions'] = 1
    elif defect == 'duplicate-vehicle': run['frames'][0]['vehicles'] *= 2
    elif defect == 'nonfinite-position': run['frames'][0]['vehicles'][0]['x'] = float('nan')
    elif defect == 'early-final-frame': run['frames'][0]['t'] = 9
    result = run_audit(tmp_path, bundle)
    assert result.returncode != 0
    assert json.loads(result.stdout)['status'] == 'FAIL'


def test_audit_rejects_mismatched_comparison_demand(tmp_path):
    bundle = fixture_bundle()
    proposed = copy.deepcopy(bundle['runs'][0])
    proposed['variant'] = 'rebalanced'
    proposed['metadata']['demand_sha256'] = 'different'
    bundle['runs'].append(proposed)
    result = run_audit(tmp_path, bundle)
    assert result.returncode != 0
    assert json.loads(result.stdout)['status'] == 'FAIL'
