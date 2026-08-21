"use client";

import { useState } from "react";
import { api, ApiError, downloadUrl } from "@/lib/api";
import { useLive, useLiveData } from "@/lib/live";
import { relativeDate, timecode } from "@/lib/format";
import type { ExportRow } from "@/lib/types";
import { Toast } from "@/components/Toast";

export default function ExportsPage() {
  const { refresh, jobs } = useLive();
  const [exports] = useLiveData<ExportRow[]>(() => api.exports(), []);
  const [open, setOpen] = useState<number | null>(null);
  const [detail] = useLiveData<ExportRow | null>(
    () => (open ? api.export(open) : Promise.resolve(null)),
    null,
    [open],
  );
  const [error, setError] = useState<string | null>(null);

  const jobFor = (id: number) =>
    jobs.find((j) => j.kind === "export" && j.entity_id === id && (j.state === "running" || j.state === "queued"));

  const remove = async (row: ExportRow) => {
    if (!confirm(`Delete "${row.name}"? The rendered file is removed too.`)) return;
    try {
      await api.deleteExport(row.id);
      refresh();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
    }
  };

  return (
    <div className="stack" style={{ gap: 20 }}>
      <div className="spread">
        <div>
          <div className="eyebrow">Frame-exact re-encode · uniform 1280×720 · concat</div>
          <h1 className="display">
            The <em>deliverable</em>
          </h1>
        </div>
      </div>

      {exports.length === 0 ? (
        <div className="empty">
          Nothing exported yet. Approve clips in review, then hit <em>Export</em>.
        </div>
      ) : (
        <div className="panel rows">
          {exports.map((row) => {
            const job = jobFor(row.id);
            return (
              <div className="row" key={row.id} style={{ gridTemplateColumns: "46px minmax(0,1fr) 130px 110px auto" }}>
                <span className="row-id num">{String(row.id).padStart(2, "0")}</span>
                <div style={{ minWidth: 0 }}>
                  <div className="row-title">{row.name}</div>
                  <div className="row-sub">
                    {row.clip_count ?? 0} clips · {relativeDate(row.created_at)}
                    {row.error ? ` · ${row.error}` : ""}
                  </div>
                  {job && (
                    <div className="bar" style={{ marginTop: 6 }}>
                      <span style={{ width: `${Math.max(job.progress * 100, 2)}%` }} />
                    </div>
                  )}
                </div>
                <span
                  className="tick"
                  data-tone={row.state === "ready" ? "go" : row.state === "failed" ? "bad" : "wait"}
                  title={row.error ?? ""}
                >
                  {job ? job.label : row.state}
                </span>
                <button className="btn btn--tiny" onClick={() => setOpen(open === row.id ? null : row.id)}>
                  {open === row.id ? "Hide" : "Contents"}
                </button>
                <div className="inline" style={{ gap: 6 }}>
                  {row.state === "ready" ? (
                    <a className="btn btn--solid btn--tiny" href={downloadUrl(row.id)} download>
                      Download
                    </a>
                  ) : (
                    <button className="btn btn--tiny" onClick={() => void api.rerenderExport(row.id).then(refresh)}>
                      Retry
                    </button>
                  )}
                  <button className="btn btn--kill btn--tiny" onClick={() => remove(row)}>
                    ×
                  </button>
                </div>
              </div>
            );
          })}
        </div>
      )}

      {open && detail?.id === open && (
        <section className="panel">
          <div className="panel-head">
            <span className="eyebrow">{detail.name} — running order</span>
            <span className="dim num">{detail.clips?.length ?? 0}</span>
          </div>
          <div className="rows">
            {detail.clips?.map((clip) => (
              <div className="row" key={clip.clip_id} style={{ gridTemplateColumns: "46px minmax(0,1fr) 150px" }}>
                <span className="row-id num">{String(clip.position + 1).padStart(2, "0")}</span>
                <div style={{ minWidth: 0 }}>
                  <div className="row-title">{clip.match_title}</div>
                  {clip.note && <div className="row-sub">{clip.note}</div>}
                </div>
                <span className="row-sub num">
                  {timecode(clip.t_start)} → {timecode(clip.t_end)}
                </span>
              </div>
            ))}
          </div>
        </section>
      )}

      <Toast message={error} onDone={() => setError(null)} />
    </div>
  );
}
