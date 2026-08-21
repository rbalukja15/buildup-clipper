"use client";

import Link from "next/link";
import { Suspense, useState } from "react";
import { useSearchParams } from "next/navigation";
import { api } from "@/lib/api";
import { useLiveData } from "@/lib/live";
import { percent, span, timecode } from "@/lib/format";
import type { Match, MatchStats } from "@/lib/types";
import { Toast } from "@/components/Toast";

export default function BaselinePage() {
  return (
    <Suspense fallback={<div className="dim">Loading…</div>}>
      <Baseline />
    </Suspense>
  );
}

function Baseline() {
  const params = useSearchParams();
  const matchId = Number(params.get("match") ?? 0) || undefined;
  const [matches] = useLiveData<Match[]>(() => api.matches(), []);
  // The loader closes over matchId: without it in deps, switching match from
  // the picker leaves the previous match's numbers on screen.
  const [stats] = useLiveData<MatchStats | null>(
    () => (matchId ? api.matchStats(matchId) : Promise.resolve(null)),
    null,
    [matchId],
  );
  const [note, setNote] = useState<string | null>(null);

  if (!matchId || !stats) {
    return (
      <div className="stack">
        <Header />
        <div className="panel rows">
          {matches.map((m) => (
            <Link className="row" key={m.id} href={`/baseline?match=${m.id}`}>
              <span className="row-id num">{String(m.id).padStart(2, "0")}</span>
              <span className="row-title">{m.title}</span>
              <span className="row-sub num row-hide">{timecode(m.duration_s)}</span>
              <span className="row-sub num row-hide">{m.tag_count ?? 0} tags</span>
              <span />
              <span className="btn btn--tiny btn--go">Numbers</span>
            </Link>
          ))}
          {matches.length === 0 && <div className="empty">Ingest a match first.</div>}
        </div>
      </div>
    );
  }

  const { tags, clips, padding, exports, totals } = stats;
  const ratio = totals.ratio_of_match;

  const copyHandoff = async () => {
    try {
      await navigator.clipboard.writeText(handoffTable(stats));
      setNote("Handoff table copied — paste it into docs/handoff.md.");
    } catch {
      setNote("Clipboard blocked by the browser; the table is in the panel below.");
    }
  };

  return (
    <div className="stack" style={{ gap: 20 }}>
      <Header title={stats.title} matchId={matchId} />

      <div className="stats">
        <Tile label="Build-ups found" value={String(tags.total)} sub={`${clips.reviewed} reviewed`} />
        <Tile
          label="Cuts nudged"
          value={String(tags.adjusted)}
          sub={`${percent(tags.adjusted_share)} of tags · ${tags.corrections} corrections`}
          tone={padding.verdict === "check" ? "bad" : padding.verdict === "fits" ? "go" : undefined}
        />
        <Tile label="Approved" value={String(clips.approved)} sub={`${clips.rejected} rejected`} tone="go" />
        <Tile
          label="Total vs runtime"
          value={ratio == null ? "—" : `${ratio.toFixed(2)}×`}
          sub={`target ≤ 1.2× · ${span(stats.duration_s)} of footage`}
          tone={ratio == null ? undefined : ratio <= 1.2 ? "go" : "bad"}
        />
      </div>

      <div className="grid-2">
        <section className="panel">
          <div className="panel-head">
            <span className="eyebrow">Where the time went</span>
            <button className="btn btn--tiny" onClick={copyHandoff}>
              Copy handoff table
            </button>
          </div>
          <div className="rows">
            <Line label="Tagging pass" value={span(tags.span_s)} sub="first tag → last tag" />
            <Line label="Review pass" value={span(clips.span_s)} sub="first verdict → last verdict" />
            <Line
              label="Export render"
              value={span(exports.last_render_s)}
              sub={exports.last_name ?? `${exports.count} exports`}
            />
            <Line label="Measured total" value={span(totals.measured_s)} sub="the three spans added up" strong />
          </div>
          <p className="dim" style={{ margin: 0, padding: "10px 14px", fontSize: 11, borderTop: "1px solid var(--line)" }}>
            Spans run from the first recorded action to the last, so a coffee break inside one
            counts and the minutes before the first tag do not. Compare them against the manual
            process on the same match — that side of the table is still a stopwatch.
          </p>
        </section>

        <section className="panel" style={{ alignSelf: "start" }}>
          <div className="panel-head">
            <span className="eyebrow">Tag padding</span>
            <span className="tick" data-tone={padding.verdict === "check" ? "bad" : padding.verdict === "fits" ? "go" : "wait"}>
              {padding.verdict === "check" ? "looks wrong" : padding.verdict === "fits" ? "fits" : "too few tags"}
            </span>
          </div>
          <div className="rows">
            <Line
              label="Current window"
              value={`−${padding.before_s}s / +${padding.after_s}s`}
              sub={`median clip ${span(tags.median_window_s)}`}
            />
            <Line
              label="When corrected, he chose"
              value={
                padding.corrected_median_before_s == null
                  ? "—"
                  : `−${padding.corrected_median_before_s}s / +${padding.corrected_median_after_s}s`
              }
              sub={`${padding.corrected_sample} of ${padding.sample} hotkey tags`}
            />
          </div>
          {padding.suggested_before_s != null ? (
            <div style={{ padding: "12px 14px", borderTop: "1px solid var(--line)" }}>
              <p className="muted" style={{ marginTop: 0, fontSize: 11 }}>
                More than one tag in five was corrected, which the spec calls a wrong default.
                Restart with:
              </p>
              <pre className="code">
                BUC_TAG_PAD_BEFORE={padding.suggested_before_s}
                {"\n"}BUC_TAG_PAD_AFTER={padding.suggested_after_s}
              </pre>
            </div>
          ) : (
            <p className="dim" style={{ margin: 0, padding: "12px 14px", fontSize: 11, borderTop: "1px solid var(--line)" }}>
              {padding.verdict === "fits"
                ? "One tag in five or fewer needed an I/O correction, so the window is doing its job."
                : padding.verdict === "check"
                  ? "The window is already set to what these corrections argue for. The rate above is this match's history — a match tagged with the current window is the one to judge it by."
                  : "A handful of tags is not yet a verdict — tag a full match before changing the window."}
            </p>
          )}
        </section>
      </div>

      <section className="panel">
        <div className="panel-head">
          <span className="eyebrow">Handoff table</span>
          <span className="dim">docs/handoff.md</span>
        </div>
        <pre className="code" style={{ margin: 0, borderRadius: 0, border: 0, overflowX: "auto" }}>
          {handoffTable(stats)}
        </pre>
      </section>

      <Toast message={note} onDone={() => setNote(null)} />
    </div>
  );
}

