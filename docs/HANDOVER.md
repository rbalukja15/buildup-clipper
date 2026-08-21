# Handover

State of the project as of the last commit on `main`, written for whoever picks
it up next.

## What this is

A single-purpose tool for one football analyst: turn a full match video into a
validated compilation of opponent goalkeeper build-up sequences. Watch once, tap
`G` at each build-up, review the generated clips, export one deliverable. Built
from an MVP spec (v0.1); `README.md` is the user-facing document and states the
deliberate deviations from that spec.

Nobody has used it on real footage yet. That is the single most important gap.

## Where things stand

| Milestone | State |
|-----------|-------|
| M1 ingest + proxy + tagging player | done |
| M2 clip generation + review grid | done |
| M3 export pipeline | pipeline done and verified on synthetic footage; **the acceptance test against the analyst's real sample deliverable has not been run** |
| M4 dockerize + install + baseline | image builds and runs; the app measures its own baseline now; **not installed on the analyst's machine, no baseline recorded** |

83 tests: 80 fast (media binaries stubbed) + 3 real-ffmpeg integration tests.

```bash
cd backend && ./.venv/bin/python -m pytest -q                              # all
./.venv/bin/python -m pytest -q --ignore=tests/test_integration.py         # fast only
```

## Verified, and how

Not "the code looks right" — these were run:

- **Full pipeline, real ffmpeg**: ingest → tag → clip → approve → export produces
  a frame-exact deliverable. A 3-clip export is exactly 90.000s at 1280×720@30.
- **Mixed sources concat cleanly**: a 4:3/30fps source and a 16:9/25fps source
  join into one file with exactly the right frame count — no drops at the join.
  This is the case the analyst's real sample deliverable exercises (it mixed
  three sources).
- **Export settings changes re-encode everything**, rather than concat-copying
  new segments onto stale ones (which produced a file whose header disagreed
  with half its frames).
- **Docker**: image builds, container ingests from a bind mount and exports;
  data survives restart and container recreation; `docker compose up` works and
  the healthcheck reports healthy.
- **URL ingest**: a match ingested from an HTTP URL via yt-dlp, downloaded,
  probed, proxied, tagged, exported.
- **Browser**: hotkeys (`G`/`U`/`I`/`O`, bare vs. Ctrl/Cmd chords), tag
  selection, timeline, review approve, SSE liveness, and client-side navigation
  between search params — driven with Playwright against the built UI.
- **Fresh clone** passes all tests and builds the frontend from the committed
  lockfile.
- **The baseline page against a real render**: a 5-minute synthetic match
  ingested, nine tags, three `I`/`O` corrections, verdicts, and a real export —
  the page reported 9 build-ups, 3 nudged (33%), a 27s export render, and the
  padding its own corrections argued for (−6s/+21s). Setting
  `BUC_TAG_PAD_BEFORE=6` / `_AFTER=21` and restarting made the tagging legend
  follow and the suggestion retire itself. Screenshot-verified in Chromium.

## NOT verified

1. **The real acceptance test.** Reproducing the analyst's ~3-minute sample
   deliverable from its source footage, faster than his manual process, with
   output he signs off on. Everything else is a proxy for this.
2. **YouTube specifically.** The URL download path is verified with a generic
   HTTP URL, but `www.youtube.com` is blocked by the dev session's egress
   policy, so YouTube's own extractor has never run here. If you have network
   access, just try it. yt-dlp also needs `*.googlevideo.com` (wildcard —
   per-request hostnames) for the media itself, and YouTube may still serve a
   bot check to datacenter IPs.
3. **The Debian `apt-get install ffmpeg` line in the Dockerfile.** `deb.debian.org`
   was blocked in the dev session, so the image was built against an
   Ubuntu-based copy instead. Everything else in the Dockerfile is exercised;
   the dependencies were separately confirmed to install on the real
   `python:3.11-slim` base. On a normal network this line is unremarkable.
4. **Windows.** The target machine is Windows + Docker Desktop; all testing was
   on Linux.

## Open decisions that need real use

These are the spec's own open assumptions, and none can be settled without the
analyst:

1. **Is −3s/+27s the right window?** Tune with `BUC_TAG_PAD_BEFORE` /
   `BUC_TAG_PAD_AFTER`, no code change. The `/baseline` page now counts the
   `I`/`O` corrections and, past one tag in five, prints the window his own
   corrections imply — so this decision needs his footage, not his opinion.
2. **Are keyframe-snapped review clips good enough?** They can sit ±1–2s off.
   Lower `BUC_PROXY_GOP` for tighter cuts at the cost of a bigger proxy. The
   export is frame-exact either way.
