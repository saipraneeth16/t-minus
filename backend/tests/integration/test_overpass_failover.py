"""Overpass mirrors are hedged: a dead primary or a 200-with-error remark must not sink the query."""
import asyncio

import httpx
import pytest

from app.sources.base import SourceError
from app.sources.osm import fetch_facilities

GOOD = {"elements": [{"type": "node", "id": 1, "lat": 13.05, "lon": 80.25,
                      "tags": {"amenity": "hospital", "name": "General Hospital"}}]}


def test_falls_over_to_a_mirror_when_primary_fails(fresh_db, mock_http):
    hits = []

    def handler(req: httpx.Request):
        hits.append(req.url.host)
        if req.url.host == "overpass-api.de":
            raise httpx.ConnectError("reset by peer")
        if req.url.host == "maps.mail.ru":  # busy server: claims success but the query died
            return httpx.Response(200, json={"elements": [], "remark": "runtime error: Query timed out"})
        return httpx.Response(200, json=GOOD)

    mock_http(handler)
    res, feats = asyncio.run(fetch_facilities(["hospital"], bbox=(13.0, 80.2, 13.1, 80.3)))
    assert [f["name"] for f in feats] == ["General Hospital"]
    assert "overpass.private.coffee" in hits


def test_all_mirrors_failing_raises(fresh_db, mock_http):
    mock_http(lambda req: httpx.Response(504, text="Gateway Time-out"))
    with pytest.raises(SourceError, match="All Overpass mirrors failed"):
        asyncio.run(fetch_facilities(["hospital"], bbox=(13.0, 80.2, 13.1, 80.3)))


def _write_snapshot(tmp_path, monkeypatch, did="chennai"):
    import gzip
    import json

    from app.config import get_config
    from app.sources import osm_snapshot

    d = get_config().district(did)
    lat, lon = d.hq
    els = [{"type": "node", "id": 9, "lat": lat, "lon": lon, "tags": {"amenity": "hospital", "name": "Snapshot Hospital"}},
           {"type": "node", "id": 10, "lat": lat + 0.01, "lon": lon, "tags": {"name": "FCI Godown"}}]
    with gzip.open(tmp_path / f"{did}.json.gz", "wt", encoding="utf-8") as fh:
        json.dump({"district_id": did, "fetched_at": "2026-11-01T00:00:00+00:00", "elements": els}, fh)
    monkeypatch.setattr(osm_snapshot, "SNAPSHOT_DIR", tmp_path)
    osm_snapshot.load.cache_clear()


def test_assets_answer_instantly_from_snapshot_when_overpass_is_down(fresh_db, mock_http, tmp_path, monkeypatch):
    import time

    from app.impact.assets import osm_assets

    _write_snapshot(tmp_path, monkeypatch)
    mock_http(lambda req: httpx.Response(504, text="Gateway Time-out"))

    async def run():
        t0 = time.monotonic()
        feats, fetch_id, err = await osm_assets("chennai")
        took = time.monotonic() - t0
        await asyncio.sleep(0)  # let the background refresh start (and fail) without blocking us
        return feats, err, took

    feats, err, took = asyncio.run(run())
    assert took < 2 and err is None
    assert {f["type"] for f in feats} == {"hospital", "grain_storage"}


def test_find_facilities_uses_snapshot_instead_of_failing(fresh_db, mock_http, tmp_path, monkeypatch):
    from app.agent.tools import ToolContext, t_find_facilities

    _write_snapshot(tmp_path, monkeypatch)
    mock_http(lambda req: httpx.Response(504, text="Gateway Time-out"))
    ctx = ToolContext.__new__(ToolContext)
    ctx.district_id, ctx.facilities = "chennai", {}
    out = asyncio.run(t_find_facilities(ctx, {"types": ["hospital"]}))
    assert out["status"] == "ok" and out["counts"] == {"hospital": 1} and "snapshot" in out["note"]
