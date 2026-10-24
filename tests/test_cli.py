"""Exercise CLI commands against real, short SUMO runs in fresh directories."""
import json
from pathlib import Path
import subprocess
import sys
import pytest

from traffic_lab import cli

ROOT = Path(__file__).resolve().parents[1]


def invoke(*args):
    return subprocess.run([sys.executable, '-m', 'traffic_lab.cli', *map(str, args)], cwd=ROOT, capture_output=True, text=True, timeout=90)


def test_cli_exposes_all_commands():
    result = invoke('--help')
    assert result.returncode == 0, result.stderr
    assert all(command in result.stdout for command in ('run', 'demo', 'export', 'study'))


@pytest.fixture(scope='module')
def demonstration(tmp_path_factory):
    folder = tmp_path_factory.mktemp('cli-real')
    scenario = json.loads((ROOT/'scenarios/synthetic-crossroads/scenario.json').read_text())
    scenario.update(horizon_seconds=120, arrival_window_seconds=60)
    scenario_path = folder/'scenario.json'
    scenario_path.write_text(json.dumps(scenario))
    output = folder/'demo'
    result = invoke('demo','--scenario',scenario_path,'--demand-scale',.2,'--seed',7,'--output',output)
    assert result.returncode == 0, result.stdout + result.stderr
    receipt = json.loads(result.stdout)
    assert receipt['status'] == 'complete'
    return folder, scenario_path, output


def test_demo_contains_real_comparable_runs_and_offline_replay(demonstration):
    _, _, output = demonstration
    bundle = json.loads((output/'bundle.json').read_text())
    assert [r['variant'] for r in bundle['runs']] == ['baseline','rebalanced','constrained']
    assert len({r['metadata']['demand_sha256'] for r in bundle['runs']}) == 1
    assert all(r['frames'][-1]['t'] == 120 for r in bundle['runs'])
    assert all((output/r['variant']/'tripinfo.xml').is_file() for r in bundle['runs'])
    assert '<canvas' in (output/'replay.html').read_text()
    assert '<canvas' in (output/'traffic-lab-demo.html').read_text()


def test_cli_refuses_to_overwrite_completed_run_directory(demonstration):
    _, scenario, output = demonstration
    previous = (output/'bundle.json').read_bytes()
    result = invoke('demo','--scenario',scenario,'--scale',.2,'--out',output)
    assert result.returncode != 0
    assert (output/'bundle.json').read_bytes() == previous


def test_export_command_works_without_an_engine_rerun(demonstration):
    folder, _, output = demonstration
    result = invoke('export',output/'bundle.json','--output',folder/'exported.html')
    assert result.returncode == 0, result.stderr
    assert (folder/'exported.html').is_file()
    assert json.loads(result.stdout)['status'] == 'complete'


@pytest.mark.parametrize('run_source_name', ['baseline', 'baseline/run.json'])
def test_export_run_wraps_a_genuine_run_in_single_run_bundle(demonstration, run_source_name):
    folder, _, _ = demonstration
    run_source = folder/'demo'/run_source_name
    html = folder/f'exported-{run_source_name.replace("/", "-")}.html'
    result = invoke('export','--run',run_source,'--output',html)
    assert result.returncode == 0, result.stderr
    assert html.is_file()
    page = html.read_text(encoding='utf-8')
    assert '<canvas' in page
    assert 'Synthetic crossroads scenario explorer' in page


def test_export_rejects_missing_or_ambiguous_input(demonstration):
    folder, _, output = demonstration
    missing = invoke('export','--output',folder/'missing.html')
    ambiguous = invoke('export',output/'bundle.json','--run',output/'baseline',
                       '--output',folder/'ambiguous.html')
    assert missing.returncode != 0
    assert ambiguous.returncode != 0
    assert 'exactly one input' in missing.stderr
    assert 'exactly one input' in ambiguous.stderr


def test_study_default_matrix_preserves_replications_and_checks(monkeypatch, tmp_path):
    received = {}

    def fake_study(args, scenario):
        received.update(seeds=args.seeds, scales=args.scales,
                        skip_sensitivity=args.skip_sensitivity, skip_repeat=args.skip_repeat)
        return {'status': 'complete'}

    monkeypatch.setattr(cli, '_study', fake_study)
    assert cli.main(['study', '--output', str(tmp_path/'study')]) == 0
    assert received == {
        'seeds': [11, 22, 33, 44, 55],
        'scales': [0.6, 1.0, 1.4],
        'skip_sensitivity': False,
        'skip_repeat': False,
    }


def test_saved_scenario_can_reproduce_its_run(demonstration):
    folder, _, output = demonstration
    result = invoke('run','--scenario',output/'baseline/scenario.used.json','--seed',7,'--demand-scale',.2,'--output',folder/'rerun')
    assert result.returncode == 0, result.stderr
    original = json.loads((output/'baseline/run.json').read_text())
    repeated = json.loads((folder/'rerun/run.json').read_text())
    assert repeated['metrics'] == original['metrics']
    assert repeated['frames'] == original['frames']


def test_small_study_writes_actual_results_and_no_winner_claim(demonstration):
    folder, scenario, _ = demonstration
    out = folder/'study'
    result = invoke('study','--scenario',scenario,'--seeds',7,'--scales',.2,'--out',out)
    assert result.returncode == 0, result.stdout + result.stderr
    study = json.loads((out/'study.json').read_text())
    assert len(study['results']) == 9
    assert len(study['groups']) == 9
    assert {row['condition'] for row in study['results']} == {'default','double-horizon','half-step'}
    assert study['repeat_check']['demand_identical'] is True
    assert study['repeat_check']['metrics_identical'] is True
    assert study['repeat_check']['ledger_identical'] is True
    assert all(group['n'] == 1 for group in study['groups'])
    assert all(Path(row['path']).joinpath('run.json').is_file() for row in study['results'])
    assert 'winner' not in study


@pytest.mark.parametrize('arguments', [('--scale','nan'),('--scale','-1'),('--step','0'),('--horizon','30')])
def test_invalid_cli_options_fail_before_creating_output(tmp_path, arguments):
    out = tmp_path/'invalid'
    result = invoke('run',*arguments,'--out',out)
    assert result.returncode != 0
    assert not out.exists()
