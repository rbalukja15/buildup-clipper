# Build-Up Clipper

Local, single-user tool that turns a full match video into a compilation of
opponent goalkeeper build-up sequences. One analyst is the entire user base.

**Read `docs/HANDOVER.md` first** — current state, what is and is not verified,
open questions, and the traps in this codebase.

## Commands

```bash
# tests (from backend/)
./.venv/bin/python -m pytest -q                                # all 67
./.venv/bin/python -m pytest -q --ignore=tests/test_integration.py   # fast only, no ffmpeg needed

# dev
make dev-api      # uvicorn on :8000
make dev-ui       # next dev on :3000
make docker       # packaged build, :8000

# frontend checks (from frontend/)
npx tsc --noEmit && npm run build
```

Integration tests need real `ffmpeg`/`ffprobe`; the rest stub them out.

## Layout

- `backend/app/` — `pipeline.py` (job bodies), `jobs.py` (the single async
  worker), `media/` (ffmpeg + yt-dlp wrappers), `routers/`, `paths.py`
  (path containment — the only implementation, use it)
- `frontend/app/` — `page.tsx` (matches), `tag/` (player), `review/` (grid),
  `exports/`; `lib/live.tsx` holds the SSE plumbing
- `docs/handoff.md` — install steps and the M4 baseline table

## Conventions

- ffmpeg command construction lives in pure `*_cmd` functions so the encoding
  strategy is testable without ffmpeg installed. Keep it that way.
- Tags are the source of truth; clips are derived artifacts. Anything that moves
  a tag's window must invalidate the clip, drop its verdict, and re-render.
- Review clips are stream-copied from the 480p proxy. The export re-encodes from
  the **original** source — never the proxy.
- Comments explain why, not what. Match the surrounding density.
- Tests are named as the behaviour they protect, not `test_function_name`.
