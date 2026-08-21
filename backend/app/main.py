"""FastAPI entrypoint.

Dev mode (M1-M3): `uvicorn app.main:app --reload`, Next.js dev server alongside.
Handoff mode (M4): BUC_FRONTEND_DIR points at the built frontend and this one
process serves both API and UI.
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.responses import FileResponse, JSONResponse
from starlette.staticfiles import StaticFiles

from .config import get_settings
from .db import init_db
from .jobs import queue
from .media.ffmpeg import MediaError
from .routers import clips, events, exports, matches, media, tags

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    queue.start()
    try:
        yield
    finally:
        await queue.stop()


app = FastAPI(title="Build-Up Clipper", version="0.1.0", lifespan=lifespan)

# Single user on localhost; the dev frontend runs on another port.
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"http://(localhost|127\.0\.0\.1):\d+",
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(MediaError)
async def media_error_handler(request, exc: MediaError) -> JSONResponse:
    return JSONResponse(status_code=422, content={"detail": str(exc)})


@app.get("/api/health")
def health() -> dict:
    settings = get_settings()
    return {
        "ok": True,
        "data_dir": str(settings.data_dir),
        "tag_padding": [settings.tag_pad_before_s, settings.tag_pad_after_s],
        "export": {
            "width": settings.export_width,
            "height": settings.export_height,
            "fps": settings.export_fps,
        },
    }


for router in (matches.router, tags.router, clips.router, exports.router, media.router, events.router):
    app.include_router(router)


def _mount_frontend(app: FastAPI) -> None:
    settings = get_settings()
    frontend = settings.frontend_dir
    if not frontend or not frontend.is_dir():
        return

    app.mount("/_next", StaticFiles(directory=frontend / "_next"), name="next-assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa(full_path: str):
        """Serve the static export, falling back to its index for client routes."""
        candidate = (frontend / full_path).resolve()
        if candidate.is_dir():
            candidate = candidate / "index.html"
        if str(candidate).startswith(str(frontend.resolve())) and candidate.is_file():
            return FileResponse(candidate)
        html = frontend / f"{full_path}.html"
        if html.is_file():
            return FileResponse(html)
        return FileResponse(frontend / "index.html")


_mount_frontend(app)
