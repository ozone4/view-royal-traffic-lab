"""Regression for concurrent watchdog/finalizer process-group cleanup."""
from pathlib import Path
import threading
import time
import pytest
from traffic_lab import runner
from traffic_lab.schema import load_scenario


def test_watchdog_and_finalizer_serialize_cleanup_and_join(tmp_path, monkeypatch):
    executable = tmp_path / 'hanging-sumo'
    executable.write_text('#!/bin/sh\nsleep 30\n')
    executable.chmod(0o755)
    monkeypatch.setattr(runner, '_sumo_binary', lambda: executable)
    original = runner._terminate_process_group
    state = {'active': 0, 'peak': 0}
    lock = threading.Lock()
    watchers = []

    def observed_cleanup(process, timeout=2.0):
        with lock:
            state['active'] += 1
            state['peak'] = max(state['peak'], state['active'])
            if threading.current_thread().name == 'sumo-timeout':
                watchers.append(threading.current_thread())
        try:
            # Widen the observed race deterministically, without inventing engine results.
            time.sleep(.08)
            original(process, timeout)
        finally:
            with lock:
                state['active'] -= 1

    monkeypatch.setattr(runner, '_terminate_process_group', observed_cleanup)
    with pytest.raises(RuntimeError, match='whole-run timeout'):
        runner.run_simulation(load_scenario(Path('scenarios/synthetic-crossroads/scenario.json')),
                              variant='baseline', seed=7, demand_scale=0,
                              output_dir=tmp_path/'run', whole_run_timeout=.15)
    assert state['peak'] == 1, 'watchdog and finalizer must not signal/reap the same child concurrently'
    assert not any(w.is_alive() for w in watchers), 'no watchdog may outlive its run'
