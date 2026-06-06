import { useEffect, useMemo, useState } from "react";
import { motion } from "framer-motion";
import { Button } from "@/components/ui/button";
import { usePanelVariants } from "@/lib/motion";
import { api } from "../lib/client";
import { MACHINES } from "../lib/machines";

export function SubmitView({
  project,
  caseIds,
  canSubmit = true,
  onSubmitted,
}: {
  project: string | null;
  caseIds: string[];
  canSubmit?: boolean;
  onSubmitted: () => void;
}) {
  const [caseNames, setCaseNames] = useState<Record<string, string>>({});
  const [machine, setMachine] = useState("c2d-highcpu-56");
  const [spot, setSpot] = useState(false);
  const [jobName, setJobName] = useState("");
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const panelVariants = usePanelVariants();
  const machineSpec = useMemo(() => MACHINES.find((item) => item.name === machine) ?? MACHINES[0], [machine]);
  const validName = /^[a-z][a-z0-9-]{1,38}$/.test(jobName);
  const submitAllowed = canSubmit && Boolean(project) && caseIds.length > 0 && validName;

  function suggestJobName() {
    api.suggestJobName().then((response) => setJobName(response.name)).catch(() => {});
  }

  useEffect(() => { suggestJobName(); }, []);
  useEffect(() => {
    let alive = true;
    api.listCases().then((response) => {
      if (!alive) return;
      setCaseNames(Object.fromEntries(response.cases.map((item) => [item.case_id, item.name || item.case_id])));
    }).catch(() => {});
    return () => { alive = false; };
  }, [caseIds]);

  async function submit() {
    if (!submitAllowed || busy) return;
    setBusy(true);
    setMsg(null);
    try {
      const response = await api.submit(caseIds, machine, spot, jobName);
      setMsg(`Submitted ${response.job_name}`);
      setConfirming(false);
      onSubmitted();
    } catch (error) {
      setMsg(`ERROR: ${String(error)}`);
      setConfirming(false);
    } finally {
      setBusy(false);
    }
  }

  if (!project || caseIds.length === 0) {
    return (
      <motion.div className="step" style={{ gridTemplateColumns: "1fr" }} initial="hidden" animate="visible" exit="exit" variants={panelVariants}>
        <div className="panel">
          <div className="panel-head">
            <div className="ph-num">03</div>
            <div className="ph-text">
              <div className="ph-title">Submit</div>
              <div className="ph-sub">Select case(s) in the Cases tab first.</div>
            </div>
          </div>
          <div className="panel-body"><div className="empty-state">No project and cases selected.</div></div>
        </div>
      </motion.div>
    );
  }

  return (
    <motion.div className="step" initial="hidden" animate="visible" exit="exit" variants={panelVariants}>
      <div className="panel">
        <div className="panel-head">
          <div className="ph-num">03</div>
          <div className="ph-text">
            <div className="ph-title">Submit job</div>
            <div className="ph-sub">{project} · {caseIds.length > 1 ? "multi-task" : "single"} · {caseIds.length} case(s)</div>
          </div>
        </div>
        <div className="panel-body">
          <div className="field">
            <label className="lbl"><span>Project</span></label>
            <div className="chips"><span className="chip">{project}</span></div>
          </div>
          <div className="field">
            <label className="lbl"><span>Cases</span></label>
            <div className="chips">{caseIds.map((id) => <span className="chip" key={id}>{caseNames[id] ?? id}</span>)}</div>
          </div>
          <div className="field">
            <label className="lbl" htmlFor="job-name"><span>Codename</span></label>
            <div style={{ display: "flex", gap: 8 }}>
              <input id="job-name" className="input" style={{ flex: 1 }} required value={jobName} onChange={(event) => setJobName(event.target.value)} aria-invalid={!validName} placeholder="phoenix" />
              <Button variant="outline" onClick={suggestJobName}>Shuffle</Button>
            </div>
            {!validName && <div className="empty-state" style={{ fontStyle: "normal" }}>Use 2–39 lowercase letters, numbers, or hyphens; start with a letter.</div>}
          </div>
          <div className="field">
            <label className="lbl"><span>Machine (c2d-highcpu)</span></label>
            <div className="preset-grid">
              {MACHINES.map((item) => (
                <button key={item.name} className={`preset${machine === item.name ? " sel" : ""}`} onClick={() => setMachine(item.name)}>
                  <div className="p-name">{item.name}</div>
                  <div className="p-spec">{item.vcpus} vCPU · {item.memGiB} GiB · mpi {item.mpi}</div>
                </button>
              ))}
            </div>
          </div>
          <div className="field">
            <label className="lbl"><span>Provisioning</span></label>
            <div className="segmented two">
              <button className={`seg-opt${!spot ? " on" : ""}`} onClick={() => setSpot(false)}>Standard</button>
              <button className={`seg-opt${spot ? " on" : ""}`} onClick={() => setSpot(true)}>Spot · cheaper</button>
            </div>
          </div>
          <div className="row-end">
            <Button disabled={!submitAllowed || busy} onClick={() => setConfirming(true)}>
              {!canSubmit ? "Read-only" : busy ? "Submitting…" : "Run job"}
            </Button>
          </div>
          {msg && <div className="empty-state" style={{ fontStyle: "normal" }}>{msg}</div>}
        </div>
      </div>

      {confirming && (
        <div className="fixed inset-0 z-50 grid place-items-center bg-black/30 p-5 backdrop-blur-sm" role="dialog" aria-modal="true" aria-labelledby="submit-confirm-title">
          <div className="panel w-full max-w-lg bg-white/90">
            <div className="panel-head">
              <div className="ph-text">
                <div className="ph-title" id="submit-confirm-title">Confirm job submission</div>
                <div className="ph-sub">Review the Batch configuration before starting.</div>
              </div>
            </div>
            <div className="panel-body">
              <div className="stack">
                <Summary label="Project" value={project} />
                <Summary label="Cases" value={caseIds.map((id) => caseNames[id] ?? id).join(", ")} />
                <Summary label="Machine" value={machine} />
                <Summary label="MPI ranks" value={String(machineSpec.mpi)} />
                <Summary label="Codename" value={jobName} />
                <Summary label="Spot" value={spot ? "Yes" : "No"} />
              </div>
              <div className="row-end">
                <Button variant="outline" disabled={busy} onClick={() => setConfirming(false)}>Cancel</Button>
                <Button disabled={busy} onClick={submit}>{busy ? "Submitting…" : "Confirm and run"}</Button>
              </div>
            </div>
          </div>
        </div>
      )}
    </motion.div>
  );
}

function Summary({ label, value }: { label: string; value: string }) {
  return <div className="stack-item"><span className="stack-path">{label}</span><span className="stack-id text-right">{value}</span></div>;
}
