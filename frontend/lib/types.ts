export type IngestState = "pending" | "downloading" | "probing" | "proxying" | "ready" | "failed";
export type ClipStatus = "pending" | "approved" | "rejected";
export type RenderState = "pending" | "rendering" | "ready" | "failed";

export interface Match {
  id: number;
  title: string;
  opponent: string;
  date: string | null;
  source_type: "file" | "youtube";
  source_url: string | null;
  file_path: string | null;
  proxy_path: string | null;
  duration_s: number | null;
  fps: number | null;
  ingest_state: IngestState;
  ingest_error: string | null;
  created_at: string;
  tag_count?: number;
  approved_count?: number;
}

export interface Tag {
  id: number;
  match_id: number;
  t_start: number;
  t_end: number;
  category: string;
  source: string;
  note: string | null;
  created_at: string;
  clip_id: number | null;
  clip_status: ClipStatus | null;
  render_state: RenderState | null;
  order_index: number | null;
}

export interface Clip {
  id: number;
  tag_id: number;
  status: ClipStatus;
  order_index: number;
  review_path: string | null;
  final_path: string | null;
  render_state: RenderState;
  render_error: string | null;
  match_id: number;
  t_start: number;
  t_end: number;
  note: string | null;
  category: string;
  source: string;
  match_title: string;
  opponent: string;
}

export interface ExportRow {
  id: number;
  name: string;
  file_path: string | null;
  state: RenderState;
  error: string | null;
  created_at: string;
  clip_count?: number;
  clips?: { position: number; clip_id: number; t_start: number; t_end: number; note: string | null; match_title: string }[];
}

export interface Job {
  id: number;
  kind: "ingest" | "clip" | "export";
  entity_id: number;
  label: string;
  state: "queued" | "running" | "done" | "failed";
  progress: number;
  error: string | null;
  created_at: number;
}

/** GET /api/matches/:id/stats -- the M4 baseline numbers (backend app/stats.py). */
export interface MatchStats {
  match_id: number;
  title: string;
  duration_s: number | null;
  tags: {
    total: number;
    adjusted: number;
    corrections: number;
    adjusted_share: number | null;
    median_window_s: number | null;
    span_s: number | null;
  };
  clips: {
    pending: number;
    approved: number;
    rejected: number;
    failed_renders: number;
    reviewed: number;
    span_s: number | null;
  };
  padding: {
    before_s: number;
    after_s: number;
    sample: number;
    corrected_sample: number;
    corrected_median_before_s: number | null;
    corrected_median_after_s: number | null;
    suggested_before_s: number | null;
    suggested_after_s: number | null;
    verdict: "fits" | "check" | "unknown";
  };
  exports: { count: number; ready: number; last_render_s: number | null; last_name: string | null };
  totals: { measured_s: number | null; ratio_of_match: number | null };
}

export interface Health {
  ok: boolean;
  data_dir: string;
  /** [before, after] seconds -- the window the `G` hotkey applies. */
  tag_padding: [number, number];
  export: { width: number; height: number; fps: number };
}
