import { useEffect, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { AppShell, type Tab } from "./components/AppShell";
import { tokenStore } from "./lib/auth";
import { api, type Me } from "./lib/client";
import { usePanelVariants } from "./lib/motion";
import { UploadView } from "./views/UploadView";
import { CasesView } from "./views/CasesView";
import { SubmitView } from "./views/SubmitView";
import { RunsView } from "./views/RunsView";
import { ResultsView } from "./views/ResultsView";
import { ProfileView } from "./views/ProfileView";
import { GenerateView } from "./views/GenerateView";

export default function App() {
  const [tab, setTab] = useState<Tab>("generate");
  const [activeProject, setActiveProject] = useState<string | null>(null);
  const [selectedCaseIds, setSelectedCaseIds] = useState<string[]>([]);
  const [view, setView] = useState<"section" | "profile">("section");
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
    <AppShell
      tab={tab}
      onTab={(nextTab) => { setTab(nextTab); setView("section"); }}
      onProfile={() => setView("profile")}
      me={me}
    >
      <AnimatePresence mode="wait">
        <motion.div
          key={view === "profile" ? "profile" : tab}
          initial="hidden"
          animate="visible"
          exit="exit"
          variants={panelVariants}
          style={{ display: "contents" }}
        >
          {view === "profile" ? (
            <ProfileView me={me} onBack={() => setView("section")} />
          ) : (
            <>
          {tab === "generate" && (
            <GenerateView canRun={canRun} onCreated={(project, ids) => {
              setActiveProject(project);
              setSelectedCaseIds(ids);
              setTab("cases");
            }} />
          )}
          {tab === "upload" && (
            <UploadView canUpload={canRun} onUploaded={(project, ids) => {
              setActiveProject(project);
              setSelectedCaseIds(ids);
              setTab("cases");
            }} />
          )}
          {tab === "cases" && (
            <CasesView
              activeProject={activeProject}
              selectedCaseIds={selectedCaseIds}
              canRun={canRun}
              onChange={setSelectedCaseIds}
              onActiveProject={setActiveProject}
              onSubmit={() => setTab("submit")}
            />
          )}
          {tab === "submit" && (
            <SubmitView
              project={activeProject}
              caseIds={selectedCaseIds}
              canSubmit={canRun}
              onSubmitted={() => setTab("status")}
            />
          )}
          {tab === "status" && <RunsView />}
          {tab === "results" && <ResultsView />}
            </>
          )}
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
