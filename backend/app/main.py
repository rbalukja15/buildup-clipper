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
from .db import connect, init_db
from .jobs import queue
from .pipeline import enqueue_clip_render
from .media.ffmpeg import MediaError
from .paths import safe_join
from .routers import clips, events, exports, matches, media, tags

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("buc.main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    queue.start()
    await requeue_pending_clips()
    try:
        yield
    finally:
        await queue.stop()


async def requeue_pending_clips() -> None:
    """Pick up clip renders that a restart interrupted.

    The job queue is in-memory, so without this the rows sit at 'pending'
    forever and look identical to work that is genuinely still queued.
    """
    with connect() as conn:
        pending = conn.execute(
            "SELECT id FROM clip WHERE render_state = 'pending' AND review_path IS NULL ORDER BY id"
        ).fetchall()
    for row in pending:
        await enqueue_clip_render(int(row["id"]), f"clip {row['id']}")
    if pending:
        log.info("re-queued %d interrupted clip render(s)", len(pending))


def build_app() -> FastAPI:
    """Assemble the application.

    A factory rather than a module-level app: the frontend mount depends on
    settings, so it has to be decided when the app is built, not when this
    module happens to be imported.
    """
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

    for router in (matches.router, tags.router, clips.router, exports.router,
                   media.router, events.router):
        app.include_router(router)

    _mount_frontend(app)
    return app


def _mount_frontend(app: FastAPI) -> None:
    settings = get_settings()
    frontend = settings.frontend_dir
    if not frontend or not frontend.is_dir():
        return

    # A frontend directory without built assets (a partial or interrupted build)
    # should degrade, not take the whole API down at startup.
    assets = frontend / "_next"
    if assets.is_dir():
        app.mount("/_next", StaticFiles(directory=assets), name="next-assets")
    else:
        log.warning("no _next assets under %s -- serving HTML only", frontend)

    root = frontend.resolve()

    @app.api_route("/{full_path:path}", methods=["GET", "HEAD"], include_in_schema=False)
    def spa(full_path: str):
        """Serve the static export, falling back to its index for client routes.

        Every candidate is resolved and containment-checked: the path comes
        straight from the URL, so `..` segments and absolute-looking paths must
        not be able to reach outside the exported frontend.
        """
        for relative in (full_path, f"{full_path}.html"):
            candidate = safe_join(root, relative)
            if candidate is None:
                continue
            if candidate.is_dir():
                candidate = safe_join(root, f"{relative}/index.html")
                if candidate is None:
                    continue
            if candidate.is_file():
                return FileResponse(candidate)
        return FileResponse(root / "index.html")


app = build_app()
