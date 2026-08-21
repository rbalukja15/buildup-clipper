"""The <video> element only scrubs smoothly if Range requests work properly."""
from __future__ import annotations

from pathlib import Path

from conftest import make_match, wait_for_jobs


def test_proxy_is_served_with_range_support(client, source_video):
    match = make_match(client, source_video)
    resp = client.get(f"/api/media/proxy/{match['id']}")
    assert resp.status_code == 200
    assert resp.headers["accept-ranges"] == "bytes"


def test_range_request_returns_the_exact_slice(client, source_video):
    match = make_match(client, source_video)
    body = Path(match["proxy_path"]).read_bytes()

    resp = client.get(f"/api/media/proxy/{match['id']}", headers={"Range": "bytes=10-19"})
    assert resp.status_code == 206
    assert resp.headers["content-range"] == f"bytes 10-19/{len(body)}"
    assert resp.content == body[10:20]


def test_open_ended_and_suffix_ranges(client, source_video):
    match = make_match(client, source_video)
    body = Path(match["proxy_path"]).read_bytes()

    tail = client.get(f"/api/media/proxy/{match['id']}", headers={"Range": "bytes=100-"})
    assert tail.status_code == 206 and tail.content == body[100:]

    suffix = client.get(f"/api/media/proxy/{match['id']}", headers={"Range": "bytes=-16"})
    assert suffix.status_code == 206 and suffix.content == body[-16:]


def test_range_past_the_end_is_416(client, source_video):
    match = make_match(client, source_video)
    size = Path(match["proxy_path"]).stat().st_size
    resp = client.get(f"/api/media/proxy/{match['id']}", headers={"Range": f"bytes={size + 10}-"})
    assert resp.status_code == 416


def test_unrendered_clip_reports_409_not_500(client, source_video):
    match = make_match(client, source_video)
    tag = client.post(f"/api/matches/{match['id']}/tags", json={"t": 600.0}).json()
    client.patch(f"/api/tags/{tag['id']}", json={"t_start": 100.0, "t_end": 130.0})
    # The clip row exists but its file has just been invalidated.
    resp = client.get(f"/api/media/clip/{tag['clip_id']}")
    assert resp.status_code in (409, 200)
    wait_for_jobs(client)
    assert client.get(f"/api/media/clip/{tag['clip_id']}").status_code == 200


def test_media_outside_the_data_directory_is_refused(client, source_video, tmp_path):
    """Source files can live anywhere on disk; the API must not become a way to
    read them (or anything else) over HTTP."""
    match = make_match(client, source_video)
    secret = tmp_path / "private.mp4"
    secret.write_bytes(b"not yours")

    from app.db import connect

    with connect() as conn:
        conn.execute("UPDATE match SET proxy_path = ? WHERE id = ?", (str(secret), match["id"]))

    assert client.get(f"/api/media/proxy/{match['id']}").status_code == 403


def test_head_requests_are_answered_with_headers_only(client, source_video):
    """Video players probe with HEAD before streaming, and Next's Link prefetch
    uses it for routes -- a 405 there shows up as console noise and dead
    prefetches."""
    match = make_match(client, source_video)
    size = Path(match["proxy_path"]).stat().st_size

    head = client.head(f"/api/media/proxy/{match['id']}")
    assert head.status_code == 200
    assert head.headers["accept-ranges"] == "bytes"
    assert head.headers["content-length"] == str(size)
    assert head.content == b""


def test_head_on_an_export_download(client, source_video):
    match = make_match(client, source_video)
    clip_id = client.post(f"/api/matches/{match['id']}/tags", json={"t": 600.0}).json()["clip_id"]
    wait_for_jobs(client)
    client.patch(f"/api/clips/{clip_id}", json={"status": "approved"})
    export = client.post("/api/exports", json={"name": "head check", "match_id": match["id"]}).json()
    wait_for_jobs(client)

    head = client.head(f"/api/exports/{export['id']}/download")
    assert head.status_code == 200
    assert "attachment" in head.headers["content-disposition"]
