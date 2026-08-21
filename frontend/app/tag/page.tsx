"use client";

import Link from "next/link";
import { Suspense, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "next/navigation";
import { api, ApiError, proxyUrl } from "@/lib/api";
import { useLive, useLiveData } from "@/lib/live";
import { timecode } from "@/lib/format";
import type { Health, Match, Tag } from "@/lib/types";
import { Toast } from "@/components/Toast";

const RATES = [1, 1.25, 1.5, 2];
const SEEK_S = 5;

export default function TagPage() {
  return (
    <Suspense fallback={<div className="content dim">Loading…</div>}>
      <TagStudio />
    </Suspense>
  );
}

function TagStudio() {
  const params = useSearchParams();
  const matchId = Number(params.get("match") ?? 0);
  const { refresh } = useLive();

  const [matches] = useLiveData<Match[]>(() => api.matches(), []);
  // The padding is env-configurable and the baseline page tells the analyst
  // when to change it, so the legend has to read it rather than claim it.
  const [health] = useLiveData<Health | null>(() => api.health(), null);
  const [match] = useLiveData<Match | null>(
    () => (matchId ? api.match(matchId) : Promise.resolve(null)),
    null,
    [matchId],
  );
  const [tags, setTags] = useLiveData<Tag[]>(
    () => (matchId ? api.tags(matchId) : Promise.resolve([])),
    [],
    [matchId],
  );

  const video = useRef<HTMLVideoElement>(null);
  const [now, setNow] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [rate, setRate] = useState(1.5);
  const [activeTagId, setActiveTagId] = useState<number | null>(null);
  const [struck, setStruck] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const duration = match?.duration_s ?? video.current?.duration ?? 0;
  const fps = match?.fps ?? 25;
  const activeTag = useMemo(() => tags.find((t) => t.id === activeTagId) ?? null, [tags, activeTagId]);

  const flash = (key: string) => {
    setStruck(key);
    setTimeout(() => setStruck((k) => (k === key ? null : k)), 260);
  };

  const seekTo = useCallback((seconds: number) => {
    const el = video.current;
    if (!el) return;
    el.currentTime = Math.min(Math.max(seconds, 0), el.duration || Number.MAX_SAFE_INTEGER);
    setNow(el.currentTime);
  }, []);

  const nudge = useCallback((delta: number) => seekTo((video.current?.currentTime ?? 0) + delta), [seekTo]);

  const togglePlay = useCallback(() => {
    const el = video.current;
    if (!el) return;
    if (el.paused) void el.play();
    else el.pause();
  }, []);

  /* --- tag actions -------------------------------------------------------- */

  const markTag = useCallback(async () => {
    if (!matchId) return;
    flash("G");
    try {
      // The padding around t is applied server-side so every producer --
      // hotkey today, detection later -- gets the same window.
      const tag = await api.createTag(matchId, { t: video.current?.currentTime ?? 0 });
      setTags((current) => [...current, tag].sort((a, b) => a.t_start - b.t_start));
      setActiveTagId(tag.id);
      refresh();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
    }
  }, [matchId, refresh, setTags]);

  const patchTag = useCallback(
    async (tag: Tag, body: Record<string, unknown>) => {
      try {
        const updated = await api.updateTag(tag.id, body);
        setTags((current) =>
          current.map((t) => (t.id === tag.id ? updated : t)).sort((a, b) => a.t_start - b.t_start),
        );
        refresh();
      } catch (err) {
        setError(err instanceof ApiError ? err.message : String(err));
      }
    },
    [refresh, setTags],
  );

  const setIn = useCallback(() => {
    if (!activeTag) return;
    flash("I");
    const t = video.current?.currentTime ?? 0;
    if (t >= activeTag.t_end) {
      setError("In point must sit before the out point.");
      return;
    }
    void patchTag(activeTag, { t_start: t });
  }, [activeTag, patchTag]);

  const setOut = useCallback(() => {
    if (!activeTag) return;
    flash("O");
    const t = video.current?.currentTime ?? 0;
    if (t <= activeTag.t_start) {
      setError("Out point must sit after the in point.");
      return;
    }
    void patchTag(activeTag, { t_end: t });
  }, [activeTag, patchTag]);

  const undoLast = useCallback(async () => {
    if (tags.length === 0) return;
    flash("U");
    const newest = tags.reduce((a, b) => (a.id > b.id ? a : b));
    try {
      await api.deleteTag(newest.id);
      setTags((current) => current.filter((t) => t.id !== newest.id));
      setActiveTagId((id) => (id === newest.id ? null : id));
      refresh();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
    }
  }, [tags, refresh, setTags]);

  /* --- hotkeys ------------------------------------------------------------ */

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      if (target && (target.tagName === "INPUT" || target.tagName === "TEXTAREA" || target.isContentEditable)) {
        return; // never hijack note editing
      }
      if (event.ctrlKey || event.metaKey || event.altKey) {
        return; // never hijack browser/OS chords (Cmd+U, Ctrl+A, ...)
      }
      const key = event.key.toLowerCase();

      switch (key) {
        case "g":
          event.preventDefault();
          void markTag();
          return;
        case "i":
          event.preventDefault();
          setIn();
          return;
        case "o":
          event.preventDefault();
          setOut();
          return;
        case "u":
          event.preventDefault();
          void undoLast();
          return;
        case " ":
          event.preventDefault();
          flash("Space");
          togglePlay();
          return;
        case "arrowleft":
          event.preventDefault();
          nudge(event.shiftKey ? -1 / fps : -SEEK_S);
          return;
        case "arrowright":
          event.preventDefault();
          nudge(event.shiftKey ? 1 / fps : SEEK_S);
          return;
        case "arrowup":
          event.preventDefault();
          setRate((r) => RATES[Math.min(RATES.indexOf(r) + 1, RATES.length - 1)] ?? r);
          return;
        case "arrowdown":
          event.preventDefault();
          setRate((r) => RATES[Math.max(RATES.indexOf(r) - 1, 0)] ?? r);
          return;
        case "enter":
          if (activeTag) {
            event.preventDefault();
            seekTo(activeTag.t_start);
          }
          return;
        default:
          return;
      }
    };

    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [markTag, setIn, setOut, undoLast, togglePlay, nudge, seekTo, activeTag, fps]);

  useEffect(() => {
    if (video.current) video.current.playbackRate = rate;
  }, [rate]);

  /* --- render ------------------------------------------------------------- */

  if (!matchId) {
    return (
      <div className="content stack">
        <h1 className="display">
          Pick a <em>match</em>
        </h1>
        <div className="panel rows">
          {matches.filter((m) => m.ingest_state === "ready").map((m) => (
            <Link className="row" key={m.id} href={`/tag?match=${m.id}`}>
              <span className="row-id num">{String(m.id).padStart(2, "0")}</span>
              <span className="row-title">{m.title}</span>
              <span className="row-sub num row-hide">{timecode(m.duration_s)}</span>
              <span />
              <span />
              <span className="btn btn--tiny btn--go">Open</span>
            </Link>
          ))}
          {matches.length === 0 && <div className="empty">Ingest a match first.</div>}
        </div>
      </div>
    );
  }

  if (match && match.ingest_state !== "ready") {
    return (
      <div className="content stack">
        <h1 className="display">Preparing footage…</h1>
        <p className="muted">
          {match.ingest_state === "failed"
            ? match.ingest_error ?? "Ingest failed."
            : `Currently ${match.ingest_state}. The player opens as soon as the proxy is built.`}
        </p>
        <Link className="btn" href="/">
          Back to matches
        </Link>
      </div>
    );
  }

  return (
    <div className="stage">
      <div style={{ minWidth: 0, display: "flex", flexDirection: "column" }}>
        <div className="screen">
          <video
            ref={video}
            src={proxyUrl(matchId)}
            preload="auto"
            onTimeUpdate={(e) => setNow(e.currentTarget.currentTime)}
            onPlay={(e) => {
              setPlaying(true);
              e.currentTarget.playbackRate = rate;
            }}
            onPause={() => setPlaying(false)}
            onLoadedMetadata={(e) => {
              e.currentTarget.playbackRate = rate;
            }}
          />
        </div>

        <div className="deck">
          <div className="spread">
            <div className="inline" style={{ gap: 14 }}>
              <span className="clock num">{timecode(now, true)}</span>
              <span className="dim num">/ {timecode(duration)}</span>
            </div>
            <div className="inline">
              <span className="eyebrow">Rate</span>
              <div className="seg">
                {RATES.map((r) => (
                  <button key={r} data-on={rate === r} onClick={() => setRate(r)}>
                    {r}×
                  </button>
                ))}
              </div>
            </div>
          </div>

          <Timeline
            duration={duration}
            now={now}
            tags={tags}
            activeTagId={activeTagId}
            onSeek={seekTo}
            onPick={(tag) => {
              setActiveTagId(tag.id);
              seekTo(tag.t_start);
            }}
          />

          <div className="deck-controls">
            <button className="btn" onClick={togglePlay}>
              {playing ? "Pause" : "Play"} <span className="key" data-hot={struck === "Space"}>space</span>
            </button>
            <button className="btn btn--solid" onClick={() => void markTag()}>
              Mark build-up <span className="key" data-hot={struck === "G"}>G</span>
            </button>
            <button className="btn" onClick={setIn} disabled={!activeTag}>
              Set in <span className="key" data-hot={struck === "I"}>I</span>
            </button>
            <button className="btn" onClick={setOut} disabled={!activeTag}>
              Set out <span className="key" data-hot={struck === "O"}>O</span>
            </button>
            <button className="btn btn--kill" onClick={() => void undoLast()} disabled={tags.length === 0}>
              Undo last <span className="key" data-hot={struck === "U"}>U</span>
            </button>
          </div>
        </div>

        <div className="legend">
          <span className="legend-item">
            <span className="key">←</span>
            <span className="key">→</span> seek 5s
          </span>
          <span className="legend-item">
            <span className="key">⇧</span>+<span className="key">←</span>
            <span className="key">→</span> frame step
          </span>
          <span className="legend-item">
            <span className="key">↑</span>
            <span className="key">↓</span> speed
          </span>
          <span className="legend-item">
            <span className="key">↵</span> jump to active tag
          </span>
          <span className="legend-item dim">
            {health
              ? `Tags apply −${health.tag_padding[0]}s / +${health.tag_padding[1]}s around the keystroke.`
              : "Tags apply a fixed window around the keystroke."}
          </span>
        </div>
      </div>

      <aside className="side">
        <div className="panel-head">
          <span className="eyebrow">Tags</span>
          <div className="inline" style={{ gap: 8 }}>
            <span className="dim num">{tags.length}</span>
            <Link className="btn btn--tiny btn--go" href={`/review?match=${matchId}`}>
              Review →
            </Link>
          </div>
        </div>
        <div className="side-list">
          {tags.length === 0 && (
            <div className="empty" style={{ margin: 14, border: 0 }}>
              Press <span className="key">G</span> the moment the keeper starts a build-up.
            </div>
          )}
          {tags.map((tag, index) => (
            <div
              key={tag.id}
              className="tag-row"
              data-active={tag.id === activeTagId}
              onClick={() => {
                setActiveTagId(tag.id);
                seekTo(tag.t_start);
              }}
            >
              <span className="tag-index num">{String(index + 1).padStart(2, "0")}</span>
              <div style={{ minWidth: 0 }}>
                <div className="tag-window num">
                  {timecode(tag.t_start)} → {timecode(tag.t_end)}{" "}
                  <span className="dim">{Math.round(tag.t_end - tag.t_start)}s</span>
                </div>
                {tag.id === activeTagId ? (
                  <input
                    className="input"
                    style={{ marginTop: 6, fontSize: 11, padding: "4px 6px" }}
                    placeholder="note (optional)"
                    defaultValue={tag.note ?? ""}
                    onClick={(e) => e.stopPropagation()}
                    onBlur={(e) => {
                      if (e.currentTarget.value !== (tag.note ?? "")) {
                        void patchTag(tag, { note: e.currentTarget.value });
                      }
                    }}
                  />
                ) : (
                  tag.note && <div className="tag-note">{tag.note}</div>
                )}
              </div>
              <div className="inline" style={{ gap: 4 }}>
                <span
                  className="tick"
                  data-tone={
                    tag.render_state === "ready" ? "go" : tag.render_state === "failed" ? "bad" : "wait"
                  }
                  title={`clip ${tag.render_state ?? "pending"}`}
                />
                <button
                  className="btn btn--kill btn--tiny"
                  title="Delete tag"
                  onClick={(e) => {
                    e.stopPropagation();
                    void api.deleteTag(tag.id).then(() => {
                      setTags(tags.filter((t) => t.id !== tag.id));
                      refresh();
                    });
                  }}
                >
                  ×
                </button>
              </div>
            </div>
          ))}
        </div>
      </aside>

      <Toast message={error} onDone={() => setError(null)} />
    </div>
  );
}

