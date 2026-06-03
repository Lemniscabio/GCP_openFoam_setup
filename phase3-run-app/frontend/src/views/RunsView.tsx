import { useEffect, useState } from "react";
import { api, type RunSummary } from "../lib/client";

const PROJECT = "cfd-lemnisca";
const REGION = "us-central1";
const consoleUrl = (job: string) =>
  `https://console.cloud.google.com/batch/jobsDetail/regions/${REGION}/jobs/${job}?project=${PROJECT}`;

const STATE_COLOR: Record<string, string> = {
  RUNNING: "#2563eb", SUCCEEDED: "#059669", FAILED: "#b91c1c",
  QUEUED: "#a16207", SCHEDULED: "#a16207",
};

export function RunsView() {
  const [runs, setRuns] = useState<RunSummary[]>([]);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    async function tick() {
      try {
        const r = await api.listRuns();
        if (alive) { setRuns(r.runs); setErr(null); }
      } catch (e) {
        if (alive) setErr(String(e));
      }
    }
    tick();
    const id = setInterval(tick, 4000); // poll
    return () => { alive = false; clearInterval(id); };
  }, []);

  return (
    <div className="step" style={{ gridTemplateColumns: "1fr" }}>
      <div className="panel">
        <div className="panel-head">
          <div className="ph-num">04</div>
          <div className="ph-text">
            <div className="ph-title">Runs</div>
            <div className="ph-sub">live status · polled every 4s</div>
          </div>
        </div>
        <div className="panel-body">
          {err && <div className="empty-state">Error: {err}</div>}
          {!err && runs.length === 0 && <div className="empty-state">No runs yet.</div>}
          <div className="stack">
            {runs.map((r) => (
              <div className="stack-item" key={r.job_name} style={{ gridTemplateColumns: "1fr auto auto" }}>
                <span className="stack-path" title={r.job_name}>{r.job_name}</span>
                <span style={{ fontFamily: "var(--f-mono)", fontSize: 11.5, color: STATE_COLOR[r.state] ?? "var(--ink-2)" }}>
                  {r.state}{r.progress_pct != null ? ` · ${r.progress_pct}%` : ""}
                </span>
                <a className="btn-add" href={consoleUrl(r.job_name)} target="_blank" rel="noreferrer"
                   style={{ padding: "4px 10px", fontSize: 11.5 }}>Console ↗</a>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
