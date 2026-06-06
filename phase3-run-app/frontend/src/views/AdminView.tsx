import { useEffect, useMemo, useState } from "react";
import { motion } from "framer-motion";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { usePanelVariants } from "@/lib/motion";
import { api, type ManagedUser } from "../lib/client";

const ROLES = ["admin", "runner", "viewer"] as const;

function userSort(a: ManagedUser, b: ManagedUser) {
  if (a.status === "pending" && b.status !== "pending") return -1;
  if (a.status !== "pending" && b.status === "pending") return 1;
  return a.email.localeCompare(b.email);
}

export function AdminView() {
  const [users, setUsers] = useState<ManagedUser[]>([]);
  const [roles, setRoles] = useState<Record<string, string>>({});
  const [busyEmail, setBusyEmail] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const panelVariants = usePanelVariants();

  const sortedUsers = useMemo(() => [...users].sort(userSort), [users]);

  async function refresh() {
    setLoading(true);
    try {
      const r = await api.listUsers();
      setUsers(r.users);
      setRoles(Object.fromEntries(r.users.map((u) => [u.email, u.role ?? "runner"])));
      setErr(null);
    } catch (e) {
      setErr(String(e));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { refresh(); }, []);

  async function decide(email: string, body: { role?: string; status?: string }) {
    setBusyEmail(email);
    setErr(null);
    try {
      await api.setUser(email, body);
      await refresh();
    } catch (e) {
      setErr(String(e));
    } finally {
      setBusyEmail(null);
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
          <div className="ph-num">U</div>
          <div className="ph-text">
            <div className="ph-title">Users</div>
            <div className="ph-sub">{loading ? "loading users..." : `${users.length} account(s)`}</div>
          </div>
          <Button variant="outline" size="sm" onClick={refresh} disabled={loading}>Refresh</Button>
        </div>
        <div className="panel-body">
          {err && <div className="empty-state">Error: {err}</div>}
          {!loading && !err && users.length === 0 && <div className="empty-state">No users yet.</div>}
          {users.length > 0 && (
            <div className="admin-table-wrap">
              <table className="admin-table">
                <thead>
                  <tr>
                    <th>Email</th>
                    <th>Status</th>
                    <th>Role</th>
                    <th>Decided by</th>
                    <th>Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {sortedUsers.map((u) => {
                    const busy = busyEmail === u.email;
                    const selectedRole = roles[u.email] ?? u.role ?? "runner";
                    return (
                      <tr key={u.email}>
                        <td className="admin-email">{u.email}</td>
                        <td><Badge variant={u.status === "disabled" ? "destructive" : u.status === "pending" ? "secondary" : "default"}>{u.status}</Badge></td>
                        <td>
                          <select
                            className="input admin-select"
                            value={selectedRole}
                            onChange={(e) => setRoles((current) => ({ ...current, [u.email]: e.target.value }))}
                            disabled={busy}
                          >
                            {ROLES.map((role) => <option key={role} value={role}>{role}</option>)}
                          </select>
                        </td>
                        <td className="admin-decided">{u.decided_by ?? "-"}</td>
                        <td>
                          <div className="admin-actions">
                            <Button
                              size="sm"
                              disabled={busy}
                              onClick={() => decide(u.email, { role: selectedRole, status: "active" })}
                            >
                              Approve
                            </Button>
                            <Button
                              variant="outline"
                              size="sm"
                              disabled={busy}
                              onClick={() => decide(u.email, { status: "disabled" })}
                            >
                              Disable
                            </Button>
                          </div>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>
    </motion.div>
  );
}
