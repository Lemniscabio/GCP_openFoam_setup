import { useEffect, useRef, useState } from "react";
import { motion } from "framer-motion";
import { Button } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";
import { missingRequiredFiles, type MissingReport } from "@/lib/casecheck";
import { useListItemVariants, usePanelVariants } from "@/lib/motion";
import { api, type ProjectInfo } from "../lib/client";
import { runPool, putFile } from "../lib/upload";

type CaseFiles = { sourceName: string; name: string; files: { relPath: string; file: File }[] };

function groupIntoCases(list: FileList): CaseFiles[] {
  const entries = Array.from(list).map((file) => ({
    parts: (file.webkitRelativePath || file.name).split("/"),
    file,
  }));
  if (entries.length === 0) return [];
  const root = entries[0].parts[0];
  const isSingle = entries.some((entry) =>
    entry.parts.length === 2 && entry.parts[0] === root && entry.parts[1] === "command.sh");
  if (isSingle) {
    return [{
      sourceName: root,
      name: "",
      files: entries.map((entry) => ({ relPath: entry.parts.slice(1).join("/"), file: entry.file })),
    }];
  }
  const byCase = new Map<string, { relPath: string; file: File }[]>();
  for (const entry of entries) {
    if (entry.parts.length < 3) continue;
    const caseName = entry.parts[1];
    const files = byCase.get(caseName) ?? [];
    files.push({ relPath: entry.parts.slice(2).join("/"), file: entry.file });
    byCase.set(caseName, files);
  }
  return [...byCase.entries()].map(([sourceName, files]) => ({ sourceName, name: "", files }));
}

function projectError(project: string) {
  const value = project.trim();
  if (!value) return "Project is required.";
  if (value === "." || value === ".." || value.includes("/") || value.length > 128) {
    return "Use 1-128 characters without '/', '.' or '..'.";
  }
  return null;
}

