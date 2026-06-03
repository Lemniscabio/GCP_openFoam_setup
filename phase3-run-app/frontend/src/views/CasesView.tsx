import { useEffect, useState } from "react";
import { api, type CaseInfo } from "../lib/client";

export function CasesView({ onRun }: { onRun: (caseIds: string[]) => void }) {
  const [cases, setCases] = useState<CaseInfo[]>([]);
  const [sel, setSel] = useState<Set<string>>(new Set());
  const [err, setErr] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  async function refresh() {
    setLoading(true);
    try {
      const r = await api.listCases();
      setCases(r.cases);
      setErr(null);
    } catch (e) {
      setErr(String(e));
    } finally {
      setLoading(false);
    }
  }
  useEffect(() => { refresh(); }, []);

  function toggle(id: string) {
    setSel((s) => {
      const n = new Set(s);
      n.has(id) ? n.delete(id) : n.add(id);
      return n;
    });
  }

  return (
    <div className="step" style={{ gridTemplateColumns: "1fr" }}>
      <div className="panel">
        <div className="panel-head">
          <div className="ph-num">02</div>
          <div className="ph-text">
            <div className="ph-title">Cases</div>
            <div className="ph-sub">{loading ? "loading…" : `${cases.length} case(s) in cfd-lemnisca-cases`}</div>
          </div>
          <button className="btn-add" onClick={refresh}>Refresh</button>
        </div>
        <div className="panel-body">
          {err && <div className="empty-state">Error: {err}</div>}
          {!err && cases.length === 0 && !loading && <div className="empty-state">No cases yet — upload some.</div>}
          <div className="stack">
            {cases.map((c) => (
              <label className="stack-item" key={c.case_id} style={{ cursor: "pointer" }}>
                <input type="checkbox" checked={sel.has(c.case_id)} onChange={() => toggle(c.case_id)} disabled={!c.ready} />
                <span className="stack-id">{c.case_id}</span>
                <span className="stack-path">{c.ready ? "READY" : "incomplete"}</span>
              </label>
            ))}
          </div>
          <div className="row-end">
            <button className="btn-add" disabled={sel.size === 0} onClick={() => onRun([...sel])}>
              Run {sel.size || ""} selected →
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
