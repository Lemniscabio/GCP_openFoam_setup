import { useEffect, useState } from "react";
import { motion } from "framer-motion";
import { Button } from "@/components/ui/button";
import { usePanelVariants } from "@/lib/motion";
import { api } from "../lib/client";
import { MACHINES } from "../lib/machines";

export function RunView({
  caseIds,
  canSubmit = true,
  onSubmitted,
}: {
  caseIds: string[];
  canSubmit?: boolean;
  onSubmitted: () => void;
}) {
  const [machine, setMachine] = useState("c2d-highcpu-56");
  const [spot, setSpot] = useState(false);
  const [jobName, setJobName] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const panelVariants = usePanelVariants();

  const mode = caseIds.length > 1 ? "multi-task" : "single";
  const validName = /^[a-z][a-z0-9-]{1,38}$/.test(jobName);
  const submitAllowed = canSubmit && caseIds.length > 0 && validName;

  function suggestJobName() {
    api.suggestJobName().then((r) => setJobName(r.name)).catch(() => {});
  }

  useEffect(() => {
    suggestJobName();
  }, []);

  async function submit() {
    if (!submitAllowed || busy) return;
    setBusy(true);
    setMsg(null);
    try {
      const r = await api.submit(caseIds, machine, spot, jobName);
      setMsg(`Submitted ${r.job_name}`);
      onSubmitted();
    } catch (e) {
      setMsg(`ERROR: ${String(e)}`);
    } finally {
      setBusy(false);
    }
  }

  if (caseIds.length === 0) {
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
            <div className="ph-num">03</div>
            <div className="ph-text">
              <div className="ph-title">Run</div>
              <div className="ph-sub">Select case(s) in the Cases tab first.</div>
            </div>
          </div>
          <div className="panel-body"><div className="empty-state">No cases selected.</div></div>
        </div>
      </motion.div>
    );
  }

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
          <div className="ph-num">03</div>
          <div className="ph-text">
            <div className="ph-title">Run case(s)</div>
            <div className="ph-sub">{mode} · {caseIds.length} case(s)</div>
          </div>
        </div>
        <div className="panel-body">
          <div className="field">
            <label className="lbl"><span>Cases</span></label>
            <div className="chips">{caseIds.map((c) => <span className="chip" key={c}>{c}</span>)}</div>
          </div>
          <div className="field">
            <label className="lbl" htmlFor="job-name"><span>Job name</span></label>
            <div style={{ display: "flex", gap: 8 }}>
              <input
                id="job-name"
                className="input"
                style={{ flex: 1 }}
                required
                value={jobName}
                onChange={(e) => setJobName(e.target.value)}
                aria-invalid={!validName}
                placeholder="phoenix"
              />
              <Button variant="outline" onClick={suggestJobName}>Shuffle</Button>
            </div>
            {!validName && (
              <div className="empty-state" style={{ fontStyle: "normal" }}>
                Use 2–39 lowercase letters, numbers, or hyphens; start with a letter.
              </div>
            )}
          </div>
          <div className="field">
            <label className="lbl"><span>Machine (c2d-highcpu)</span></label>
            <div className="preset-grid">
              {MACHINES.map((m) => (
                <button key={m.name} className={`preset${machine === m.name ? " sel" : ""}`} onClick={() => setMachine(m.name)}>
                  <div className="p-name">{m.name}</div>
                  <div className="p-spec">{m.vcpus} vCPU · {m.memGiB} GiB · mpi {m.mpi}</div>
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
            <Button disabled={!submitAllowed || busy} onClick={submit}>
              {!canSubmit ? "Read-only" : busy ? "Submitting…" : "Run job"}
            </Button>
          </div>
          {msg && <div className="empty-state" style={{ fontStyle: "normal" }}>{msg}</div>}
        </div>
      </div>
    </motion.div>
  );
}
