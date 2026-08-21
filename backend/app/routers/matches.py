from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException

from ..config import get_settings
from ..db import connect
from ..jobs import notify
from ..pipeline import _safe_unlink, enqueue_ingest
from ..schemas import MatchCreate

router = APIRouter(prefix="/api/matches", tags=["matches"])


def _match_row(match_id: int) -> dict:
    with connect() as conn:
        row = conn.execute("SELECT * FROM match WHERE id = ?", (match_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="match not found")
    return dict(row)


@router.get("")
def list_matches() -> list[dict]:
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT m.*,
                   (SELECT COUNT(*) FROM tag t WHERE t.match_id = m.id) AS tag_count,
                   (SELECT COUNT(*) FROM tag t JOIN clip c ON c.tag_id = t.id
                     WHERE t.match_id = m.id AND c.status = 'approved') AS approved_count
            FROM match m ORDER BY m.id DESC
            """
        ).fetchall()
    return [dict(r) for r in rows]


@router.post("", status_code=201)
async def create_match(payload: MatchCreate) -> dict:
    file_path = None
    if payload.source_type == "file":
        candidate = Path(payload.file_path).expanduser()
        if not candidate.is_file():
            raise HTTPException(status_code=400, detail=f"file not found: {candidate}")
        file_path = str(candidate.resolve())

    with connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO match (title, opponent, date, source_type, source_url, file_path)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (payload.title, payload.opponent, payload.date, payload.source_type,
             payload.source_url, file_path),
        )
        match_id = int(cur.lastrowid)

    await enqueue_ingest(match_id, payload.title)
    await notify("match", match_id)
    return _match_row(match_id)


@router.get("/{match_id}")
def get_match(match_id: int) -> dict:
    return _match_row(match_id)


@router.post("/{match_id}/reingest")
async def reingest(match_id: int) -> dict:
    row = _match_row(match_id)
    await enqueue_ingest(match_id, row["title"])
    await notify("match", match_id)
    return {"ok": True}


@router.delete("/{match_id}", status_code=204, response_model=None)
async def delete_match(match_id: int) -> None:
    settings = get_settings()
    row = _match_row(match_id)
    with connect() as conn:
        clips = conn.execute(
            "SELECT c.review_path, c.final_path FROM clip c JOIN tag t ON t.id = c.tag_id WHERE t.match_id = ?",
            (match_id,),
        ).fetchall()
        conn.execute("DELETE FROM match WHERE id = ?", (match_id,))

    for clip in clips:
        for key in ("review_path", "final_path"):
            if clip[key]:
                _safe_unlink(Path(clip[key]), settings)
    if row["proxy_path"]:
        proxy = Path(row["proxy_path"])
        if proxy.parent.resolve() == settings.proxy_dir.resolve():
            proxy.unlink(missing_ok=True)
    await notify("match", match_id)
