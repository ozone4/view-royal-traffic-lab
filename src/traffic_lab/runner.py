"""Bounded real-SUMO execution, engine-ledger accounting, and sampled replay data."""
from __future__ import annotations

from hashlib import sha256
import json
import math
import os
from pathlib import Path
import re
import signal
import subprocess
import time
from typing import Any
import xml.etree.ElementTree as ET
import threading

import sumolib
from sumolib.miscutils import getFreeSocketPort
import traci

from .demand import build_frozen_demand, write_routes
from .network import compile_network

LABEL = "Synthetic demonstration, not calibrated to View Royal"
APPROACHES = ("N", "E", "S", "W")


def _digest(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _sumo_binary() -> Path:
    """Return the wheel's native SUMO executable, never its console-script wrapper."""
    return Path(sumolib.checkBinary("sumo"))


def _engine_version() -> str:
    try:
        result = subprocess.run([str(_sumo_binary()), "--version"], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError(f"SUMO version probe failed: {exc}") from exc
    if result.returncode != 0:
        raise RuntimeError(f"SUMO version probe failed: status {result.returncode}: {result.stderr.strip()}")
    version = next((line.strip() for line in result.stdout.splitlines() if line.strip()), "")
    if not version:
        raise RuntimeError("SUMO version probe failed: empty output")
    return version


def _geometry(network_path: Path) -> dict[str, Any]:
    net = sumolib.net.readNet(str(network_path), withInternal=True)
    lanes = []
    for edge in net.getEdges(withInternal=True):
        for lane in edge.getLanes():
            lanes.append({"id": lane.getID(), "shape": [[round(x, 3), round(y, 3)] for x, y in lane.getShape()], "width": round(lane.getWidth(), 3)})
    junctions = [{"id": node.getID(), "shape": [[round(x, 3), round(y, 3)] for x, y in node.getShape()]} for node in net.getNodes()]
    xs = [point[0] for lane in lanes for point in lane["shape"]]
    ys = [point[1] for lane in lanes for point in lane["shape"]]
    return {"bounds": [min(xs), min(ys), max(xs), max(ys)], "lanes": lanes, "junctions": junctions}


def _tripinfo(path: Path) -> dict[str, dict[str, Any]]:
    """Parse a fully flushed tripinfo file; missing/corrupt output is a failed run."""
    if not path.is_file():
        raise RuntimeError(f"SUMO did not write required tripinfo output: {path}")
    try:
        root = ET.parse(path).getroot()
    except (ET.ParseError, OSError) as exc:
        raise RuntimeError(f"SUMO tripinfo output is malformed: {path}: {exc}") from exc
    records: dict[str, dict[str, float]] = {}
    try:
        for entry in root.findall("tripinfo"):
            vehicle_id = entry.attrib["id"]
            records[vehicle_id] = {
                "duration": float(entry.attrib["duration"]),
                "timeLoss": float(entry.attrib["timeLoss"]),
                "departDelay": float(entry.attrib["departDelay"]),
                "vaporized": entry.attrib.get("vaporized", ""),
            }
    except (KeyError, ValueError) as exc:
        raise RuntimeError(f"SUMO tripinfo output has an invalid trip record: {path}: {exc}") from exc
    return records


def _queues() -> dict[str, int]:
    return {
        approach: sum(
            1
            for vehicle_id in traci.lane.getLastStepVehicleIDs(f"{approach}_in_0")
            if traci.vehicle.getSpeed(vehicle_id) < 0.1
        )
        for approach in APPROACHES
    }


def _frame(now: float, queues: dict[str, int] | None = None) -> dict[str, Any]:
    vehicles = []
    for vehicle_id in traci.vehicle.getIDList():
        x, y = traci.vehicle.getPosition(vehicle_id)
        vehicles.append({"id": vehicle_id, "x": round(x, 3), "y": round(y, 3), "angle": round(traci.vehicle.getAngle(vehicle_id), 3), "speed": round(traci.vehicle.getSpeed(vehicle_id), 3), "approach": vehicle_id.split("-")[0]})
    return {"t": round(now, 3), "vehicles": vehicles, "signals": [{"id": "J", "state": traci.trafficlight.getRedYellowGreenState("J")}], "queues": queues if queues is not None else _queues()}


def _terminate_process_group(process: subprocess.Popen[Any], timeout: float = 2.0) -> None:
    """Bound cleanup even if TraCI is blocked; the native child owns its session."""
    if process.poll() is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait(timeout=timeout)


def _failure_artifact(output: Path, reason: str) -> None:
    (output / "failed-run.json").write_text(json.dumps({
        "status": "failed", "diagnostics": {"valid": False, "warnings": [reason]},
    }, indent=2, sort_keys=True))


def _engine_log_warnings(output: Path) -> list[str]:
    """Return distinct unassessed engine Warning/Error lines from retained logs."""
    warnings: list[str] = []
    seen: set[tuple[str, str]] = set()
    for name in ("sumo.log", "netconvert.log"):
        path = output / name
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for line in lines:
            match = re.search(r"\b(Warning|Error):\s*(.+)", line)
            if not match:
                continue
            message = f"{match.group(1)}: {match.group(2).strip()}"
            key = (name, message)
            if key not in seen:
                seen.add(key)
                warnings.append(f"{name}: {message}")
    return warnings


def _declared_changes(scenario: dict[str, Any], variant: str) -> list[str]:
    phases = scenario["controls"][variant]["phases"]
    greens = '; '.join(f'{name} {phases[index * 3]["duration"]:g} s'
                       for index, name in enumerate(('North', 'East', 'South', 'West')))
    cycle = sum(phase['duration'] for phase in phases)
    details = [f'Protected green time: {greens}. Cycle: {cycle:g} s.']
    if variant == 'constrained':
        details.append('Baseline signal timing; eastbound exit speed reduced to 1 m/s.')
    return details


def run_simulation(scenario: dict[str, Any], *, variant: str, seed: int, demand_scale: float, output_dir: str | Path, capture_frames: bool = True, whole_run_timeout: float = 120) -> dict[str, Any]:
    """Run a fresh output directory. All state and metrics originate from TraCI."""
    if variant not in {"baseline", "rebalanced", "constrained"}:
        raise ValueError("invalid variant")
    if whole_run_timeout <= 0:
        raise ValueError("whole_run_timeout must be positive")
    if not math.isfinite(demand_scale) or demand_scale < 0:
        raise ValueError("demand_scale must be finite non-negative")
    output = Path(output_dir)
    if output.exists():
        raise FileExistsError(f"refusing to overwrite existing output directory: {output}")
    output.mkdir(parents=True)
    demand = build_frozen_demand(scenario, seed=seed, demand_scale=demand_scale)
    routes = write_routes(demand, output / "demand.rou.xml")
    network = compile_network(scenario, output, variant=variant)
    tripinfo_path = output / "tripinfo.xml"
    params = {"variant": variant, "seed": seed, "demand_scale": demand_scale, "horizon_seconds": scenario["horizon_seconds"], "step_seconds": scenario["step_seconds"]}
    (output / "params.json").write_text(json.dumps(params, indent=2, sort_keys=True))
    command = [str(_sumo_binary()), "--net-file", str(network), "--route-files", str(routes), "--step-length", str(scenario["step_seconds"]), "--end", str(scenario["horizon_seconds"]), "--seed", str(seed), "--tripinfo-output", str(tripinfo_path), "--time-to-teleport", "-1", "--collision.action", "warn"]
    (output / "sumo-command.json").write_text(json.dumps(command, indent=2))

    requested = {request.id for request in demand.requests if request.depart <= scenario["horizon_seconds"]}
    requests_by_id = {request.id: request for request in demand.requests}
    frames: list[dict[str, Any]] = []
    departed: set[str] = set()
    arrived: set[str] = set()
    departed_at: dict[str, float] = {}
    depart_delays: dict[str, float] = {}
    active_at_horizon: set[str] = set()
    raw_trips: dict[str, dict[str, Any]] = {}
    engine_version = ""
    maxima = {approach: 0 for approach in APPROACHES}
    global_max_stopped = 0
    teleports = collisions = 0
    deadline = time.monotonic() + whole_run_timeout
    process: subprocess.Popen[Any] | None = None
    connected = False
    watchdog_stop = threading.Event()
    timed_out = threading.Event()
    log = (output / "sumo.log").open("w", encoding="utf-8")
    cleanup_lock = threading.Lock()
    cleanup_failures: list[str] = []
    watcher: threading.Thread | None = None

    def terminate_child() -> None:
        # The timeout thread and finalizer can arrive together. Only one may
        # signal/reap this process group, and its errors belong in run diagnostics.
        with cleanup_lock:
            if process is not None:
                try:
                    _terminate_process_group(process)
                except Exception as exc:
                    cleanup_failures.append(f"SUMO process cleanup failed: {exc}")

    def remaining() -> float:
        return deadline - time.monotonic()

    def enforce_deadline() -> None:
        if timed_out.is_set() or remaining() <= 0:
            raise TimeoutError(f"SUMO whole-run timeout after {whole_run_timeout}s")

    def close_connection() -> None:
        nonlocal connected
        if not connected:
            return
        try:
            connection = traci.getConnection("traffic-lab")
            connection._socket.settimeout(max(0.05, min(2.0, max(remaining(), 0.05))))
            traci.close(False)
        finally:
            connected = False

    try:
        port = getFreeSocketPort()
        process = subprocess.Popen(command + ["--remote-port", str(port)], stdout=log, stderr=subprocess.STDOUT, start_new_session=True)

        def watchdog() -> None:
            if not watchdog_stop.wait(max(0.0, remaining())):
                timed_out.set()
                terminate_child()

        watcher = threading.Thread(target=watchdog, name="sumo-timeout", daemon=True)
        watcher.start()
        # Connecting ourselves keeps the native process handle available for bounded cleanup.
        while True:
            enforce_deadline()
            if process.poll() is not None:
                raise RuntimeError(f"SUMO exited before TraCI was ready with status {process.returncode}")
            try:
                traci.init(port, numRetries=0, label="traffic-lab", proc=process)
                connected = True
                traci.getConnection("traffic-lab")._socket.settimeout(max(0.05, min(2.0, remaining())))
                break
            except Exception:
                if process.poll() is not None:
                    raise RuntimeError(f"SUMO exited before TraCI was ready with status {process.returncode}")
                time.sleep(min(0.05, max(0.0, remaining())))

        next_frame = 0.0
        while traci.simulation.getTime() < scenario["horizon_seconds"]:
            enforce_deadline()
            traci.simulationStep()  # Deliberately global: controller tests observe/patch this boundary.
            enforce_deadline()
            now = traci.simulation.getTime()
            departed_now = set(traci.simulation.getDepartedIDList())
            departed.update(departed_now)
            for vehicle_id in departed_now & requested:
                try:
                    # An event is observed after the step, but SUMO's actual
                    # departure can precede that observation by one step.
                    # Query the vehicle instead of substituting the observation clock.
                    departed_at[vehicle_id] = traci.vehicle.getDeparture(vehicle_id)
                    depart_delays[vehicle_id] = traci.vehicle.getDepartDelay(vehicle_id)
                except Exception:
                    # A removed event vehicle remains inserted; unavailable engine
                    # timestamps/delays stay unknown rather than being invented.
                    pass
            arrived.update(traci.simulation.getArrivedIDList())
            teleports += len(traci.simulation.getStartingTeleportIDList()) + len(traci.simulation.getEndingTeleportIDList())
            collisions += traci.simulation.getCollidingVehiclesNumber()
            queues = _queues()
            for approach, count in queues.items():
                maxima[approach] = max(maxima[approach], count)
            global_max_stopped = max(global_max_stopped, sum(queues.values()))
            if capture_frames and now + 1e-9 >= next_frame:
                frames.append(_frame(now, queues))
                next_frame += scenario["frame_interval_seconds"]

        # This must be read while the engine is still open; event sets cannot identify removal.
        active_at_horizon = set(traci.vehicle.getIDList()) & requested
        if capture_frames and (not frames or frames[-1]["t"] != scenario["horizon_seconds"]):
            frames.append(_frame(scenario["horizon_seconds"], _queues()))
        close_connection()
        enforce_deadline()
        process.wait(timeout=max(0.05, min(2.0, remaining())))
        if process.returncode != 0:
            raise RuntimeError(f"SUMO exited with status {process.returncode}")
        raw_trips = _tripinfo(tripinfo_path)
        engine_version = _engine_version()
    except Exception as exc:
        failure = str(exc)
    else:
        failure = None
    finally:
        watchdog_stop.set()
        if connected:
            try:
                close_connection()
            except Exception as exc:
                failure = failure or f"TraCI cleanup failed: {exc}"
        terminate_child()
        if watcher is not None:
            watcher.join(timeout=5.0)
            if watcher.is_alive():
                cleanup_failures.append("SUMO watchdog did not stop within its cleanup bound")
        log.close()
    if cleanup_failures:
        failure = "; ".join(([failure] if failure else []) + cleanup_failures)

    if failure:
        _failure_artifact(output, failure)
        raise RuntimeError(f"SUMO run failed: {failure}")

    engine_warnings = _engine_log_warnings(output)
    completed = {vehicle_id for vehicle_id in arrived & requested if not raw_trips.get(vehicle_id, {}).get("vaporized")}
    if completed - raw_trips.keys():
        missing = sorted(completed - raw_trips.keys())
        _failure_artifact(output, f"tripinfo.xml omitted completed vehicles: {missing[:3]}")
        raise RuntimeError("SUMO run failed: tripinfo.xml omitted completed vehicles")
    active = active_at_horizon
    neverinserted = requested - departed
    removed = (departed & requested) - completed - active
    unexpected_removals = len(removed)
    per_approach: dict[str, dict[str, int]] = {}
    for approach in APPROACHES:
        relevant = {request.id for request in demand.requests if request.approach == approach and request.depart <= scenario["horizon_seconds"]}
        per_approach[approach] = {
            "requested": len(relevant), "completed": len(relevant & completed), "active": len(relevant & active),
            "not_inserted": len(relevant & neverinserted), "removed": len(relevant & removed),
            "max_stopped_vehicles": maxima[approach],
        }
    trips = [raw_trips[vehicle_id] for vehicle_id in completed]
    mean = lambda key: round(sum(trip[key] for trip in trips) / len(trips), 4) if trips else None
    missing_depart_delays = (departed & requested) - depart_delays.keys()
    inserted_delays = [depart_delays[vehicle_id] for vehicle_id in departed & requested if vehicle_id in depart_delays]
    metrics = {
        "requested": len(requested), "inserted": len(completed) + len(active) + len(removed), "completed": len(completed),
        "active": len(active), "not_inserted": len(neverinserted), "removed": len(removed),
        "outside_horizon": len(demand.requests) - len(requested), "completed_mean_time_loss_seconds": mean("timeLoss"),
        "completed_mean_duration_seconds": mean("duration"),
        "inserted_mean_depart_delay_seconds": round(sum(inserted_delays) / len(inserted_delays), 4) if inserted_delays and not missing_depart_delays else None,
        "max_stopped_vehicles": global_max_stopped, "per_approach": per_approach,
        "definitions": {
            "completed_mean_time_loss_seconds": "SUMO completed-trip timeLoss; not control delay.",
            "inserted_mean_depart_delay_seconds": "Mean TraCI departDelay at every actual insertion, including vehicles active at the horizon; never-inserted requests are censored.",
            "max_stopped_vehicles": "Maximum, over every simulation step, of the simultaneous total stopped vehicles across all inbound lanes (speed below 0.1 m/s).",
            "per_approach.max_stopped_vehicles": "Maximum, over every simulation step, of stopped vehicles on that approach's inbound lane (speed below 0.1 m/s).",
        },
    }
    ledger = {}
    for vehicle_id, request in requests_by_id.items():
        status = "completed" if vehicle_id in completed else "active" if vehicle_id in active else "removed" if vehicle_id in removed else "not_inserted"
        ledger[vehicle_id] = {
            "approach": request.approach, "planned_depart": request.depart, "actual_depart": departed_at.get(vehicle_id),
            "depart_delay_seconds": depart_delays.get(vehicle_id), "status": status,
            "censored_insertion_wait_seconds": max(0.0, scenario["horizon_seconds"] - request.depart) if status == "not_inserted" else None,
        }
    (output / "vehicle-ledger.json").write_text(json.dumps(ledger, indent=2, sort_keys=True))
    warnings = []
    if neverinserted:
        warnings.append(f"{len(neverinserted)} requested vehicles were never inserted by horizon and remain censored.")
    if removed:
        warnings.append(f"{len(removed)} inserted vehicles disappeared before the horizon without a recorded arrival.")
    if missing_depart_delays:
        warnings.append(f"Could not read departure delay for {len(missing_depart_delays)} inserted vehicle(s); insertion-delay mean is unavailable.")
    warnings.extend(engine_warnings)
    diagnostics = {"valid": not (collisions or teleports or unexpected_removals or missing_depart_delays or engine_warnings), "collisions": collisions, "teleports": teleports, "unexpected_removals": unexpected_removals, "warnings": warnings}
    evidence = scenario["evidence"]
    run = {"schema_version": 1, "run_id": f"{variant}-seed{seed}-scale{demand_scale:g}", "variant": variant, "title": scenario["title"], "label": LABEL, "changes": _declared_changes(scenario, variant), "limitations": ["Synthetic demonstration only; not calibrated to View Royal.", "Vehicle mode is passenger only; results do not establish safety."], "metadata": {"engine_version": engine_version, "seed": seed, "demand_scale": demand_scale, "demand_sha256": demand.sha256, "network_sha256": _digest(network), "scenario_sha256": sha256(json.dumps(scenario, sort_keys=True).encode()).hexdigest(), "horizon_seconds": scenario["horizon_seconds"], "step_seconds": scenario["step_seconds"], "warmup_seconds": scenario["warmup_seconds"], "arrival_window_seconds": scenario["arrival_window_seconds"], "frame_interval_seconds": scenario["frame_interval_seconds"], **evidence, "modes": scenario["modes"], "units": scenario["units"]}, "geometry": _geometry(network), "frames": frames, "metrics": metrics, "diagnostics": diagnostics}
    (output / "run.json").write_text(json.dumps(run, indent=2, sort_keys=True))
    return run
