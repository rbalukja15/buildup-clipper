from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from ..db import connect
from ..jobs import notify
from ..pipeline import enqueue_clip_render, invalidate_clip
from ..schemas import ClipReorder, ClipUpdate

router = APIRouter(prefix="/api/clips", tags=["clips"])

CLIP_SELECT = """
SELECT c.*, t.match_id, t.t_start, t.t_end, t.note, t.category, t.source,
       m.title AS match_title, m.opponent
FROM clip c
JOIN tag t ON t.id = c.tag_id
JOIN match m ON m.id = t.match_id
"""


def _clip(clip_id: int) -> dict:
    with connect() as conn:
        row = conn.execute(CLIP_SELECT + " WHERE c.id = ?", (clip_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="clip not found")
    return dict(row)


@router.get("")
def list_clips(
    match_id: int | None = Query(default=None),
    status: str | None = Query(default=None),
) -> list[dict]:
    where, params = [], []
    if match_id is not None:
        where.append("t.match_id = ?")
        params.append(match_id)
    if status is not None:
        where.append("c.status = ?")
        params.append(status)
    sql = CLIP_SELECT + (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY c.order_index, c.id"
    with connect() as conn:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]


@router.get("/{clip_id}")
def get_clip(clip_id: int) -> dict:
    return _clip(clip_id)


@router.patch("/{clip_id}")
async def update_clip(clip_id: int, payload: ClipUpdate) -> dict:
    clip = _clip(clip_id)
    with connect() as conn:
        if payload.status is not None:
            conn.execute("UPDATE clip SET status = ? WHERE id = ?", (payload.status, clip_id))
        if payload.note is not None:
            # The note lives on the tag -- one source of truth, survives re-render.
            conn.execute("UPDATE tag SET note = ? WHERE id = ?", (payload.note, clip["tag_id"]))
    await notify("clip", clip_id)
    return _clip(clip_id)


@router.post("/reorder")
async def reorder(payload: ClipReorder) -> dict:
    with connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            for position, clip_id in enumerate(payload.clip_ids):
                conn.execute("UPDATE clip SET order_index = ? WHERE id = ?", (position, clip_id))
        except Exception:
            conn.execute("ROLLBACK")
            raise
        conn.execute("COMMIT")
    await notify("clip", None)
    return {"ok": True}


@router.post("/{clip_id}/rerender")
async def rerender(clip_id: int) -> dict:
    _clip(clip_id)
    invalidate_clip(clip_id)
    await enqueue_clip_render(clip_id, f"clip {clip_id}")
    await notify("clip", clip_id)
    return {"ok": True}
