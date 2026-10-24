"""Self-contained Canvas replay export for Traffic Lab engine-frame bundles.

The viewer deliberately replays exported frame samples only.  It performs no
trajectory construction and keeps the engine-produced metrics verbatim.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from .compare import assert_comparable


SCHEMA_VERSION = 1
SYNTHETIC_LABEL = "Synthetic demonstration, not calibrated to View Royal"
_REQUIRED_METADATA = (
    "engine_version", "seed", "demand_scale", "demand_sha256", "network_sha256",
    "scenario_sha256", "horizon_seconds", "step_seconds", "warmup_seconds",
    "arrival_window_seconds", "frame_interval_seconds", "geometry_status",
    "demand_status", "control_status", "model_status", "modes", "units",
)
_REQUIRED_METRICS = (
    "requested", "inserted", "completed", "active", "not_inserted", "removed",
    "outside_horizon", "completed_mean_time_loss_seconds",
    "completed_mean_duration_seconds", "inserted_mean_depart_delay_seconds",
    "max_stopped_vehicles", "per_approach", "definitions",
)
_DIRECTIONS = ("N", "E", "S", "W")


def export_bundle(bundle: dict, output: Path) -> Path:
    """Validate *bundle* then write one HTML file containing the replay data.

    The template is intentionally read from the source checkout's ``viewer``
    directory.  Packaging it into a wheel needs package-data configuration in
    the owning build configuration; this module raises a clear error if that
    source template is not present.
    """
    _validate_bundle(bundle)
    destination = Path(output)
    template_path = Path(__file__).resolve().parents[2] / "viewer" / "replay.html"
    if not template_path.is_file():
        raise FileNotFoundError(
            f"Replay template is unavailable at {template_path}. "
            "Source-checkout export requires viewer/replay.html."
        )
    encoded = json.dumps(bundle, ensure_ascii=False, separators=(",", ":"))
    # JSON in a script element must not be able to close that element.  These
    # replacements keep JSON semantics while preventing HTML parsing as markup.
    safe_json = (encoded.replace("<", "\\u003c")
                        .replace(">", "\\u003e")
                        .replace("&", "\\u0026")
                        .replace("\u2028", "\\u2028")
                        .replace("\u2029", "\\u2029"))
    document = template_path.read_text(encoding="utf-8")
    marker = "__TRAFFIC_LAB_BUNDLE_JSON__"
    if document.count(marker) != 1:
        raise RuntimeError("Replay template must contain exactly one data marker")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("x", encoding="utf-8") as exported:
        exported.write(document.replace(marker, safe_json))
    return destination


def _validate_bundle(bundle: Any) -> None:
    _require_mapping(bundle, "bundle")
    _require_equal(bundle.get("schema_version"), SCHEMA_VERSION, "bundle.schema_version")
    _require_text(bundle.get("title"), "bundle.title")
    _require_equal(bundle.get("label"), SYNTHETIC_LABEL, "bundle.label")
    runs = bundle.get("runs")
    if not isinstance(runs, list) or not runs:
        raise ValueError("bundle.runs must be a non-empty list")
    run_ids: set[str] = set()
    for index, run in enumerate(runs):
        _validate_run(run, index)
        run_id = run["run_id"]
        if run_id in run_ids:
            raise ValueError(f"bundle.runs[{index}].run_id must be unique")
        run_ids.add(run_id)
    assert_comparable(runs)
    for index, run in enumerate(runs[1:], 1):
        if [frame["t"] for frame in run["frames"]] != [frame["t"] for frame in runs[0]["frames"]]:
            raise ValueError(
                f"runs are not comparable: frame timestamps differ "
                f"between {runs[0]['run_id']} and {run['run_id']}"
            )


def _validate_run(run: Any, index: int) -> None:
    name = f"bundle.runs[{index}]"
    _require_mapping(run, name)
    _require_equal(run.get("schema_version"), SCHEMA_VERSION, f"{name}.schema_version")
    _require_text(run.get("run_id"), f"{name}.run_id")
    if run.get("variant") not in {"baseline", "rebalanced", "constrained"}:
        raise ValueError(f"{name}.variant must be baseline, rebalanced, or constrained")
    _require_text(run.get("title"), f"{name}.title")
    _require_equal(run.get("label"), SYNTHETIC_LABEL, f"{name}.label")
    _require_string_list(run.get("changes"), f"{name}.changes")
    _require_string_list(run.get("limitations"), f"{name}.limitations")
    metadata = run.get("metadata")
    _require_mapping(metadata, f"{name}.metadata")
    for field in _REQUIRED_METADATA:
        if field not in metadata:
            raise ValueError(f"{name}.metadata.{field} is required")
    _require_positive_or_zero(metadata["horizon_seconds"], f"{name}.metadata.horizon_seconds")
    _require_positive(metadata["step_seconds"], f"{name}.metadata.step_seconds")
    _require_positive(metadata["frame_interval_seconds"], f"{name}.metadata.frame_interval_seconds")
    if not isinstance(metadata["modes"], list) or not all(isinstance(mode, str) for mode in metadata["modes"]):
        raise ValueError(f"{name}.metadata.modes must be a list of strings")
    geometry = run.get("geometry")
    _validate_geometry(geometry, f"{name}.geometry")
    _validate_frames(run.get("frames"), metadata["horizon_seconds"], geometry["bounds"], f"{name}.frames")
    _validate_metrics(run.get("metrics"), f"{name}.metrics")
    _validate_diagnostics(run.get("diagnostics"), f"{name}.diagnostics")


def _validate_geometry(geometry: Any, name: str) -> None:
    _require_mapping(geometry, name)
    bounds = geometry.get("bounds")
    if not isinstance(bounds, list) or len(bounds) != 4 or not all(_is_number(value) for value in bounds):
        raise ValueError(f"{name}.bounds must be [minx, miny, maxx, maxy]")
    if bounds[0] >= bounds[2] or bounds[1] >= bounds[3]:
        raise ValueError(f"{name}.bounds must have positive extent")
    for field in ("lanes", "junctions"):
        values = geometry.get(field)
        if not isinstance(values, list):
            raise ValueError(f"{name}.{field} must be a list")
        for item_index, item in enumerate(values):
            _require_mapping(item, f"{name}.{field}[{item_index}]")
            _require_text(item.get("id"), f"{name}.{field}[{item_index}].id")
            _validate_shape(item.get("shape"), f"{name}.{field}[{item_index}].shape")
            if field == "lanes":
                _require_positive(item.get("width"), f"{name}.{field}[{item_index}].width")


def _validate_shape(shape: Any, name: str) -> None:
    if not isinstance(shape, list) or not shape:
        raise ValueError(f"{name} must be a non-empty coordinate list")
    for point in shape:
        if not isinstance(point, list) or len(point) != 2 or not all(_is_number(value) for value in point):
            raise ValueError(f"{name} must contain [x, y] numeric coordinates")


def _validate_frames(frames: Any, horizon: float | int, bounds: list, name: str) -> None:
    if not isinstance(frames, list) or not frames:
        raise ValueError(f"{name} must be a non-empty list")
    previous_time = -math.inf
    for frame_index, frame in enumerate(frames):
        frame_name = f"{name}[{frame_index}]"
        _require_mapping(frame, frame_name)
        time = frame.get("t")
        if not _is_number(time) or time < 0 or time > horizon or time < previous_time:
            raise ValueError(f"{frame_name}.t must be ordered and within the horizon")
        previous_time = time
        vehicles = frame.get("vehicles")
        signals = frame.get("signals")
        queues = frame.get("queues")
        if not isinstance(vehicles, list) or not isinstance(signals, list):
            raise ValueError(f"{frame_name}.vehicles and signals must be lists")
        _require_mapping(queues, f"{frame_name}.queues")
        for direction in _DIRECTIONS:
            if not isinstance(queues.get(direction), int) or queues[direction] < 0:
                raise ValueError(f"{frame_name}.queues.{direction} must be a non-negative integer")
        for vehicle_index, vehicle in enumerate(vehicles):
            vehicle_name = f"{frame_name}.vehicles[{vehicle_index}]"
            _require_mapping(vehicle, vehicle_name)
            _require_text(vehicle.get("id"), f"{vehicle_name}.id")
            for field in ("x", "y", "angle", "speed"):
                if not _is_number(vehicle.get(field)):
                    raise ValueError(f"{vehicle_name}.{field} must be numeric")
            if vehicle["x"] < bounds[0] or vehicle["x"] > bounds[2] or vehicle["y"] < bounds[1] or vehicle["y"] > bounds[3]:
                raise ValueError(f"{vehicle_name} position is outside geometry bounds")
            if vehicle.get("approach") not in _DIRECTIONS:
                raise ValueError(f"{vehicle_name}.approach must be N, E, S, or W")
        for signal_index, signal in enumerate(signals):
            signal_name = f"{frame_name}.signals[{signal_index}]"
            _require_mapping(signal, signal_name)
            _require_text(signal.get("id"), f"{signal_name}.id")
            _require_text(signal.get("state"), f"{signal_name}.state")
    if frames[-1]["t"] != horizon:
        raise ValueError(f"{name} must include a final horizon frame")


def _validate_metrics(metrics: Any, name: str) -> None:
    _require_mapping(metrics, name)
    for field in _REQUIRED_METRICS:
        if field not in metrics:
            raise ValueError(f"{name}.{field} is required")
    for field in ("requested", "inserted", "completed", "active", "not_inserted", "removed", "outside_horizon", "max_stopped_vehicles"):
        if not isinstance(metrics[field], int) or metrics[field] < 0:
            raise ValueError(f"{name}.{field} must be a non-negative integer")
    if metrics["requested"] != metrics["completed"] + metrics["active"] + metrics["not_inserted"] + metrics["removed"]:
        raise ValueError(f"{name} requested accounting does not balance")
    if metrics["inserted"] != metrics["completed"] + metrics["active"] + metrics["removed"]:
        raise ValueError(f"{name} inserted accounting does not balance")
    for field in ("completed_mean_time_loss_seconds", "completed_mean_duration_seconds", "inserted_mean_depart_delay_seconds"):
        if metrics[field] is not None:
            _require_positive_or_zero(metrics[field], f"{name}.{field}")
        cohort = "inserted" if field.startswith("inserted_") else "completed"
        if (metrics[cohort] == 0) != (metrics[field] is None):
            raise ValueError(f"{name}.{field} must be null exactly when its {cohort} cohort is empty")
    approaches = metrics["per_approach"]
    _require_mapping(approaches, f"{name}.per_approach")
    for direction in _DIRECTIONS:
        _require_mapping(approaches.get(direction), f"{name}.per_approach.{direction}")
        for field in ("requested", "completed", "active", "not_inserted", "removed", "max_stopped_vehicles"):
            if not isinstance(approaches[direction].get(field), int) or approaches[direction][field] < 0:
                raise ValueError(f"{name}.per_approach.{direction}.{field} must be a non-negative integer")
    for field in ("requested", "completed", "active", "not_inserted", "removed"):
        if sum(approaches[d][field] for d in _DIRECTIONS) != metrics[field]:
            raise ValueError(f"{name}.per_approach {field} does not reconcile with global count")
    for direction in _DIRECTIONS:
        row = approaches[direction]
        if row["requested"] != sum(row[f] for f in ("completed", "active", "not_inserted", "removed")):
            raise ValueError(f"{name}.per_approach.{direction} accounting does not balance")
    _require_mapping(metrics["definitions"], f"{name}.definitions")
    if not all(isinstance(key, str) and isinstance(value, str) for key, value in metrics["definitions"].items()):
        raise ValueError(f"{name}.definitions must map strings to strings")


def _validate_diagnostics(diagnostics: Any, name: str) -> None:
    _require_mapping(diagnostics, name)
    if not isinstance(diagnostics.get("valid"), bool):
        raise ValueError(f"{name}.valid must be boolean")
    for field in ("collisions", "teleports", "unexpected_removals"):
        if not isinstance(diagnostics.get(field), int) or diagnostics[field] < 0:
            raise ValueError(f"{name}.{field} must be a non-negative integer")
    _require_string_list(diagnostics.get("warnings"), f"{name}.warnings")


def _require_mapping(value: Any, name: str) -> None:
    if not isinstance(value, dict):
        raise ValueError(f"{name} must be an object")


def _require_text(value: Any, name: str) -> None:
    if not isinstance(value, str):
        raise ValueError(f"{name} must be a string")


def _require_string_list(value: Any, name: str) -> None:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError(f"{name} must be a list of strings")


def _require_equal(value: Any, expected: Any, name: str) -> None:
    if value != expected:
        raise ValueError(f"{name} must equal {expected!r}")


def _require_positive(value: Any, name: str) -> None:
    if not _is_number(value) or value <= 0:
        raise ValueError(f"{name} must be positive")


def _require_positive_or_zero(value: Any, name: str) -> None:
    if not _is_number(value) or value < 0:
        raise ValueError(f"{name} must be non-negative")


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
