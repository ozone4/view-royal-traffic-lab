"""Comparison must fail closed on missing or unmatched provenance."""
from copy import deepcopy
import pytest
from traffic_lab.compare import assert_comparable, ComparisonError


def run(variant='baseline'):
    return {'variant':variant,'changes':['Explicit fixture change'],
            'metadata':{'seed':42,'demand_sha256':'demand','scenario_sha256':'scenario',
                        'network_sha256':variant,'engine_version':'TEST FIXTURE',
                        'horizon_seconds':180,'step_seconds':.5,'warmup_seconds':0,
                        'frame_interval_seconds':2,'arrival_window_seconds':100,
                        'demand_scale':1,'modes':['passenger'],'units':'m,s',
                        'geometry_status':'synthetic','demand_status':'synthetic',
                        'control_status':'synthetic','model_status':'demonstration_only'},
            'diagnostics':{'valid':True,'collisions':0,'teleports':0,'unexpected_removals':0}}


@pytest.mark.parametrize('key', ['seed','demand_sha256','scenario_sha256','engine_version','frame_interval_seconds','arrival_window_seconds','modes','units'])
def test_missing_matched_field_on_both_runs_is_rejected(key):
    a,b=run(),run('rebalanced')
    del a['metadata'][key]; del b['metadata'][key]
    with pytest.raises(ComparisonError,match=key):
        assert_comparable([a,b])


@pytest.mark.parametrize('key,value', [('scenario_sha256','other'),('frame_interval_seconds',3),('arrival_window_seconds',150),('modes',['bus']),('units','feet'),('demand_scale',1.3)])
def test_additional_provenance_mismatches_are_rejected(key,value):
    a,b=run(),run('rebalanced'); b['metadata'][key]=value
    with pytest.raises(ComparisonError,match=key):
        assert_comparable([a,b])


def test_invalid_single_run_cannot_bypass_diagnostics():
    a=run(); a['diagnostics']['valid']=False
    with pytest.raises(ComparisonError,match='diagnostics'):
        assert_comparable([a])


def test_valid_declared_network_change_is_allowed():
    assert_comparable([run(),run('rebalanced'),run('constrained')])


def test_network_change_requires_a_declared_change():
    a,b=run(),run('constrained'); b['changes']=[]
    with pytest.raises(ComparisonError,match='declared'):
        assert_comparable([a,b])