function Timeline({
  duration,
  now,
  tags,
  activeTagId,
  onSeek,
  onPick,
}: {
  duration: number;
  now: number;
  tags: Tag[];
  activeTagId: number | null;
  onSeek: (s: number) => void;
  onPick: (tag: Tag) => void;
}) {
  const pct = (value: number) => (duration > 0 ? (value / duration) * 100 : 0);

  return (
    <div
      className="timeline"
      onClick={(event) => {
        const box = event.currentTarget.getBoundingClientRect();
        onSeek(((event.clientX - box.left) / box.width) * duration);
      }}
      role="slider"
      aria-label="Match timeline"
      aria-valuemin={0}
      aria-valuemax={Math.round(duration)}
      aria-valuenow={Math.round(now)}
      tabIndex={-1}
    >
      {tags.map((tag) => (
        <div
          key={tag.id}
          className="timeline-tag"
          data-status={tag.clip_status ?? "pending"}
          data-active={tag.id === activeTagId}
          style={{ left: `${pct(tag.t_start)}%`, width: `${Math.max(pct(tag.t_end - tag.t_start), 0.25)}%` }}
          title={`${timecode(tag.t_start)} → ${timecode(tag.t_end)}`}
          onClick={(event) => {
            event.stopPropagation();
            onPick(tag);
          }}
        />
      ))}
      <div className="playhead" style={{ left: `${pct(now)}%` }} />
    </div>
  );
}
