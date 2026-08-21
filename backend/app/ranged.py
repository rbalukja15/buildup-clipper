"""HTTP Range support for <video> seeking.

Starlette's FileResponse only learned range handling recently; the player is
the whole product here, so serve ranges ourselves rather than depend on it.
"""
from __future__ import annotations

import mimetypes
import re
from pathlib import Path

from fastapi import HTTPException
from starlette.requests import Request
from starlette.responses import FileResponse, Response, StreamingResponse

_RANGE = re.compile(r"bytes=(\d*)-(\d*)")
CHUNK = 1024 * 512


def serve_media(
    path: Path, request: Request, download_name: str | None = None
) -> StreamingResponse | FileResponse | Response:
    if not path.is_file():
        raise HTTPException(status_code=404, detail=f"file not found: {path.name}")

    media_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    size = path.stat().st_size
    headers = {"accept-ranges": "bytes", "cache-control": "no-cache"}
    if download_name:
        headers["content-disposition"] = f'attachment; filename="{download_name}"'

    if request.method == "HEAD":
        # Video players and route prefetchers probe with HEAD before fetching;
        # answering with the headers alone is the whole point of the method.
        return Response(
            status_code=200,
            media_type=media_type,
            headers={**headers, "content-length": str(size)},
        )

    range_header = request.headers.get("range")
    match = _RANGE.fullmatch(range_header.strip()) if range_header else None
    if match is None:
        return FileResponse(path, media_type=media_type, headers=headers)

    start_raw, end_raw = match.groups()
    if start_raw == "" and end_raw == "":
        raise HTTPException(status_code=416, detail="invalid range")
    if start_raw == "":  # suffix range: last N bytes
        length = min(int(end_raw), size)
        start, end = size - length, size - 1
    else:
        start = int(start_raw)
        end = min(int(end_raw), size - 1) if end_raw else size - 1
    if start >= size or start > end:
        return StreamingResponse(
            iter(()), status_code=416, headers={**headers, "content-range": f"bytes */{size}"}
        )

    def chunks():
        with path.open("rb") as fh:
            fh.seek(start)
            remaining = end - start + 1
            while remaining > 0:
                data = fh.read(min(CHUNK, remaining))
                if not data:
                    break
                remaining -= len(data)
                yield data

    headers.update({
        "content-range": f"bytes {start}-{end}/{size}",
        "content-length": str(end - start + 1),
    })
    return StreamingResponse(chunks(), status_code=206, media_type=media_type, headers=headers)
