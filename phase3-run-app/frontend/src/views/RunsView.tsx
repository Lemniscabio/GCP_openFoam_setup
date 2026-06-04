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
              <div
                className="stack-item"
                key={r.job_name}
                style={{ display: "grid", gridTemplateColumns: "1fr auto auto", alignItems: "center", gap: 12, minWidth: 0 }}
              >
                <span
                  title={r.job_name}
                  style={{ minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", fontFamily: "var(--f-mono)", fontSize: 12, color: "var(--ink-2)" }}
                >
                  {r.job_name}
                </span>
                <span
                  style={{
                    display: "inline-flex",
                    alignItems: "center",
                    flexShrink: 0,
                    padding: "2px 8px",
                    borderRadius: 999,
                    fontSize: 10.5,
                    fontWeight: 700,
                    fontFamily: "var(--f-mono)",
                    whiteSpace: "nowrap",
                    color: STATE_COLOR[r.state] ?? "var(--ink-2)",
                    background: (STATE_COLOR[r.state] ?? "#888") + "18",
                    border: "1px solid " + (STATE_COLOR[r.state] ?? "#888") + "30",
                  }}
                >
                  {r.state}{r.progress_pct != null ? ` · ${r.progress_pct}%` : ""}
                </span>
                <a className="btn-add" href={consoleUrl(r.job_name)} target="_blank" rel="noreferrer"
                   style={{ flexShrink: 0, padding: "4px 10px", fontSize: 11.5 }}>Console ↗</a>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
