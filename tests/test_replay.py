"""Exporter contracts using plainly synthetic fixture data, never engine evidence."""

import html
import json
import re
from copy import deepcopy
from pathlib import Path

import pytest

from traffic_lab.replay import export_bundle


LABEL = "Synthetic demonstration, not calibrated to View Royal"


def synthetic_run(*, run_id="baseline", variant="baseline", title="Synthetic baseline"):
    """A deliberately tiny, synthetic replay fixture for exporter tests only."""
    return {
        "schema_version": 1,
        "run_id": run_id,
        "variant": variant,
        "title": title,
        "label": LABEL,
        "changes": ["Synthetic signal timing adjustment"],
        "limitations": ["Synthetic test fixture; not a field observation."],
        "metadata": {
            "engine_version": "SUMO 1.28.0",
            "seed": 42,
            "demand_scale": 1.0,
            "demand_sha256": "demand-test-sha",
            "network_sha256": "network-test-sha",
            "scenario_sha256": "scenario-test-sha",
            "horizon_seconds": 10,
            "step_seconds": 1,
            "warmup_seconds": 0,
            "arrival_window_seconds": 8,
            "frame_interval_seconds": 5,
            "geometry_status": "synthetic",
            "demand_status": "synthetic",
            "control_status": "synthetic",
            "model_status": "demonstration",
            "modes": ["vehicle"],
            "units": "metres, seconds, m/s",
        },
        "geometry": {
            "bounds": [-20, -20, 20, 20],
            "lanes": [{"id": "north_in", "shape": [[0, 20], [0, -20]], "width": 3.2}],
            "junctions": [{"id": "junction", "shape": [[-3, -3], [3, -3], [3, 3], [-3, 3]]}],
        },
        "frames": [
            {
                "t": 0,
                "vehicles": [{"id": "synthetic-car", "x": 0, "y": 12, "angle": 180, "speed": 6, "approach": "N"}],
                "signals": [{"id": "tls-main", "state": "GrGr"}],
                "queues": {"N": 1, "E": 0, "S": 0, "W": 0},
            },
            {
                "t": 10,
                "vehicles": [],
                "signals": [{"id": "tls-main", "state": "rGrG"}],
                "queues": {"N": 0, "E": 0, "S": 0, "W": 0},
            },
        ],
        "metrics": {
            "requested": 2,
            "inserted": 2,
            "completed": 1,
            "active": 1,
            "not_inserted": 0,
            "removed": 0,
            "outside_horizon": 0,
            "completed_mean_time_loss_seconds": 3.5,
            "completed_mean_duration_seconds": 8.0,
            "inserted_mean_depart_delay_seconds": 0.5,
            "max_stopped_vehicles": 1,
            "per_approach": {
                direction: {"requested": 2 if direction == "N" else 0,
                            "completed": 1 if direction == "N" else 0,
                            "active": 1 if direction == "N" else 0,
                            "not_inserted": 0, "removed": 0,
                            "max_stopped_vehicles": 1 if direction == "N" else 0}
                for direction in "NESW"
            },
            "definitions": {
                "max_stopped_vehicles": "Maximum sampled stopped vehicles on inbound lanes at speed under 0.1 m/s.",
                "completed_mean_time_loss_seconds": "Mean SUMO time loss for completed vehicles only.",
            },
        },
        "diagnostics": {"valid": True, "collisions": 0, "teleports": 0, "unexpected_removals": 0, "warnings": []},
    }


def synthetic_bundle(*runs):
    return {"schema_version": 1, "title": "Synthetic replay", "label": LABEL, "runs": list(runs)}


def embedded_bundle(document: str) -> dict:
    match = re.search(r'<script id="traffic-lab-data" type="application/json">(.*?)</script>', document, re.S)
    assert match, "the data payload must be embedded in a JSON script element"
    return json.loads(html.unescape(match.group(1)))


def test_export_bundle_writes_self_contained_replay_with_precomputed_data(tmp_path: Path):
    bundle = synthetic_bundle(synthetic_run(), synthetic_run(run_id="rebalanced", variant="rebalanced"))

    result = export_bundle(bundle, tmp_path / "replay.html")

    assert result == tmp_path / "replay.html"
    document = result.read_text(encoding="utf-8")
    assert "<canvas" in document
    assert "traffic-lab-data" in document
    assert "https://" not in document
    assert "src=" not in document
    assert embedded_bundle(document) == bundle
    assert "requestAnimationFrame" in document
    assert "interpolat" not in document.lower()
    assert "Synthetic demonstration, not calibrated to View Royal" in document
    assert "Vehicle-only model" in document
    assert "Playback speed" in document
    assert "Simulation time" in document
    assert "Sample interval" in document
    assert "Metric definitions" in document


def test_export_bundle_escapes_malicious_text_without_html_or_script_termination(tmp_path: Path):
    evil = '</script><img src=x onerror=alert(1)>'
    bundle = synthetic_bundle(synthetic_run(title=evil))
    bundle["title"] = evil

    result = export_bundle(bundle, tmp_path / "evil.html")
    document = result.read_text(encoding="utf-8")

    assert "<img src=x" not in document
    assert "</script><img" not in document
    assert embedded_bundle(document)["title"] == evil
    assert "innerHTML" not in document


