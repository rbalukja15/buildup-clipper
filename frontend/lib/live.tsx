"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import { API_BASE, api } from "./api";
import type { Job } from "./types";

interface Live {
  jobs: Job[];
  /** Bumped whenever the backend says a row changed -- pages re-fetch on it. */
  revision: number;
  connected: boolean;
  refresh: () => void;
}

const LiveContext = createContext<Live>({ jobs: [], revision: 0, connected: false, refresh: () => {} });

export function LiveProvider({ children }: { children: React.ReactNode }) {
  const [jobs, setJobs] = useState<Job[]>([]);
  const [revision, setRevision] = useState(0);
  const [connected, setConnected] = useState(false);
  const retry = useRef<ReturnType<typeof setTimeout> | null>(null);

  const bump = useCallback(() => setRevision((r) => r + 1), []);

  useEffect(() => {
    let source: EventSource | null = null;
    let closed = false;

    const upsert = (job: Job) =>
      setJobs((current) => {
        const next = current.filter((j) => j.id !== job.id);
        next.push(job);
        return next.slice(-40);
      });

    const connect = () => {
      source = new EventSource(`${API_BASE}/api/events`);
      source.onopen = () => setConnected(true);
      source.onmessage = (event) => {
        const payload = JSON.parse(event.data);
        if (payload.type === "hello") setJobs(payload.jobs ?? []);
        else if (payload.type === "job") {
          upsert(payload.job);
          if (payload.job.state === "done" || payload.job.state === "failed") bump();
        } else if (payload.type === "changed") bump();
      };
      source.onerror = () => {
        setConnected(false);
        source?.close();
        // The backend is a local process; a restart should heal on its own.
        if (!closed) retry.current = setTimeout(connect, 2000);
      };
    };

    connect();
    api.jobs().then(setJobs).catch(() => undefined);

    return () => {
      closed = true;
      source?.close();
      if (retry.current) clearTimeout(retry.current);
    };
  }, [bump]);

  const value = useMemo(() => ({ jobs, revision, connected, refresh: bump }), [jobs, revision, connected, bump]);
  return <LiveContext.Provider value={value}>{children}</LiveContext.Provider>;
}

export const useLive = () => useContext(LiveContext);

export const activeJobs = (jobs: Job[]) => jobs.filter((j) => j.state === "queued" || j.state === "running");

/** Re-runs `load` on mount and whenever the backend reports a change. */
export function useLiveData<T>(
  load: () => Promise<T>,
  initial: T,
): [T, React.Dispatch<React.SetStateAction<T>>] {
  const { revision } = useLive();
  const [data, setData] = useState<T>(initial);
  const loadRef = useRef(load);
  loadRef.current = load;

  useEffect(() => {
    let cancelled = false;
    loadRef.current().then((value) => {
      if (!cancelled) setData(value);
    }).catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [revision]);

  return [data, setData];
}
