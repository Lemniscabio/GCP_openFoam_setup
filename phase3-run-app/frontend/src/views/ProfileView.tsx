import { useEffect, useState } from "react";
import { motion } from "framer-motion";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { usePanelVariants } from "@/lib/motion";
import { api, type ManagedUser, type Me, type ProjectInfo, type RunRecord } from "../lib/client";
import { AdminView } from "./AdminView";

export function ProfileView({ me, onBack }: { me: Me; onBack: () => void }) {
  const [myRuns, setMyRuns] = useState<RunRecord[]>([]);
  const [projects, setProjects] = useState<ProjectInfo[]>([]);
  const [users, setUsers] = useState<ManagedUser[]>([]);
  const [adminRuns, setAdminRuns] = useState<RunRecord[]>([]);
  const [reportUser, setReportUser] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [reportErr, setReportErr] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [reportLoading, setReportLoading] = useState(me.role === "admin");
  const panelVariants = usePanelVariants();

  useEffect(() => {
    let alive = true;
    api.getMyRuns()
      .then((response) => { if (alive) setMyRuns(response.runs); })
      .catch((error) => { if (alive) setErr(String(error)); })
      .finally(() => { if (alive) setLoading(false); });
    if (me.role === "admin") {
      Promise.all([api.getProjects(), api.listUsers()])
        .then(([projectResponse, userResponse]) => {
          if (!alive) return;
          setProjects(projectResponse.projects);
          setUsers(userResponse.users);
        })
        .catch((error) => { if (alive) setReportErr(String(error)); });
    }
    return () => { alive = false; };
  }, [me.role]);

  useEffect(() => {
    if (me.role !== "admin") return;
    let alive = true;
    setReportLoading(true);
    api.getAdminRuns(reportUser || undefined)
      .then((response) => { if (alive) { setAdminRuns(response.runs); setReportErr(null); } })
      .catch((error) => { if (alive) setReportErr(String(error)); })
      .finally(() => { if (alive) setReportLoading(false); });
    return () => { alive = false; };
  }, [me.role, reportUser]);

  return (
    <motion.div className="step" style={{ gridTemplateColumns: "1fr" }} initial="hidden" animate="visible" exit="exit" variants={panelVariants}>
      <div className="panel">
        <div className="panel-head">
          <div className="ph-num">P</div>
          <div className="ph-text">
            <div className="ph-title">Profile</div>
            <div className="ph-sub">Account identity and activity</div>
          </div>
          <Button variant="outline" size="sm" onClick={onBack}>Back to sections</Button>
        </div>
        <div className="panel-body">
          <div className="stack">
            <Identity label="Email" value={me.email} />
            <Identity label="Role" value={me.role ?? "pending"} badge />
            <Identity label="Status" value={me.status} badge />
          </div>
        </div>
      </div>

      <div className="panel">
        <div className="panel-head">
          <div className="ph-num">R</div>
          <div className="ph-text">
            <div className="ph-title">My runs</div>
            <div className="ph-sub">{loading ? "loading…" : `${myRuns.length} submission(s)`}</div>
          </div>
        </div>
        <div className="panel-body">
          {err && <div className="empty-state">Error: {err}</div>}
          {!loading && !err && myRuns.length === 0 && <div className="empty-state">No runs yet.</div>}
          <RunList runs={myRuns} />
        </div>
      </div>

      {me.role === "admin" && <AdminView />}

      {me.role === "admin" && (
        <div className="panel">
          <div className="panel-head">
            <div className="ph-num">A</div>
            <div className="ph-text">
              <div className="ph-title">Reporting</div>
              <div className="ph-sub">Projects and run activity across users</div>
            </div>
          </div>
          <div className="panel-body">
            <div className="field">
              <label className="lbl"><span>Projects</span></label>
              <div className="chips">
                {projects.length === 0 ? <span className="empty-state">No projects.</span> : projects.map((project) => <span className="chip" key={project.name}>{project.name}</span>)}
              </div>
            </div>
            <div className="field">
              <label className="lbl" htmlFor="report-user"><span>Runs by user</span></label>
              <select id="report-user" className="input" value={reportUser} onChange={(event) => setReportUser(event.target.value)}>
                <option value="">All users</option>
                {users.map((user) => <option key={user.email} value={user.email}>{user.email}</option>)}
              </select>
            </div>
            {reportErr && <div className="empty-state">Error: {reportErr}</div>}
            {reportLoading && <div className="empty-state">Loading report…</div>}
            {!reportLoading && !reportErr && adminRuns.length === 0 && <div className="empty-state">No runs for this selection.</div>}
            <RunList runs={adminRuns} showUser />
          </div>
        </div>
      )}
    </motion.div>
  );
}

function Identity({ label, value, badge = false }: { label: string; value: string; badge?: boolean }) {
  return (
    <div className="stack-item">
      <span className="stack-path">{label}</span>
      <span className="stack-id text-right">{badge ? <Badge variant="secondary">{value}</Badge> : value}</span>
    </div>
  );
}

function RunList({ runs, showUser = false }: { runs: RunRecord[]; showUser?: boolean }) {
  return (
    <div className="stack">
      {runs.map((run) => (
        <div className="stack-item" key={run.batch_job_id}>
          <span className="stack-id">
            {run.job_name}
            <span className="stack-path block">{run.project}{showUser ? ` · ${run.submitted_by}` : ""} · {new Date(run.submitted_at).toLocaleString()}</span>
          </span>
          <Badge variant={run.state === "SUCCEEDED" ? "default" : "secondary"}>{run.state}</Badge>
        </div>
      ))}
    </div>
  );
}
