"""Regression coverage for reviewer-confirmed artifact-contract boundaries."""
from pathlib import Path
import math
import subprocess

import pytest

from traffic_lab import replay, runner
from traffic_lab.demand import build_frozen_demand
from traffic_lab.schema import load_scenario


SCENARIO = Path("scenarios/synthetic-crossroads/scenario.json")


@pytest.mark.parametrize(
    ("probe", "expected"),
    [
        (subprocess.TimeoutExpired(["sumo", "--version"], 10), "timed out"),
        (OSError("version executable unavailable"), "unavailable"),
        (subprocess.CompletedProcess(["sumo", "--version"], 2, "", "version failed"), "status 2"),
        (subprocess.CompletedProcess(["sumo", "--version"], 0, "\n", ""), "empty output"),
    ],
    ids=["timeout", "oserror", "nonzero", "empty"],
)
def test_engine_version_rejects_unusable_probe_results(monkeypatch, probe, expected):
    def probe_version(*args, **kwargs):
        if isinstance(probe, BaseException):
            raise probe
        return probe

    monkeypatch.setattr(runner.subprocess, "run", probe_version)

    with pytest.raises(RuntimeError, match="SUMO version probe failed") as error:
        runner._engine_version()

    assert expected in str(error.value)


@pytest.mark.parametrize("reason", ["timed out", "unavailable", "status 2", "empty output"])
def test_unusable_version_probe_writes_invalid_failed_run_after_engine_completion(tmp_path, monkeypatch, reason):
    def unavailable_version():
        raise RuntimeError(f"SUMO version probe failed: {reason}")

    monkeypatch.setattr(runner, "_engine_version", unavailable_version)
    output = tmp_path / "probe-failure"

    with pytest.raises(RuntimeError, match="SUMO version probe failed"):
        runner.run_simulation(
            load_scenario(SCENARIO), variant="baseline", seed=7, demand_scale=0.03,
            output_dir=output, capture_frames=False,
        )

    failed = (output / "failed-run.json").read_text(encoding="utf-8")
    assert '"valid": false' in failed
    assert reason in failed
    assert not (output / "run.json").exists()
    assert (output / "tripinfo.xml").is_file(), "the real engine completed before provenance failed"


def test_normal_small_engine_run_retains_valid_departure_metrics(tmp_path):
    run = runner.run_simulation(
        load_scenario(SCENARIO), variant="baseline", seed=7, demand_scale=0.03,
        output_dir=tmp_path / "normal", capture_frames=False,
    )

    assert run["diagnostics"]["valid"] is True
    assert run["metadata"]["engine_version"].startswith("Eclipse SUMO")
    assert run["metrics"]["inserted"] > 0
    assert run["metrics"]["inserted_mean_depart_delay_seconds"] is not None


@pytest.mark.parametrize("scale", [math.nan, math.inf, -math.inf], ids=["nan", "positive-infinity", "negative-infinity"])
def test_run_simulation_rejects_nonfinite_demand_before_creating_output(tmp_path, scale):
    output = tmp_path / "nonfinite"

    with pytest.raises(ValueError, match="finite non-negative"):
        runner.run_simulation(
            load_scenario(SCENARIO), variant="baseline", seed=7, demand_scale=scale,
            output_dir=output,
        )

    assert not output.exists()


@pytest.mark.parametrize("scale", [math.nan, math.inf, -math.inf], ids=["nan", "positive-infinity", "negative-infinity"])
def test_shared_demand_builder_rejects_nonfinite_scale(scale):
    with pytest.raises(ValueError, match="finite non-negative"):
        build_frozen_demand(load_scenario(SCENARIO), seed=7, demand_scale=scale)


def test_zero_demand_scale_remains_valid(tmp_path):
    run = runner.run_simulation(
        load_scenario(SCENARIO), variant="baseline", seed=7, demand_scale=0,
        output_dir=tmp_path / "zero", capture_frames=False,
    )

    assert run["diagnostics"]["valid"] is True
    assert run["metrics"]["requested"] == 0


def test_export_bundle_rejects_racing_creator_without_overwriting_winner(tmp_path, monkeypatch):
    destination = tmp_path / "replay.html"
    winner = b"winner-owned-bytes"
    original_open = Path.open

    def race_open(path, mode="r", *args, **kwargs):
        if path == destination and ("w" in mode or "x" in mode) and not destination.exists():
            with original_open(destination, "wb") as created:
                created.write(winner)
        return original_open(path, mode, *args, **kwargs)

    monkeypatch.setattr(replay, "_validate_bundle", lambda bundle: None)
    monkeypatch.setattr(Path, "open", race_open)

    with pytest.raises(FileExistsError):
        replay.export_bundle({"minimal": "test-only"}, destination)

    assert destination.read_bytes() == winner
