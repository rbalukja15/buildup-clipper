"""Regressions found by review after the first working version.

Each test here corresponds to a defect that shipped in the first cut.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from conftest import make_match, wait_for_jobs


# --------------------------------------------------------------------------- #
# a moved tag window invalidates the analyst's verdict, not just the file
# --------------------------------------------------------------------------- #

def test_retrimming_a_tag_resets_its_approval(client, source_video):
    """An approved clip that is then trimmed must be re-watched: the verdict was
    about the old cut."""
    match = make_match(client, source_video)
    tag = client.post(f"/api/matches/{match['id']}/tags", json={"t": 600.0}).json()
    wait_for_jobs(client)
    client.patch(f"/api/clips/{tag['clip_id']}", json={"status": "approved"})

    client.patch(f"/api/tags/{tag['id']}", json={"t_end": 615.0})
    wait_for_jobs(client)

    assert client.get(f"/api/clips/{tag['clip_id']}").json()["status"] == "pending"


def test_a_rejected_clip_gets_a_second_chance_after_the_cut_is_fixed(client, source_video):
    match = make_match(client, source_video)
    tag = client.post(f"/api/matches/{match['id']}/tags", json={"t": 600.0}).json()
    wait_for_jobs(client)
    client.patch(f"/api/clips/{tag['clip_id']}", json={"status": "rejected"})

    client.patch(f"/api/tags/{tag['id']}", json={"t_start": 590.0})
    wait_for_jobs(client)
    assert client.get(f"/api/clips/{tag['clip_id']}").json()["status"] == "pending"


def test_a_plain_rerender_keeps_the_verdict(client, source_video):
    """Re-cutting the same window is a repair, not a new decision."""
    match = make_match(client, source_video)
    tag = client.post(f"/api/matches/{match['id']}/tags", json={"t": 600.0}).json()
    wait_for_jobs(client)
    client.patch(f"/api/clips/{tag['clip_id']}", json={"status": "approved"})

    client.post(f"/api/clips/{tag['clip_id']}/rerender")
    wait_for_jobs(client)
    assert client.get(f"/api/clips/{tag['clip_id']}").json()["status"] == "approved"


# --------------------------------------------------------------------------- #
# export segments must not outlive the settings they were encoded with
# --------------------------------------------------------------------------- #

def test_changing_export_settings_re_encodes_every_segment(client, source_video, monkeypatch):
    """Segments are concat-copied, so one encoded at a different size would make
    the deliverable's header disagree with its frames."""
    from app import config
    from app.media import ffmpeg

    match = make_match(client, source_video)
    clip_id = client.post(f"/api/matches/{match['id']}/tags", json={"t": 600.0}).json()["clip_id"]
    wait_for_jobs(client)
    client.patch(f"/api/clips/{clip_id}", json={"status": "approved"})
    export = client.post("/api/exports", json={"name": "first", "match_id": match["id"]}).json()
    wait_for_jobs(client)
    assert client.get(f"/api/exports/{export['id']}").json()["state"] == "ready"

    encodes: list[str] = []
    original = ffmpeg.run_ffmpeg

    async def spy(cmd, total_s=None, on_progress=None):
        if "libx264" in cmd:
            encodes.append(" ".join(cmd))
        await original(cmd, total_s, on_progress)

    monkeypatch.setattr(ffmpeg, "run_ffmpeg", spy)

    # Same settings -> the existing segment is reused.
    client.post(f"/api/exports/{export['id']}/rerender")
    wait_for_jobs(client)
    assert encodes == [], "an unchanged segment should not be re-encoded"

    # Analyst raises the export resolution, as docs/handoff.md suggests.
    monkeypatch.setenv("BUC_EXPORT_HEIGHT", "1080")
    monkeypatch.setenv("BUC_EXPORT_WIDTH", "1920")
    config.reset_settings()

    client.post(f"/api/exports/{export['id']}/rerender")
    wait_for_jobs(client)
    assert len(encodes) == 1, "a settings change must re-encode the segment"
    assert "scale=1920:1080" in encodes[0]


def test_export_whose_clips_vanished_reports_failure_and_stops_serving(client, source_video):
    """Deleting a match cascades to export_clip; the old file must not keep
    being downloadable as if it were still valid."""
    match = make_match(client, source_video)
    clip_id = client.post(f"/api/matches/{match['id']}/tags", json={"t": 600.0}).json()["clip_id"]
    wait_for_jobs(client)
    client.patch(f"/api/clips/{clip_id}", json={"status": "approved"})
    export = client.post("/api/exports", json={"name": "doomed", "match_id": match["id"]}).json()
    wait_for_jobs(client)
    assert client.get(f"/api/exports/{export['id']}/download").status_code == 200

    client.delete(f"/api/matches/{match['id']}")
    client.post(f"/api/exports/{export['id']}/rerender")
    wait_for_jobs(client)

    row = client.get(f"/api/exports/{export['id']}").json()
    assert row["state"] == "failed"
    assert row["error"] and "no clips" in row["error"]
    assert row["file_path"] is None
    assert client.get(f"/api/exports/{export['id']}/download").status_code == 409


