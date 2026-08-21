"""The M4 baseline numbers: what the analyst would otherwise count by hand."""
from __future__ import annotations

from conftest import make_match, wait_for_jobs


def _tag(client, match_id: int, t: float) -> dict:
    resp = client.post(f"/api/matches/{match_id}/tags", json={"t": t})
    assert resp.status_code == 201, resp.text
    return resp.json()


def _stats(client, match_id: int) -> dict:
    resp = client.get(f"/api/matches/{match_id}/stats")
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_stats_counts_tags_verdicts_and_corrections(client, source_video):
    match = make_match(client, source_video)
    tags = [_tag(client, match["id"], t) for t in (600.0, 1200.0, 1800.0)]
    client.patch(f"/api/tags/{tags[0]['id']}", json={"t_end": 620.0})
    client.patch(f"/api/clips/{tags[1]['clip_id']}", json={"status": "approved"})
    client.patch(f"/api/clips/{tags[2]['clip_id']}", json={"status": "rejected"})
    wait_for_jobs(client)

    stats = _stats(client, match["id"])
    assert stats["duration_s"] == 5400.0
    assert stats["tags"]["total"] == 3
    assert stats["tags"]["adjusted"] == 1
    assert stats["tags"]["corrections"] == 1
    assert stats["tags"]["adjusted_share"] == round(1 / 3, 3)
    assert stats["clips"]["approved"] == 1
    assert stats["clips"]["rejected"] == 1
    assert stats["clips"]["pending"] == 1
    assert stats["clips"]["reviewed"] == 2
    # Every action happens within the same second here, so the spans are real
    # but zero -- what matters is that they were measured at all.
    assert stats["tags"]["span_s"] == 0
    assert stats["clips"]["span_s"] == 0


def test_repeated_corrections_of_one_tag_all_count(client, source_video):
    match = make_match(client, source_video)
    tag = _tag(client, match["id"], 600.0)
    client.patch(f"/api/tags/{tag['id']}", json={"t_start": 595.0})
    client.patch(f"/api/tags/{tag['id']}", json={"t_end": 620.0})
    wait_for_jobs(client)

    stats = _stats(client, match["id"])
    assert stats["tags"]["adjusted"] == 1
    assert stats["tags"]["corrections"] == 2


def test_editing_only_the_note_is_not_a_correction(client, source_video):
    match = make_match(client, source_video)
    tag = _tag(client, match["id"], 600.0)
    client.patch(f"/api/tags/{tag['id']}", json={"note": "long build-up"})
    wait_for_jobs(client)

    assert _stats(client, match["id"])["tags"]["adjusted"] == 0


def test_moving_a_tag_takes_its_clip_back_out_of_the_reviewed_count(client, source_video):
    match = make_match(client, source_video)
    tag = _tag(client, match["id"], 600.0)
    client.patch(f"/api/clips/{tag['clip_id']}", json={"status": "approved"})
    assert _stats(client, match["id"])["clips"]["reviewed"] == 1

    client.patch(f"/api/tags/{tag['id']}", json={"t_end": 640.0})
    wait_for_jobs(client)
    stats = _stats(client, match["id"])
    assert stats["clips"]["reviewed"] == 0
    assert stats["clips"]["pending"] == 1


def test_taking_back_a_verdict_stops_it_counting_as_reviewed(client, source_video):
    match = make_match(client, source_video)
    tag = _tag(client, match["id"], 600.0)
    client.patch(f"/api/clips/{tag['clip_id']}", json={"status": "approved"})
    client.patch(f"/api/clips/{tag['clip_id']}", json={"status": "pending"})
    wait_for_jobs(client)

    assert _stats(client, match["id"])["clips"]["reviewed"] == 0


def test_padding_verdict_waits_for_enough_tags(client, source_video):
    match = make_match(client, source_video)
    tag = _tag(client, match["id"], 600.0)
    client.patch(f"/api/tags/{tag['id']}", json={"t_start": 595.0})
    wait_for_jobs(client)

    padding = _stats(client, match["id"])["padding"]
    assert padding["verdict"] == "unknown"   # one tag in one is not a signal
    assert padding["suggested_before_s"] is None


def test_padding_that_is_rarely_corrected_is_left_alone(client, source_video):
    match = make_match(client, source_video)
    tags = [_tag(client, match["id"], t) for t in (600.0, 1200.0, 1800.0, 2400.0, 3000.0)]
    client.patch(f"/api/tags/{tags[0]['id']}", json={"t_start": 595.0})
    wait_for_jobs(client)

    padding = _stats(client, match["id"])["padding"]
    assert padding["verdict"] == "fits"      # 1 in 5, at the limit, not over it
    assert padding["suggested_before_s"] is None
    assert padding["before_s"] == 3.0 and padding["after_s"] == 27.0


def test_often_corrected_padding_suggests_the_window_the_analyst_chose(client, source_video):
    match = make_match(client, source_video)
    tags = [_tag(client, match["id"], t) for t in (600.0, 1200.0, 1800.0, 2400.0, 3000.0)]
    # Two of five corrected: past the one-in-five limit the spec calls wrong.
    client.patch(f"/api/tags/{tags[0]['id']}", json={"t_start": 595.0, "t_end": 615.0})
    client.patch(f"/api/tags/{tags[1]['id']}", json={"t_start": 1193.0, "t_end": 1220.0})
    wait_for_jobs(client)

    padding = _stats(client, match["id"])["padding"]
    assert padding["verdict"] == "check"
    assert padding["corrected_sample"] == 2
    assert padding["suggested_before_s"] == 6.0    # median of 5s and 7s
    assert padding["suggested_after_s"] == 17.5    # median of 15s and 20s


