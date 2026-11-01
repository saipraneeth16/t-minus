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
