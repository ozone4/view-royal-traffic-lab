"""Strict parsing for the deliberately fixed, synthetic M1 scenario."""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any


class ScenarioError(ValueError):
    pass


APPROACHES = ("N", "E", "S", "W")
VARIANTS = ("baseline", "rebalanced", "constrained")
LANE_LENGTH_METRES = 250.0
EXPECTED_EVIDENCE = {
    "geometry_status": "synthetic",
    "demand_status": "synthetic_frozen",
    "control_status": "synthetic",
    "model_status": "demonstration_only",
}
# These IDs, rates, and routes are the frozen passenger demand definition.  The
# origin is outside the junction, so its heading is toward the centre: N-left
# therefore exits east, while N-right exits west.
EXPECTED_MOVEMENTS = (
    ("N-left", "N", "N_in_E_out", 240.0),
    ("N-through", "N", "N_in_S_out", 480.0),
    ("N-right", "N", "N_in_W_out", 180.0),
    ("E-left", "E", "E_in_S_out", 300.0),
    ("E-through", "E", "E_in_W_out", 600.0),
    ("E-right", "E", "E_in_N_out", 180.0),
    ("S-left", "S", "S_in_W_out", 240.0),
    ("S-through", "S", "S_in_N_out", 480.0),
    ("S-right", "S", "S_in_E_out", 180.0),
    ("W-left", "W", "W_in_N_out", 300.0),
    ("W-through", "W", "W_in_E_out", 600.0),
    ("W-right", "W", "W_in_S_out", 180.0),
)
EXPECTED_ROUTES = {route for _, _, route, _ in EXPECTED_MOVEMENTS}