function Header({ title, matchId }: { title?: string; matchId?: number } = {}) {
  return (
    <div className="spread">
      <div>
        <div className="eyebrow">{title ?? "Pick a match"}</div>
        <h1 className="display">
          Match <em>baseline</em>
        </h1>
      </div>
      {matchId && (
        <div className="inline">
          <Link className="btn btn--tiny" href={`/tag?match=${matchId}`}>
            Tag
          </Link>
          <Link className="btn btn--tiny" href={`/review?match=${matchId}`}>
            Review
          </Link>
          <Link className="btn btn--tiny" href="/baseline">
            All matches
          </Link>
        </div>
      )}
    </div>
  );
}

function Tile({
  label,
  value,
  sub,
  tone,
}: {
  label: string;
  value: string;
  sub: string;
  tone?: "go" | "bad";
}) {
  return (
    <div className="stat" data-tone={tone}>
      <div className="eyebrow">{label}</div>
      <div className="stat-value num">{value}</div>
      <div className="row-sub">{sub}</div>
    </div>
  );
}

function Line({ label, value, sub, strong }: { label: string; value: string; sub?: string; strong?: boolean }) {
  return (
    <div className="row" style={{ gridTemplateColumns: "minmax(0, 1fr) auto" }}>
      <div style={{ minWidth: 0 }}>
        <div className="row-title" style={strong ? { color: "var(--lime)" } : undefined}>
          {label}
        </div>
        {sub && <div className="row-sub">{sub}</div>}
      </div>
      <span className="num" style={{ fontSize: strong ? 16 : 14 }}>
        {value}
      </span>
    </div>
  );
}

/** The table in docs/handoff.md, with the clipper column filled in. */
function handoffTable(s: MatchStats): string {
  const rows: [string, string, string][] = [
    ["Match runtime", "", span(s.duration_s)],
    ["Time to first tagged pass (wall clock)", "", span(s.tags.span_s)],
    ["Time spent reviewing / fixing cuts", "", span(s.clips.span_s)],
    ["Time spent joining + exporting", "", span(s.exports.last_render_s)],
    ["**Total time per match**", "", span(s.totals.measured_s)],
    ["Number of build-ups found", "", String(s.tags.total)],
    [
      "Cuts the analyst had to nudge (`I`/`O`)",
      "—",
      `${s.tags.adjusted} (${percent(s.tags.adjusted_share)})`,
    ],
    ["Clips rejected after review", "—", String(s.clips.rejected)],
  ];
  return [
    "| measure | manual | clipper |",
    "|---------|--------|---------|",
    ...rows.map(([a, b, c]) => `| ${a} | ${b} | ${c} |`),
  ].join("\n");
}
