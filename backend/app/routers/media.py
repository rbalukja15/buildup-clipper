"""Serves proxies and review clips to the browser player.

Only files inside the app's own media tree are ever served -- source paths can
point anywhere on the analyst's disk, and originals are never exposed.
"""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException
from starlette.requests import Request

from ..config import get_settings
from ..db import connect
from ..pipeline import _is_within
from ..ranged import serve_media

router = APIRouter(prefix="/api/media", tags=["media"])


def _guard(path_str: str | None, what: str) -> Path:
    if not path_str:
        raise HTTPException(status_code=409, detail=f"{what} is not rendered yet")
    path = Path(path_str)
    settings = get_settings()
    if not any(_is_within(path.resolve(), root) for root in settings.media_roots()):
        raise HTTPException(status_code=403, detail="path outside the media directory")
    return path


@router.get("/proxy/{match_id}")
def proxy(match_id: int, request: Request):
    with connect() as conn:
        row = conn.execute("SELECT proxy_path FROM match WHERE id = ?", (match_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="match not found")
    return serve_media(_guard(row["proxy_path"], "proxy"), request)


@router.get("/clip/{clip_id}")
def clip(clip_id: int, request: Request):
    with connect() as conn:
        row = conn.execute("SELECT review_path FROM clip WHERE id = ?", (clip_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="clip not found")
    return serve_media(_guard(row["review_path"], "clip"), request)
