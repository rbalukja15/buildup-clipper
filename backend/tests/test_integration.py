"""Real ffmpeg, end to end: source video in, deliverable out.

This is the acceptance test from the spec in miniature -- it proves the cut
strategy actually produces a joinable, correctly-normalized file, which asserting
on command strings alone cannot.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from conftest import wait_for_jobs

pytestmark = pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="ffmpeg/ffprobe not installed",
)


@pytest.fixture
def live_client(tmp_path, monkeypatch):
    """Same app as the unit tests, but nothing is stubbed."""
    from fastapi.testclient import TestClient

    monkeypatch.setenv("BUC_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.delenv("BUC_FRONTEND_DIR", raising=False)

    from app import config

    config.reset_settings()
    from app.main import app

    with TestClient(app) as client:
        yield client
    config.reset_settings()


@pytest.fixture(scope="module")
def match_video(tmp_path_factory) -> Path:
    """40s of 720p25 colour bars with a burned-in frame counter."""
    path = tmp_path_factory.mktemp("source") / "match.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
         "-f", "lavfi", "-i", "testsrc2=size=1280x720:rate=25:duration=40",
         "-f", "lavfi", "-i", "sine=frequency=440:duration=40",
         "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
         "-g", "250", "-c:a", "aac", "-shortest", str(path)],
        check=True,
    )
    return path


def probe(path: Path) -> dict:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-show_entries", "stream=codec_type,codec_name,width,height,avg_frame_rate,nb_read_packets",
         "-count_packets", "-of", "json", str(path)],
        check=True, capture_output=True, text=True,
    ).stdout
    data = json.loads(out)
    video = next(s for s in data["streams"] if s["codec_type"] == "video")
    return {
        "duration": float(data["format"]["duration"]),
        "width": video["width"],
        "height": video["height"],
        "fps": eval(video["avg_frame_rate"]),  # noqa: S307 -- ffprobe emits "30/1"
        "packets": int(video["nb_read_packets"]),
        "streams": [s["codec_type"] for s in data["streams"]],
    }


def test_full_pipeline_produces_a_playable_deliverable(live_client, match_video):
    created = live_client.post("/api/matches", json={
        "title": "Integration FC", "opponent": "Integration FC",
        "source_type": "file", "file_path": str(match_video)})
    assert created.status_code == 201
    match_id = created.json()["id"]
    wait_for_jobs(live_client, timeout=180)

    match = live_client.get(f"/api/matches/{match_id}").json()
    assert match["ingest_state"] == "ready", match["ingest_error"]
    assert match["duration_s"] == pytest.approx(40.0, abs=0.5)
    assert match["fps"] == pytest.approx(25.0, abs=0.1)

    # -- proxy: 480p, and dense keyframes for scrubbing --------------------
    proxy = probe(Path(match["proxy_path"]))
    assert proxy["height"] == 480
    assert proxy["width"] == 854  # 16:9 preserved by scale=-2:480
    assert "audio" in proxy["streams"], "the analyst tags by ear as well as by eye"
    keyframes = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "frame=key_frame",
         "-of", "csv=p=0", "-read_intervals", "%+10", str(match["proxy_path"])],
        check=True, capture_output=True, text=True,
    ).stdout.split()
    assert keyframes.count("1") >= 8, "short GOP is what makes browser seeking snappy"

    # -- tag two build-ups -------------------------------------------------
    windows = [(5.0, 13.0), (22.0, 30.0)]
    clip_ids = []
    for t_start, t_end in windows:
        tag = live_client.post(f"/api/matches/{match_id}/tags",
                               json={"t_start": t_start, "t_end": t_end}).json()
        clip_ids.append(tag["clip_id"])
    wait_for_jobs(live_client, timeout=180)

    for clip_id in clip_ids:
        clip = live_client.get(f"/api/clips/{clip_id}").json()
        assert clip["render_state"] == "ready", clip["render_error"]
        review = probe(Path(clip["review_path"]))
        # Stream-copied, so the cut snaps to keyframes -- generous tolerance is
        # the documented trade-off for an instant review clip.
        assert review["duration"] == pytest.approx(8.0, abs=2.5)
        assert review["height"] == 480

    # -- approve and export -------------------------------------------------
    for clip_id in clip_ids:
        live_client.patch(f"/api/clips/{clip_id}", json={"status": "approved"})
    export = live_client.post("/api/exports",
                              json={"name": "Integration FC GK build-up", "match_id": match_id}).json()
    wait_for_jobs(live_client, timeout=300)

    ready = live_client.get(f"/api/exports/{export['id']}").json()
    assert ready["state"] == "ready", ready["error"]

    final = probe(Path(ready["file_path"]))
    assert (final["width"], final["height"]) == (1280, 720)
    assert final["fps"] == 30
    assert final["streams"] == ["video"], "audio is dropped so mixed sources concat cleanly"
    # Frame-exact: 16s of source at 30fps, within a couple of frames.
    assert final["duration"] == pytest.approx(16.0, abs=0.15)
    assert final["packets"] == pytest.approx(480, abs=4)


def test_segments_from_different_sources_concat_without_a_glitch(live_client, match_video, tmp_path):
    """The sample deliverable mixed three sources; a 4:3 25fps source and a
    16:9 25fps source must still join into one continuous file."""
    odd_source = tmp_path / "odd.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
         "-f", "lavfi", "-i", "testsrc2=size=640x480:rate=30:duration=20",
         "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", str(odd_source)],
        check=True,
    )

    clip_ids = []
    for path, window in ((match_video, (4.0, 10.0)), (odd_source, (3.0, 9.0))):
        match_id = live_client.post("/api/matches", json={
            "title": path.stem, "source_type": "file", "file_path": str(path)}).json()["id"]
        wait_for_jobs(live_client, timeout=180)
        tag = live_client.post(f"/api/matches/{match_id}/tags",
                               json={"t_start": window[0], "t_end": window[1]}).json()
        clip_ids.append(tag["clip_id"])
    wait_for_jobs(live_client, timeout=180)

    export = live_client.post("/api/exports",
                              json={"name": "Mixed sources", "clip_ids": clip_ids}).json()
    wait_for_jobs(live_client, timeout=300)
    ready = live_client.get(f"/api/exports/{export['id']}").json()
    assert ready["state"] == "ready", ready["error"]

    final = probe(Path(ready["file_path"]))
    assert (final["width"], final["height"]) == (1280, 720), "the 4:3 source is padded, not stretched"
    assert final["duration"] == pytest.approx(12.0, abs=0.2)
    assert final["packets"] == pytest.approx(360, abs=4), "no dropped or duplicated frames at the join"


def test_changing_export_settings_produces_a_uniform_file(live_client, match_video, monkeypatch):
    """The dangerous case: segments encoded under old settings, concat-copied
    together with new ones. ffmpeg exits 0 and the header lies about half the
    frames, so this has to be checked on real output, not on a mock."""
    from app import config

    match_id = live_client.post("/api/matches", json={
        "title": "Settings change", "source_type": "file", "file_path": str(match_video)}).json()["id"]
    wait_for_jobs(live_client, timeout=180)

    clip_ids = []
    for window in ((3.0, 7.0), (20.0, 24.0)):
        tag = live_client.post(f"/api/matches/{match_id}/tags",
                               json={"t_start": window[0], "t_end": window[1]}).json()
        clip_ids.append(tag["clip_id"])
    wait_for_jobs(live_client, timeout=180)
    for clip_id in clip_ids:
        live_client.patch(f"/api/clips/{clip_id}", json={"status": "approved"})

    export = live_client.post("/api/exports",
                              json={"name": "settings", "match_id": match_id}).json()
    wait_for_jobs(live_client, timeout=300)
    first = probe(Path(live_client.get(f"/api/exports/{export['id']}").json()["file_path"]))
    assert (first["width"], first["height"], first["fps"]) == (1280, 720, 30)

    # The analyst re-renders at a different size, as docs/handoff.md invites.
    monkeypatch.setenv("BUC_EXPORT_WIDTH", "640")
    monkeypatch.setenv("BUC_EXPORT_HEIGHT", "360")
    monkeypatch.setenv("BUC_EXPORT_FPS", "25")
    config.reset_settings()

    live_client.post(f"/api/exports/{export['id']}/rerender")
    wait_for_jobs(live_client, timeout=300)

    row = live_client.get(f"/api/exports/{export['id']}").json()
    assert row["state"] == "ready", row["error"]
    second = probe(Path(row["file_path"]))
    assert (second["width"], second["height"]) == (640, 360), "stale 720p segments were reused"
    assert second["fps"] == 25
    assert second["duration"] == pytest.approx(8.0, abs=0.15)
    # 8s at 25fps: proves every frame came from the new encode, not a mix.
    assert second["packets"] == pytest.approx(200, abs=3)
