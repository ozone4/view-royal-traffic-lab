"""Frozen, explicit synthetic passenger-demand generation."""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import math
import random
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET


@dataclass(frozen=True, order=True)
class Request:
    id: str
    depart: float
    route: str
    approach: str


@dataclass(frozen=True)
class FrozenDemand:
    requests: tuple[Request, ...]
    sha256: str


def _route_edges(route: str) -> str:
    source, destination = route.split("_in_", 1)
    return f"{source}_in {destination}"


def _xml(demand: FrozenDemand) -> bytes:
    root = ET.Element("routes")
    ET.SubElement(root, "vType", id="passenger", vClass="passenger", accel="2.6", decel="4.5", length="5", minGap="2.5", maxSpeed="13.89")
    routes = sorted({request.route for request in demand.requests})
    for route in routes:
        ET.SubElement(root, "route", id=route, edges=_route_edges(route))
    for request in demand.requests:
        ET.SubElement(root, "vehicle", id=request.id, type="passenger", route=request.route, depart=f"{request.depart:.1f}", departLane="best", departSpeed="max")
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def build_frozen_demand(scenario: dict[str, Any], *, seed: int, demand_scale: float) -> FrozenDemand:
    if not math.isfinite(demand_scale) or demand_scale < 0:
        raise ValueError("demand_scale must be finite non-negative")
    rng = random.Random(seed)
    requests: list[Request] = []
    for movement in sorted(scenario["movements"], key=lambda m: m["id"]):
        total = round(movement["rate_per_hour"] * demand_scale * scenario["arrival_window_seconds"] / 3600)
        # jitter avoids artificial platoons while retaining a fully explicit seed-derived list.
        for number in range(total):
            depart = round((number + rng.random()) * scenario["arrival_window_seconds"] / max(total, 1), 1)
            requests.append(Request(f"{movement['id']}-{number:04d}", depart, movement["route"], movement["approach"]))
    requests.sort(key=lambda request: (request.depart, request.id))
    provisional = FrozenDemand(tuple(requests), "")
    return FrozenDemand(provisional.requests, sha256(_xml(provisional)).hexdigest())


def write_routes(demand: FrozenDemand, path: str | Path) -> Path:
    output = Path(path)
    output.write_bytes(_xml(demand))
    return output
