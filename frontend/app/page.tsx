"use client";

import Link from "next/link";
import { useCallback, useState } from "react";
import { api, ApiError } from "@/lib/api";
import { useLive, useLiveData } from "@/lib/live";
import { relativeDate, timecode } from "@/lib/format";
import type { IngestState, Match } from "@/lib/types";
import { Toast } from "@/components/Toast";

const TONE: Record<IngestState, "go" | "wait" | "bad"> = {
  ready: "go",
  failed: "bad",
  pending: "wait",
  downloading: "wait",
  probing: "wait",
  proxying: "wait",
};

export default function MatchesPage() {
  const { refresh } = useLive();
  const [matches] = useLiveData<Match[]>(() => api.matches(), []);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [sourceType, setSourceType] = useState<"file" | "youtube">("file");

  const submit = useCallback(
    async (event: React.FormEvent<HTMLFormElement>) => {
      event.preventDefault();
      const form = event.currentTarget;
      const data = new FormData(form);
      setBusy(true);
      try {
        await api.createMatch({
          title: String(data.get("title") ?? "").trim(),
          opponent: String(data.get("opponent") ?? "").trim(),
          date: String(data.get("date") ?? "") || null,
          source_type: sourceType,
          file_path: sourceType === "file" ? String(data.get("source") ?? "").trim() : null,
          source_url: sourceType === "youtube" ? String(data.get("source") ?? "").trim() : null,
        });
        form.reset();
        refresh();
      } catch (err) {
        setError(err instanceof ApiError ? err.message : String(err));
      } finally {
        setBusy(false);
      }
    },
    [sourceType, refresh],
  );

  const remove = async (match: Match) => {
    if (!confirm(`Delete "${match.title}" with its tags and clips?`)) return;
    try {
      await api.deleteMatch(match.id);
      refresh();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
    }
  };

  return (
    <div className="stack" style={{ gap: 22 }}>
      <div className="spread">
        <div>
          <div className="eyebrow">Opponent goalkeeper build-up</div>
          <h1 className="display">
            Match <em>library</em>
          </h1>
        </div>
        <div className="dim" style={{ textAlign: "right", maxWidth: 260 }}>
          Watch once, tap <span className="key">G</span> at every build-up, review, export.
        </div>
      </div>

      <div className="grid-2">
        <section className="panel">
          <div className="panel-head">
            <span className="eyebrow">Matches</span>
            <span className="dim num">{matches.length}</span>
          </div>
          {matches.length === 0 ? (
            <div className="empty">No matches yet — add a source on the right to start.</div>
          ) : (
            <div className="rows">
              {matches.map((match) => (
                <div className="row" key={match.id}>
                  <span className="row-id num">{String(match.id).padStart(2, "0")}</span>
                  <div style={{ minWidth: 0 }}>
                    <div className="row-title">{match.title}</div>
                    <div className="row-sub">
                      {[match.opponent, match.date && relativeDate(match.date), match.source_type]
                        .filter(Boolean)
                        .join(" · ")}
                    </div>
                  </div>
                  <span className="tick row-hide" data-tone={TONE[match.ingest_state]} title={match.ingest_error ?? ""}>
                    {match.ingest_state}
                  </span>
                  <span className="row-sub row-hide num">
                    {match.duration_s ? timecode(match.duration_s) : "--:--"}
                  </span>
                  <span className="row-sub row-hide num">
                    {match.tag_count ?? 0} tags · {match.approved_count ?? 0} ok
                  </span>
                  <div className="inline" style={{ gap: 6 }}>
                    {match.ingest_state === "ready" ? (
                      <>
                        <Link className="btn btn--go btn--tiny" href={`/tag?match=${match.id}`}>
                          Tag
                        </Link>
                        <Link className="btn btn--tiny" href={`/review?match=${match.id}`}>
                          Review
                        </Link>
                      </>
                    ) : (
                      <button className="btn btn--tiny" onClick={() => api.reingest(match.id).then(refresh)}>
                        Retry
                      </button>
                    )}
                    <button className="btn btn--kill btn--tiny" onClick={() => remove(match)} title="Delete match">
                      ×
                    </button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </section>

        <section className="panel" style={{ alignSelf: "start" }}>
          <div className="panel-head">
            <span className="eyebrow">New match</span>
          </div>
          <form className="stack" style={{ padding: 14 }} onSubmit={submit}>
            <div className="field">
              <label htmlFor="title">Title</label>
              <input className="input" id="title" name="title" required placeholder="Rivals FC (a) — 2nd leg" />
            </div>
            <div className="inline" style={{ gap: 12 }}>
              <div className="field" style={{ flex: 1 }}>
                <label htmlFor="opponent">Opponent</label>
                <input className="input" id="opponent" name="opponent" placeholder="Rivals FC" />
              </div>
              <div className="field" style={{ flex: 1 }}>
                <label htmlFor="date">Date</label>
                <input className="input" id="date" name="date" type="date" />
              </div>
            </div>
            <div className="field">
              <label>Source</label>
              <div className="seg">
                <button type="button" data-on={sourceType === "file"} onClick={() => setSourceType("file")}>
                  Local file
                </button>
                <button type="button" data-on={sourceType === "youtube"} onClick={() => setSourceType("youtube")}>
                  YouTube
                </button>
              </div>
            </div>
            <div className="field">
              <label htmlFor="source">{sourceType === "file" ? "Path on this machine" : "URL"}</label>
              <input
                className="input"
                id="source"
                name="source"
                required
                placeholder={sourceType === "file" ? "/data/videos/source/match.mp4" : "https://youtu.be/…"}
              />
            </div>
            <button className="btn btn--solid" type="submit" disabled={busy}>
              {busy ? "Queuing…" : "Ingest match"}
            </button>
            <p className="dim" style={{ margin: 0, fontSize: 11 }}>
              Ingest downloads if needed, probes the file, then builds a 480p proxy with dense
              keyframes so the browser scrubs instantly.
            </p>
          </form>
        </section>
      </div>

      <Toast message={error} onDone={() => setError(null)} />
    </div>
  );
}
