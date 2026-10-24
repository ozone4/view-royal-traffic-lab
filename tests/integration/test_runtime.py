import pathlib
import subprocess
import sys
import pytest
import xml.etree.ElementTree as ET

# Cold macOS startup exceeded the old 20-second probe once. Keep a bounded,
# explicit startup allowance and fail on timeout; never retry into a green test.
RUNTIME_STARTUP_TIMEOUT = 60


def test_installed_cli_entrypoint():
    executable = pathlib.Path(sys.executable).parent / "traffic-lab"
    assert executable.is_file(), f"Missing installed CLI: {executable}"
    result = subprocess.run([str(executable), "--help"], capture_output=True,
                            text=True, timeout=RUNTIME_STARTUP_TIMEOUT)
    assert result.returncode == 0, result.stderr
    assert "{run,demo,study,export}" in result.stdout


@pytest.mark.parametrize("name", ["sumo", "netconvert"])
def test_pinned_runtime_available(name):
    executable = pathlib.Path(sys.executable).parent / name
    assert executable.is_file(), f"Missing isolated runtime: {executable}"
    result = subprocess.run([str(executable), "--version"], capture_output=True, text=True, timeout=RUNTIME_STARTUP_TIMEOUT)
    assert result.returncode == 0, result.stderr
    assert "1.28.0" in result.stdout


def test_real_minimal_simulation(tmp_path):
    binary = pathlib.Path(sys.executable).parent
    (tmp_path / "nodes.xml").write_text('<nodes><node id="a" x="0" y="0"/><node id="b" x="200" y="0"/></nodes>')
    (tmp_path / "edges.xml").write_text('<edges><edge id="ab" from="a" to="b" speed="13.9" numLanes="1"/></edges>')
    result = subprocess.run([str(binary / "netconvert"), "--node-files", str(tmp_path / "nodes.xml"), "--edge-files", str(tmp_path / "edges.xml"), "--output-file", str(tmp_path / "network.xml")], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    (tmp_path / "routes.xml").write_text('<routes><vehicle id="proof" depart="0"><route edges="ab"/></vehicle></routes>')
    result = subprocess.run([str(binary / "sumo"), "--net-file", str(tmp_path / "network.xml"), "--route-files", str(tmp_path / "routes.xml"), "--end", "60", "--seed", "42", "--tripinfo-output", str(tmp_path / "trips.xml"), "--time-to-teleport", "-1"], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    trip = ET.parse(tmp_path / "trips.xml").getroot().find("tripinfo")
    assert trip is not None and trip.attrib["id"] == "proof"
    assert float(trip.attrib["arrival"]) > 0
