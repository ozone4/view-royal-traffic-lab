"""Adversarial synthetic exporter fixtures, never simulation evidence."""
import pytest
from traffic_lab.replay import export_bundle
from test_replay import synthetic_run, synthetic_bundle

COUNTS = ('requested', 'completed', 'active', 'not_inserted', 'removed')
MEANS = ('completed_mean_time_loss_seconds', 'completed_mean_duration_seconds', 'inserted_mean_depart_delay_seconds')


def balanced_fixture():
    run = synthetic_run()
    for key in COUNTS:
        run['metrics']['per_approach']['N'][key] = run['metrics'][key]
    return run


def test_removed_vehicle_cannot_be_hidden_by_valid_diagnostic_flag(tmp_path):
    run = balanced_fixture()
    m = run['metrics']
    m.update(completed=0, removed=1, completed_mean_time_loss_seconds=None, completed_mean_duration_seconds=None)
    m['per_approach']['N'].update(completed=0, removed=1)
    with pytest.raises(ValueError):
        export_bundle(synthetic_bundle(run), tmp_path/'hidden-removal.html')


@pytest.mark.parametrize('field', COUNTS)
def test_approach_counts_must_reconcile_with_global_counts(tmp_path, field):
    run = balanced_fixture()
    run['metrics']['per_approach']['N'][field] += 1
    with pytest.raises(ValueError):
        export_bundle(synthetic_bundle(run), tmp_path/'bad-approach.html')


@pytest.mark.parametrize('field', MEANS)
def test_empty_cohort_cannot_have_a_numeric_mean(tmp_path, field):
    run = balanced_fixture()
    m = run['metrics']
    for key, value in m.items():
        if isinstance(value, (int, float)):
            m[key] = None if key in MEANS else 0
    for direction in m['per_approach'].values():
        for key in direction:
            direction[key] = 0
    m[field] = 5.0
    with pytest.raises(ValueError):
        export_bundle(synthetic_bundle(run), tmp_path/'empty-cohort-mean.html')
