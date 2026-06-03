import { useState } from "react";
import { AppShell, type Tab } from "./components/AppShell";
import { UploadView } from "./views/UploadView";
import { CasesView } from "./views/CasesView";
import { RunView } from "./views/RunView";
import { RunsView } from "./views/RunsView";

export default function App() {
  const [tab, setTab] = useState<Tab>("upload");
  return (
    <AppShell tab={tab} onTab={setTab}>
      {tab === "upload" && <UploadView />}
      {tab === "cases" && <CasesView />}
      {tab === "run" && <RunView />}
      {tab === "runs" && <RunsView />}
    </AppShell>
  );
}
