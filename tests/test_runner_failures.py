"""Runner failure artifacts must retain engine evidence and be plainly invalid."""
from pathlib import Path
import time

import pytest

from traffic_lab import runner
from traffic_lab.schema import load_scenario


SCENARIO = Path("scenarios/synthetic-crossroads/scenario.json")


def test_nonzero_engine_exit_keeps_real_log_and_writes_failed_diagnostic(tmp_path, monkeypatch):
    executable = tmp_path / "failed-sumo"
    executable.write_text("#!/bin/sh\necho deliberate-engine-failure >&2\nexit 7\n")
    executable.chmod(0o755)
    monkeypatch.setattr(runner, "_sumo_binary", lambda: executable)

    with pytest.raises(RuntimeError, match="SUMO run failed"):
        runner.run_simulation(
            load_scenario(SCENARIO),
            variant="baseline",
            seed=7,
            demand_scale=0.03,
            output_dir=tmp_path / "failed",
            whole_run_timeout=3,
        )

    output = tmp_path / "failed"
    assert "deliberate-engine-failure" in (output / "sumo.log").read_text()
    diagnostic = (output / "failed-run.json").read_text()
    assert '"valid": false' in diagnostic


def test_startup_timeout_kills_native_process_group(tmp_path, monkeypatch):
    executable = tmp_path / "hanging-sumo"
    executable.write_text("#!/bin/sh\necho started >&2\nsleep 30\n")
    executable.chmod(0o755)
    monkeypatch.setattr(runner, "_sumo_binary", lambda: executable)

    started = time.monotonic()
    with pytest.raises(RuntimeError, match="whole-run timeout"):
        runner.run_simulation(
            load_scenario(SCENARIO),
            variant="baseline",
            seed=7,
            demand_scale=0.03,
            output_dir=tmp_path / "timed-out",
            whole_run_timeout=0.3,
        )
    assert time.monotonic() - started < 3
    assert "started" in (tmp_path / "timed-out" / "sumo.log").read_text()
    assert '"status": "failed"' in (tmp_path / "timed-out" / "failed-run.json").read_text()


def test_successful_runner_marks_engine_log_warnings_invalid_and_deduplicates(tmp_path, monkeypatch):
    original_tripinfo = runner._tripinfo

    def inject_engine_messages(path):
        result = original_tripinfo(path)
        output = path.parent
        with (output / "sumo.log").open("a", encoding="utf-8") as log:
            log.write("Warning: TLS J has an unassessed timing condition\n")
            log.write("Warning: TLS J has an unassessed timing condition\n")
        with (output / "netconvert.log").open("a", encoding="utf-8") as log:
            log.write("Error: generated network needs review\n")
        return result

    monkeypatch.setattr(runner, "_tripinfo", inject_engine_messages)
    run = runner.run_simulation(
        load_scenario(SCENARIO),
        variant="baseline",
        seed=7,
        demand_scale=0.03,
        output_dir=tmp_path / "engine-messages",
        capture_frames=False,
    )

    assert run["diagnostics"]["valid"] is False
    assert run["diagnostics"]["warnings"] == [
        "sumo.log: Warning: TLS J has an unassessed timing condition",
        "netconvert.log: Error: generated network needs review",
    ]
    assert (tmp_path / "engine-messages" / "sumo.log").read_text().count("unassessed timing condition") == 2
    assert "generated network needs review" in (tmp_path / "engine-messages" / "netconvert.log").read_text()


def test_successful_runner_without_engine_log_warnings_remains_valid(tmp_path):
    run = runner.run_simulation(
        load_scenario(SCENARIO),
        variant="baseline",
        seed=7,
        demand_scale=0.03,
        output_dir=tmp_path / "no-engine-messages",
        capture_frames=False,
    )

    assert run["diagnostics"]["valid"] is True
    assert run["diagnostics"]["warnings"] == []