def test_clamped_tags_stay_out_of_the_padding_sample(client, source_video):
    match = make_match(client, source_video)
    _tag(client, match["id"], 1.0)       # clamped to 0 at the start
    _tag(client, match["id"], 5399.0)    # clamped to the end of the match
    _tag(client, match["id"], 600.0)
    wait_for_jobs(client)

    assert _stats(client, match["id"])["padding"]["sample"] == 1


def test_a_window_supplied_whole_says_nothing_about_the_padding(client, source_video):
    match = make_match(client, source_video)
    client.post(f"/api/matches/{match['id']}/tags", json={"t_start": 600.0, "t_end": 640.0})
    wait_for_jobs(client)

    assert _stats(client, match["id"])["padding"]["sample"] == 0


def test_export_render_time_lands_in_the_total(client, source_video):
    match = make_match(client, source_video)
    tag = _tag(client, match["id"], 600.0)
    client.patch(f"/api/clips/{tag['clip_id']}", json={"status": "approved"})
    resp = client.post("/api/exports", json={"name": "GK build-up", "match_id": match["id"]})
    assert resp.status_code == 201
    wait_for_jobs(client)

    stats = _stats(client, match["id"])
    assert stats["exports"] == {
        "count": 1, "ready": 1, "last_render_s": 0, "last_name": "GK build-up",
    }
    assert stats["totals"]["measured_s"] == 0
    assert stats["totals"]["ratio_of_match"] == 0.0


def test_a_failed_export_is_still_timed(client, source_video, monkeypatch):
    match = make_match(client, source_video)
    tag = _tag(client, match["id"], 600.0)
    client.patch(f"/api/clips/{tag['clip_id']}", json={"status": "approved"})

    from app.media import ffmpeg

    async def boom(cmd, total_s=None, on_progress=None):
        raise ffmpeg.MediaError("no encoder")

    monkeypatch.setattr(ffmpeg, "run_ffmpeg", boom)
    client.post("/api/exports", json={"name": "Broken", "match_id": match["id"]})
    wait_for_jobs(client)

    exports = _stats(client, match["id"])["exports"]
    assert exports["count"] == 1 and exports["ready"] == 0
    assert exports["last_render_s"] == 0


def test_stats_for_a_match_that_does_not_exist_is_a_404(client):
    assert client.get("/api/matches/999/stats").status_code == 404


def test_a_match_with_no_tags_reports_nothing_rather_than_zero(client, source_video):
    match = make_match(client, source_video)
    stats = _stats(client, match["id"])
    assert stats["tags"]["total"] == 0
    assert stats["tags"]["adjusted_share"] is None
    assert stats["tags"]["span_s"] is None
    assert stats["totals"]["measured_s"] is None
    assert stats["totals"]["ratio_of_match"] is None


def test_padding_already_matching_the_corrections_is_not_suggested_again(client, source_video, monkeypatch):
    match = make_match(client, source_video)
    tags = [_tag(client, match["id"], t) for t in (600.0, 1200.0, 1800.0, 2400.0, 3000.0)]
    client.patch(f"/api/tags/{tags[0]['id']}", json={"t_start": 594.0, "t_end": 621.0})
    client.patch(f"/api/tags/{tags[1]['id']}", json={"t_start": 1194.0, "t_end": 1221.0})
    wait_for_jobs(client)

    from app import config

    monkeypatch.setenv("BUC_TAG_PAD_BEFORE", "6")
    monkeypatch.setenv("BUC_TAG_PAD_AFTER", "21")
    config.reset_settings()

    padding = _stats(client, match["id"])["padding"]
    # The correction rate is this match's history and stays high; the advice has
    # already been taken, so there is nothing left to advise.
    assert padding["verdict"] == "check"
    assert padding["corrected_median_before_s"] == 6.0
    assert padding["suggested_before_s"] is None
    assert padding["suggested_after_s"] is None


def test_a_database_from_before_the_measurement_columns_still_opens(fake_media):
    """The analyst's database predates these columns. It has to migrate, and the
    rows already in it simply have nothing to report."""
    from fastapi.testclient import TestClient

    from app.config import get_settings
    from app.db import MIGRATIONS, SCHEMA, _connect_path
    from app.main import app

    settings = get_settings()
    settings.ensure_dirs()
    old = _connect_path(settings.db_path)
    old.executescript(SCHEMA)
    for table, column, _ in MIGRATIONS:      # rewind to the pre-migration shape
        old.execute(f"ALTER TABLE {table} DROP COLUMN {column}")
    old.execute(
        "INSERT INTO match (id, title, source_type, file_path, duration_s, fps, ingest_state) "
        "VALUES (1, 'Last season', 'file', '/tmp/old.mp4', 5400, 25, 'ready')"
    )
    old.execute("INSERT INTO tag (id, match_id, t_start, t_end) VALUES (1, 1, 597, 627)")
    old.execute("INSERT INTO clip (id, tag_id, status) VALUES (1, 1, 'approved')")
    old.close()

    with TestClient(app) as client:
        stats = _stats(client, 1)
        assert stats["tags"]["total"] == 1
        assert stats["tags"]["adjusted"] == 0
        assert stats["clips"]["approved"] == 1
        assert stats["clips"]["reviewed"] == 0        # no verdict timestamp to read
        assert stats["padding"]["sample"] == 0        # no keystroke moment to read
        # and the row is still editable through the normal path
        assert client.patch("/api/tags/1", json={"t_end": 630.0}).status_code == 200
        assert _stats(client, 1)["tags"]["adjusted"] == 1
