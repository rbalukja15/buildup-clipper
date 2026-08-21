# Build-Up Clipper

Turn a full match video into a validated compilation of opponent goalkeeper
build-up sequences.

Replaces the scrub-cut-join-in-an-editor workflow with: **watch the match once,
tap a hotkey at each GK build-up, review the generated clips, export one
deliverable video.**

Single user, no auth, runs locally. Videos never leave the machine.

---

## Quick start (dev mode)

Needs Python 3.11+, Node 20+, `ffmpeg`/`ffprobe` on PATH, and `yt-dlp` if you
want YouTube sources.

```bash
# terminal 1 -- API
cd backend
python3 -m venv .venv && ./.venv/bin/pip install -r requirements.txt
BUC_DATA_DIR=../data ./.venv/bin/uvicorn app.main:app --reload --port 8000

# terminal 2 -- UI
cd frontend
npm install
npm run dev          # http://localhost:3000
```

`make dev-api` / `make dev-ui` do the same thing.

## Quick start (handoff mode)

One container, FastAPI serving both the API and the built UI:

```bash
docker compose up --build      # http://localhost:8000
```

Match files dropped into `./data/videos/source` are selectable by path
(`/data/videos/source/yourfile.mp4` inside the container). The database lives in
`./data/db`. Both are bind-mounted, so nothing is lost when the container is
rebuilt.

---

## How it works

1. **Create match** — opponent, date, and a source: a local file path or a
   YouTube URL.
2. **Ingest** (background job) — download if a URL, probe duration/fps, then
   build a 480p proxy with a short GOP so the browser scrubs instantly.
3. **Tag** — the proxy plays at 1–2×. Every keystroke is a job:

   | key | action |
   |-----|--------|
   | `G` | mark a GK build-up at the playhead → creates a tag `t−3s … t+27s` |
   | `I` / `O` | set the exact in/out point of the active tag |
   | `U` | undo (delete) the most recent tag |
   | `space` | play / pause |
   | `←` `→` | seek ±5s |
   | `⇧` + `←` `→` | frame step |
   | `↑` `↓` | playback rate (1× → 2×) |
   | `↵` | jump to the active tag |

4. **Clips** — every tag renders a review clip automatically.
5. **Review** — clip grid: play, `A` to approve, `R` to reject, drag the number
   to reorder, optional note per clip.
6. **Export** — approved clips are re-encoded frame-exact with uniform
   parameters and joined into one `.mp4`. That file is the deliverable.

## ffmpeg strategy

| stage | approach | why |
|-------|----------|-----|
| Proxy | 480p, `+faststart`, GOP 25, keeps audio | dense keyframes make browser seeking snappy; audio is a useful tagging cue |
| Review clip | `-ss` **before** `-i`, `-c copy` from the proxy | instant, no re-encode; cuts snap to keyframes (±1–2s, fine for review) |
| Export segment | `-ss` before `-i` + re-encode from the **original** source | frame-exact, and never inherits the proxy's quality |
| Export join | `scale`+`pad`+`fps`+`setsar` normalization, then concat demuxer with `-c copy` | mixed sources (different matches, resolutions, frame rates) concat without a glitch or a second generation loss |

Export segments drop audio (`-an`) so segments from different sources always
have identical stream layouts. To keep audio, remove `-an` from
`export_segment_cmd` and add matching `-c:a aac -ar 48000 -ac 2`.

## Data model (SQLite)

```
match   (id, title, opponent, date, source_type, source_url, file_path,
         proxy_path, duration_s, fps, ingest_state, ingest_error, created_at)
tag     (id, match_id, t_start, t_end, category, source, note, created_at)
clip    (id, tag_id, status, order_index, review_path, final_path,
         render_state, render_error)
export  (id, name, file_path, state, error, created_at)
export_clip (export_id, clip_id, position)
```

**Tags are the source of truth; clips are derived artifacts.** Editing a tag's
window deletes its rendered files, marks the clip `pending`, and re-renders it.

`tag.source` is `'manual'` for every hotkey tag. It exists so an automated
producer (CV detection, Wyscout import) can write tags later without a schema
change. `tag.category` is fixed to `'gk_buildup'` — the schema supports more
categories, the UI deliberately exposes one.

Exports can select clips **across matches** — the running order is
`export_clip.position`, not the clip's review order.

Two columns are additions to the spec's schema: `match.ingest_state` /
`ingest_error` and `clip.render_state` / `render_error`. Without them a failed
download or a missing file is invisible in the UI.

