"""The encoding strategy is the product's core; assert the commands directly."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import Settings
from app.media import ffmpeg, ytdlp


@pytest.fixture
def settings(tmp_path):
    return Settings(data_dir=tmp_path)


def test_proxy_is_480p_faststart_and_short_gop(settings):
    cmd = ffmpeg.proxy_cmd(Path("/in.mp4"), Path("/out.mp4"), settings)
    assert "scale=-2:480" in cmd
    assert "+faststart" in cmd
    gop = cmd[cmd.index("-g") + 1]
    assert gop == str(settings.proxy_gop)
    assert cmd[cmd.index("-keyint_min") + 1] == gop
    assert cmd[cmd.index("-sc_threshold") + 1] == "0"


def test_review_clip_stream_copies_and_seeks_before_input(settings):
    cmd = ffmpeg.review_clip_cmd(Path("/in.mp4"), Path("/out.mp4"), 100.0, 130.0, settings)
    assert cmd[cmd.index("-ss") + 1] == "100.000"
    assert cmd.index("-ss") < cmd.index("-i"), "input seek must precede -i to stay instant"
    assert cmd[cmd.index("-t") + 1] == "30.000"
    assert cmd[cmd.index("-c") + 1] == "copy"


def test_review_clip_clamps_negative_start(settings):
    cmd = ffmpeg.review_clip_cmd(Path("/in.mp4"), Path("/out.mp4"), -2.0, 25.0, settings)
    assert cmd[cmd.index("-ss") + 1] == "0.000"


def test_export_segment_normalizes_every_source_identically(settings):
    cmd = ffmpeg.export_segment_cmd(Path("/in.mp4"), Path("/out.mp4"), 10.0, 40.0, settings)
    vf = cmd[cmd.index("-vf") + 1]
    assert "scale=1280:720:force_original_aspect_ratio=decrease" in vf
    assert "pad=1280:720" in vf
    assert "fps=30" in vf and "setsar=1" in vf
    assert cmd[cmd.index("-c:v") + 1] == "libx264"
    assert cmd[cmd.index("-pix_fmt") + 1] == "yuv420p"
    assert cmd[cmd.index("-video_track_timescale") + 1] == "90000"
    assert "-an" in cmd, "uniform audio-free segments concat without stream mismatch"
    assert cmd[cmd.index("-t") + 1] == "30.000"


def test_export_dimensions_follow_settings(tmp_path):
    settings = Settings(data_dir=tmp_path, export_width=1920, export_height=1080, export_fps=25)
    cmd = ffmpeg.export_segment_cmd(Path("/in.mp4"), Path("/o.mp4"), 0.0, 5.0, settings)
    vf = cmd[cmd.index("-vf") + 1]
    assert "scale=1920:1080" in vf and "fps=25" in vf


def test_zero_length_window_never_produces_a_zero_duration_cut(settings):
    cmd = ffmpeg.review_clip_cmd(Path("/in.mp4"), Path("/out.mp4"), 10.0, 10.0, settings)
    assert float(cmd[cmd.index("-t") + 1]) > 0


def test_concat_stream_copies(settings, tmp_path):
    cmd = ffmpeg.concat_cmd(tmp_path / "list.txt", tmp_path / "out.mp4", settings)
    assert cmd[cmd.index("-f") + 1] == "concat"
    assert cmd[cmd.index("-safe") + 1] == "0"
    assert cmd[cmd.index("-c") + 1] == "copy"


def test_concat_list_escapes_quotes_in_paths(tmp_path):
    weird = tmp_path / "Mario's clips.mp4"
    weird.write_bytes(b"x")
    listing = ffmpeg.write_concat_list([weird], tmp_path / "list.txt").read_text()
    assert listing.startswith("file '")
    assert r"'\''" in listing, "an unescaped apostrophe would break the demuxer"


def test_parse_probe_reads_duration_and_frame_rate():
    payload = json.dumps({
        "format": {"duration": "5400.5"},
        "streams": [
            {"codec_type": "audio"},
            {"codec_type": "video", "width": 1920, "height": 1080, "avg_frame_rate": "30000/1001"},
        ],
    })
    info = ffmpeg.parse_probe(payload)
    assert info.duration_s == pytest.approx(5400.5)
    assert info.fps == pytest.approx(29.97, abs=0.01)
    assert (info.width, info.height) == (1920, 1080)


def test_parse_probe_falls_back_when_avg_frame_rate_is_degenerate():
    payload = json.dumps({
        "format": {"duration": "60"},
        "streams": [{"codec_type": "video", "width": 640, "height": 360,
                     "avg_frame_rate": "0/0", "r_frame_rate": "25/1"}],
    })
    assert ffmpeg.parse_probe(payload).fps == pytest.approx(25.0)


def test_parse_probe_rejects_audio_only_source():
    payload = json.dumps({"format": {"duration": "60"}, "streams": [{"codec_type": "audio"}]})
    with pytest.raises(ffmpeg.MediaError):
        ffmpeg.parse_probe(payload)


def test_missing_binary_gives_an_actionable_message():
    with pytest.raises(ffmpeg.MediaError, match="not found on PATH"):
        ffmpeg._require("definitely-not-a-real-binary-xyz")


def test_ytdlp_progress_parsing():
    assert ytdlp.parse_percent("[download]  42.5% of 1.20GiB at 3.00MiB/s") == pytest.approx(0.425)
    assert ytdlp.parse_percent("[info] downloading format") is None


def test_ytdlp_caps_resolution_and_forces_mp4(tmp_path):
    settings = Settings(data_dir=tmp_path)
    cmd = ytdlp.download_cmd("https://youtu.be/abc", tmp_path / "match_1", settings)
    assert "--no-playlist" in cmd
    assert cmd[cmd.index("--merge-output-format") + 1] == "mp4"
    assert "height<=1080" in cmd[cmd.index("-f") + 1]
    assert cmd[cmd.index("-o") + 1].endswith("match_1.%(ext)s")


# --------------------------------------------------------------------------- #
# finding yt-dlp -- the documented dev command runs the venv interpreter
# directly, so PATH alone does not find a pip-installed yt-dlp
# --------------------------------------------------------------------------- #

def test_ytdlp_is_found_beside_the_running_interpreter(tmp_path, monkeypatch):
    """The venv case: `./.venv/bin/uvicorn app.main:app` never puts the venv's
    bin directory on PATH."""
    import sys

    venv_bin = tmp_path / "venv" / "bin"
    venv_bin.mkdir(parents=True)
    (venv_bin / "yt-dlp").write_text("#!/bin/sh\n")
    (venv_bin / "python").write_text("")

    monkeypatch.setattr(sys, "executable", str(venv_bin / "python"))
    monkeypatch.setattr(ytdlp.shutil, "which", lambda _name: None)   # nothing on PATH

    assert ytdlp.resolve_ytdlp(Settings(data_dir=tmp_path)) == [str(venv_bin / "yt-dlp")]


def test_an_explicit_override_wins(tmp_path):
    settings = Settings(data_dir=tmp_path, ytdlp="/opt/tools/yt-dlp")
    assert ytdlp.resolve_ytdlp(settings) == ["/opt/tools/yt-dlp"]


def test_falls_back_to_the_module_in_this_interpreter(tmp_path, monkeypatch):
    import sys

    monkeypatch.setattr(sys, "executable", str(tmp_path / "python"))
    monkeypatch.setattr(ytdlp.shutil, "which", lambda _name: None)
    monkeypatch.setattr(ytdlp.importlib.util, "find_spec", lambda _name: object())

    assert ytdlp.resolve_ytdlp(Settings(data_dir=tmp_path)) == [sys.executable, "-m", "yt_dlp"]


def test_a_missing_ytdlp_says_what_to_do(tmp_path, monkeypatch):
    import sys

    monkeypatch.setattr(sys, "executable", str(tmp_path / "python"))
    monkeypatch.setattr(ytdlp.shutil, "which", lambda _name: None)
    monkeypatch.setattr(ytdlp.importlib.util, "find_spec", lambda _name: None)

    with pytest.raises(ffmpeg.MediaError, match="pip install"):
        ytdlp.resolve_ytdlp(Settings(data_dir=tmp_path))
