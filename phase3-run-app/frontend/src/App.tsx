import { useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { AppShell, type Tab } from "./components/AppShell";
import { usePanelVariants } from "./lib/motion";
import { UploadView } from "./views/UploadView";
import { CasesView } from "./views/CasesView";
import { RunView } from "./views/RunView";
import { RunsView } from "./views/RunsView";

export default function App() {
  const [tab, setTab] = useState<Tab>("upload");
  const [selected, setSelected] = useState<string[]>([]);
  const panelVariants = usePanelVariants();

  return (
    <AppShell tab={tab} onTab={setTab}>
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
              onRun={(ids) => {
                setSelected(ids);
                setTab("run");
              }}
            />
          )}
          {tab === "run" && (
            <RunView caseIds={selected} onSubmitted={() => setTab("runs")} />
          )}
          {tab === "runs" && <RunsView />}
        </motion.div>
      </AnimatePresence>
    </AppShell>
  );
}
