"""ffmpeg/ffprobe wrappers.

Command construction is kept in pure functions (``*_cmd``) so the encoding
strategy can be unit-tested on a machine with no ffmpeg installed; only
``run_ffmpeg``/``probe`` actually touch the binary.
"""
from __future__ import annotations

import asyncio
import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Awaitable, Callable, Sequence

from ..config import Settings, get_settings

ProgressCb = Callable[[float], Awaitable[None]] | None


class MediaError(RuntimeError):
    """ffmpeg/ffprobe failed, or is not installed."""


@dataclass
class MediaInfo:
    duration_s: float
    fps: float
    width: int
    height: int


def _require(binary: str) -> str:
    if shutil.which(binary) is None and not Path(binary).exists():
        raise MediaError(
            f"'{binary}' not found on PATH. Install ffmpeg (and yt-dlp for YouTube "
            f"sources), or point BUC_FFMPEG/BUC_FFPROBE at the binaries."
        )
    return binary


# --------------------------------------------------------------------------- #
# command builders
# --------------------------------------------------------------------------- #

def probe_cmd(src: Path, ffprobe: str = "ffprobe") -> list[str]:
    return [
        ffprobe, "-v", "error",
        "-show_entries", "format=duration",
        "-show_entries", "stream=codec_type,width,height,avg_frame_rate,r_frame_rate,duration",
        "-of", "json", str(src),
    ]


def parse_probe(payload: str) -> MediaInfo:
    data = json.loads(payload)
    streams = data.get("streams", [])
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    if video is None:
        raise MediaError("source has no video stream")

    duration = _to_float(data.get("format", {}).get("duration")) or _to_float(video.get("duration")) or 0.0
    fps = _parse_rate(video.get("avg_frame_rate")) or _parse_rate(video.get("r_frame_rate")) or 25.0
    return MediaInfo(
        duration_s=duration,
        fps=fps,
        width=int(video.get("width") or 0),
        height=int(video.get("height") or 0),
    )


def _to_float(value) -> float | None:
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return f if f > 0 else None


def _parse_rate(rate: str | None) -> float | None:
    if not rate or "/" not in rate:
        return _to_float(rate)
    num, _, den = rate.partition("/")
    try:
        n, d = float(num), float(den)
    except ValueError:
        return None
    return n / d if d else None


def proxy_cmd(src: Path, dst: Path, settings: Settings) -> list[str]:
    """480p proxy: short GOP + faststart so browser seeking is snappy.

    Audio is kept (low bitrate) -- the analyst tags while watching and the
    whistle is a useful cue. It is the *export* that drops audio.
    """
    gop = str(settings.proxy_gop)
    return [
        settings.ffmpeg, "-y", "-hide_banner", "-nostdin",
        "-i", str(src),
        "-vf", f"scale=-2:{settings.proxy_height}",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", str(settings.proxy_crf),
        "-g", gop, "-keyint_min", gop, "-sc_threshold", "0",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "96k", "-ac", "1",
        "-movflags", "+faststart",
        "-progress", "pipe:1", "-nostats",
        str(dst),
    ]


def review_clip_cmd(src: Path, dst: Path, t_start: float, t_end: float, settings: Settings) -> list[str]:
    """Stream-copy cut: instant, but snaps to keyframes (+-1-2s is fine here)."""
    duration = max(t_end - t_start, 0.1)
    return [
        settings.ffmpeg, "-y", "-hide_banner", "-nostdin",
        "-ss", f"{max(t_start, 0.0):.3f}",
        "-i", str(src),
        "-t", f"{duration:.3f}",
        "-c", "copy",
        "-avoid_negative_ts", "make_zero",
        "-movflags", "+faststart",
        "-progress", "pipe:1", "-nostats",
        str(dst),
    ]


def export_segment_cmd(src: Path, dst: Path, t_start: float, t_end: float, settings: Settings) -> list[str]:
    """Frame-exact, uniformly normalized segment for the deliverable.

    ``-ss`` before ``-i`` is still frame-accurate when re-encoding (ffmpeg
    decodes from the preceding keyframe and discards), and much faster than
    seeking after input. Scale+pad+fps+setsar make every segment identical so
    the concat demuxer can stream-copy them together.
    """
    duration = max(t_end - t_start, 0.1)
    w, h = settings.export_width, settings.export_height
    vf = (
        f"scale={w}:{h}:force_original_aspect_ratio=decrease,"
        f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2,"
        f"fps={settings.export_fps},setsar=1"
    )
    cmd = [
        settings.ffmpeg, "-y", "-hide_banner", "-nostdin",
        "-ss", f"{max(t_start, 0.0):.3f}",
        "-i", str(src),
        "-t", f"{duration:.3f}",
        "-vf", vf,
        "-c:v", "libx264", "-preset", settings.export_preset, "-crf", str(settings.export_crf),
        "-pix_fmt", "yuv420p", "-profile:v", "high", "-level", "4.0",
        "-video_track_timescale", "90000",
        "-an",
        "-movflags", "+faststart",
        "-progress", "pipe:1", "-nostats",
        str(dst),
    ]
    return cmd


def concat_cmd(list_file: Path, dst: Path, settings: Settings) -> list[str]:
    """Join uniformly-encoded segments without a second generation loss."""
    return [
        settings.ffmpeg, "-y", "-hide_banner", "-nostdin",
        "-f", "concat", "-safe", "0",
        "-i", str(list_file),
        "-c", "copy",
        "-movflags", "+faststart",
        "-progress", "pipe:1", "-nostats",
        str(dst),
    ]


def write_concat_list(paths: Sequence[Path], list_file: Path) -> Path:
    """concat demuxer list; single quotes in paths are escaped per its syntax."""
    lines = []
    for p in paths:
        escaped = str(p.resolve()).replace("'", r"'\''")
        lines.append(f"file '{escaped}'")
    list_file.parent.mkdir(parents=True, exist_ok=True)
    list_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return list_file


# --------------------------------------------------------------------------- #
# execution
# --------------------------------------------------------------------------- #

async def probe(src: Path, settings: Settings | None = None) -> MediaInfo:
    settings = settings or get_settings()
    _require(settings.ffprobe)
    proc = await asyncio.create_subprocess_exec(
        *probe_cmd(src, settings.ffprobe),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    out, err = await proc.communicate()
    if proc.returncode != 0:
        raise MediaError(f"ffprobe failed for {src.name}: {err.decode(errors='replace')[-500:]}")
    return parse_probe(out.decode())


async def run_ffmpeg(
    cmd: list[str],
    total_s: float | None = None,
    on_progress: ProgressCb = None,
) -> None:
    """Run ffmpeg, translating ``-progress`` output into 0..1 fractions."""
    _require(cmd[0])
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    async def pump_progress() -> None:
        assert proc.stdout is not None
        async for raw in proc.stdout:
            line = raw.decode(errors="replace").strip()
            if not line.startswith("out_time_ms=") or not total_s or on_progress is None:
                continue
            try:
                done_s = int(line.split("=", 1)[1]) / 1_000_000
            except ValueError:
                continue
            await on_progress(min(max(done_s / total_s, 0.0), 0.99))

    async def drain_stderr() -> bytes:
        assert proc.stderr is not None
        return await proc.stderr.read()

    _, err = await asyncio.gather(pump_progress(), drain_stderr())
    await proc.wait()
    if proc.returncode != 0:
        tail = err.decode(errors="replace").strip().splitlines()[-8:]
        raise MediaError("ffmpeg failed:\n" + "\n".join(tail))
    if on_progress is not None:
        await on_progress(1.0)