export function UploadView({
  onUploaded,
}: {
  onUploaded: (project: string, ids: string[]) => void;
}) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [projects, setProjects] = useState<ProjectInfo[]>([]);
  const [project, setProject] = useState("");
  const [cases, setCases] = useState<CaseFiles[]>([]);
  const [log, setLog] = useState<string[]>([]);
  const [progress, setProgress] = useState({ done: 0, total: 0 });
  const [busy, setBusy] = useState(false);
  const [over, setOver] = useState(false);
  const [preflight, setPreflight] = useState<MissingReport[] | null>(null);
  const panelVariants = usePanelVariants();
  const listVariants = useListItemVariants();
  const invalidProject = projectError(project);

  useEffect(() => {
    let alive = true;
    api.getProjects()
      .then((response) => { if (alive) setProjects(response.projects); })
      .catch((error) => { if (alive) setLog([`Unable to load projects: ${String(error)}`]); });
    return () => { alive = false; };
  }, []);

  const say = (message: string) => setLog((current) => [...current, message]);

  function setCaseName(index: number, name: string) {
    setCases((current) => current.map((item, i) => (i === index ? { ...item, name } : item)));
  }

  function onPicked(list: FileList | null) {
    if (!list) return;
    const grouped = groupIntoCases(list);
    setCases(grouped);
    setLog([`Detected ${grouped.length} case(s): ${grouped.map((item) => `${item.sourceName} (${item.files.length} files)`).join(", ")}`]);
    setProgress({ done: 0, total: grouped.reduce((total, item) => total + item.files.length, 0) });
  }

  function openPreflight() {
    if (invalidProject || cases.length === 0 || busy) return;
    setPreflight(missingRequiredFiles(cases.map((item) => ({
      name: item.name.trim() || item.sourceName,
      files: item.files.map((file) => file.relPath),
    }))));
  }

  async function upload() {
    if (invalidProject || cases.length === 0 || busy) return;
    const selectedProject = project.trim();
    setPreflight(null);
    setBusy(true);
    try {
      say(`Allocating ${cases.length} case id(s) in ${selectedProject}…`);
      const response = await api.allocate(selectedProject, cases.map((item) => ({
        files: item.files.map((file) => file.relPath),
      })));
      const allocated: { case_id: string; uploads: { url: string }[] }[] = response.cases;
      const uploadedCaseIds: string[] = [];
      let done = 0;
      for (let i = 0; i < allocated.length; i++) {
        const caseId = allocated[i].case_id;
        const localFiles = cases[i].files;
        say(`Uploading ${localFiles.length} files → ${caseId}…`);
        const tasks = allocated[i].uploads.map((signed, j) => async () => {
          await putFile(signed.url, localFiles[j].file);
          done += 1;
          setProgress((current) => ({ ...current, done }));
        });
        await runPool(tasks, 10);
        await api.finalize(caseId, { name: cases[i].name, project: selectedProject });
        uploadedCaseIds.push(caseId);
        say(`✓ ${caseId} uploaded + finalized`);
      }
      setCases([]);
      onUploaded(selectedProject, uploadedCaseIds);
    } catch (error) {
      say(`ERROR: ${String(error)}`);
    } finally {
      setBusy(false);
    }
  }

  const pct = progress.total ? Math.round((progress.done / progress.total) * 100) : 0;

  return (
    <motion.div className="step" initial="hidden" animate="visible" exit="exit" variants={panelVariants}>
      <div className="panel">
        <div className="panel-head">
          <div className="ph-num">01</div>
          <div className="ph-text">
            <div className="ph-title">Upload cases</div>
            <div className="ph-sub">Choose a project, then drop a case folder or a parent folder of cases.</div>
          </div>
        </div>
        <div className="panel-body">
          <div className="field">
            <label className="lbl" htmlFor="upload-project"><span>Project</span></label>
            <input
              id="upload-project"
              className="input"
              list="upload-projects"
              value={project}
              onChange={(event) => setProject(event.target.value)}
              placeholder="Select or enter a project"
              aria-invalid={Boolean(invalidProject)}
            />
            <datalist id="upload-projects">
              {projects.map((item) => <option key={item.name} value={item.name} />)}
            </datalist>
            {invalidProject && <div className="empty-state" style={{ fontStyle: "normal" }}>{invalidProject}</div>}
          </div>
          <div
            className={`drop${over ? " over" : ""}`}
            onClick={() => inputRef.current?.click()}
            onDragOver={(event) => { event.preventDefault(); setOver(true); }}
            onDragLeave={() => setOver(false)}
            onDrop={(event) => { event.preventDefault(); setOver(false); onPicked(event.dataTransfer.files); }}
          >
            <div className="drop-icon">⬓</div>
            <div className="drop-text">
              <strong>Drop a case folder, or click to choose</strong>
              <span>bulk: a parent folder whose subfolders are cases · single: one case folder</span>
            </div>
          </div>
          {busy && <Progress value={pct} className="h-1.5" />}
          {/* @ts-expect-error webkitdirectory is non-standard */}
          <input ref={inputRef} type="file" webkitdirectory="" directory="" hidden onChange={(event) => onPicked(event.target.files)} />
          {cases.length > 0 && (
            <div className="stack">
              {cases.map((item, index) => (
                <motion.div className="stack-item" key={item.sourceName} custom={index} variants={listVariants} initial="hidden" animate="visible">
                  <span className="stack-id">{item.sourceName}</span>
                  <input
                    aria-label={`Case name for ${item.sourceName}`}
                    className="input"
                    placeholder="Case name"
                    value={item.name}
                    onChange={(event) => setCaseName(index, event.target.value)}
                  />
                  <span className="stack-path">{item.files.length} files</span>
                </motion.div>
              ))}
            </div>
          )}
          <div className="row-end">
            <Button disabled={Boolean(invalidProject) || !cases.length || busy} onClick={openPreflight}>
              {busy ? `Uploading… ${pct}%` : `Upload ${cases.length || ""} case(s)`}
            </Button>
          </div>
        </div>
      </div>

      <div className="panel">
        <div className="panel-head">
          <div className="ph-num" style={{ color: "var(--green)" }}>↑</div>
          <div className="ph-text">
            <div className="ph-title">Activity</div>
            <div className="ph-sub">{progress.total ? `${progress.done}/${progress.total} files` : "idle"}</div>
          </div>
        </div>
        <div className="panel-body" style={{ paddingBottom: 0 }}>
          <div className="panel-foot" style={{ margin: "0 -22px", borderRadius: 0, flex: 1, maxHeight: "none" }}>
            <div className="foot-code">
              {log.length === 0 ? <span className="foot-empty">Pick a folder to begin.</span> : log.map((line, i) => <div key={i}>{line}</div>)}
            </div>
          </div>
        </div>
      </div>

      {preflight !== null && (
        <div className="fixed inset-0 z-50 grid place-items-center bg-black/30 p-5 backdrop-blur-sm" role="dialog" aria-modal="true" aria-labelledby="upload-confirm-title">
          <div className="panel w-full max-w-lg bg-white/90">
            <div className="panel-head">
              <div className="ph-text">
                <div className="ph-title" id="upload-confirm-title">{preflight.length ? "Upload blocked" : "Confirm upload"}</div>
                <div className="ph-sub">{preflight.length ? "Required files are missing." : `${cases.length} case(s) will upload to ${project.trim()}.`}</div>
              </div>
            </div>
            <div className="panel-body">
              {preflight.length > 0 && (
                <div className="stack">
                  {preflight.map((report) => (
                    <div className="stack-item" key={report.name}>
                      <span className="stack-id">{report.name}</span>
                      <span className="stack-path">Missing: {report.missing.join(", ")}</span>
                    </div>
                  ))}
                </div>
              )}
              <div className="row-end">
                <Button variant="outline" onClick={() => setPreflight(null)}>{preflight.length ? "Close" : "Cancel"}</Button>
                {preflight.length === 0 && <Button onClick={upload}>Confirm upload</Button>}
              </div>
            </div>
          </div>
        </div>
      )}
    </motion.div>
  );
}