def test_export_bundle_preserves_empty_traffic_and_nullable_metrics(tmp_path: Path):
    run = synthetic_run()
    run["frames"] = [{"t": 0, "vehicles": [], "signals": [], "queues": {"N": 0, "E": 0, "S": 0, "W": 0}}]
    run["metadata"]["horizon_seconds"] = 0
    run["metrics"].update({
        "requested": 0, "inserted": 0, "completed": 0, "active": 0,
        "completed_mean_time_loss_seconds": None,
        "completed_mean_duration_seconds": None,
        "inserted_mean_depart_delay_seconds": None,
        "max_stopped_vehicles": 0,
    })

    for approach in run["metrics"]["per_approach"].values():
        for field in approach:
            approach[field] = 0
    result = export_bundle(synthetic_bundle(run), tmp_path / "empty.html")
    document = result.read_text(encoding="utf-8")

    assert embedded_bundle(document)["runs"][0]["frames"][0]["vehicles"] == []
    assert "Not available" in document
    assert "No sampled vehicles in this frame" in document


@pytest.mark.parametrize(
    "diagnostics",
    [
        {"valid": False, "collisions": 0, "teleports": 0, "unexpected_removals": 0, "warnings": ["Synthetic test warning"]},
        {"valid": True, "collisions": 1, "teleports": 0, "unexpected_removals": 0, "warnings": []},
        {"valid": True, "collisions": 0, "teleports": 1, "unexpected_removals": 0, "warnings": []},
        {"valid": True, "collisions": 0, "teleports": 0, "unexpected_removals": 1, "warnings": []},
    ],
)
def test_export_bundle_rejects_invalid_single_run_diagnostics(tmp_path: Path, diagnostics: dict):
    run = synthetic_run()
    run["metrics"].update({"requested": 4, "inserted": 1, "completed": 1, "active": 0, "not_inserted": 3, "removed": 0})
    run["metrics"]["per_approach"]["N"].update(requested=4, completed=1, active=0, not_inserted=3)
    run["diagnostics"] = diagnostics

    with pytest.raises(ValueError, match="diagnostics invalidate comparison"):
        export_bundle(synthetic_bundle(run), tmp_path / "one-run.html")

    assert not (tmp_path / "one-run.html").exists()


def test_export_bundle_allows_variant_specific_network_hashes(tmp_path: Path):
    baseline = synthetic_run()
    proposal = synthetic_run(run_id="constrained", variant="constrained")
    proposal["metadata"]["network_sha256"] = "network-with-declared-constraint"

    result = export_bundle(synthetic_bundle(baseline, proposal), tmp_path / "variant-network.html")

    assert result.is_file()
    assert embedded_bundle(result.read_text(encoding="utf-8"))["runs"][1]["metadata"]["network_sha256"] == "network-with-declared-constraint"


@pytest.mark.parametrize(
    "field",
    [
        "seed", "demand_sha256", "horizon_seconds", "step_seconds", "frame_interval_seconds",
        "warmup_seconds", "arrival_window_seconds", "engine_version", "scenario_sha256",
        "geometry_status", "demand_status", "control_status", "model_status", "modes", "units",
    ],
)
def test_export_bundle_rejects_non_comparable_runs(tmp_path: Path, field: str):
    baseline = synthetic_run()
    proposal = deepcopy(synthetic_run(run_id="constrained", variant="constrained"))
    current = proposal["metadata"][field]
    proposal["metadata"][field] = ["pedestrian"] if isinstance(current, list) else (
        "different" if isinstance(current, str) else 99
    )
    if field == "horizon_seconds":
        proposal["frames"][-1]["t"] = 99

    with pytest.raises(ValueError, match=fr"mismatched {field}"):
        export_bundle(synthetic_bundle(baseline, proposal), tmp_path / "mismatch.html")


@pytest.mark.parametrize("field", ["warmup_seconds", "arrival_window_seconds", "geometry_status", "modes", "units"])
def test_export_bundle_rejects_missing_canonical_comparison_metadata(tmp_path: Path, field: str):
    run = synthetic_run()
    del run["metadata"][field]

    with pytest.raises(ValueError, match=field):
        export_bundle(synthetic_bundle(run), tmp_path / "missing.html")

    assert not (tmp_path / "missing.html").exists()


def test_export_bundle_rejects_runs_with_different_sample_timestamps(tmp_path: Path):
    baseline = synthetic_run()
    proposal = synthetic_run(run_id="constrained", variant="constrained")
    proposal["frames"][0]["t"] = 1

    with pytest.raises(ValueError, match="frame timestamps"):
        export_bundle(synthetic_bundle(baseline, proposal), tmp_path / "mismatch.html")


def test_export_bundle_rejects_frames_outside_declared_geometry_or_horizon(tmp_path: Path):
    run = synthetic_run()
    run["frames"][0]["vehicles"][0]["x"] = 200

    with pytest.raises(ValueError, match="bounds"):
        export_bundle(synthetic_bundle(run), tmp_path / "bad.html")

    run = synthetic_run()
    run["frames"][-1]["t"] = 9
    with pytest.raises(ValueError, match="final horizon"):
        export_bundle(synthetic_bundle(run), tmp_path / "short.html")
