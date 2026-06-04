import { useEffect, useState } from "react";
import { motion } from "framer-motion";
import { Badge } from "@/components/ui/badge";
import { useListItemVariants, usePanelVariants } from "@/lib/motion";
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
  const panelVariants = usePanelVariants();
  const listVariants = useListItemVariants();

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
    <motion.div
      className="step"
      style={{ gridTemplateColumns: "1fr" }}
      initial="hidden"
      animate="visible"
      exit="exit"
      variants={panelVariants}
    >
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
            {runs.map((r, index) => {
              const stateBadge = (
                <Badge style={{ color: STATE_COLOR[r.state] ?? undefined, flexShrink: 0 }}>
                  {r.state}{r.progress_pct != null ? ` · ${r.progress_pct}%` : ""}
                </Badge>
              );

              return (
              <motion.div
                className="stack-item"
                key={r.job_name}
                custom={index}
                variants={listVariants}
                initial="hidden"
                animate="visible"
                style={{ display: "grid", gridTemplateColumns: "1fr auto auto", alignItems: "center", gap: 12, minWidth: 0 }}
              >
                <span
                  title={r.job_name}
                  style={{ minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", fontFamily: "var(--f-mono)", fontSize: 12, color: "var(--ink-2)" }}
                >
                  {r.job_name}
                </span>
                {r.state === "RUNNING" ? (
                  <motion.span
                    animate={{ opacity: [1, 0.6, 1] }}
                    transition={{ duration: 2, repeat: Infinity, ease: "easeInOut" }}
                    style={{ display: "inline-flex", flexShrink: 0 }}
                  >
                    {stateBadge}
                  </motion.span>
                ) : stateBadge}
                <a className="btn-add" href={consoleUrl(r.job_name)} target="_blank" rel="noreferrer"
                   style={{ flexShrink: 0, padding: "4px 10px", fontSize: 11.5 }}>Console ↗</a>
              </motion.div>
              );
            })}
          </div>
        </div>
      </div>
    </motion.div>
  );
}
