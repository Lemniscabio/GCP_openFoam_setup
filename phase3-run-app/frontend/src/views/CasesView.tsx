import { useEffect, useMemo, useState } from "react";
import { motion } from "framer-motion";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { useListItemVariants, usePanelVariants } from "@/lib/motion";
import { api, type CaseInfo } from "../lib/client";

type MetadataState = { status: "loading" } | { status: "ready"; value: unknown } | { status: "missing" } | { status: "error"; message: string };

export function CasesView({
  activeProject,
  selectedCaseIds,
  onChange,
  onActiveProject,
  onSubmit,
  canRun = true,
}: {
  activeProject: string | null;
  selectedCaseIds: string[];
  onChange: (caseIds: string[]) => void;
  onActiveProject: (project: string) => void;
  onSubmit: () => void;
  canRun?: boolean;
}) {
  const [cases, setCases] = useState<CaseInfo[]>([]);
  const [expandedProjects, setExpandedProjects] = useState<Set<string>>(new Set());
  const [expandedCases, setExpandedCases] = useState<Set<string>>(new Set());
  const [metadata, setMetadata] = useState<Record<string, MetadataState>>({});
  const [err, setErr] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const panelVariants = usePanelVariants();
  const listVariants = useListItemVariants();
  const selected = useMemo(() => new Set(selectedCaseIds), [selectedCaseIds]);
  const projects = useMemo(() => {
    const grouped = new Map<string, CaseInfo[]>();
    for (const item of cases) grouped.set(item.project, [...(grouped.get(item.project) ?? []), item]);
    return [...grouped.entries()].sort(([a], [b]) => a.localeCompare(b));
  }, [cases]);

  async function refresh() {
    setLoading(true);
    try {
      const response = await api.listCases();
      setCases(response.cases);
      setErr(null);
    } catch (error) {
      setErr(String(error));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { refresh(); }, []);
  useEffect(() => {
    if (!activeProject) return;
    setExpandedProjects((current) => new Set(current).add(activeProject));
  }, [activeProject]);

  function toggleProject(project: string) {
    setExpandedProjects((current) => {
      const next = new Set(current);
      next.has(project) ? next.delete(project) : next.add(project);
      return next;
    });
  }

  function toggleSelection(item: CaseInfo) {
    if (!item.ready) return;
    if (selected.has(item.case_id)) {
      onChange(selectedCaseIds.filter((id) => id !== item.case_id));
      return;
    }
    if (activeProject !== item.project) {
      onActiveProject(item.project);
      onChange([item.case_id]);
      return;
    }
    onChange([...selectedCaseIds, item.case_id]);
  }

  async function toggleCase(item: CaseInfo) {
    const key = `${item.project}/${item.case_id}`;
    if (expandedCases.has(key)) {
      setExpandedCases((current) => {
        const next = new Set(current);
        next.delete(key);
        return next;
      });
      return;
    }
    setExpandedCases((current) => new Set(current).add(key));
    if (metadata[key]) return;
    setMetadata((current) => ({ ...current, [key]: { status: "loading" } }));
    try {
      const response = await api.getCaseMetadata(item.project, item.case_id);
      setMetadata((current) => ({ ...current, [key]: { status: "ready", value: response.metadata } }));
    } catch (error) {
      const message = String(error);
      setMetadata((current) => ({
        ...current,
        [key]: message.includes("-> 404") ? { status: "missing" } : { status: "error", message },
      }));
    }
  }

  return (
    <motion.div className="step" style={{ gridTemplateColumns: "1fr" }} initial="hidden" animate="visible" exit="exit" variants={panelVariants}>
      <div className="panel">
        <div className="panel-head">
          <div className="ph-num">02</div>
          <div className="ph-text">
            <div className="ph-title">Cases</div>
            <div className="ph-sub">{loading ? "loading…" : `${cases.length} case(s) across ${projects.length} project(s)`}</div>
          </div>
          <Button variant="outline" size="sm" onClick={refresh}>Refresh</Button>
        </div>
        <div className="panel-body">
          {err && <div className="empty-state">Error: {err}</div>}
          {!err && cases.length === 0 && !loading && <div className="empty-state">No cases yet — upload some.</div>}
          <div className="stack max-h-[60vh] overflow-y-auto">
            {projects.map(([project, projectCases], projectIndex) => {
              const isOpen = expandedProjects.has(project);
              return (
                <motion.div key={project} custom={projectIndex} variants={listVariants} initial="hidden" animate="visible" className="grid gap-1">
                  <button className="stack-item w-full cursor-pointer text-left" onClick={() => toggleProject(project)} aria-expanded={isOpen}>
                    <span className="text-[11px] text-[var(--ink-2)]">{isOpen ? "▾" : "▸"}</span>
                    <span className="stack-id">{project}</span>
                    {activeProject === project && <Badge variant="secondary">ACTIVE</Badge>}
                    <span className="stack-path">{projectCases.length} case(s)</span>
                  </button>
                  {isOpen && (
                    <div className="ml-5 grid gap-1 border-l border-black/10 pl-3">
                      {projectCases.map((item) => {
                        const key = `${project}/${item.case_id}`;
                        const isCaseOpen = expandedCases.has(key);
                        const metadataState = metadata[key];
                        return (
                          <div key={item.case_id} className="grid gap-1">
                            <div className="stack-item">
                              <input
                                type="checkbox"
                                checked={selected.has(item.case_id)}
                                onChange={() => toggleSelection(item)}
                                disabled={!item.ready}
                                aria-label={`Select ${item.name || item.case_id}`}
                              />
                              <button className="min-w-0 flex-1 cursor-pointer border-0 bg-transparent text-left" onClick={() => toggleCase(item)} aria-expanded={isCaseOpen}>
                                <span className="stack-id block">{item.name || item.case_id}</span>
                                <span className="stack-path block">{item.case_id}</span>
                              </button>
                              <Badge variant={item.ready ? "default" : "secondary"}>{item.ready ? "READY" : "incomplete"}</Badge>
                            </div>
                            {isCaseOpen && (
                              <div className="ml-7 rounded-lg border border-black/10 bg-white/45 p-3 font-mono text-xs text-[var(--ink-2)]">
                                {!metadataState || metadataState.status === "loading" ? "Loading metadata…" : null}
                                {metadataState?.status === "missing" ? "No metadata." : null}
                                {metadataState?.status === "error" ? `Error: ${metadataState.message}` : null}
                                {metadataState?.status === "ready" ? <pre className="m-0 overflow-x-auto whitespace-pre-wrap">{JSON.stringify(metadataState.value, null, 2)}</pre> : null}
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
          <div className="row-end">
            <Button disabled={!canRun || selectedCaseIds.length === 0} onClick={onSubmit}>
              {canRun ? `Submit ${selectedCaseIds.length || ""} selected →` : "Read-only"}
            </Button>
          </div>
        </div>
      </div>
    </motion.div>
  );
}