# --------------------------------------------------------------------------- #
# interrupted work is picked back up
# --------------------------------------------------------------------------- #

def test_clip_renders_interrupted_by_a_restart_are_requeued(fake_media, source_video):
    """The job queue is in-memory: without a startup sweep these rows sit at
    'pending' forever, indistinguishable from work that is still queued."""
    from fastapi.testclient import TestClient

    from app.db import connect
    from app.main import app

    with TestClient(app) as first:
        match = make_match(first, source_video)
        clip_id = first.post(f"/api/matches/{match['id']}/tags", json={"t": 600.0}).json()["clip_id"]
        wait_for_jobs(first)

    # The state db._recover_interrupted leaves behind after a crash mid-render.
    with connect() as conn:
        conn.execute(
            "UPDATE clip SET render_state = 'pending', review_path = NULL WHERE id = ?", (clip_id,)
        )

    with TestClient(app) as restarted:          # a second run of the lifespan
        wait_for_jobs(restarted)
        clip = restarted.get(f"/api/clips/{clip_id}").json()
        assert clip["render_state"] == "ready"
        assert clip["review_path"]


# --------------------------------------------------------------------------- #
# input validation at the edge
# --------------------------------------------------------------------------- #

def test_duplicate_clip_ids_do_not_break_an_export(client, source_video):
    match = make_match(client, source_video)
    clip_id = client.post(f"/api/matches/{match['id']}/tags", json={"t": 600.0}).json()["clip_id"]
    wait_for_jobs(client)

    resp = client.post("/api/exports", json={"name": "dupes", "clip_ids": [clip_id, clip_id]})
    assert resp.status_code == 201
    assert [c["clip_id"] for c in resp.json()["clips"]] == [clip_id]


def test_a_contradictory_tag_payload_is_rejected_not_crashed(client, source_video):
    match = make_match(client, source_video)
    resp = client.post(f"/api/matches/{match['id']}/tags", json={"t": 600.0, "t_start": 500.0})
    assert resp.status_code == 422


@pytest.mark.parametrize("url", ["--rm-cache-dir", "file:///etc/passwd", "-o/tmp/pwned"])
def test_source_url_must_be_http(client, url):
    """source_url ends up in a subprocess argv."""
    resp = client.post("/api/matches", json={
        "title": "sneaky", "source_type": "youtube", "source_url": url})
    assert resp.status_code == 422


# --------------------------------------------------------------------------- #
# the SPA fallback must not read outside the exported frontend
# --------------------------------------------------------------------------- #

@pytest.fixture
def frontend_client(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    frontend = tmp_path / "frontend"
    frontend.mkdir()
    (frontend / "index.html").write_text("<html>app</html>")
    (frontend / "tag.html").write_text("<html>tag</html>")

    # A sibling that shares the directory-name prefix, and a secret elsewhere.
    (tmp_path / "frontend-secrets").mkdir()
    (tmp_path / "frontend-secrets" / "creds.txt").write_text("SECRET")
    (tmp_path / "private.html").write_text("PRIVATE")

    monkeypatch.setenv("BUC_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("BUC_FRONTEND_DIR", str(frontend))

    from app import config, main

    config.reset_settings()

    # The catch-all is mounted at import time, so build a fresh app rather than
    # reloading the module (which would rebind the shared job queue).
    spa_app = main.build_app()
    with TestClient(spa_app) as c:
        yield c
    config.reset_settings()


def test_spa_serves_the_exported_frontend(frontend_client):
    assert frontend_client.get("/").text == "<html>app</html>"
    assert frontend_client.get("/tag").text == "<html>tag</html>"


@pytest.mark.parametrize("path", [
    "/%2e%2e/frontend-secrets/creds.txt",
    "/%2e%2e/private",
    "/%2e%2e%2f%2e%2e%2fetc/passwd",
])
def test_spa_never_serves_files_outside_its_root(frontend_client, path):
    """A traversal must land on the SPA index, never on a file outside."""
    resp = frontend_client.get(path)
    assert resp.status_code == 200
    assert resp.text == "<html>app</html>", f"{path} escaped the frontend directory"
    assert "SECRET" not in resp.text and "PRIVATE" not in resp.text