3. **Does tagging at 1.5–2× fit how he works?** If he settles at 1×, the
   "watch once" premise needs rethinking.

`docs/handoff.md` has the install steps and the baseline table to fill in on the
day. Recording that baseline is the point of M4 — without it "faster than
manual" stays a feeling rather than a number. The clipper half of that table now
comes out of the app (**NUM** in the rail → *Copy handoff table*); the manual
half is still a stopwatch, and nobody but the analyst can produce it.

## Architecture, briefly

- **Measurement** `app/stats.py` turns the rows into the M4 numbers. It reads
  columns written for no other purpose (`tag.t_marked`, `tag.adjust_count`,
  `clip.reviewed_at`, `export.started_at/finished_at`) — nothing in the pipeline
  branches on them, so getting them wrong cannot break a render, only a report.
- **Backend** FastAPI + SQLite (WAL) + ffmpeg + yt-dlp. All long work runs on a
  single in-process async worker (`app/jobs.py`) so two ffmpeg runs never fight
  for a laptop's CPU. Progress streams over SSE at `/api/events`.
- **Frontend** Next.js static export. In the packaged build FastAPI serves it,
  so the analyst runs one container. The player is a plain `<video>` on the
  480p proxy; the backend implements HTTP Range itself, which is what makes
  seeking work.
- **The central rule**: tags are the source of truth, clips are derived. Moving
  a tag's window deletes its rendered files, resets the clip to pending, drops
  the analyst's verdict (it was about a different cut), and re-renders.

### Things worth knowing before you change something

- **Every duration on the baseline page is a span between recorded actions**,
  not a stopwatch: first tag to last tag, first verdict to last verdict. Idle
  time inside a span counts and the lead-in does not. If you add a measure,
  keep that honest — an optimistic number here is worse than no number.
- **The padding advice is per match and historical.** A match's correction rate
  reflects the window it was tagged with, so it does not drop when the setting
  changes; the page only stops suggesting once the current padding already
  matches what the corrections argue for.
- **Export segments are cached on disk** and reused across re-renders. They are
  keyed by an encode fingerprint (`pipeline.export_fingerprint`). If you add an
  encoding parameter, add it to that fingerprint or stale segments will be
  silently reused.
- **`app/paths.py` is the only place path containment is implemented.** A second
  slightly different copy is how the traversal bug got in the first time. Use
  `is_within` / `safe_join`, don't hand-roll a prefix check.
- **`useLiveData` needs an explicit deps list** when its loader closes over
  state or a search param. Client-side navigation between two search params of
  the same route does not remount the component, so nothing else re-triggers
  the fetch.
- **Keyboard handlers must ignore Ctrl/Cmd/Alt chords.** Cmd+U used to delete
  the newest tag and its clip. Shift is load-bearing (frame-step) and must keep
  working.
- **The review clip is cut from the proxy; the export is cut from the original.**
  Never let the export path touch `proxy_path` — that would ship 480p as the
  deliverable. There is a test pinning this.

## Dev environment gotchas

Things that cost time here, so they don't cost it again:

- In a fresh remote session the **Docker daemon is not running**, though the
  binaries are present. Start it with
  `nohup dockerd --host=unix:///var/run/docker.sock &`, then wait for
  `docker info`. Docker Hub may rate-limit anonymous pulls (429); a
  `registry-mirrors` entry in `/etc/docker/daemon.json` fixes that.
- If the egress policy blocks Debian archives, build against an Ubuntu-based
  copy of the Dockerfile rather than changing the real one. Pass
  `--network=host` and install the proxy CA so npm and pip can verify TLS.
- **Headless Chromium has no H.264 decoder**, so video is black in screenshots
  and the console logs `NotSupportedError`. This is not an app bug — real
  Chrome/Edge play the proxy fine.
- Do not `pkill -f "<pattern>"` when the pattern also appears in the command you
  are running: it matches its own shell and kills the whole call.
- FastAPI ≥0.141 represents included routers as `_IncludedRouter` objects rather
  than flattening them into `app.routes`, so counting routes there
  under-reports. Check endpoints by calling them.

## History

The first working version was reviewed by an independent adversarial pass (five
reviewers over backend, frontend, packaging, security and spec conformance, with
a skeptic per finding). Fifteen findings survived verification and are all
fixed; see commit `5d90c15` for the list and `backend/tests/test_regressions.py`
for the coverage. That commit is a decent map of where this code is easy to get
wrong.
