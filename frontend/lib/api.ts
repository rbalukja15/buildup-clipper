import type { Clip, ExportRow, Job, Match, Tag } from "./types";

/** Empty in the packaged build (FastAPI serves the UI); the dev server points
 *  at uvicorn on :8000 via .env.development. */
export const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? "";

export class ApiError extends Error {
  constructor(message: string, readonly status: number) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: init?.body ? { "content-type": "application/json", ...init?.headers } : init?.headers,
  });
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`;
    try {
      const body = await res.json();
      if (typeof body.detail === "string") detail = body.detail;
      else if (Array.isArray(body.detail)) detail = body.detail.map((d: any) => d.msg).join("; ");
    } catch {
      /* non-JSON error body -- keep the status line */
    }
    throw new ApiError(detail, res.status);
  }
  return res.status === 204 ? (undefined as T) : ((await res.json()) as T);
}

const post = <T,>(path: string, body?: unknown) =>
  request<T>(path, { method: "POST", body: body === undefined ? undefined : JSON.stringify(body) });

export const api = {
  matches: () => request<Match[]>("/api/matches"),
  match: (id: number) => request<Match>(`/api/matches/${id}`),
  createMatch: (body: Record<string, unknown>) => post<Match>("/api/matches", body),
  reingest: (id: number) => post<{ ok: true }>(`/api/matches/${id}/reingest`),
  deleteMatch: (id: number) => request<void>(`/api/matches/${id}`, { method: "DELETE" }),

  tags: (matchId: number) => request<Tag[]>(`/api/matches/${matchId}/tags`),
  createTag: (matchId: number, body: Record<string, unknown>) =>
    post<Tag>(`/api/matches/${matchId}/tags`, body),
  updateTag: (tagId: number, body: Record<string, unknown>) =>
    request<Tag>(`/api/tags/${tagId}`, { method: "PATCH", body: JSON.stringify(body) }),
  deleteTag: (tagId: number) => request<void>(`/api/tags/${tagId}`, { method: "DELETE" }),
  undoLastTag: (matchId: number) =>
    request<void>(`/api/matches/${matchId}/tags/last`, { method: "DELETE" }),

  clips: (params: { matchId?: number; status?: string } = {}) => {
    const q = new URLSearchParams();
    if (params.matchId != null) q.set("match_id", String(params.matchId));
    if (params.status) q.set("status", params.status);
    return request<Clip[]>(`/api/clips${q.size ? `?${q}` : ""}`);
  },
  updateClip: (id: number, body: Record<string, unknown>) =>
    request<Clip>(`/api/clips/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
  reorderClips: (clipIds: number[]) => post<{ ok: true }>("/api/clips/reorder", { clip_ids: clipIds }),
  rerenderClip: (id: number) => post<{ ok: true }>(`/api/clips/${id}/rerender`),

  exports: () => request<ExportRow[]>("/api/exports"),
  export: (id: number) => request<ExportRow>(`/api/exports/${id}`),
  createExport: (body: Record<string, unknown>) => post<ExportRow>("/api/exports", body),
  rerenderExport: (id: number) => post<{ ok: true }>(`/api/exports/${id}/rerender`),
  deleteExport: (id: number) => request<void>(`/api/exports/${id}`, { method: "DELETE" }),

  jobs: () => request<Job[]>("/api/jobs"),
};

export const proxyUrl = (matchId: number) => `${API_BASE}/api/media/proxy/${matchId}`;
export const clipUrl = (clipId: number) => `${API_BASE}/api/media/clip/${clipId}`;
export const downloadUrl = (exportId: number) => `${API_BASE}/api/exports/${exportId}/download`;
