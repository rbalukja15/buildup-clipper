# M4 handoff — install and baseline

The point of M4 is not just installing the tool. It is getting a **number**: how
long a match takes the analyst today, so the improvement is measurable rather
than felt.

## Install (analyst's Windows machine)

1. Install Docker Desktop.
2. Copy this repository to the machine.
3. `docker compose up --build` — first build pulls ffmpeg, so allow a few
   minutes.
4. Open <http://localhost:8000>.
5. Drop a match file into `data\videos\source\`. In the UI, choose **Local
   file** and enter the container path: `/data/videos/source/<filename>.mp4`.

Everything stays on the machine: the container has no outbound calls except
yt-dlp when a YouTube URL is used.

## Baseline run

Run one real match **side by side** with the current manual process, and record:

| measure | manual | clipper |
|---------|--------|---------|
| Match runtime | | |
| Time to first tagged pass (wall clock) | | |
| Time spent reviewing / fixing cuts | | |
| Time spent joining + exporting | | |
| **Total time per match** | | |
| Number of build-ups found | | |
| Cuts the analyst had to nudge (`I`/`O`) | — | |
| Clips rejected after review | — | |

Target: full deliverable in ≤ 1.2× match runtime.

## What to watch for

- **Padding**: how many tags needed `I`/`O` correction? More than ~1 in 5 means
  `BUC_TAG_PAD_BEFORE`/`BUC_TAG_PAD_AFTER` are wrong for this footage.
- **Tagging speed**: which playback rate did the analyst settle on? If it is 1×,
  the "watch once" premise needs revisiting.
- **Review clips**: was keyframe snapping ever bad enough to mislead a decision?
- **Output**: does the analyst sign off on the export quality, or does it need a
  higher bitrate (`BUC_EXPORT_CRF`) or resolution (`BUC_EXPORT_HEIGHT`)?

Record the answers here, in this file, on the day. They decide what M5 is.
