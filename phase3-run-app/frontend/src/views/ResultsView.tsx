import { useEffect, useMemo, useState } from "react";
import { motion } from "framer-motion";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { usePanelVariants } from "@/lib/motion";
import { api, type ResultFile, type ResultRun } from "../lib/client";

type PendingDownload =
  | { kind: "single"; label: string; object: string }
  | {
      kind: "archive";
      label: string;
      project: string;
      job: string;
      caseId?: string;
      fileCount?: number;
    };

const runKey = (run: ResultRun) => `${run.project}/${run.codename}`;
const caseKey = (run: ResultRun, caseId: string) => `${runKey(run)}/${caseId}`;
const objectPath = (run: ResultRun, caseId: string, name: string) =>
  `results/${run.project}/${run.codename}/${caseId}/${name}`;

function formatSize(bytes: number) {
  if (bytes < 1024) return `${bytes} B`;
  const units = ["KiB", "MiB", "GiB", "TiB"];
  let value = bytes / 1024;
  let unit = units[0];
  for (let i = 1; value >= 1024 && i < units.length; i++) {
    value /= 1024;
    unit = units[i];
  }
  return `${value.toFixed(value >= 10 ? 1 : 2)} ${unit}`;
}

export function ResultsView() {
  const [runs, setRuns] = useState<ResultRun[]>([]);
  const [expandedProjects, setExpandedProjects] = useState<Set<string>>(new Set());
  const [expandedRuns, setExpandedRuns] = useState<Set<string>>(new Set());
  const [expandedCases, setExpandedCases] = useState<Set<string>>(new Set());
  const [files, setFiles] = useState<Record<string, ResultFile[]>>({});
  const [loadingFiles, setLoadingFiles] = useState<Set<string>>(new Set());
  const [pending, setPending] = useState<PendingDownload | null>(null);
  const [missing, setMissing] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const panelVariants = usePanelVariants();
  const projects = useMemo(() => {
    const grouped = new Map<string, ResultRun[]>();
    for (const run of runs) grouped.set(run.project, [...(grouped.get(run.project) ?? []), run]);
    return [...grouped.entries()].sort(([a], [b]) => a.localeCompare(b));
  }, [runs]);

  useEffect(() => {
    let alive = true;
    api.getResults()
      .then((response) => { if (alive) { setRuns(response.results); setErr(null); } })
      .catch((error) => { if (alive) setErr(String(error)); })
      .finally(() => { if (alive) setLoading(false); });
    return () => { alive = false; };
  }, []);

  function toggle(setter: React.Dispatch<React.SetStateAction<Set<string>>>, key: string) {
    setter((current) => {
      const next = new Set(current);
      next.has(key) ? next.delete(key) : next.add(key);
      return next;
    });
  }

  async function loadCase(run: ResultRun, caseId: string) {
    const key = caseKey(run, caseId);
    if (files[key]) return files[key];
    setLoadingFiles((current) => new Set(current).add(key));
    try {
      const response = await api.getResultFiles(run.project, run.codename, caseId);
      setFiles((current) => ({ ...current, [key]: response.files }));
      return response.files;
    } finally {
      setLoadingFiles((current) => {
        const next = new Set(current);
        next.delete(key);
        return next;
      });
    }
  }

  async function expandCase(run: ResultRun, caseId: string) {
    const key = caseKey(run, caseId);
    toggle(setExpandedCases, key);
    if (!expandedCases.has(key)) {
      try { await loadCase(run, caseId); } catch (error) { setErr(String(error)); }
    }
  }

  function confirmCase(run: ResultRun, caseId: string, caseFiles: ResultFile[]) {
    setPending({
      kind: "archive",
      label: `${run.codename} / ${caseId}`,
      project: run.project,
      job: run.codename,
      caseId,
      fileCount: caseFiles.length,
    });
  }

  function confirmRun(run: ResultRun) {
    setPending({
      kind: "archive",
      label: `${run.project} / ${run.codename}`,
      project: run.project,
      job: run.codename,
    });
  }

  function followDownloadUrl(url: string) {
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.rel = "noreferrer";
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
  }

  async function download() {
    if (!pending || busy) return;
    const downloadRequest = pending;
    setBusy(true);
    setMissing([]);
    try {
      if (downloadRequest.kind === "single") {
        const response = await api.postDownloads([downloadRequest.object]);
        setMissing(response.missing);
        if (response.downloads.length > 0) {
          followDownloadUrl(response.downloads[0].url);
        }
      } else {
        const response = await api.postArchive(
          downloadRequest.project,
          downloadRequest.job,
          downloadRequest.caseId,
        );
        setMissing(response.missing);
        followDownloadUrl(response.url);
      }
      setPending(null);
    } catch (error) {
      setErr(String(error));
    } finally {
      setBusy(false);
    }
  }

  return (
    <motion.div className="step" style={{ gridTemplateColumns: "1fr" }} initial="hidden" animate="visible" exit="exit" variants={panelVariants}>
      <div className="panel">
        <div className="panel-head">
          <div className="ph-num">05</div>
          <div className="ph-text">
            <div className="ph-title">Results</div>
            <div className="ph-sub">{loading ? "loading…" : `${runs.length} run(s) across ${projects.length} project(s)`}</div>
          </div>
        </div>
        <div className="panel-body">
          {err && <div className="empty-state">Error: {err}</div>}
          {missing.length > 0 && <div className="empty-state" style={{ fontStyle: "normal" }}>{missing.length} object(s) were missing and could not be downloaded.</div>}
          {!loading && !err && runs.length === 0 && <div className="empty-state">No results yet.</div>}
          <div className="stack">
            {projects.map(([project, projectRuns]) => {
              const projectOpen = expandedProjects.has(project);
              return (
                <div className="grid gap-1" key={project}>
                  <button className="stack-item w-full cursor-pointer text-left" onClick={() => toggle(setExpandedProjects, project)} aria-expanded={projectOpen}>
                    <span className="text-[11px] text-[var(--ink-2)]">{projectOpen ? "▾" : "▸"}</span>
                    <span className="stack-id">{project}</span>
                    <span className="stack-path">{projectRuns.length} run(s)</span>
                  </button>
                  {projectOpen && (
                    <div className="ml-5 grid gap-1 border-l border-black/10 pl-3">
                      {projectRuns.map((run) => {
                        const key = runKey(run);
                        const runOpen = expandedRuns.has(key);
                        return (
                          <div className="grid gap-1" key={key}>
                            <div className="stack-item">
                              <button className="min-w-0 flex-1 cursor-pointer border-0 bg-transparent text-left" onClick={() => toggle(setExpandedRuns, key)} aria-expanded={runOpen}>
                                <span className="stack-id block">{runOpen ? "▾ " : "▸ "}{run.codename}</span>
                                <span className="stack-path block">{run.submitted_by} · {new Date(run.submitted_at).toLocaleString()}</span>
                              </button>
                              <Badge variant={run.state === "SUCCEEDED" ? "default" : "secondary"}>{run.state}</Badge>
                              <Button variant="outline" size="sm" disabled={busy} onClick={() => confirmRun(run)}>Download all</Button>
                            </div>
                            {runOpen && (
                              <div className="ml-5 grid gap-1 border-l border-black/10 pl-3">
                                {run.case_ids.map((caseId, index) => {
                                  const keyForCase = caseKey(run, caseId);
                                  const caseOpen = expandedCases.has(keyForCase);
                                  const caseFiles = files[keyForCase];
                                  const caseName = run.case_names[index] || caseId;
                                  return (
                                    <div className="grid gap-1" key={caseId}>
                                      <div className="stack-item">
                                        <button className="min-w-0 flex-1 cursor-pointer border-0 bg-transparent text-left" onClick={() => expandCase(run, caseId)} aria-expanded={caseOpen}>
                                          <span className="stack-id block">{caseOpen ? "▾ " : "▸ "}{caseName}</span>
                                          <span className="stack-path block">{caseId} · {run.state} · {run.submitted_by} · {new Date(run.submitted_at).toLocaleString()}</span>
                                        </button>
                                        <Button variant="outline" size="sm" disabled={!caseFiles || caseFiles.length === 0} onClick={() => confirmCase(run, caseId, caseFiles)}>Download case</Button>
                                      </div>
                                      {caseOpen && (
                                        <div className="ml-5 grid gap-1">
                                          {loadingFiles.has(keyForCase) && <div className="empty-state">Loading files…</div>}
                                          {caseFiles?.length === 0 && <div className="empty-state">No result files.</div>}
                                          {caseFiles?.map((file) => (
                                            <div className="stack-item" key={file.name}>
                                              <span className="stack-id">{file.name}</span>
                                              <span className="stack-path">{formatSize(file.size)}</span>
                                              <Button variant="outline" size="sm" onClick={() => setPending({
                                                kind: "single",
                                                label: file.name,
                                                object: objectPath(run, caseId, file.name),
                                              })}>Download</Button>
                                            </div>
                                          ))}
                                        </div>
                                      )}
                                    </div>
                                  );
                                })}
                              </div>
                            )}
                          </div>
                        );
                      })}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      </div>

      {pending && (
        <div className="fixed inset-0 z-50 grid place-items-center bg-black/30 p-5 backdrop-blur-sm" role="dialog" aria-modal="true" aria-labelledby="download-confirm-title">
          <div className="panel w-full max-w-lg bg-white/90">
            <div className="panel-head">
              <div className="ph-text">
                <div className="ph-title" id="download-confirm-title">Confirm download</div>
                <div className="ph-sub">{pending.label}</div>
              </div>
            </div>
            <div className="panel-body">
              <div className="empty-state" style={{ fontStyle: "normal" }}>
                {pending.kind === "single"
                  ? "1 file will be downloaded."
                  : pending.fileCount !== undefined
                    ? `${pending.fileCount} file(s) will be packaged into a zip archive.`
                    : "All result files will be packaged into a zip archive."}
              </div>
              <div className="row-end">
                <Button variant="outline" disabled={busy} onClick={() => setPending(null)}>Cancel</Button>
                <Button disabled={busy} onClick={download}>{busy ? "Preparing…" : "Confirm download"}</Button>
              </div>
            </div>
          </div>
        </div>
      )}
    </motion.div>
  );
}
