"""Test harness: a real app + database on a temp dir, with ffmpeg faked out.

Every ffmpeg/yt-dlp invocation is replaced by a stub that writes a small file
at the command's output path, so the whole pipeline runs on a machine with no
media tooling installed. The command *contents* are asserted separately in
test_ffmpeg.py.
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


@pytest.fixture
def client(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    monkeypatch.setenv("BUC_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.delenv("BUC_FRONTEND_DIR", raising=False)

    from app import config

    config.reset_settings()

    from app.media import ffmpeg, ytdlp

    async def fake_run(cmd, total_s=None, on_progress=None):
        Path(cmd[-1]).parent.mkdir(parents=True, exist_ok=True)
        Path(cmd[-1]).write_bytes(b"\x00fake-media" * 32)
        if on_progress:
            await on_progress(1.0)

    async def fake_probe(src, settings=None):
        return ffmpeg.MediaInfo(duration_s=5400.0, fps=25.0, width=1920, height=1080)

    async def fake_download(url, out_stem, on_progress=None, settings=None):
        out = Path(f"{out_stem}.mp4")
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(b"\x00fake-download" * 32)
        return out

    monkeypatch.setattr(ffmpeg, "run_ffmpeg", fake_run)
    monkeypatch.setattr(ffmpeg, "probe", fake_probe)
    monkeypatch.setattr(ytdlp, "download", fake_download)

    from app.main import app

    with TestClient(app) as c:
        yield c

    config.reset_settings()


@pytest.fixture
def source_video(tmp_path):
    path = tmp_path / "match.mp4"
    path.write_bytes(b"\x00source" * 64)
    return path


def wait_for_jobs(client, timeout: float = 10.0) -> list[dict]:
    """Block until the in-process worker has drained."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        jobs = client.get("/api/jobs").json()
        if jobs and all(j["state"] in ("done", "failed") for j in jobs):
            return jobs
        time.sleep(0.02)
    raise AssertionError(f"jobs did not finish in {timeout}s: {client.get('/api/jobs').json()}")


def make_match(client, source_video, title="Rivals away") -> dict:
    resp = client.post(
        "/api/matches",
        json={"title": title, "opponent": "Rivals", "date": "2026-03-01",
              "source_type": "file", "file_path": str(source_video)},
    )
    assert resp.status_code == 201, resp.text
    wait_for_jobs(client)
    return client.get(f"/api/matches/{resp.json()['id']}").json()