def _finite_number(value: Any, name: str, *, positive: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ScenarioError(f"{name} must be a finite {'positive ' if positive else ''}number")
    numeric = float(value)
    if positive and numeric <= 0:
        raise ScenarioError(f"{name} must be a finite positive number")
    return numeric


def _aligned(value: float, step: float, name: str) -> None:
    if not math.isclose(value / step, round(value / step), rel_tol=0, abs_tol=1e-9):
        raise ScenarioError(f"{name} must align with step_seconds")


def _state(approach_index: int, signal: str) -> str:
    return "r" * (approach_index * 3) + signal * 3 + "r" * (9 - approach_index * 3)


def _validate_timing(raw: dict[str, Any]) -> tuple[float, float, float, float]:
    horizon = _finite_number(raw.get("horizon_seconds"), "horizon_seconds", positive=True)
    step = _finite_number(raw.get("step_seconds"), "step_seconds", positive=True)
    arrivals = _finite_number(raw.get("arrival_window_seconds"), "arrival_window_seconds", positive=True)
    frames = _finite_number(raw.get("frame_interval_seconds"), "frame_interval_seconds", positive=True)
    if raw.get("warmup_seconds") != 0 or isinstance(raw.get("warmup_seconds"), bool):
        raise ScenarioError("warmup_seconds must be exactly 0 for the fixed network")
    if arrivals > horizon:
        raise ScenarioError("arrival_window_seconds must not exceed horizon_seconds")
    for value, name in ((horizon, "horizon_seconds"), (arrivals, "arrival_window_seconds"), (frames, "frame_interval_seconds")):
        _aligned(value, step, name)
    return horizon, step, arrivals, frames


def _validate_lanes(lanes: Any) -> None:
    if not isinstance(lanes, dict) or set(lanes) != set(APPROACHES):
        raise ScenarioError("lanes must exactly define the four fixed approaches")
    for approach in APPROACHES:
        lane = lanes[approach]
        if not isinstance(lane, dict) or set(lane) != {"edge", "length"}:
            raise ScenarioError("lane definition is unsupported")
        if lane["edge"] != f"{approach}_in":
            raise ScenarioError("lane edge must match the fixed network")
        length = _finite_number(lane["length"], "lane length", positive=True)
        if length != LANE_LENGTH_METRES:
            raise ScenarioError("lane length must be 250 metres in the fixed network")


def _validate_movements(raw: dict[str, Any]) -> None:
    movements = raw.get("movements")
    if not isinstance(movements, list) or len(movements) != len(EXPECTED_MOVEMENTS):
        raise ScenarioError("movements must exactly define frozen demand")
    ids = [movement.get("id") for movement in movements if isinstance(movement, dict)]
    if len(ids) != len(set(ids)):
        raise ScenarioError("duplicate movement id")
    for movement, expected in zip(movements, EXPECTED_MOVEMENTS):
        movement_id, approach, route, rate = expected
        if not isinstance(movement, dict) or set(movement) != {"id", "approach", "lanes", "route", "rate_per_hour"}:
            raise ScenarioError("movement definition is unsupported")
        if movement.get("id") != movement_id:
            raise ScenarioError("movement id must match frozen demand")
        if movement.get("approach") != approach:
            raise ScenarioError("movement approach must match its fixed route")
        if movement.get("lanes") != [approach]:
            raise ScenarioError("movement lane reference is invalid")
        if movement.get("route") != route:
            raise ScenarioError("movement route must match frozen demand")
        if _finite_number(movement.get("rate_per_hour"), "movement rate_per_hour") != rate:
            raise ScenarioError("movement rate_per_hour must match frozen demand")
    if raw.get("legal_routes") != [movement[2] for movement in EXPECTED_MOVEMENTS]:
        raise ScenarioError("legal_routes must exactly enumerate frozen movement routes")


def _validate_phases(variant: str, control: Any) -> list[float]:
    if not isinstance(control, dict) or set(control) != {"phases"}:
        raise ScenarioError(f"control {variant} is unsupported")
    phases = control.get("phases")
    if not isinstance(phases, list) or len(phases) != 12:
        raise ScenarioError(f"control {variant} needs protected green and clearance phases")
    durations: list[float] = []
    for index, approach in enumerate(APPROACHES):
        green, yellow, all_red = phases[index * 3 : index * 3 + 3]
        expected_green = _state(index, "G")
        expected_yellow = _state(index, "y")
        if not all(isinstance(phase, dict) for phase in (green, yellow, all_red)):
            raise ScenarioError("invalid control phase")
        phase_durations = [
            _finite_number(phase.get("duration"), "clearance duration", positive=True)
            for phase in (green, yellow, all_red)
        ]
        if not isinstance(green, dict) or set(green) != {"approach", "state", "duration"}:
            raise ScenarioError("invalid control phase")
        if green.get("approach") != approach or green.get("state") != expected_green:
            raise ScenarioError("invalid conflicts: green phase must protect its one fixed approach")
        if not isinstance(yellow, dict) or set(yellow) != {"state", "duration"} or yellow.get("state") != expected_yellow:
            raise ScenarioError("control phase must provide matching yellow clearance")
        if not isinstance(all_red, dict) or set(all_red) != {"state", "duration"} or all_red.get("state") != "r" * 12:
            raise ScenarioError("control phase must provide all-red clearance")
        durations.extend(phase_durations)
    return durations


def _validate_controls(raw: dict[str, Any]) -> None:
    controls = raw.get("controls")
    if not isinstance(controls, dict) or set(controls) != set(VARIANTS):
        raise ScenarioError("controls must define baseline, rebalanced, constrained")
    timings = {variant: _validate_phases(variant, controls[variant]) for variant in VARIANTS}
    cycles = {variant: sum(durations) for variant, durations in timings.items()}
    if not all(math.isclose(cycles["baseline"], cycles[variant], rel_tol=0, abs_tol=1e-9) for variant in VARIANTS[1:]):
        raise ScenarioError("all variants must have identical cycle length")
    if timings["constrained"] != timings["baseline"]:
        raise ScenarioError("constrained timing must match baseline")
    # Rebalancing can change the protected green allocations only; clearance is
    # part of the fixed safety model and must remain identical.
    for index in range(1, 12, 3):
        if timings["rebalanced"][index : index + 2] != timings["baseline"][index : index + 2]:
            raise ScenarioError("rebalanced clearance timing must match baseline")
    for variant in VARIANTS:
        controls[variant]["cycle_seconds"] = cycles[variant]


def load_scenario(path: str | Path) -> dict[str, Any]:
    """Load only the explicit synthetic M1 configuration the builders support."""
    try:
        raw = json.loads(Path(path).read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise ScenarioError(f"cannot parse scenario: {exc}") from exc
    if not isinstance(raw, dict) or raw.get("schema_version") != 1:
        raise ScenarioError("schema_version must be 1")
    required_keys = {
        "schema_version", "title", "label", "horizon_seconds", "step_seconds", "warmup_seconds",
        "arrival_window_seconds", "frame_interval_seconds", "modes", "units", "evidence", "lanes",
        "movements", "legal_routes", "controls",
    }
    if set(raw) != required_keys:
        raise ScenarioError("scenario contains unsupported settings")
    _validate_timing(raw)
    if raw.get("modes") != ["passenger"]:
        raise ScenarioError("modes must be exactly passenger")
    if raw.get("units") != "metres, seconds, metres/second":
        raise ScenarioError("units must match the fixed network")
    if raw.get("evidence") != EXPECTED_EVIDENCE:
        raise ScenarioError("evidence geometry_status/demand_status/control_status/model_status must match the synthetic sandbox")
    _validate_lanes(raw.get("lanes"))
    _validate_movements(raw)
    _validate_controls(raw)
    return raw
