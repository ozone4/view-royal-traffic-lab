"""Local commands for genuine SUMO runs, offline replays and matched studies."""
from __future__ import annotations

import argparse
from collections import defaultdict
from contextlib import redirect_stderr, redirect_stdout
from copy import deepcopy
import io
import json
import math
from pathlib import Path
from statistics import mean
import sys
import tempfile

from .compare import assert_comparable
from .replay import export_bundle
from .runner import run_simulation
from .schema import load_scenario

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SCENARIO = ROOT / 'scenarios/synthetic-crossroads/scenario.json'
VARIANTS = ('baseline', 'rebalanced', 'constrained')
LABEL = 'Synthetic demonstration, not calibrated to View Royal'


def _number(value: str) -> float:
    result = float(value)
    if not math.isfinite(result) or result < 0:
        raise argparse.ArgumentTypeError('must be a finite nonnegative number')
    return result


def _positive(value: str) -> float:
    result = _number(value)
    if result == 0:
        raise argparse.ArgumentTypeError('must be positive')
    return result


def _seed(value: str) -> int:
    result = int(value)
    if not 0 <= result <= 2**31 - 1:
        raise argparse.ArgumentTypeError('seed must be between 0 and 2147483647')
    return result


def _write_json(path: Path, value: object) -> None:
    with path.open('x', encoding='utf-8') as stream:
        json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write('\n')


def _source_form(scenario: dict) -> dict:
    """Remove parser-derived fields when saving or revalidating source JSON."""
    source = deepcopy(scenario)
    for control in source['controls'].values():
        control.pop('cycle_seconds', None)
    return source


def _checked_scenario(data: dict) -> dict:
    # Reuse the canonical parser for overrides rather than bypass its validation.
    with tempfile.TemporaryDirectory(prefix='traffic-lab-scenario-') as temporary:
        path = Path(temporary) / 'scenario.json'
        _write_json(path, data)
        return load_scenario(path)


def _scenario(args: argparse.Namespace) -> dict:
    scenario = json.loads(args.scenario.read_text(encoding='utf-8'))
    for argument, key in (('horizon', 'horizon_seconds'), ('step', 'step_seconds')):
        if getattr(args, argument) is not None:
            scenario[key] = getattr(args, argument)
    return _checked_scenario(scenario)


def _run(scenario: dict, variant: str, seed: int, scale: float, output: Path, frames: bool) -> dict:
    if output.exists():
        raise FileExistsError(f'refusing to overwrite existing output: {output}')
    console = io.StringIO()
    try:
        with redirect_stdout(console), redirect_stderr(console):
            run = run_simulation(scenario, variant=variant, seed=seed, demand_scale=scale,
                                 output_dir=output, capture_frames=frames)
    finally:
        if output.is_dir():
            with (output / 'runner-console.log').open('x', encoding='utf-8') as stream:
                stream.write(console.getvalue())
    _write_json(output / 'scenario.used.json', _source_form(scenario))
    if not run['diagnostics']['valid']:
        raise ValueError(f'Invalid run diagnostics; inspect {output / "run.json"}')
    return run


def _bundle(runs: list[dict]) -> dict:
    assert_comparable(runs)
    return {'schema_version': 1, 'title': 'Synthetic crossroads scenario explorer',
            'label': LABEL, 'runs': runs}


def _fresh_directory(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=False)


def _demo(args: argparse.Namespace, scenario: dict) -> dict:
    _fresh_directory(args.out)
    runs = [_run(scenario, variant, args.seed, args.scale, args.out / variant, True)
            for variant in VARIANTS]
    bundle = _bundle(runs)
    _write_json(args.out / 'bundle.json', bundle)
    html = export_bundle(bundle, args.out / 'replay.html')
    export_bundle(bundle, args.out / 'traffic-lab-demo.html')
    return {'status': 'complete', 'label': LABEL, 'html': str(html), 'runs': len(runs)}


