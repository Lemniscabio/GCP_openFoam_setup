import { useRef, useState } from "react";
import { motion } from "framer-motion";
import { Button } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";
import { useListItemVariants, usePanelVariants } from "@/lib/motion";
import { api } from "../lib/client";
import { runPool, putFile } from "../lib/upload";

type CaseFiles = { name: string; files: { relPath: string; file: File }[] };

// Group a webkitdirectory FileList into cases.
// Paths look like "<root>/...". If "<root>/command.sh" exists -> single case (root).
// Otherwise each immediate subdir of root is a case (bulk import).
function groupIntoCases(list: FileList): CaseFiles[] {
  const entries = Array.from(list).map((f) => ({
    parts: (f.webkitRelativePath || f.name).split("/"),
    file: f,
  }));
  if (entries.length === 0) return [];
  const root = entries[0].parts[0];
  const isSingle = entries.some((e) => e.parts.length === 2 && e.parts[1] === "command.sh" && e.parts[0] === root);
  if (isSingle) {
    return [{ name: root, files: entries.map((e) => ({ relPath: e.parts.slice(1).join("/"), file: e.file })) }];
  }
  const byCase = new Map<string, { relPath: string; file: File }[]>();
  for (const e of entries) {
    if (e.parts.length < 3) continue; // skip stray files directly under root
    const caseName = e.parts[1];
    const relPath = e.parts.slice(2).join("/");
    if (!byCase.has(caseName)) byCase.set(caseName, []);
    byCase.get(caseName)!.push({ relPath, file: e.file });
  }
  return [...byCase.entries()].map(([name, files]) => ({ name, files }));
}

export function UploadView() {
  const inputRef = useRef<HTMLInputElement>(null);
  const [cases, setCases] = useState<CaseFiles[]>([]);
  const [log, setLog] = useState<string[]>([]);
  const [progress, setProgress] = useState({ done: 0, total: 0 });
  const [busy, setBusy] = useState(false);
  const [over, setOver] = useState(false);
  const panelVariants = usePanelVariants();
  const listVariants = useListItemVariants();

  const say = (m: string) => setLog((l) => [...l, m]);

  function onPicked(list: FileList | null) {
    if (!list) return;
    const grouped = groupIntoCases(list);
    setCases(grouped);
    setLog([`Detected ${grouped.length} case(s): ${grouped.map((c) => `${c.name} (${c.files.length} files)`).join(", ")}`]);
    setProgress({ done: 0, total: grouped.reduce((n, c) => n + c.files.length, 0) });
  }

  async function upload() {
    if (cases.length === 0 || busy) return;
    setBusy(true);
    try {
      say(`Allocating ${cases.length} case id(s)…`);
      const resp = await api.allocate(cases.map((c) => ({ files: c.files.map((f) => f.relPath) })));
      const allocated: { case_id: string; uploads: { url: string }[] }[] = resp.cases;
      let done = 0;
      // Upload each case's files (pair uploads[j] with files[j] by index), then finalize.
      for (let i = 0; i < allocated.length; i++) {
        const cid = allocated[i].case_id;
        const ups = allocated[i].uploads;
        const local = cases[i].files;
        say(`Uploading ${local.length} files → ${cid}…`);
        const tasks = ups.map((u, j) => async () => {
          await putFile(u.url, local[j].file);
          done += 1;
          setProgress((p) => ({ ...p, done }));
        });
        await runPool(tasks, 10);
        await api.finalize(cid);
        say(`✓ ${cid} uploaded + finalized`);
      }
      say("All cases uploaded. Switch to Cases to run them.");
      setCases([]);
    } catch (e) {
      say(`ERROR: ${String(e)}`);
    } finally {
      setBusy(false);
    }
  }

  const pct = progress.total ? Math.round((progress.done / progress.total) * 100) : 0;

  return (
    <motion.div
      className="step"
      initial="hidden"
      animate="visible"
      exit="exit"
      variants={panelVariants}
    >
      <div className="panel">
        <div className="panel-head">
          <div className="ph-num">01</div>
          <div className="ph-text">
            <div className="ph-title">Upload cases</div>
            <div className="ph-sub">Drop a case folder (or a parent folder of cases). Files go straight to GCS.</div>
          </div>
        </div>
        <div className="panel-body">
          <div
            className={`drop${over ? " over" : ""}`}
            onClick={() => inputRef.current?.click()}
            onDragOver={(e) => { e.preventDefault(); setOver(true); }}
            onDragLeave={() => setOver(false)}
            onDrop={(e) => { e.preventDefault(); setOver(false); onPicked(e.dataTransfer.files); }}
          >
            <div className="drop-icon">⬓</div>
            <div className="drop-text">
              <strong>Drop a case folder, or click to choose</strong>
              <span>bulk: a parent folder whose subfolders are cases · single: one case folder</span>
            </div>
          </div>
          {busy && <Progress value={pct} className="h-1.5" />}
          {/* @ts-expect-error webkitdirectory is non-standard */}
          <input ref={inputRef} type="file" webkitdirectory="" directory="" hidden
                 onChange={(e) => onPicked(e.target.files)} />
          {cases.length > 0 && (
            <div className="stack">
              {cases.map((c, index) => (
                <motion.div
                  className="stack-item"
                  key={c.name}
                  custom={index}
                  variants={listVariants}
                  initial="hidden"
                  animate="visible"
                >
                  <span className="stack-id">{c.name}</span>
                  <span className="stack-path">{c.files.length} files</span>
                </motion.div>
              ))}
            </div>
          )}
          <div className="row-end">
            <Button disabled={!cases.length || busy} onClick={upload}>
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
              {log.length === 0 ? <span className="foot-empty">Pick a folder to begin.</span>
                : log.map((l, i) => <div key={i}>{l}</div>)}
            </div>
          </div>
        </div>
      </div>
    </motion.div>
  );
}
