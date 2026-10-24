"""Controller acceptance tests of model meaning, not just internally balanced totals."""
import json
from pathlib import Path
import pytest
import traci
from traffic_lab.schema import load_scenario, ScenarioError
from traffic_lab.runner import run_simulation

SCENARIO = Path(__file__).resolve().parents[1] / 'scenarios/synthetic-crossroads/scenario.json'


def test_named_turns_match_physical_incoming_headings():
    scenario = load_scenario(SCENARIO)
    # Origins: N vehicles travel south; their left turn goes east, right west.
    left = {'N':'E', 'E':'S', 'S':'W', 'W':'N'}
    right = {'N':'W', 'E':'N', 'S':'E', 'W':'S'}
    for movement in scenario['movements']:
        origin = movement['approach']
        if movement['id'].endswith('-left'):
            assert movement['route'] == f'{origin}_in_{left[origin]}_out'
        elif movement['id'].endswith('-right'):
            assert movement['route'] == f'{origin}_in_{right[origin]}_out'


@pytest.mark.parametrize('defect', ['all-green', 'missing-clearance', 'invalid-state-length', 'unmodelled-warmup', 'mismatched-lane-geometry'])
def test_unsupported_or_conflicting_assumptions_are_rejected_before_engine(tmp_path, defect):
    document = json.loads(SCENARIO.read_text())
    if defect == 'all-green': document['controls']['baseline']['phases'][0]['state'] = 'G'*12
    elif defect == 'invalid-state-length': document['controls']['baseline']['phases'][0]['state'] = 'G'
    elif defect == 'missing-clearance':
        # Turn the yellow stage into another positive-duration green. Total cycle is unchanged.
        document['controls']['baseline']['phases'][1] = {**document['controls']['baseline']['phases'][0], 'duration':3}
    elif defect == 'unmodelled-warmup': document['warmup_seconds'] = -5
    elif defect == 'mismatched-lane-geometry': document['lanes']['N']['length'] = -1
    path = tmp_path/'bad.json'
    path.write_text(json.dumps(document))
    with pytest.raises(ScenarioError):
        load_scenario(path)


def small_scenario():
    scenario = load_scenario(SCENARIO)
    scenario.update(horizon_seconds=180, arrival_window_seconds=100)
    return scenario


def test_metrics_do_not_change_when_frame_capture_is_disabled(tmp_path):
    scenario = small_scenario()
    displayed = run_simulation(scenario, variant='baseline', seed=42, demand_scale=.25, output_dir=tmp_path/'with-frames')
    batch = run_simulation(scenario, variant='baseline', seed=42, demand_scale=.25, output_dir=tmp_path/'without-frames', capture_frames=False)
    assert displayed['metrics']['max_stopped_vehicles'] > 0
    assert batch['metrics'] == displayed['metrics'], 'Batch experiment metrics must not depend on saving replay frames'


def test_compiled_network_turns_and_signal_links_match_declared_approaches(tmp_path):
    from traffic_lab.network import compile_network
    from xml.etree import ElementTree as ET
    scenario = small_scenario()
    root = ET.parse(compile_network(scenario, tmp_path, variant='baseline')).getroot()
    connections = {(c.get('from'), c.get('to')): c for c in root.findall('connection') if c.get('tl') == 'J'}
    assert len(connections) == 12
    for movement in scenario['movements']:
        origin, destination = movement['route'].split('_in_')
        link = connections[(origin + '_in', destination)]
        expected_direction = 'l' if movement['id'].endswith('left') else 'r' if movement['id'].endswith('right') else 's'
        assert link.get('dir') == expected_direction
    phases = root.find("tlLogic[@id='J']").findall('phase')
    for index, origin in enumerate(('N','E','S','W')):
        green_state = phases[index*3].get('state')
        protected = {source for (source, _), link in connections.items() if green_state[int(link.get('linkIndex'))] == 'G'}
        assert protected == {origin + '_in'}


