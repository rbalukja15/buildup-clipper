"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { activeJobs, useLive } from "@/lib/live";

const NAV = [
  { href: "/", label: "MTC", title: "Matches" },
  { href: "/tag", label: "TAG", title: "Tag" },
  { href: "/review", label: "REV", title: "Review" },
  { href: "/exports", label: "OUT", title: "Exports" },
];

export function Shell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const { jobs, connected } = useLive();
  const running = activeJobs(jobs);
  const failed = jobs.filter((j) => j.state === "failed").slice(-1)[0];

  return (
    <div className="shell">
      <nav className="rail">
        <div className="rail-mark">
          Build<em>·</em>Up
        </div>
        {NAV.map((item) => (
          <Link
            key={item.href}
            href={item.href}
            className="rail-link"
            title={item.title}
            data-active={item.href === "/" ? pathname === "/" : pathname.startsWith(item.href)}
          >
            {item.label}
          </Link>
        ))}
      </nav>

      <div className="main">
        <header className="strip">
          <span className="tick" data-tone={connected ? "go" : "bad"}>
            {connected ? "live" : "offline"}
          </span>

          <div className="jobs">
            {running.slice(-2).map((job) => (
              <div className="job" key={job.id}>
                <div className="job-label">
                  <span>{job.label}</span>
                  <span className="num">{Math.round(job.progress * 100)}%</span>
                </div>
                <div className="bar">
                  <span style={{ width: `${Math.max(job.progress * 100, 2)}%` }} />
                </div>
              </div>
            ))}
            {running.length === 0 && failed && (
              <span className="tick" data-tone="bad" title={failed.error ?? ""}>
                {failed.label} failed
              </span>
            )}
            {running.length === 0 && !failed && <span className="dim">idle</span>}
          </div>
        </header>

        <main className={pathname.startsWith("/tag") ? "content content--flush" : "content"}>{children}</main>
      </div>
    </div>
  );
}
