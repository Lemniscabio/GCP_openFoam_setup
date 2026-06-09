import { useEffect, useState } from "react";
import { motion } from "framer-motion";
import { Badge } from "@/components/ui/badge";
import { useListItemVariants, usePanelVariants } from "@/lib/motion";
import { api, type JobEvent, type JobLog, type RunSummary } from "../lib/client";

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
  const [openEvents, setOpenEvents] = useState<Set<string>>(new Set());
  const [events, setEvents] = useState<Record<string, JobEvent[]>>({});
  const [eventsLoading, setEventsLoading] = useState<Set<string>>(new Set());
  const [eventsError, setEventsError] = useState<Record<string, string>>({});
  const [openLogs, setOpenLogs] = useState<Set<string>>(new Set());
  const [logs, setLogs] = useState<Record<string, JobLog>>({});
  const [logsLoading, setLogsLoading] = useState<Set<string>>(new Set());
  const [logsError, setLogsError] = useState<Record<string, string>>({});
  const [err, setErr] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
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
      } finally {
        if (alive) setLoading(false);
      }
    }
    tick();
    const id = setInterval(tick, 4000);
    return () => { alive = false; clearInterval(id); };
  }, []);

  async function toggleEvents(job: string) {
    const opening = !openEvents.has(job);
    setOpenEvents((current) => {
      const next = new Set(current);
      opening ? next.add(job) : next.delete(job);
      return next;
    });
    if (!opening || Object.hasOwn(events, job) || eventsLoading.has(job)) return;

    setEventsLoading((current) => new Set(current).add(job));
    try {
      const response = await api.getJobEvents(job);
      setEvents((current) => ({ ...current, [job]: response.events }));
      setEventsError((current) => {
        const next = { ...current };
        delete next[job];
        return next;
      });
    } catch (error) {
      setEventsError((current) => ({ ...current, [job]: String(error) }));
    } finally {
      setEventsLoading((current) => {
        const next = new Set(current);
        next.delete(job);
        return next;
      });
    }
  }

  async function toggleLog(job: string, project: string, caseId: string) {
    const key = `${job}/${caseId}`;
    const opening = !openLogs.has(key);
    setOpenLogs((current) => {
      const next = new Set(current);
      opening ? next.add(key) : next.delete(key);
      return next;
    });
    if (!opening || Object.hasOwn(logs, key) || logsLoading.has(key)) return;

    setLogsLoading((current) => new Set(current).add(key));
    try {
      const response = await api.getJobLog(job, project, caseId);
      setLogs((current) => ({ ...current, [key]: response }));
      setLogsError((current) => {
        const next = { ...current };
        delete next[key];
        return next;
      });
    } catch (error) {
      setLogsError((current) => ({ ...current, [key]: String(error) }));
    } finally {
      setLogsLoading((current) => {
        const next = new Set(current);
        next.delete(key);
        return next;
      });
    }
  }

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
            <div className="ph-sub">live status · auto-updated</div>
          </div>
        </div>
        <div className="panel-body">
          {err && <div className="empty-state">Error: {err}</div>}
          {loading && (
            <div className="stack">
              {[0, 1, 2].map((i) => (
                <div key={i} className="stack-item skeleton-row" style={{ animationDelay: `${i * 120}ms` }}>
                  <span className="skel skel-long" />
                  <span className="skel skel-short" />
                  <span className="skel skel-btn" />
                </div>
              ))}
            </div>
          )}
          {!loading && !err && runs.length === 0 && <div className="empty-state">No runs yet.</div>}
          <div className="stack">
            {runs.map((r, index) => {
              const job = r.batch_job_id || r.job_name;
              const stateBadge = (
                <Badge style={{ color: STATE_COLOR[r.state] ?? undefined, flexShrink: 0 }}>
                  {r.state}{r.progress_pct != null ? ` · ${r.progress_pct}%` : ""}
                </Badge>
              );

              return (
              <motion.div
                className="stack-item"
                key={job}
                custom={index}
                variants={listVariants}
                initial="hidden"
                animate="visible"
                style={{ display: "block", minWidth: 0 }}
              >
                <div style={{ display: "grid", gridTemplateColumns: "1fr auto auto auto", alignItems: "center", gap: 8 }}>
                  <span
                    title={job}
                    style={{ minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", fontFamily: "var(--f-mono)", fontSize: 12, color: "var(--ink-2)" }}
                  >
                    {job}
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
                  <button className="btn-add" type="button" onClick={() => void toggleEvents(job)}
                    style={{ flexShrink: 0, padding: "4px 10px", fontSize: 11.5 }}>
                    {openEvents.has(job) ? "Hide events" : "Events"}
                  </button>
                  <a className="btn-add" href={consoleUrl(job)} target="_blank" rel="noreferrer"
                    style={{ flexShrink: 0, padding: "4px 10px", fontSize: 11.5 }}>Console ↗</a>
                </div>

                {openEvents.has(job) && (
                  <div style={{ marginTop: 10, padding: 10, borderRadius: 6, background: "#15171b" }}>
                    {eventsLoading.has(job) && <div className="foot-code">Loading events…</div>}
                    {eventsError[job] && <div className="foot-code">Error: {eventsError[job]}</div>}
                    {!eventsLoading.has(job) && !eventsError[job] && events[job]?.length === 0 && (
                      <div className="foot-code foot-empty">No events (job may be aged out).</div>
                    )}
                    {events[job]?.map((event, eventIndex) => (
                      <div className="foot-code" key={`${event.event_time}-${event.type}-${eventIndex}`}>
                        {event.event_time || "time unavailable"} · {event.type || "EVENT"} — {event.description}
                      </div>
                    ))}
                  </div>
                )}

                {r.case_ids.length > 0 && (
                  <div style={{ display: "grid", gap: 8, marginTop: 10 }}>
                    {r.case_ids.map((caseId) => {
                      const logKey = `${job}/${caseId}`;
                      const log = logs[logKey];
                      return (
                        <div key={caseId} style={{ borderTop: "1px solid var(--line-2)", paddingTop: 8 }}>
                          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8 }}>
                            <span style={{ fontFamily: "var(--f-mono)", fontSize: 11.5, color: "var(--ink-2)" }}>{caseId}</span>
                            <button className="btn-add" type="button" onClick={() => void toggleLog(job, r.project, caseId)}
                              style={{ padding: "4px 10px", fontSize: 11.5 }}>
                              {openLogs.has(logKey) ? "Hide log" : "View log"}
                            </button>
                          </div>
                          {openLogs.has(logKey) && (
                            <div style={{ marginTop: 8, padding: 10, borderRadius: 6, background: "#15171b" }}>
                              {logsLoading.has(logKey) && <div className="foot-code">Loading log…</div>}
                              {logsError[logKey] && <div className="foot-code">Error: {logsError[logKey]}</div>}
                              {log?.missing && <div className="foot-code foot-empty">No log yet (still running?).</div>}
                              {log?.truncated && <div className="foot-code foot-empty">Showing last 256 KB.</div>}
                              {log && !log.missing && (
                                <pre className="foot-code" style={{ maxHeight: 320, overflow: "auto" }}>{log.text}</pre>
                              )}
                            </div>
                          )}
                        </div>
                      );
                    })}
                  </div>
                )}
              </motion.div>
              );
            })}
          </div>
        </div>
      </div>
    </motion.div>
  );
}
