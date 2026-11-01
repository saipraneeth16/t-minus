"""Bundled OpenStreetMap snapshot: the floor under the live Overpass source.

Written by ``python -m scripts.build_osm_snapshot`` into ``app/snapshots/osm/<district>.json.gz``
and shipped inside the image. When neither a fresh nor an older Overpass result is cached, the
facility tool and the critical-assets panel answer from here instantly instead of waiting on (or
failing with) a public Overpass server; a live refresh then runs in the background.
© OpenStreetMap contributors (ODbL).
"""
from __future__ import annotations

import functools
import gzip
import json
from pathlib import Path

from app.config import DistrictCfg, get_config
from app.geo import radius_box

SNAPSHOT_DIR = Path(__file__).resolve().parents[1] / "snapshots" / "osm"

# Every tag the facility/asset classifiers and normalisers read.
KEEP_TAGS = frozenset({
    "name", "name:en", "name:ta", "amenity", "healthcare", "emergency", "social_facility", "shelter_type",
    "man_made", "industrial", "power", "operator", "addr:full", "addr:street", "beds", "capacity", "voltage",
    "generator:source", "backup_generator", "power_supply", "emergency_power",
})


def snapshot_box(d: DistrictCfg) -> tuple[float, float, float, float]:
    """Covers both live search boxes (facility radius and asset radius) without a boundary file."""
    km = max(get_config().search_radius_km(d), float(d.search_radius_km or 15.0))
    return radius_box(d.hq[0], d.hq[1], km)


@functools.lru_cache(maxsize=64)
def load(district_id: str) -> dict | None:
    p = SNAPSHOT_DIR / f"{district_id}.json.gz"
    if not p.exists():
        return None
    try:
        with gzip.open(p, "rt", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def payload(district_id: str) -> dict | None:
    """Overpass-shaped payload ({"elements": [...]}) for the normalisers, or None."""
    doc = load(district_id)
    return {"elements": doc["elements"]} if doc else None


def fetched_at(district_id: str) -> str | None:
    doc = load(district_id)
    return doc.get("fetched_at") if doc else None
