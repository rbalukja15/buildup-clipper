"""YouTube ingestion via yt-dlp."""
from __future__ import annotations

import asyncio
import re
import shutil
from pathlib import Path

from ..config import Settings, get_settings
from .ffmpeg import MediaError, ProgressCb

_PCT = re.compile(r"\[download\]\s+(\d{1,3}(?:\.\d+)?)%")


def download_cmd(url: str, out_stem: Path, settings: Settings, max_height: int = 1080) -> list[str]:
    """Prefer a single mp4 at <=1080p; the proxy is what gets watched anyway,
    so there is no point pulling 4K over a hotel wifi."""
    return [
        settings.ytdlp,
        "--no-playlist",
        "--newline",
        "--no-part",
        "-f", f"bv*[height<={max_height}]+ba/b[height<={max_height}]/bv*+ba/b",
        "--merge-output-format", "mp4",
        "-o", f"{out_stem}.%(ext)s",
        url,
    ]


def parse_percent(line: str) -> float | None:
    m = _PCT.search(line)
    return float(m.group(1)) / 100.0 if m else None


async def download(url: str, out_stem: Path, on_progress: ProgressCb = None,
                   settings: Settings | None = None) -> Path:
    settings = settings or get_settings()
    if shutil.which(settings.ytdlp) is None and not Path(settings.ytdlp).exists():
        raise MediaError(
            f"'{settings.ytdlp}' not found on PATH. Install yt-dlp, or use a local "
            f"file source instead of a YouTube URL."
        )
    out_stem.parent.mkdir(parents=True, exist_ok=True)
    for stale in out_stem.parent.glob(f"{out_stem.name}.*"):
        stale.unlink()

    proc = await asyncio.create_subprocess_exec(
        *download_cmd(url, out_stem, settings),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    tail: list[str] = []
    assert proc.stdout is not None
    async for raw in proc.stdout:
        line = raw.decode(errors="replace").strip()
        tail.append(line)
        del tail[:-15]
        pct = parse_percent(line)
        if pct is not None and on_progress is not None:
            await on_progress(min(pct, 0.99))
    await proc.wait()
    if proc.returncode != 0:
        raise MediaError("yt-dlp failed:\n" + "\n".join(tail[-8:]))

    produced = sorted(out_stem.parent.glob(f"{out_stem.name}.*"))
    if not produced:
        raise MediaError("yt-dlp reported success but produced no file")
    return produced[0]
