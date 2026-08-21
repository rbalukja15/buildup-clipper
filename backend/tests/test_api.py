"""End-to-end walk of the analyst's flow: create -> tag -> review -> export."""
from __future__ import annotations

from pathlib import Path

from conftest import make_match, wait_for_jobs


def test_health_reports_the_tuning_knobs(client):
    body = client.get("/api/health").json()
    assert body["ok"] is True
    assert body["tag_padding"] == [3.0, 27.0]
    assert body["export"] == {"width": 1280, "height": 720, "fps": 30}


def test_ingest_probes_and_builds_a_proxy(client, source_video):
    match = make_match(client, source_video)
    assert match["ingest_state"] == "ready"
    assert match["duration_s"] == 5400.0 and match["fps"] == 25.0
    assert Path(match["proxy_path"]).is_file()


def test_ingest_from_youtube_downloads_first(client):
    resp = client.post("/api/matches", json={
        "title": "Away leg", "opponent": "Rivals",
        "source_type": "youtube", "source_url": "https://youtu.be/abc123",
    })
    assert resp.status_code == 201
    wait_for_jobs(client)
    match = client.get(f"/api/matches/{resp.json()['id']}").json()
    assert match["ingest_state"] == "ready"
    assert Path(match["file_path"]).is_file()


def test_missing_local_file_is_rejected_before_a_row_is_created(client):
    resp = client.post("/api/matches", json={
        "title": "Nope", "source_type": "file", "file_path": "/no/such/match.mp4"})
    assert resp.status_code == 400
    assert client.get("/api/matches").json() == []


def test_youtube_source_requires_a_url(client):
    resp = client.post("/api/matches", json={"title": "Nope", "source_type": "youtube"})
    assert resp.status_code == 422


def test_hotkey_tag_applies_default_padding_and_renders_a_clip(client, source_video):
    match = make_match(client, source_video)
    tag = client.post(f"/api/matches/{match['id']}/tags", json={"t": 600.0}).json()
    assert (tag["t_start"], tag["t_end"]) == (597.0, 627.0)
    assert tag["category"] == "gk_buildup" and tag["source"] == "manual"

    wait_for_jobs(client)
    clip = client.get(f"/api/clips/{tag['clip_id']}").json()
    assert clip["render_state"] == "ready"
    assert clip["status"] == "pending"
    assert Path(clip["review_path"]).is_file()


def test_tag_near_kickoff_does_not_seek_before_zero(client, source_video):
    match = make_match(client, source_video)
    tag = client.post(f"/api/matches/{match['id']}/tags", json={"t": 1.0}).json()
    assert tag["t_start"] == 0.0


def test_tag_is_clamped_to_the_end_of_the_match(client, source_video):
    match = make_match(client, source_video)
    tag = client.post(f"/api/matches/{match['id']}/tags", json={"t": 5395.0}).json()
    assert tag["t_end"] == 5400.0


def test_editing_a_tag_invalidates_and_rerenders_its_clip(client, source_video):
    match = make_match(client, source_video)
    tag = client.post(f"/api/matches/{match['id']}/tags", json={"t": 600.0}).json()
    wait_for_jobs(client)
    review_path = Path(client.get(f"/api/clips/{tag['clip_id']}").json()["review_path"])
    review_path.write_bytes(b"stale")

    updated = client.patch(f"/api/tags/{tag['id']}", json={"t_start": 590.0, "t_end": 620.0}).json()
    assert (updated["t_start"], updated["t_end"]) == (590.0, 620.0)
    wait_for_jobs(client)

    clip = client.get(f"/api/clips/{tag['clip_id']}").json()
    assert clip["render_state"] == "ready"
    assert review_path.read_bytes() != b"stale", "the derived clip must be rebuilt, not reused"


def test_editing_only_the_note_does_not_rerender(client, source_video):
    match = make_match(client, source_video)
    tag = client.post(f"/api/matches/{match['id']}/tags", json={"t": 600.0}).json()
    wait_for_jobs(client)
    jobs_before = len(client.get("/api/jobs").json())

    client.patch(f"/api/tags/{tag['id']}", json={"note": "short goal kick, left CB"})
    assert len(client.get("/api/jobs").json()) == jobs_before
    assert client.get(f"/api/clips/{tag['clip_id']}").json()["note"] == "short goal kick, left CB"


def test_undo_removes_the_last_tag_and_its_clip(client, source_video):
    match = make_match(client, source_video)
    first = client.post(f"/api/matches/{match['id']}/tags", json={"t": 300.0}).json()
    client.post(f"/api/matches/{match['id']}/tags", json={"t": 600.0})
    wait_for_jobs(client)

    assert client.delete(f"/api/matches/{match['id']}/tags/last").status_code == 204
    tags = client.get(f"/api/matches/{match['id']}/tags").json()
    assert [t["id"] for t in tags] == [first["id"]]
    assert len(client.get(f"/api/clips?match_id={match['id']}").json()) == 1


def test_undo_with_no_tags_is_a_404_not_a_crash(client, source_video):
    match = make_match(client, source_video)
    assert client.delete(f"/api/matches/{match['id']}/tags/last").status_code == 404


