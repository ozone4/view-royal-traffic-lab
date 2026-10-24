from pathlib import Path

from traffic_lab.compare import ComparisonError, assert_comparable
from traffic_lab.runner import run_simulation
from traffic_lab.schema import load_scenario


SCENARIO = Path("scenarios/synthetic-crossroads/scenario.json")


def test_real_sumo_run_writes_reconciled_engine_artifact(tmp_path):
    scenario = load_scenario(SCENARIO)
    run = run_simulation(scenario, variant="baseline", seed=7, demand_scale=0.03, output_dir=tmp_path / "baseline")
    metrics = run["metrics"]
    assert (tmp_path / "baseline" / "run.json").is_file()
    assert (tmp_path / "baseline" / "tripinfo.xml").is_file()
    assert "SUMO" in run["metadata"]["engine_version"]
    assert "1.28.0" in run["metadata"]["engine_version"]
    assert metrics["requested"] == metrics["completed"] + metrics["active"] + metrics["not_inserted"] + metrics["removed"]
    assert metrics["inserted"] == metrics["completed"] + metrics["active"] + metrics["removed"]
    assert run["diagnostics"]["teleports"] == 0
    assert run["diagnostics"]["valid"] is True
    assert run["frames"][-1]["t"] == scenario["horizon_seconds"]
    assert all(set(frame["queues"]) == {"N", "E", "S", "W"} for frame in run["frames"])


def test_comparison_guard_requires_matched_evidence_but_allows_constrained_variant():
    base = {"variant": "baseline", "metadata": {"seed": 1, "demand_sha256": "x", "network_sha256": "n", "horizon_seconds": 900, "step_seconds": .5, "warmup_seconds": 0, "engine_version": "SUMO 1.28.0", "geometry_status": "synthetic", "demand_status": "synthetic_frozen", "control_status": "synthetic", "model_status": "demonstration_only"}, "diagnostics": {"valid": True, "collisions": 0, "teleports": 0, "unexpected_removals": 0}}
    base['metadata'].update(scenario_sha256='fixture-scenario', demand_scale=1,
                            frame_interval_seconds=2, arrival_window_seconds=600,
                            modes=['passenger'], units='metres, seconds, metres/second')
    constrained = {**base, "variant": "constrained", "changes": ["Reduced eastbound exit speed"], "metadata": {**base["metadata"], "network_sha256": "different"}}
    assert_comparable([base, constrained])
    bad = {**base, "metadata": {**base["metadata"], "seed": 2}}
    try:
        assert_comparable([base, bad])
    except ComparisonError as error:
        assert "seed" in str(error)
    else:
        raise AssertionError("mismatched frozen demand evidence must fail")
