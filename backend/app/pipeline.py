"""Job bodies: ingest, clip render, export render.

Tags are the source of truth; clips are derived artifacts. Anything that
changes a tag's window invalidates its clip and schedules a re-render.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path

from .config import get_settings
from .db import connect
from .jobs import Job, notify, queue
from .media import ffmpeg, ytdlp

log = logging.getLogger("buc.pipeline")


def _slug(text: str, fallback: str = "export") -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "-", text or "").strip("-").lower()
    return (s or fallback)[:60]


# --------------------------------------------------------------------------- #
# ingest
# --------------------------------------------------------------------------- #

def _set_match_state(match_id: int, state: str, error: str | None = None) -> None:
    with connect() as conn:
        conn.execute(
            "UPDATE match SET ingest_state = ?, ingest_error = ? WHERE id = ?",
            (state, error, match_id),
        )


async def ingest_match(job: Job) -> None:
    """Download (if URL) -> probe -> 480p proxy."""
    settings = get_settings()
    match_id = job.entity_id
    with connect() as conn:
        row = conn.execute("SELECT * FROM match WHERE id = ?", (match_id,)).fetchone()
    if row is None:
        raise RuntimeError(f"match {match_id} disappeared")

    try:
        source = Path(row["file_path"]) if row["file_path"] else None

        if row["source_type"] == "youtube" and (source is None or not source.exists()):
            _set_match_state(match_id, "downloading")
            await notify("match", match_id)
            job.label = "Downloading source"
            source = await ytdlp.download(
                row["source_url"],
                settings.source_dir / f"match_{match_id}",
                on_progress=lambda p: job.set_progress(p * 0.45),
                settings=settings,
            )
            with connect() as conn:
                conn.execute("UPDATE match SET file_path = ? WHERE id = ?", (str(source), match_id))

        if source is None or not source.exists():
            raise ffmpeg.MediaError(f"source file not found: {source}")

        _set_match_state(match_id, "probing")
        await notify("match", match_id)
        info = await ffmpeg.probe(source, settings)
        with connect() as conn:
            conn.execute(
                "UPDATE match SET duration_s = ?, fps = ? WHERE id = ?",
                (info.duration_s, info.fps, match_id),
            )
        await job.set_progress(0.5)

        _set_match_state(match_id, "proxying")
        await notify("match", match_id)
        job.label = "Building 480p proxy"
        proxy_path = settings.proxy_dir / f"match_{match_id}.mp4"
        await ffmpeg.run_ffmpeg(
            ffmpeg.proxy_cmd(source, proxy_path, settings),
            total_s=info.duration_s or None,
            on_progress=lambda p: job.set_progress(0.5 + p * 0.5),
        )

        with connect() as conn:
            conn.execute(
                "UPDATE match SET proxy_path = ?, ingest_state = 'ready', ingest_error = NULL WHERE id = ?",
                (str(proxy_path), match_id),
            )
        await notify("match", match_id)
    except Exception as exc:  # noqa: BLE001 -- state is surfaced in the UI
        _set_match_state(match_id, "failed", str(exc))
        await notify("match", match_id)
        raise


async def enqueue_ingest(match_id: int, title: str) -> Job:
    _set_match_state(match_id, "pending")
    return await queue.submit("ingest", match_id, f"Ingest: {title}", ingest_match)


# --------------------------------------------------------------------------- #
# review clips
# --------------------------------------------------------------------------- #

async def render_clip(job: Job) -> None:
    settings = get_settings()
    clip_id = job.entity_id
    with connect() as conn:
        row = conn.execute(
            """
            SELECT c.id, t.t_start, t.t_end, m.proxy_path, m.file_path, m.title
            FROM clip c
            JOIN tag t ON t.id = c.tag_id
            JOIN match m ON m.id = t.match_id
            WHERE c.id = ?
            """,
            (clip_id,),
        ).fetchone()
    if row is None:
        return  # tag (and clip) deleted while queued -- nothing to do

    # Review clips are cut from the proxy: it is small, local, and already has
    # dense keyframes, so the cut lands close to the requested window.
    src = Path(row["proxy_path"] or row["file_path"] or "")
    dst = settings.clip_dir / f"clip_{clip_id}.mp4"
    try:
        with connect() as conn:
            conn.execute("UPDATE clip SET render_state = 'rendering', render_error = NULL WHERE id = ?", (clip_id,))
        await notify("clip", clip_id)
        if not src.exists():
            raise ffmpeg.MediaError(f"source for clip {clip_id} not found: {src}")

        await ffmpeg.run_ffmpeg(
            ffmpeg.review_clip_cmd(src, dst, row["t_start"], row["t_end"], settings),
            total_s=max(row["t_end"] - row["t_start"], 0.1),
            on_progress=job.set_progress,
        )
        with connect() as conn:
            conn.execute(
                "UPDATE clip SET review_path = ?, render_state = 'ready', render_error = NULL WHERE id = ?",
                (str(dst), clip_id),
            )
        await notify("clip", clip_id)
    except Exception as exc:  # noqa: BLE001
        with connect() as conn:
            conn.execute(
                "UPDATE clip SET render_state = 'failed', render_error = ? WHERE id = ?",
                (str(exc), clip_id),
            )
        await notify("clip", clip_id)
        raise


async def enqueue_clip_render(clip_id: int, label: str = "clip") -> Job:
    return await queue.submit("clip", clip_id, f"Render {label}", render_clip)


def invalidate_clip(clip_id: int) -> None:
    """A tag moved: throw away the derived files and mark the clip pending."""
    settings = get_settings()
    with connect() as conn:
        row = conn.execute("SELECT review_path, final_path FROM clip WHERE id = ?", (clip_id,)).fetchone()
        if row is None:
            return
        for key in ("review_path", "final_path"):
            if row[key]:
                _safe_unlink(Path(row[key]), settings)
        conn.execute(
            "UPDATE clip SET review_path = NULL, final_path = NULL, render_state = 'pending', "
            "render_error = NULL WHERE id = ?",
            (clip_id,),
        )


def _safe_unlink(path: Path, settings) -> None:
    """Only ever delete inside our own media tree."""
    try:
        resolved = path.resolve()
    except OSError:
        return
    if not any(_is_within(resolved, root) for root in (settings.clip_dir, settings.export_dir, settings.work_dir)):
        return
    try:
        resolved.unlink(missing_ok=True)
    except OSError:
        log.warning("could not delete %s", resolved)


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root.resolve())
    except ValueError:
        return False
    return True


# --------------------------------------------------------------------------- #
# export
# --------------------------------------------------------------------------- #

async def render_export(job: Job) -> None:
    """Re-encode each selected clip frame-exact and uniform, then concat."""
    settings = get_settings()
    export_id = job.entity_id
    with connect() as conn:
        export = conn.execute("SELECT * FROM export WHERE id = ?", (export_id,)).fetchone()
        members = conn.execute(
            """
            SELECT c.id AS clip_id, c.final_path, t.t_start, t.t_end,
                   m.file_path, m.proxy_path, ec.position
            FROM export_clip ec
            JOIN clip c ON c.id = ec.clip_id
            JOIN tag t ON t.id = c.tag_id
            JOIN match m ON m.id = t.match_id
            WHERE ec.export_id = ?
            ORDER BY ec.position
            """,
            (export_id,),
        ).fetchall()
    if export is None:
        raise RuntimeError(f"export {export_id} disappeared")
    if not members:
        raise RuntimeError("export has no clips")

    try:
        with connect() as conn:
            conn.execute("UPDATE export SET state = 'rendering', error = NULL WHERE id = ?", (export_id,))
        await notify("export", export_id)

        segments: list[Path] = []
        total = len(members)
        for i, m in enumerate(members):
            # Segments come from the ORIGINAL source, not the 480p proxy --
            # the proxy exists for scrubbing, the deliverable must not inherit it.
            src = Path(m["file_path"] or "")
            if not src.exists():
                raise ffmpeg.MediaError(f"original source missing for clip {m['clip_id']}: {src}")
            seg = settings.clip_dir / f"clip_{m['clip_id']}_final.mp4"
            if not (m["final_path"] and Path(m["final_path"]).exists()):
                job.label = f"Encoding clip {i + 1}/{total}"
                await ffmpeg.run_ffmpeg(
                    ffmpeg.export_segment_cmd(src, seg, m["t_start"], m["t_end"], settings),
                    total_s=max(m["t_end"] - m["t_start"], 0.1),
                    on_progress=lambda p, i=i: job.set_progress((i + p) / (total + 1)),
                )
                with connect() as conn:
                    conn.execute("UPDATE clip SET final_path = ? WHERE id = ?", (str(seg), m["clip_id"]))
            else:
                seg = Path(m["final_path"])
            segments.append(seg)
            await job.set_progress((i + 1) / (total + 1))

        job.label = "Joining deliverable"
        list_file = settings.work_dir / f"export_{export_id}.txt"
        ffmpeg.write_concat_list(segments, list_file)
        out = settings.export_dir / f"export_{export_id}_{_slug(export['name'])}.mp4"
        await ffmpeg.run_ffmpeg(ffmpeg.concat_cmd(list_file, out, settings))
        list_file.unlink(missing_ok=True)

        with connect() as conn:
            conn.execute(
                "UPDATE export SET file_path = ?, state = 'ready', error = NULL WHERE id = ?",
                (str(out), export_id),
            )
        await notify("export", export_id)
    except Exception as exc:  # noqa: BLE001
        with connect() as conn:
            conn.execute("UPDATE export SET state = 'failed', error = ? WHERE id = ?", (str(exc), export_id))
        await notify("export", export_id)
        raise


async def enqueue_export(export_id: int, name: str) -> Job:
    return await queue.submit("export", export_id, f"Export: {name}", render_export)
