"""Bundle an OpenStreetMap snapshot (facilities + critical assets) for every configured district.

    python -m scripts.build_osm_snapshot                 # all districts missing a snapshot
    python -m scripts.build_osm_snapshot --force chennai # re-fetch specific districts

Public Overpass servers are often overloaded (504s, 30-60 s answers), so the app must never
*depend* on them answering in time. The snapshot written here (``app/snapshots/osm/``,
shipped inside the image) is the floor: pages answer from cache or snapshot immediately and
refresh from Overpass in the background. © OpenStreetMap contributors (ODbL).
"""
from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import gzip
import json
import sys

from app.config import get_config
from app.sources.osm import _ASSET_FILTERS, _OVERPASS_FILTERS, query_overpass
from app.sources.osm_snapshot import KEEP_TAGS, SNAPSHOT_DIR, snapshot_box


def build_query(box: tuple[float, float, float, float]) -> str:
    scope = f"({box[0]:.5f},{box[1]:.5f},{box[2]:.5f},{box[3]:.5f})"
    filters = dict.fromkeys(f for fs in list(_OVERPASS_FILTERS.values()) + list(_ASSET_FILTERS.values()) for f in fs)
    return "[out:json][timeout:170];(" + "".join(f + scope + ";" for f in filters) + ");out center tags 6000;"


def slim(payload: dict) -> list[dict]:
    out = []
    for el in payload.get("elements", []):
        lat = el.get("lat") or (el.get("center") or {}).get("lat")
        lon = el.get("lon") or (el.get("center") or {}).get("lon")
        if lat is None or lon is None:
            continue
        tags = {k: v for k, v in (el.get("tags") or {}).items() if k in KEEP_TAGS}
        out.append({"type": el.get("type"), "id": el.get("id"), "lat": round(float(lat), 6),
                    "lon": round(float(lon), 6), "tags": tags})
    return out


async def one(did: str, sem: asyncio.Semaphore) -> tuple[str, str]:
    d = get_config().district(did)
    box = snapshot_box(d)
    async with sem:
        for attempt in range(1, 4):
            try:
                res = await query_overpass(build_query(box), budget_s=200.0, per_try_s=180.0, stagger_s=60.0)
                break
            except Exception as exc:  # noqa: BLE001
                if attempt == 3:
                    return did, f"FAILED: {str(exc)[:120]}"
                await asyncio.sleep(15 * attempt)
    els = slim(res.payload)
    doc = {"district_id": did, "box": box, "fetched_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
           "attribution": "© OpenStreetMap contributors (ODbL), via Overpass API", "elements": els}
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    with gzip.open(SNAPSHOT_DIR / f"{did}.json.gz", "wt", encoding="utf-8") as fh:
        json.dump(doc, fh, separators=(",", ":"), ensure_ascii=False)
    return did, f"ok {len(els)} elements"


async def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("districts", nargs="*")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--parallel", type=int, default=2)
    a = ap.parse_args(argv)
    from app.db.session import init_db

    init_db()
    ids = a.districts or [d.id for d in get_config().districts]
    if not a.force:
        ids = [i for i in ids if not (SNAPSHOT_DIR / f"{i}.json.gz").exists()]
    sem = asyncio.Semaphore(a.parallel)
    bad = 0
    for coro in asyncio.as_completed([one(i, sem) for i in ids]):
        did, msg = await coro
        bad += msg.startswith("FAILED")
        print(f"{did}: {msg}", flush=True)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main(sys.argv[1:])))
