"""Independent serialized-artifact audit. Does not simulate or derive display metrics."""
import json
import math
from pathlib import Path
import sys

COUNTS = ('requested', 'completed', 'active', 'not_inserted', 'removed')


def audit(bundle):
    errors = []
    runs = bundle.get('runs', [])
    if not runs:
        return ['Missing runs']
    baseline = runs[0]['metadata']
    for run in runs:
        name = run.get('variant', '?')
        def require(ok, message):
            if not ok:
                errors.append(f'{name}: {message}')
        m = run['metrics']
        for key in (*COUNTS, 'inserted'):
            require(type(m[key]) is int and m[key] >= 0, f'invalid count {key}')
        require(m['requested'] == sum(m[k] for k in ('completed', 'active', 'not_inserted', 'removed')), 'requested demand not reconciled')
        require(m['inserted'] == sum(m[k] for k in ('completed', 'active', 'removed')), 'inserted demand not reconciled')
        for key in COUNTS:
            require(sum(m['per_approach'][a][key] for a in 'NESW') == m[key], f'approach total mismatch: {key}')
        for key in ('demand_sha256', 'seed', 'horizon_seconds'):
            require(run['metadata'][key] == baseline[key], f'comparison mismatch: {key}')
        d = run['diagnostics']
        require(d['valid'] is True, 'diagnostics invalid')
        require(not any(d[k] for k in ('collisions', 'teleports', 'unexpected_removals')), 'diagnostic incident present')
        frames = run['frames']
        require(bool(frames), 'no replay frames')
        if not frames:
            continue
        horizon = run['metadata']['horizon_seconds']
        require(math.isclose(frames[-1]['t'], horizon, abs_tol=1e-6), 'final frame does not reach horizon')
        require(len(frames[-1]['vehicles']) == m['active'], 'final-frame active count mismatch')
        for a in 'NESW':
            require(sum(v['approach'] == a for v in frames[-1]['vehicles']) == m['per_approach'][a]['active'], f'final-frame approach count mismatch: {a}')
        last_time = -1
        bounds = run['geometry']['bounds']
        for frame in frames:
            require(math.isfinite(frame['t']) and last_time < frame['t'] <= horizon, 'invalid/non-increasing frame time')
            last_time = frame['t']
            vehicles = frame['vehicles']
            require(len({v['id'] for v in vehicles}) == len(vehicles), 'duplicate vehicle ID in frame')
            for v in vehicles:
                require(math.isfinite(v['x']) and math.isfinite(v['y']), 'non-finite vehicle position')
                require(bounds[0] - 10 <= v['x'] <= bounds[2] + 10 and bounds[1] - 10 <= v['y'] <= bounds[3] + 10, 'vehicle outside shared network bounds')
                require(v['approach'] in 'NESW' and len(v['approach']) == 1, 'invalid vehicle origin')
    return errors


def main():
    try:
        if len(sys.argv) != 2:
            raise ValueError('Usage: audit_artifacts.py path/to/bundle.json')
        bundle = json.loads(Path(sys.argv[1]).read_text())
        errors = audit(bundle)
        receipt = {'status': 'FAIL' if errors else 'PASS', 'runs': len(bundle['runs']), 'errors': errors[:30]}
    except (OSError, ValueError, TypeError, KeyError, IndexError) as exc:
        receipt = {'status': 'FAIL', 'errors': [str(exc)]}
    print(json.dumps(receipt, indent=2))
    return 0 if receipt['status'] == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
