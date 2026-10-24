import subprocess
import sys
from pathlib import Path

from traffic_lab.network import compile_network, network_input_files
from traffic_lab.schema import load_scenario


SCENARIO_PATH = Path("scenarios/synthetic-crossroads/scenario.json")


def test_network_sources_compile_and_expose_all_legal_turns(tmp_path):
    scenario = load_scenario(SCENARIO_PATH)
    output = compile_network(scenario, tmp_path)
    assert output.is_file()
    text = output.read_text()
    assert '<tlLogic id="J"' in text
    for route in scenario["legal_routes"]:
        start, end = route.split("_")[0], route.split("_")[-2]
        assert start in text and end in text
    assert {p.name for p in network_input_files(tmp_path)} >= {"nodes.nod.xml", "edges.edg.xml", "connections.con.xml", "tls.tll.xml"}


def test_network_compiler_rejects_an_unsupported_fixed_variant(tmp_path):
    scenario = load_scenario(SCENARIO_PATH)
    try:
        compile_network(scenario, tmp_path, variant="custom")
    except ValueError as error:
        assert "variant" in str(error)
    else:
        raise AssertionError("unsupported fixed-network variants must not be ignored")


def test_network_compiler_fails_loudly_on_malformed_source(tmp_path):
    (tmp_path / "nodes.nod.xml").write_text("<nodes>")
    try:
        compile_network({}, tmp_path, source_dir=tmp_path)
    except RuntimeError as error:
        assert "netconvert" in str(error)
    else:
        raise AssertionError("malformed XML must not be accepted")
