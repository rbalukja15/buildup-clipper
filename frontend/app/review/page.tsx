"use client";

import Link from "next/link";
import { Suspense, useCallback, useEffect, useMemo, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { api, ApiError, clipUrl } from "@/lib/api";
import { useLive, useLiveData } from "@/lib/live";
import { timecode } from "@/lib/format";
import type { Clip, ClipStatus, Match } from "@/lib/types";
import { Toast } from "@/components/Toast";

type Filter = "all" | "pending" | "approved" | "rejected";

export default function ReviewPage() {
  return (
    <Suspense fallback={<div className="dim">Loading…</div>}>
      <ReviewGrid />
    </Suspense>
  );
}

function ReviewGrid() {
  const params = useSearchParams();
  const router = useRouter();
  const matchId = Number(params.get("match") ?? 0) || undefined;
  const { refresh } = useLive();

  const [matches] = useLiveData<Match[]>(() => api.matches(), []);
  const [clips, setClips] = useLiveData<Clip[]>(() => api.clips({ matchId }), [], [matchId]);
  const [filter, setFilter] = useState<Filter>("all");
  const [dragId, setDragId] = useState<number | null>(null);
  const [cursor, setCursor] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [exporting, setExporting] = useState(false);

  const visible = useMemo(
    () => (filter === "all" ? clips : clips.filter((c) => c.status === filter)),
    [clips, filter],
  );
  const approved = useMemo(() => clips.filter((c) => c.status === "approved"), [clips]);
  const match = matches.find((m) => m.id === matchId);

  const setStatus = useCallback(
    async (clip: Clip, status: ClipStatus) => {
      const next = clip.status === status ? "pending" : status;
      setClips((current) => current.map((c) => (c.id === clip.id ? { ...c, status: next } : c)));
      try {
        await api.updateClip(clip.id, { status: next });
        refresh();
      } catch (err) {
        setError(err instanceof ApiError ? err.message : String(err));
      }
    },
    [refresh, setClips],
  );

  const commitOrder = useCallback(
    async (ordered: Clip[]) => {
      setClips(ordered.map((clip, index) => ({ ...clip, order_index: index })));
      try {
        await api.reorderClips(ordered.map((c) => c.id));
      } catch (err) {
        setError(err instanceof ApiError ? err.message : String(err));
      }
    },
    [setClips],
  );

  const drop = useCallback(
    (targetId: number) => {
      if (dragId === null || dragId === targetId) return;
      const ordered = [...clips];
      const from = ordered.findIndex((c) => c.id === dragId);
      const to = ordered.findIndex((c) => c.id === targetId);
      if (from < 0 || to < 0) return;
      const [moved] = ordered.splice(from, 1);
      ordered.splice(to, 0, moved);
      setDragId(null);
      void commitOrder(ordered);
    },
    [clips, dragId, commitOrder],
  );

  // Review is a keyboard loop too: A approves, R rejects, arrows move.
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      if (target && (target.tagName === "INPUT" || target.tagName === "TEXTAREA")) return;
      if (event.ctrlKey || event.metaKey || event.altKey) {
        return; // never hijack browser/OS chords (Cmd+U, Ctrl+A, ...)
      }
      const clip = visible[cursor];
      if (event.key === "ArrowRight") setCursor((c) => Math.min(c + 1, visible.length - 1));
      else if (event.key === "ArrowLeft") setCursor((c) => Math.max(c - 1, 0));
      else if (clip && event.key.toLowerCase() === "a") void setStatus(clip, "approved");
      else if (clip && event.key.toLowerCase() === "r") void setStatus(clip, "rejected");
      else return;
      event.preventDefault();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [visible, cursor, setStatus]);

  const createExport = async () => {
    const name = prompt(
      "Name this deliverable",
      match ? `${match.opponent || match.title} — GK build-up` : "GK build-up compilation",
    );
    if (!name) return;
    setExporting(true);
    try {
      await api.createExport({ name, clip_ids: approved.map((c) => c.id) });
      refresh();
      router.push("/exports");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setExporting(false);
    }
  };

  return (
    <div className="stack" style={{ gap: 20 }}>
      <div className="spread">
        <div>
          <div className="eyebrow">{match ? match.title : "All matches"}</div>
          <h1 className="display">
            Clip <em>review</em>
          </h1>
        </div>
        <div className="inline">
          <div className="seg">
            {(["all", "pending", "approved", "rejected"] as Filter[]).map((f) => (
              <button key={f} data-on={filter === f} onClick={() => { setFilter(f); setCursor(0); }}>
                {f} {f === "all" ? clips.length : clips.filter((c) => c.status === f).length}
              </button>
            ))}
          </div>
          {matchId && (
            <Link className="btn btn--tiny" href={`/tag?match=${matchId}`}>
              ← Back to tagging
            </Link>
          )}
        </div>
      </div>

      <div className="panel spread" style={{ padding: "12px 14px" }}>
        <span className="muted">
          <span className="key">A</span> approve · <span className="key">R</span> reject ·{" "}
          <span className="key">←</span>
          <span className="key">→</span> move · drag the number to reorder
        </span>
        <div className="inline">
          <span className="tick" data-tone="go">
            {approved.length} approved
          </span>
          <button className="btn btn--solid" onClick={createExport} disabled={approved.length === 0 || exporting}>
            {exporting ? "Queuing…" : `Export ${approved.length} clip${approved.length === 1 ? "" : "s"}`}
          </button>
        </div>
      </div>

      {visible.length === 0 ? (
        <div className="empty">
          No clips here yet. Tag a match with <span className="key">G</span> and its review clips appear
          within seconds.
        </div>
      ) : (
        <div className="clips">
          {visible.map((clip, index) => (
            <article
              key={clip.id}
              className="clip"
              data-status={clip.status}
              data-drag={dragId === clip.id}
              style={index === cursor ? { outline: "1px solid var(--line-strong)", outlineOffset: 2 } : undefined}
              onClick={() => setCursor(index)}
              onDragOver={(e) => e.preventDefault()}
              onDrop={() => drop(clip.id)}
            >
              {clip.render_state === "ready" ? (
                <video src={clipUrl(clip.id)} controls preload="none" />
              ) : (
                <div
                  className="empty"
                  style={{ border: 0, aspectRatio: "16 / 9", display: "grid", placeItems: "center" }}
                >
                  <span className="tick" data-tone={clip.render_state === "failed" ? "bad" : "wait"}>
                    {clip.render_state}
                  </span>
                </div>
              )}

              <div className="clip-body">
                <div className="clip-top">
                  <span
                    className="clip-pos num"
                    draggable
                    onDragStart={() => setDragId(clip.id)}
                    onDragEnd={() => setDragId(null)}
                    title="Drag to reorder"
                  >
                    {String(clip.order_index + 1).padStart(2, "0")}
                  </span>
                  <span className="num muted">
                    {timecode(clip.t_start)} → {timecode(clip.t_end)}
                  </span>
                </div>
                {!matchId && <div className="row-sub">{clip.match_title}</div>}

                <input
                  className="input"
                  style={{ fontSize: 11, padding: "5px 7px" }}
                  placeholder="note (optional)"
                  defaultValue={clip.note ?? ""}
                  onBlur={(e) => {
                    if (e.currentTarget.value !== (clip.note ?? "")) {
                      void api.updateClip(clip.id, { note: e.currentTarget.value }).then(refresh);
                    }
                  }}
                />

                <div className="clip-actions">
                  <button
                    className={clip.status === "approved" ? "btn btn--solid btn--tiny" : "btn btn--go btn--tiny"}
                    onClick={() => void setStatus(clip, "approved")}
                  >
                    Approve
                  </button>
                  <button
                    className="btn btn--kill btn--tiny"
                    onClick={() => void setStatus(clip, "rejected")}
                  >
                    Reject
                  </button>
                  <button
                    className="btn btn--tiny"
                    style={{ marginLeft: "auto" }}
                    title="Re-cut this clip"
                    onClick={() => void api.rerenderClip(clip.id).then(refresh)}
                  >
                    ↻
                  </button>
                </div>
              </div>
            </article>
          ))}
        </div>
      )}

      <Toast message={error} onDone={() => setError(null)} />
    </div>
  );
}
