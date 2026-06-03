"use client";

// [M7-SCHED-04] CVE job monitor — scheduled / new-evidence re-runs and their status,
// so the admin can observe the scheduler (retry/backoff) and re-publish upgraded data.

import Link from "next/link";
import { useEffect, useState } from "react";

import { listJobs, type CveJob } from "../../lib/api";

const STATUS_COLOR: Record<string, string> = {
  PENDING: "#c98a00",
  RUNNING: "#2f6fb0",
  DONE: "#1b8a3a",
  FAILED: "#b03030",
};

export default function JobsPage() {
  const [jobs, setJobs] = useState<CveJob[]>([]);
  const [error, setError] = useState<string | null>(null);

  async function refresh() {
    try {
      setJobs(await listJobs());
      setError(null);
    } catch (e) {
      setError(`Could not load jobs: ${String(e)}`);
    }
  }

  useEffect(() => {
    void refresh();
    const t = setInterval(() => void refresh(), 5000); // live-ish view of the queue
    return () => clearInterval(t);
  }, []);

  return (
    <main
      style={{ maxWidth: 920, margin: "2rem auto", fontFamily: "system-ui" }}
    >
      <p>
        <Link href="/themes">← All themes</Link>
      </p>
      <h1>CVE jobs</h1>
      <p>
        <small>
          Scheduled re-runs (due filings) + new-evidence triggers, with
          retry/backoff. Re-published by an admin after they complete.
        </small>
      </p>
      <p>
        <button type="button" onClick={() => void refresh()}>
          Refresh
        </button>
      </p>
      {error && <p style={{ color: "crimson" }}>{error}</p>}

      <table
        style={{ borderCollapse: "collapse", width: "100%", fontSize: 14 }}
      >
        <thead>
          <tr>
            {[
              "company",
              "trigger",
              "status",
              "attempts",
              "reason",
              "updated",
            ].map((h) => (
              <th
                key={h}
                style={{
                  textAlign: "left",
                  borderBottom: "1px solid #ccc",
                  padding: 6,
                }}
              >
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {jobs.map((j) => (
            <tr key={j.id}>
              <td style={{ padding: 6 }}>{j.company}</td>
              <td style={{ padding: 6 }}>{j.trigger}</td>
              <td
                style={{
                  padding: 6,
                  color: STATUS_COLOR[j.status] ?? "#444",
                  fontWeight: 600,
                }}
              >
                {j.status}
              </td>
              <td style={{ padding: 6 }}>{j.attempts}</td>
              <td style={{ padding: 6 }}>{j.reason ?? "—"}</td>
              <td style={{ padding: 6 }}>
                <small>{j.updated_at}</small>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {jobs.length === 0 && <p>No jobs yet.</p>}
    </main>
  );
}
