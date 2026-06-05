import { useEffect, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { AppShell, type Tab } from "./components/AppShell";
import { tokenStore } from "./lib/auth";
import { api, type Me } from "./lib/client";
import { usePanelVariants } from "./lib/motion";
import { UploadView } from "./views/UploadView";
import { AdminView } from "./views/AdminView";
import { CasesView } from "./views/CasesView";
import { RunView } from "./views/RunView";
import { RunsView } from "./views/RunsView";

export default function App() {
  const [tab, setTab] = useState<Tab>("upload");
  const [selected, setSelected] = useState<string[]>([]);
  const [me, setMe] = useState<Me | null>(null);
  const [accessError, setAccessError] = useState<string | null>(null);
  const panelVariants = usePanelVariants();

  useEffect(() => {
    let alive = true;
    api.getMe()
      .then((nextMe) => {
        if (!alive) return;
        setMe(nextMe);
        setAccessError(null);
      })
      .catch((e) => {
        if (alive) setAccessError(String(e));
      });
    return () => { alive = false; };
  }, []);

  const canRun = me?.role !== "viewer";

  useEffect(() => {
    if (!me) return;
    if (!canRun && (tab === "upload" || tab === "run")) {
      setTab("cases");
      return;
    }
    if (tab === "admin" && me.role !== "admin") setTab("cases");
  }, [canRun, me, tab]);

  if (accessError) {
    return <AccessState title="Unable to verify access" detail={accessError} />;
  }

  if (!me) {
    return <AccessState title="Verifying access" detail="Checking account approval…" />;
  }

  if (me.status === "pending") {
    return <AccessState title="Access pending admin approval" signOutOnly />;
  }

  if (me.status === "disabled") {
    return <AccessState title="Access revoked — contact an admin" signOutOnly />;
  }

  return (
    <AppShell tab={tab} onTab={setTab} me={me} canRun={canRun}>
      <AnimatePresence mode="wait">
        <motion.div
          key={tab}
          initial="hidden"
          animate="visible"
          exit="exit"
          variants={panelVariants}
          style={{ display: "contents" }}
        >
          {tab === "upload" && <UploadView />}
          {tab === "cases" && (
            <CasesView
              canRun={canRun}
              onRun={(ids) => {
                if (!canRun) return;
                setSelected(ids);
                setTab("run");
              }}
            />
          )}
          {tab === "run" && (
            <RunView caseIds={selected} canSubmit={canRun} onSubmitted={() => setTab("runs")} />
          )}
          {tab === "runs" && <RunsView />}
          {tab === "admin" && me.role === "admin" && <AdminView />}
        </motion.div>
      </AnimatePresence>
    </AppShell>
  );
}

function AccessState({
  title,
  detail,
  signOutOnly = false,
}: {
  title: string;
  detail?: string;
  signOutOnly?: boolean;
}) {
  function signOut() {
    tokenStore.clear();
    location.reload();
  }

  return (
    <div className="signin">
      <div className="panel signin-card">
        <div className="brand-mark">OF</div>
        <h1 className="signin-title">{title}</h1>
        {detail && <p className="signin-sub">{detail}</p>}
        {signOutOnly && (
          <button className="btn-add" onClick={signOut}>
            Sign out
          </button>
        )}
      </div>
    </div>
  );
}
