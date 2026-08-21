from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException
from starlette.requests import Request

from ..config import get_settings
from ..db import connect
from ..jobs import notify
from ..pipeline import _safe_unlink, _slug, enqueue_export
from ..ranged import serve_media
from ..schemas import ExportCreate

router = APIRouter(prefix="/api/exports", tags=["exports"])


def _export(export_id: int) -> dict:
    with connect() as conn:
        row = conn.execute("SELECT * FROM export WHERE id = ?", (export_id,)).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="export not found")
        clips = conn.execute(
            """
            SELECT ec.position, c.id AS clip_id, t.t_start, t.t_end, t.note, m.title AS match_title
            FROM export_clip ec
            JOIN clip c ON c.id = ec.clip_id
            JOIN tag t ON t.id = c.tag_id
            JOIN match m ON m.id = t.match_id
            WHERE ec.export_id = ? ORDER BY ec.position
            """,
            (export_id,),
        ).fetchall()
    out = dict(row)
    out["clips"] = [dict(c) for c in clips]
    return out


@router.get("")
def list_exports() -> list[dict]:
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT e.*, (SELECT COUNT(*) FROM export_clip ec WHERE ec.export_id = e.id) AS clip_count
            FROM export e ORDER BY e.id DESC
            """
        ).fetchall()
    return [dict(r) for r in rows]


@router.post("", status_code=201)
async def create_export(payload: ExportCreate) -> dict:
    """Clip selection is explicit, or defaults to every approved clip of a match
    in review order. Exports can mix matches -- the sample deliverable did."""
    with connect() as conn:
        clip_ids = payload.clip_ids
        if not clip_ids:
            if payload.match_id is None:
                raise HTTPException(status_code=400, detail="provide clip_ids or match_id")
            clip_ids = [
                int(r["id"])
                for r in conn.execute(
                    """
                    SELECT c.id FROM clip c JOIN tag t ON t.id = c.tag_id
                    WHERE t.match_id = ? AND c.status = 'approved'
                    ORDER BY c.order_index, c.id
                    """,
                    (payload.match_id,),
                ).fetchall()
            ]
        if not clip_ids:
            raise HTTPException(status_code=400, detail="no approved clips to export")

        found = {
            int(r["id"])
            for r in conn.execute(
                f"SELECT id FROM clip WHERE id IN ({','.join('?' * len(clip_ids))})", clip_ids
            ).fetchall()
        }
        missing = [c for c in clip_ids if c not in found]
        if missing:
            raise HTTPException(status_code=400, detail=f"unknown clip ids: {missing}")

        export_id = int(conn.execute("INSERT INTO export (name) VALUES (?)", (payload.name,)).lastrowid)
        conn.executemany(
            "INSERT INTO export_clip (export_id, clip_id, position) VALUES (?, ?, ?)",
            [(export_id, clip_id, position) for position, clip_id in enumerate(clip_ids)],
        )

    await enqueue_export(export_id, payload.name)
    await notify("export", export_id)
    return _export(export_id)


@router.get("/{export_id}")
def get_export(export_id: int) -> dict:
    return _export(export_id)


@router.post("/{export_id}/rerender")
async def rerender_export(export_id: int) -> dict:
    row = _export(export_id)
    await enqueue_export(export_id, row["name"])
    await notify("export", export_id)
    return {"ok": True}


@router.get("/{export_id}/download")
def download_export(export_id: int, request: Request):
    row = _export(export_id)
    if not row["file_path"]:
        raise HTTPException(status_code=409, detail="export is not ready yet")
    return serve_media(Path(row["file_path"]), request, download_name=f"{_slug(row['name'])}.mp4")


@router.delete("/{export_id}", status_code=204, response_model=None)
async def delete_export(export_id: int) -> None:
    row = _export(export_id)
    with connect() as conn:
        conn.execute("DELETE FROM export WHERE id = ?", (export_id,))
    if row["file_path"]:
        _safe_unlink(Path(row["file_path"]), get_settings())
    await notify("export", export_id)
