/** mm:ss.d -- the analyst reads these against a match clock all day. */
export function timecode(seconds: number | null | undefined, withTenths = false): string {
  if (seconds == null || Number.isNaN(seconds)) return "--:--";
  const total = Math.max(seconds, 0);
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = Math.floor(total % 60);
  const pad = (n: number) => String(n).padStart(2, "0");
  const base = h > 0 ? `${h}:${pad(m)}:${pad(s)}` : `${pad(m)}:${pad(s)}`;
  return withTenths ? `${base}.${Math.floor((total % 1) * 10)}` : base;
}

export const duration = (from: number, to: number) => `${Math.round(to - from)}s`;

export function relativeDate(iso: string): string {
  const d = new Date(iso.includes("T") ? iso : `${iso.replace(" ", "T")}Z`);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleDateString(undefined, { day: "2-digit", month: "short", year: "numeric" });
}
