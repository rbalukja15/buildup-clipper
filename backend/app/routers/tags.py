from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ..config import get_settings
from ..db import connect
from ..jobs import notify
from ..pipeline import enqueue_clip_render, invalidate_clip
from ..schemas import TagCreate, TagUpdate

router = APIRouter(prefix="/api", tags=["tags"])

TAG_SELECT = """
SELECT t.*, c.id AS clip_id, c.status AS clip_status, c.render_state, c.order_index
FROM tag t LEFT JOIN clip c ON c.tag_id = t.id
"""


def _tag(tag_id: int) -> dict:
    with connect() as conn:
        row = conn.execute(TAG_SELECT + " WHERE t.id = ?", (tag_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="tag not found")
    return dict(row)


@router.get("/matches/{match_id}/tags")
def list_tags(match_id: int) -> list[dict]:
    with connect() as conn:
        rows = conn.execute(TAG_SELECT + " WHERE t.match_id = ? ORDER BY t.t_start", (match_id,)).fetchall()
    return [dict(r) for r in rows]


@router.post("/matches/{match_id}/tags", status_code=201)
async def create_tag(match_id: int, payload: TagCreate) -> dict:
    settings = get_settings()
    with connect() as conn:
        match = conn.execute("SELECT duration_s FROM match WHERE id = ?", (match_id,)).fetchone()
        if match is None:
            raise HTTPException(status_code=404, detail="match not found")

        padded = payload.t is not None and payload.t_start is None
        if padded:
            t_start = max(payload.t - settings.tag_pad_before_s, 0.0)
            t_end = payload.t + settings.tag_pad_after_s
        else:
            t_start, t_end = max(payload.t_start, 0.0), payload.t_end
        if match["duration_s"]:
            t_end = min(t_end, float(match["duration_s"]))
        if t_end <= t_start:
            raise HTTPException(status_code=400, detail="tag window is empty")

        # A tag without its clip would be invisible in review, so the pair is
        # written atomically.
        conn.execute("BEGIN IMMEDIATE")
        try:
            # t_marked is the raw keystroke moment, kept only when the padding
            # produced the window. It is what lets the stats say which padding
            # the analyst actually settled on, rather than only that he
            # corrected something -- a window supplied whole says nothing about
            # the padding, so it stores no moment.
            tag_id = int(conn.execute(
                "INSERT INTO tag (match_id, t_start, t_end, category, source, note, t_marked) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (match_id, t_start, t_end, payload.category, payload.source, payload.note,
                 payload.t if padded else None),
            ).lastrowid)
            next_index = conn.execute(
                "SELECT COALESCE(MAX(c.order_index), -1) + 1 FROM clip c "
                "JOIN tag t ON t.id = c.tag_id WHERE t.match_id = ?",
                (match_id,),
            ).fetchone()[0]
            clip_id = int(conn.execute(
                "INSERT INTO clip (tag_id, order_index) VALUES (?, ?)", (tag_id, next_index)
            ).lastrowid)
        except Exception:
            conn.execute("ROLLBACK")
            raise
        conn.execute("COMMIT")

    await enqueue_clip_render(clip_id, f"clip {clip_id}")
    await notify("tag", tag_id)
    return _tag(tag_id)


@router.patch("/tags/{tag_id}")
async def update_tag(tag_id: int, payload: TagUpdate) -> dict:
    current = _tag(tag_id)
    t_start = current["t_start"] if payload.t_start is None else max(payload.t_start, 0.0)
    t_end = current["t_end"] if payload.t_end is None else payload.t_end
    if t_end <= t_start:
        raise HTTPException(status_code=400, detail="t_end must be greater than t_start")

    window_moved = (t_start, t_end) != (current["t_start"], current["t_end"])
    with connect() as conn:
        # adjust_count counts I/O corrections: the signal for whether the
        # default padding fits this footage.
        conn.execute(
            "UPDATE tag SET t_start = ?, t_end = ?, note = ?, adjust_count = adjust_count + ? WHERE id = ?",
            (t_start, t_end, current["note"] if payload.note is None else payload.note,
             1 if window_moved else 0, tag_id),
        )

    # Tags are the source of truth: a moved window invalidates the derived clip.
    if window_moved and current["clip_id"]:
        invalidate_clip(current["clip_id"])
        # The verdict was about the old cut. Approving a clip and then trimming
        # it must not ship the untrimmed decision -- and a clip rejected for a
        # bad cut deserves a fresh look once the cut is fixed. (Deliberately
        # not inside invalidate_clip: a plain re-render keeps its verdict.)
        with connect() as conn:
            conn.execute(
                "UPDATE clip SET status = 'pending', reviewed_at = NULL WHERE id = ?",
                (current["clip_id"],),
            )
        await enqueue_clip_render(current["clip_id"], f"clip {current['clip_id']}")
    await notify("tag", tag_id)
    return _tag(tag_id)


@router.delete("/tags/{tag_id}", status_code=204, response_model=None)
async def delete_tag(tag_id: int) -> None:
    current = _tag(tag_id)
    if current["clip_id"]:
        invalidate_clip(current["clip_id"])
    with connect() as conn:
        conn.execute("DELETE FROM tag WHERE id = ?", (tag_id,))
    await notify("tag", tag_id)


@router.delete("/matches/{match_id}/tags/last", status_code=204, response_model=None)
async def delete_last_tag(match_id: int) -> None:
    """Backs the `U` hotkey: undo the most recently created tag."""
    with connect() as conn:
        row = conn.execute(
            "SELECT id FROM tag WHERE match_id = ? ORDER BY id DESC LIMIT 1", (match_id,)
        ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="no tags to undo")
    await delete_tag(int(row["id"]))
