import { useEffect, useState } from "react";
import { motion } from "framer-motion";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { useListItemVariants, usePanelVariants } from "@/lib/motion";
import { api, type CaseInfo } from "../lib/client";

export function CasesView({ onRun }: { onRun: (caseIds: string[]) => void }) {
  const [cases, setCases] = useState<CaseInfo[]>([]);
  const [sel, setSel] = useState<Set<string>>(new Set());
  const [err, setErr] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const panelVariants = usePanelVariants();
  const listVariants = useListItemVariants();

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
          <div className="ph-num">02</div>
          <div className="ph-text">
            <div className="ph-title">Cases</div>
            <div className="ph-sub">{loading ? "loading…" : `${cases.length} case(s) in cfd-lemnisca-cases`}</div>
          </div>
          <Button variant="outline" size="sm" onClick={refresh}>Refresh</Button>
        </div>
        <div className="panel-body">
          {err && <div className="empty-state">Error: {err}</div>}
          {!err && cases.length === 0 && !loading && <div className="empty-state">No cases yet — upload some.</div>}
          <div className="stack">
            {cases.map((c, index) => (
              <motion.label
                className="stack-item"
                key={c.case_id}
                custom={index}
                variants={listVariants}
                initial="hidden"
                animate="visible"
                style={{ cursor: "pointer" }}
              >
                <input type="checkbox" checked={sel.has(c.case_id)} onChange={() => toggle(c.case_id)} disabled={!c.ready} />
                <span className="stack-id">{c.case_id}</span>
                <Badge variant={c.ready ? "default" : "secondary"}>{c.ready ? "READY" : "incomplete"}</Badge>
              </motion.label>
            ))}
          </div>
          <div className="row-end">
            <Button disabled={sel.size === 0} onClick={() => onRun([...sel])}>
              Run {sel.size || ""} selected →
            </Button>
          </div>
        </div>
      </div>
    </motion.div>
  );
}
