import { useState } from "react";
import { AppShell, type Tab } from "./components/AppShell";
import { UploadView } from "./views/UploadView";
import { CasesView } from "./views/CasesView";
import { RunView } from "./views/RunView";
import { RunsView } from "./views/RunsView";

export default function App() {
  const [tab, setTab] = useState<Tab>("upload");
  const [selected, setSelected] = useState<string[]>([]);

  return (
    <AppShell tab={tab} onTab={setTab}>
      {tab === "upload" && <UploadView />}
      {tab === "cases" && (
        <CasesView onRun={(ids) => { setSelected(ids); setTab("run"); }} />
      )}
      {tab === "run" && (
        <RunView caseIds={selected} onSubmitted={() => setTab("runs")} />
      )}
      {tab === "runs" && <RunsView />}
    </AppShell>
  );
}