def test_review_approve_reject_and_reorder(client, source_video):
    match = make_match(client, source_video)
    ids = [client.post(f"/api/matches/{match['id']}/tags", json={"t": t}).json()["clip_id"]
           for t in (300.0, 600.0, 900.0)]
    wait_for_jobs(client)

    client.patch(f"/api/clips/{ids[0]}", json={"status": "approved"})
    client.patch(f"/api/clips/{ids[1]}", json={"status": "rejected"})
    client.patch(f"/api/clips/{ids[2]}", json={"status": "approved", "note": "keeper under press"})

    approved = client.get(f"/api/clips?match_id={match['id']}&status=approved").json()
    assert [c["id"] for c in approved] == [ids[0], ids[2]]
    assert approved[1]["note"] == "keeper under press"

    client.post("/api/clips/reorder", json={"clip_ids": [ids[2], ids[0], ids[1]]})
    ordered = client.get(f"/api/clips?match_id={match['id']}").json()
    assert [c["id"] for c in ordered] == [ids[2], ids[0], ids[1]]


def test_export_joins_approved_clips_in_review_order(client, source_video):
    match = make_match(client, source_video)
    ids = [client.post(f"/api/matches/{match['id']}/tags", json={"t": t}).json()["clip_id"]
           for t in (300.0, 600.0, 900.0)]
    wait_for_jobs(client)
    for clip_id, status in zip(ids, ("approved", "rejected", "approved")):
        client.patch(f"/api/clips/{clip_id}", json={"status": status})
    client.post("/api/clips/reorder", json={"clip_ids": [ids[2], ids[0], ids[1]]})

    export = client.post("/api/exports", json={"name": "Rivals GK build-up",
                                               "match_id": match["id"]}).json()
    assert [c["clip_id"] for c in export["clips"]] == [ids[2], ids[0]], "rejected clips stay out"
    wait_for_jobs(client)

    ready = client.get(f"/api/exports/{export['id']}").json()
    assert ready["state"] == "ready", ready.get("error")
    assert Path(ready["file_path"]).is_file()

    download = client.get(f"/api/exports/{export['id']}/download")
    assert download.status_code == 200
    assert "attachment" in download.headers["content-disposition"]
    assert "rivals-gk-build-up.mp4" in download.headers["content-disposition"]


def test_export_can_mix_clips_from_several_matches(client, tmp_path):
    matches = []
    for name in ("first", "second"):
        src = tmp_path / f"{name}.mp4"
        src.write_bytes(b"\x00src" * 64)
        matches.append(make_match(client, src, title=name))
    clip_ids = [client.post(f"/api/matches/{m['id']}/tags", json={"t": 400.0}).json()["clip_id"]
                for m in matches]
    wait_for_jobs(client)

    export = client.post("/api/exports", json={"name": "Season review", "clip_ids": clip_ids}).json()
    wait_for_jobs(client)
    assert client.get(f"/api/exports/{export['id']}").json()["state"] == "ready"


def test_export_encodes_from_the_original_not_the_proxy(client, source_video, monkeypatch):
    """The proxy exists for scrubbing; shipping it as the deliverable would be a
    silent quality regression."""
    from app.media import ffmpeg

    seen: list[str] = []
    original_run = ffmpeg.run_ffmpeg

    async def spy(cmd, total_s=None, on_progress=None):
        seen.append(" ".join(cmd))
        await original_run(cmd, total_s, on_progress)

    match = make_match(client, source_video)
    clip_id = client.post(f"/api/matches/{match['id']}/tags", json={"t": 600.0}).json()["clip_id"]
    wait_for_jobs(client)
    client.patch(f"/api/clips/{clip_id}", json={"status": "approved"})

    monkeypatch.setattr(ffmpeg, "run_ffmpeg", spy)
    client.post("/api/exports", json={"name": "quality check", "match_id": match["id"]})
    wait_for_jobs(client)

    segment_cmds = [c for c in seen if "libx264" in c]
    assert segment_cmds, "the export must re-encode, not stream-copy the proxy"
    assert str(source_video) in segment_cmds[0]
    assert match["proxy_path"] not in segment_cmds[0]


def test_export_without_approved_clips_is_refused(client, source_video):
    match = make_match(client, source_video)
    resp = client.post("/api/exports", json={"name": "empty", "match_id": match["id"]})
    assert resp.status_code == 400
    assert "no approved clips" in resp.json()["detail"]


def test_export_rejects_unknown_clip_ids(client):
    resp = client.post("/api/exports", json={"name": "bogus", "clip_ids": [999]})
    assert resp.status_code == 400


def test_deleting_a_match_removes_its_tags_clips_and_files(client, source_video):
    match = make_match(client, source_video)
    clip_id = client.post(f"/api/matches/{match['id']}/tags", json={"t": 600.0}).json()["clip_id"]
    wait_for_jobs(client)
    review_path = Path(client.get(f"/api/clips/{clip_id}").json()["review_path"])

    assert client.delete(f"/api/matches/{match['id']}").status_code == 204
    assert client.get("/api/matches").json() == []
    assert client.get(f"/api/clips/{clip_id}").status_code == 404
    assert not review_path.exists()
    assert not Path(match["proxy_path"]).exists()