def test_declared_signal_changes_describe_the_input_not_a_generic_label():
    from traffic_lab.runner import _declared_changes
    scenario = small_scenario()
    scenario['controls']['rebalanced']['phases'][0]['duration'] = 10
    scenario['controls']['rebalanced']['phases'][3]['duration'] = 34
    description = ' '.join(_declared_changes(scenario, 'rebalanced'))
    assert 'North 10 s' in description
    assert 'East 34 s' in description
    assert '1 m/s' in ' '.join(_declared_changes(scenario, 'constrained'))


def test_ledger_departure_times_match_actual_engine_departure(tmp_path, monkeypatch):
    import json
    scenario = small_scenario()
    original_step = traci.simulationStep
    observed = {}
    def observe_departure(*args, **kwargs):
        result = original_step(*args, **kwargs)
        for vehicle_id in traci.simulation.getDepartedIDList():
            observed[vehicle_id] = traci.vehicle.getDeparture(vehicle_id)
        return result
    monkeypatch.setattr(traci, 'simulationStep', observe_departure)
    output = tmp_path/'actual-departure'
    run_simulation(scenario, variant='baseline', seed=7, demand_scale=.25, output_dir=output)
    ledger = json.loads((output/'vehicle-ledger.json').read_text())
    assert observed
    for vehicle_id, actual in observed.items():
        record = ledger[vehicle_id]
        assert record['actual_depart'] == pytest.approx(actual)
        assert record['actual_depart'] - record['planned_depart'] == pytest.approx(record['depart_delay_seconds'])


def test_total_queue_peak_matches_independent_engine_halting_counts(tmp_path, monkeypatch):
    scenario = small_scenario()
    original_step = traci.simulationStep
    totals = []
    def observe_halts(*args, **kwargs):
        result = original_step(*args, **kwargs)
        totals.append(sum(traci.lane.getLastStepHaltingNumber(f'{origin}_in_0') for origin in ('N','E','S','W')))
        return result
    monkeypatch.setattr(traci, 'simulationStep', observe_halts)
    run = run_simulation(scenario, variant='baseline', seed=7, demand_scale=.25, output_dir=tmp_path/'queues')
    assert run['metrics']['max_stopped_vehicles'] == max(totals)


def test_inserted_depart_delay_includes_active_inserted_vehicles(tmp_path, monkeypatch):
    scenario = small_scenario()
    original_step = traci.simulationStep
    delays = {}
    def observe_departures(*args, **kwargs):
        result = original_step(*args, **kwargs)
        for vehicle_id in traci.simulation.getDepartedIDList():
            delays[vehicle_id] = traci.vehicle.getDepartDelay(vehicle_id)
        return result
    monkeypatch.setattr(traci, 'simulationStep', observe_departures)
    run = run_simulation(scenario, variant='baseline', seed=42, demand_scale=2, output_dir=tmp_path/'depart-delay')
    assert run['metrics']['active'] > 0
    assert len(delays) == run['metrics']['inserted']
    assert run['metrics']['inserted_mean_depart_delay_seconds'] == pytest.approx(sum(delays.values()) / len(delays), abs=1e-4)


def test_actual_removed_vehicle_is_not_misreported_as_still_active(tmp_path, monkeypatch):
    scenario = small_scenario()
    original_step = traci.simulationStep
    removed = []
    def step_and_remove(*args, **kwargs):
        result = original_step(*args, **kwargs)
        ids = traci.vehicle.getIDList()
        if not removed and ids:
            victim = ids[0]
            removed.append(victim)
            traci.vehicle.remove(victim)
        return result
    monkeypatch.setattr(traci, 'simulationStep', step_and_remove)
    run = run_simulation(scenario, variant='baseline', seed=42, demand_scale=.25, output_dir=tmp_path/'injected-removal')
    assert len(removed) == 1
    assert run['diagnostics']['valid'] is False
    assert run['diagnostics']['unexpected_removals'] == 1
    assert run['metrics']['removed'] == 1
    assert run['metrics']['active'] == len(run['frames'][-1]['vehicles'])
    m = run['metrics']
    assert m['requested'] == sum(m[k] for k in ('completed','active','not_inserted','removed'))
