"""Session measurement: what a match actually cost, in numbers.

M4 asks two questions that were tally marks on paper -- is this faster than the
manual process, and does the default tag padding fit this footage? Both are
answerable from rows the app already writes, so it answers them itself.

Every duration here is a **span between recorded actions** (first tag to last
tag, first verdict to last verdict), not a stopwatch. Idle time inside a span
counts; time before the first action does not. That is the honest reading, and
the UI says so.
"""
from __future__ import annotations

from datetime import datetime, timezone

from .config import get_settings
from .db import connect

# Below this many tags a share is noise rather than a signal, so the padding
# verdict stays "unknown" rather than pretending to a conclusion.
MIN_TAGS_FOR_VERDICT = 5

# The spec's own rule: more than roughly one tag in five corrected means the
# default window is wrong for this footage.
ADJUST_SHARE_LIMIT = 0.2


def _epoch(stamp: str | None) -> float | None:
    """SQLite's datetime('now') is UTC, second resolution, no timezone suffix."""
    if not stamp:
        return None
    try:
        return datetime.strptime(stamp, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc).timestamp()
    except ValueError:
        return None


def _span_s(stamps: list[str | None]) -> int | None:
    moments = sorted(e for e in (_epoch(s) for s in stamps) if e is not None)
    if len(moments) < 2:
        return None
    return int(moments[-1] - moments[0])


def _median(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2


def _round(value: float | None, places: int = 1) -> float | None:
    return None if value is None else round(value, places)


def match_stats(match_id: int) -> dict | None:
    settings = get_settings()
    with connect() as conn:
        match = conn.execute("SELECT * FROM match WHERE id = ?", (match_id,)).fetchone()
        if match is None:
            return None
        tags = conn.execute(
            """
            SELECT t.t_start, t.t_end, t.t_marked, t.adjust_count, t.created_at,
                   c.status, c.render_state, c.reviewed_at
            FROM tag t LEFT JOIN clip c ON c.tag_id = t.id
            WHERE t.match_id = ? ORDER BY t.id
            """,
            (match_id,),
        ).fetchall()
        exports = conn.execute(
            """
            SELECT DISTINCT e.id, e.name, e.state, e.started_at, e.finished_at, e.created_at
            FROM export e
            JOIN export_clip ec ON ec.export_id = e.id
            JOIN clip c ON c.id = ec.clip_id
            JOIN tag t ON t.id = c.tag_id
            WHERE t.match_id = ? ORDER BY e.id
            """,
            (match_id,),
        ).fetchall()

    duration_s = float(match["duration_s"]) if match["duration_s"] else None
    total = len(tags)
    adjusted = sum(1 for t in tags if (t["adjust_count"] or 0) > 0)
    corrections = sum(int(t["adjust_count"] or 0) for t in tags)

    counts = {"pending": 0, "approved": 0, "rejected": 0}
    for t in tags:
        if t["status"] in counts:
            counts[t["status"]] += 1

    tagging_s = _span_s([t["created_at"] for t in tags])
    review_s = _span_s([t["reviewed_at"] for t in tags])

    last_export = exports[-1] if exports else None
    export_s = None
    if last_export is not None:
        start, end = _epoch(last_export["started_at"]), _epoch(last_export["finished_at"])
        if start is not None and end is not None:
            export_s = int(end - start)

    measured = [s for s in (tagging_s, review_s, export_s) if s is not None]
    measured_s = sum(measured) if measured else None

    return {
        "match_id": int(match["id"]),
        "title": match["title"],
        "duration_s": duration_s,
        "tags": {
            "total": total,
            "adjusted": adjusted,
            "corrections": corrections,
            "adjusted_share": round(adjusted / total, 3) if total else None,
            "median_window_s": _round(_median([t["t_end"] - t["t_start"] for t in tags])),
            "span_s": tagging_s,
        },
        "clips": {
            **counts,
            "failed_renders": sum(1 for t in tags if t["render_state"] == "failed"),
            "reviewed": sum(1 for t in tags if t["reviewed_at"]),
            "span_s": review_s,
        },
        "padding": _padding(tags, settings, duration_s, total, adjusted),
        "exports": {
            "count": len(exports),
            "ready": sum(1 for e in exports if e["state"] == "ready"),
            "last_render_s": export_s,
            "last_name": last_export["name"] if last_export is not None else None,
        },
        "totals": {
            "measured_s": measured_s,
            # The spec's target is a full deliverable in <= 1.2x match runtime.
            "ratio_of_match": (
                round(measured_s / duration_s, 2) if measured_s is not None and duration_s else None
            ),
        },
    }


def _padding(rows, settings, duration_s: float | None, total: int, adjusted: int) -> dict:
    """What padding the analyst's own corrections argue for.

    Only hotkey tags carry `t_marked`, and only they say anything about the
    padding -- a window supplied whole was never padded. Tags clamped at 0 or at
    the end of the match are dropped too: their window says more about where the
    match ends than about what the analyst wanted.
    """
    usable = [
        r for r in rows
        if r["t_marked"] is not None
        and r["t_start"] > 0
        and (duration_s is None or r["t_end"] < duration_s - 0.01)
    ]
    corrected = [r for r in usable if (r["adjust_count"] or 0) > 0]
    share = (adjusted / total) if total else 0.0

    if total < MIN_TAGS_FOR_VERDICT:
        verdict = "unknown"
    elif share > ADJUST_SHARE_LIMIT:
        verdict = "check"
    else:
        verdict = "fits"

    before = _round(_median([r["t_marked"] - r["t_start"] for r in corrected]))
    after = _round(_median([r["t_end"] - r["t_marked"] for r in corrected]))

    # Nothing to suggest once the padding already matches what the corrections
    # argue for: the share stays high because it is the history of this match,
    # and repeating the number he just set would read as the advice not landing.
    already_set = before == settings.tag_pad_before_s and after == settings.tag_pad_after_s
    suggest = verdict == "check" and bool(corrected) and not already_set

    return {
        "before_s": settings.tag_pad_before_s,
        "after_s": settings.tag_pad_after_s,
        "sample": len(usable),
        "corrected_sample": len(corrected),
        "corrected_median_before_s": before,
        "corrected_median_after_s": after,
        "suggested_before_s": before if suggest else None,
        "suggested_after_s": after if suggest else None,
        "verdict": verdict,
    }
