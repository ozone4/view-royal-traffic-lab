"""Generate and compile a small explicit four-approach SUMO network."""
from __future__ import annotations

from pathlib import Path
import subprocess
import sys
from typing import Any


NODES = """<nodes>
  <node id="N" x="0" y="250"/><node id="E" x="250" y="0"/>
  <node id="S" x="0" y="-250"/><node id="W" x="-250" y="0"/>
  <node id="J" x="0" y="0" type="traffic_light"/>
</nodes>\n"""
def _edges(variant: str) -> str:
    # The constrained variant changes physical receiving capacity: eastbound exit is 1 m/s.
    east_speed = "1.00" if variant == "constrained" else "13.89"
    return f'''<edges>
  <edge id="N_in" from="N" to="J" speed="13.89" numLanes="1"/><edge id="N_out" from="J" to="N" speed="13.89" numLanes="1"/>
  <edge id="E_in" from="E" to="J" speed="13.89" numLanes="1"/><edge id="E_out" from="J" to="E" speed="{east_speed}" numLanes="1"/>
  <edge id="S_in" from="S" to="J" speed="13.89" numLanes="1"/><edge id="S_out" from="J" to="S" speed="13.89" numLanes="1"/>
  <edge id="W_in" from="W" to="J" speed="13.89" numLanes="1"/><edge id="W_out" from="J" to="W" speed="13.89" numLanes="1"/>
</edges>\n'''
CONNECTIONS = """<connections>
  <connection from="N_in" to="W_out" fromLane="0" toLane="0" tl="J" linkIndex="0"/><connection from="N_in" to="S_out" fromLane="0" toLane="0" tl="J" linkIndex="1"/><connection from="N_in" to="E_out" fromLane="0" toLane="0" tl="J" linkIndex="2"/>
  <connection from="E_in" to="N_out" fromLane="0" toLane="0" tl="J" linkIndex="3"/><connection from="E_in" to="W_out" fromLane="0" toLane="0" tl="J" linkIndex="4"/><connection from="E_in" to="S_out" fromLane="0" toLane="0" tl="J" linkIndex="5"/>
  <connection from="S_in" to="E_out" fromLane="0" toLane="0" tl="J" linkIndex="6"/><connection from="S_in" to="N_out" fromLane="0" toLane="0" tl="J" linkIndex="7"/><connection from="S_in" to="W_out" fromLane="0" toLane="0" tl="J" linkIndex="8"/>
  <connection from="W_in" to="S_out" fromLane="0" toLane="0" tl="J" linkIndex="9"/><connection from="W_in" to="E_out" fromLane="0" toLane="0" tl="J" linkIndex="10"/><connection from="W_in" to="N_out" fromLane="0" toLane="0" tl="J" linkIndex="11"/>
</connections>\n"""


def _tls(scenario: dict[str, Any]) -> str:
    phases = scenario["controls"][scenario.get("_variant", "baseline")]["phases"]
    lines = [f'  <phase duration="{phase["duration"]}" state="{phase["state"]}"/>' for phase in phases]
    return '<additional>\n<tlLogic id="J" type="static" programID="0" offset="0">\n' + "\n".join(lines) + "\n</tlLogic>\n</additional>\n"


def network_input_files(directory: str | Path) -> list[Path]:
    root = Path(directory)
    return [root / name for name in ("nodes.nod.xml", "edges.edg.xml", "connections.con.xml", "tls.tll.xml")]


def compile_network(scenario: dict[str, Any], output_dir: str | Path, *, variant: str = "baseline", source_dir: str | Path | None = None, timeout: int = 30) -> Path:
    """Compile XML with isolated netconvert; warnings are retained in ``netconvert.log``."""
    if variant not in {"baseline", "rebalanced", "constrained"}:
        raise ValueError(f"unsupported fixed-network variant: {variant}")
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    source = Path(source_dir) if source_dir is not None else output
    if source_dir is None:
        document = dict(scenario)
        document["_variant"] = variant
        for path, content in zip(network_input_files(output), (NODES, _edges(variant), CONNECTIONS, _tls(document))):
            path.write_text(content)
    files = network_input_files(source)
    destination = output / "network.net.xml"
    command = [
        str(Path(sys.executable).parent / "netconvert"), "--node-files", str(files[0]), "--edge-files", str(files[1]),
        "--connection-files", str(files[2]), "--tllogic-files", str(files[3]), "--output-file", str(destination),
        "--no-turnarounds", "true",
    ]
    try:
        completed = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError(f"netconvert failed: {exc}") from exc
    (output / "netconvert.log").write_text(completed.stdout + completed.stderr)
    if completed.returncode != 0 or not destination.is_file():
        raise RuntimeError(f"netconvert failed ({completed.returncode}): {completed.stderr.strip()}")
    return destination