def _aggregate(results: list[dict]) -> list[dict]:
    groups = defaultdict(list)
    for row in results:
        groups[(row['condition'], row['scale'], row['variant'])].append(row)
    summaries = []
    for (condition, scale, variant), rows in sorted(groups.items()):
        values = {}
        for key in rows[0]['metrics']:
            if key in {'per_approach', 'definitions'}:
                continue
            samples = [r['metrics'][key] for r in rows if r['metrics'][key] is not None]
            values[key] = {'n': len(samples), 'mean': mean(samples) if samples else None,
                           'min': min(samples) if samples else None,
                           'max': max(samples) if samples else None}
        summaries.append({'condition': condition, 'scale': scale, 'variant': variant,
                          'n': len(rows), 'metrics': values})
    return summaries


def _study(args: argparse.Namespace, scenario: dict) -> dict:
    if len(set(args.seeds)) != len(args.seeds) or len(set(args.scales)) != len(args.scales):
        raise ValueError('study seeds and scales must be unique')
    _fresh_directory(args.out)
    results, stored = [], {}

    def experiment(condition: str, settings: dict, seed: int, scale: float) -> list[dict]:
        runs = []
        for variant in VARIANTS:
            output = args.out / condition / f'seed{seed}-scale{scale:g}' / variant
            run = _run(settings, variant, seed, scale, output, False)
            stored[(condition, seed, scale, variant)] = run
            runs.append(run)
            results.append({'condition': condition, 'seed': seed, 'scale': scale,
                            'variant': variant, 'path': str(output),
                            'metadata': run['metadata'], 'metrics': run['metrics'],
                            'diagnostics': run['diagnostics']})
        assert_comparable(runs)
        return runs

    for scale in args.scales:
        for seed in args.seeds:
            experiment('default', scenario, seed, scale)
    reference_seed = args.seeds[0]
    reference_scale = 1.0 if 1.0 in args.scales else args.scales[0]
    if not args.skip_sensitivity:
        longer = _source_form(scenario)
        longer['horizon_seconds'] *= 2
        finer = _source_form(scenario)
        finer['step_seconds'] /= 2
        experiment('double-horizon', _checked_scenario(longer), reference_seed, reference_scale)
        experiment('half-step', _checked_scenario(finer), reference_seed, reference_scale)
    repeat_check = None
    if not args.skip_repeat:
        baseline = stored[('default', reference_seed, reference_scale, 'baseline')]
        repeat = _run(scenario, 'baseline', reference_seed, reference_scale, args.out/'repeat-baseline', False)
        original_path = Path(next(r['path'] for r in results if r['condition'] == 'default'
                                 and r['seed'] == reference_seed and r['scale'] == reference_scale
                                 and r['variant'] == 'baseline'))
        repeat_check = {
            'seed': reference_seed, 'scale': reference_scale,
            'demand_identical': baseline['metadata']['demand_sha256'] == repeat['metadata']['demand_sha256'],
            'metrics_identical': baseline['metrics'] == repeat['metrics'],
            'ledger_identical': json.loads((original_path/'vehicle-ledger.json').read_text())
                                == json.loads((args.out/'repeat-baseline/vehicle-ledger.json').read_text()),
            'path': str(args.out/'repeat-baseline'),
        }
        if not all(repeat_check[key] for key in ('demand_identical','metrics_identical','ledger_identical')):
            _write_json(args.out/'failed-repeat-check.json', repeat_check)
            raise ValueError('identical-input repeat differed; see failed-repeat-check.json')
    report = {'schema_version': 1, 'status': 'complete', 'label': LABEL,
              'seeds': args.seeds, 'scales': args.scales, 'results': results,
              'groups': _aggregate(results), 'repeat_check': repeat_check,
              'limitations': ['Passenger vehicles only; no walking, cycling or transit simulation.',
                              'Seed ranges are descriptive, not confidence intervals or calibration.',
                              'Completed-only timeLoss excludes unfinished and uninserted trips.',
                              'Cross-horizon/step results are sensitivity checks, not matched proposal comparisons.',
                              'No automatic winner, local forecast or safety conclusion.']}
    _write_json(args.out/'study.json', report)
    lines = ['# Synthetic scenario sensitivity study', '', LABEL, '',
             '| Condition | Demand factor | Variant | Seeds | Completed mean (range) | Active mean | Uninserted mean |',
             '|---|---:|---|---:|---:|---:|---:|']
    for group in report['groups']:
        m = group['metrics']; completed = m['completed']
        lines.append(f"| {group['condition']} | {group['scale']:g} | {group['variant']} | {group['n']} | "
                     f"{completed['mean']:.1f} ({completed['min']}–{completed['max']}) | "
                     f"{m['active']['mean']:.1f} | {m['not_inserted']['mean']:.1f} |")
    lines += ['', 'Full accounting, all metrics, per-approach outcomes and diagnostics are in `study.json` and each real run directory.', '', *['- '+line for line in report['limitations']]]
    with (args.out/'study.md').open('x', encoding='utf-8') as stream:
        stream.write('\n'.join(lines)+'\n')
    return {'status': 'complete', 'label': LABEL, 'study': str(args.out/'study.json'),
            'simulations': len(results) + int(repeat_check is not None), 'repeat_check': repeat_check}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description='Local synthetic SUMO scenario explorer. No calibration or safety claims.')
    commands = parser.add_subparsers(dest='command', required=True)
    for command in ('run', 'demo', 'study'):
        sub = commands.add_parser(command)
        sub.add_argument('--scenario', type=Path, default=DEFAULT_SCENARIO)
        sub.add_argument('--out', '--output', dest='out', type=Path, required=True,
                         help='Fresh output directory; existing paths are never overwritten')
        sub.add_argument('--horizon', type=_positive)
        sub.add_argument('--step', type=_positive)
        if command == 'study':
            sub.add_argument('--seeds', nargs='+', type=_seed, default=[11, 22, 33, 44, 55])
            sub.add_argument('--scales', nargs='+', type=_number, default=[.6, 1., 1.4])
            sub.add_argument('--skip-sensitivity', action='store_true')
            sub.add_argument('--skip-repeat', action='store_true')
        else:
            sub.add_argument('--seed', type=_seed, default=42)
            sub.add_argument('--scale', '--demand-scale', dest='scale', type=_number, default=1.)
        if command == 'run':
            sub.add_argument('--variant', choices=VARIANTS, default='baseline')
            sub.add_argument('--no-frames', action='store_true')
    exporter = commands.add_parser('export')
    exporter.add_argument('bundle', type=Path, nargs='?', help='Existing bundle.json to export')
    exporter.add_argument('--run', type=Path, help='Run directory or run.json to wrap in a single-run bundle')
    exporter.add_argument('--out', '--output', dest='out', type=Path, required=True)
    args = parser.parse_args(argv)
    if args.command == 'export' and bool(args.bundle) == bool(args.run):
        parser.error('export requires exactly one input: BUNDLE or --run RUN')
    args.out = args.out.resolve()
    try:
        if args.command == 'export':
            if args.run:
                run_path = args.run / 'run.json' if args.run.is_dir() else args.run
                if run_path.name != 'run.json':
                    parser.error('--run must name a run directory or run.json')
                bundle = _bundle([json.loads(run_path.read_text(encoding='utf-8'))])
            else:
                bundle = json.loads(args.bundle.read_text(encoding='utf-8'))
            html = export_bundle(bundle, args.out)
            receipt = {'status': 'complete', 'html': str(html)}
        else:
            scenario = _scenario(args)
            if args.command == 'demo':
                receipt = _demo(args, scenario)
            elif args.command == 'study':
                receipt = _study(args, scenario)
            else:
                run = _run(scenario, args.variant, args.seed, args.scale, args.out, not args.no_frames)
                receipt = {'status': 'complete', 'label': LABEL, 'run': str(args.out/'run.json'), 'metrics': run['metrics']}
        print(json.dumps(receipt, allow_nan=False))
        return 0
    except (OSError, ValueError, RuntimeError) as exc:
        print(f'traffic-lab: {exc}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
