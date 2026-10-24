import json
from pathlib import Path

import pytest

from traffic_lab.demand import build_frozen_demand, write_routes
from traffic_lab.schema import ScenarioError, load_scenario


SCENARIO = Path("scenarios/synthetic-crossroads/scenario.json")


def test_synthetic_scenario_is_strictly_valid_and_evidenced():
    scenario = load_scenario(SCENARIO)
    assert scenario["schema_version"] == 1
    assert scenario["evidence"]["geometry_status"] == "synthetic"
    assert scenario["evidence"]["demand_status"] == "synthetic_frozen"
    assert scenario["evidence"]["control_status"] == "synthetic"
    assert scenario["evidence"]["model_status"] == "demonstration_only"
    assert scenario["modes"] == ["passenger"]
    assert scenario["arrival_window_seconds"] == 600


@pytest.mark.parametrize(
    "mutate, message",
    [
        (lambda d: d.update(arrival_window_seconds=-1), "arrival_window_seconds"),
        (lambda d: d.update(step_seconds=float("nan")), "step_seconds"),
        (lambda d: d["movements"][0].update(lanes=["missing"]), "lane"),
        (lambda d: d["movements"][1].update(id=d["movements"][0]["id"]), "duplicate"),
        (lambda d: d["controls"]["baseline"]["phases"].__setitem__(0, {"state":"G", "duration": 0}), "clearance"),
    ],
)
def test_schema_rejects_invalid_scenario_values(tmp_path, mutate, message):
    document = json.loads(SCENARIO.read_text())
    mutate(document)
    path = tmp_path / "bad.json"
    path.write_text(json.dumps(document))
    with pytest.raises(ScenarioError, match=message):
        load_scenario(path)


@pytest.mark.parametrize(
    "mutate, message",
    [
        (lambda d: d["lanes"]["N"].update(edge="not_a_fixed_edge"), "edge"),
        (lambda d: d["lanes"]["N"].update(length=249), "length"),
        (lambda d: d["evidence"].update(geometry_status="observed"), "geometry_status"),
        (lambda d: d.update(warmup_seconds=1), "warmup_seconds"),
        (lambda d: d.update(frame_interval_seconds=0.3), "frame_interval_seconds"),
        (lambda d: d["movements"][0].update(route="N_in_S_out"), "route"),
        (lambda d: d["controls"]["baseline"]["phases"].__setitem__(2, {"state": "rrrrrrrrrrrr", "duration": 2, "approach": "N"}), "phase"),
    ],
)
def test_schema_rejects_unmodelled_fixed_network_assumptions(tmp_path, mutate, message):
    document = json.loads(SCENARIO.read_text())
    mutate(document)
    path = tmp_path / "unsupported.json"
    path.write_text(json.dumps(document))
    with pytest.raises(ScenarioError, match=message):
        load_scenario(path)


def test_frozen_demand_is_seeded_identical_across_variants_and_routes_legal(tmp_path):
    scenario = load_scenario(SCENARIO)
    one = build_frozen_demand(scenario, seed=42, demand_scale=0.15)
    two = build_frozen_demand(scenario, seed=42, demand_scale=0.15)
    assert one.sha256 == two.sha256
    assert one.requests == two.requests
    assert {r.approach for r in one.requests} == {"N", "E", "S", "W"}
    assert len({r.id for r in one.requests}) == len(one.requests)
    assert all(r.route in scenario["legal_routes"] for r in one.requests)
    first = write_routes(one, tmp_path / "a.rou.xml")
    second = write_routes(two, tmp_path / "b.rou.xml")
    assert first.read_bytes() == second.read_bytes()
    assert 'vClass="passenger"' in first.read_text()