## Architecture

- **Backend**: FastAPI + SQLite (WAL) + ffmpeg + yt-dlp. Every long job runs on a
  single in-process async worker — one ffmpeg at a time, so encodes never fight
  each other for a laptop's CPU. Progress is streamed to the UI over SSE
  (`/api/events`).
- **Frontend**: Next.js static export. The player is a plain HTML5 `<video>` on
  the proxy; the backend serves it with full HTTP Range support, which is what
  makes seeking work.
- A crash mid-job is recoverable: transient rows (`downloading`, `rendering`)
  are reset at startup rather than left hanging.

### Configuration

All env vars, all optional:

| var | default | meaning |
|-----|---------|---------|
| `BUC_DATA_DIR` | `./data` | root for `db/` and `videos/` |
| `BUC_TAG_PAD_BEFORE` / `BUC_TAG_PAD_AFTER` | `3` / `27` | the `G` hotkey window |
| `BUC_EXPORT_WIDTH` / `_HEIGHT` / `_FPS` | `1280` / `720` / `30` | deliverable normalization |
| `BUC_EXPORT_CRF` / `_PRESET` | `20` / `veryfast` | export quality vs. speed |
| `BUC_PROXY_HEIGHT` / `_GOP` / `_CRF` | `480` / `25` / `28` | proxy build |
| `BUC_FFMPEG` / `BUC_FFPROBE` / `BUC_YTDLP` | on PATH | binary locations |
| `BUC_FRONTEND_DIR` | unset | serve a built UI from this directory |

## Tests

```bash
cd backend
./.venv/bin/pip install -r requirements-dev.txt
./.venv/bin/python -m pytest              # all 47
./.venv/bin/python -m pytest --ignore=tests/test_integration.py   # 45 fast, ffmpeg stubbed
./.venv/bin/python -m pytest tests/test_integration.py            # 2 real-ffmpeg, ~30s
```

The fast suite stubs ffmpeg, so it runs anywhere; the encoding strategy itself is
asserted on the generated commands. The integration suite renders real video and
checks the deliverable is 1280×720@30, frame-exact, and joins mixed sources
without dropping frames.

## Milestones

- **M1** — ingest + proxy + tagging player, tags persisted. ✅
- **M2** — clip generation + review grid with approve/reject/reorder. ✅
- **M3** — export pipeline + acceptance test. ✅ (pipeline verified against
  generated footage; the real acceptance test is reproducing the sample
  deliverable from its source footage)
- **M4** — dockerize ✅, install on the analyst's machine, run one real match
  side-by-side with the manual process, record the baseline. See
  [`docs/handoff.md`](docs/handoff.md).

## Assumptions to validate in first real use

1. **The −3s/+27s window fits real GK build-ups.** Change it with
   `BUC_TAG_PAD_BEFORE`/`AFTER` without touching code; if the analyst is
   constantly hitting `I`/`O`, the default is wrong.
2. **Keyframe-snapped review clips are tolerable.** They can be ±1–2s off. The
   export is frame-exact regardless. If review feels sloppy, lower
   `BUC_PROXY_GOP` (denser keyframes = tighter cuts, bigger proxy).
3. **Tagging while watching at 1.5–2× fits how the analyst works.** Worth
   testing on one real match before any UI polish.

## Keeping YouTube ingest working

`yt-dlp` is installed by `requirements.txt`, so it lands in the same virtualenv
as the app and is found there automatically — the dev command runs the venv's
interpreter without activating it, so a PATH lookup alone would miss it. Point
`BUC_YTDLP` at a specific binary to override.

It is deliberately **not** pinned (`yt-dlp>=…` in `backend/requirements.txt`).
YouTube changes its player regularly and an aging yt-dlp stops being able to
extract video — the symptom is an ingest that fails with "Failed to extract any
player response". The fix is always the same: get a newer yt-dlp.

```bash
docker compose build --no-cache clipper && docker compose up -d   # packaged
./.venv/bin/pip install -U yt-dlp                                 # dev mode
```

Local-file sources are unaffected by this.

## Notes

- The browser needs H.264 support to play the proxy — Chrome, Edge, and Firefox
  are fine. A bare open-source Chromium build may not be.
- `data/` is gitignored: videos and the database never belong in the repo.
- On Linux hosts the container runs as root, so files under `./data` end up
  root-owned. On Windows and macOS Docker Desktop maps ownership to your user,
  so this only matters if you run the container on a Linux box.
