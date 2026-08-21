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
