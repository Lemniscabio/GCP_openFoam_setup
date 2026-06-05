import { type ReactNode } from "react";
import { motion } from "framer-motion";
import { Badge } from "@/components/ui/badge";

import { usePanelVariants } from "@/lib/motion";
import type { Me } from "@/lib/client";

export type Tab = "upload" | "cases" | "run" | "runs" | "admin";
const TABS: { id: Tab; n: string; label: string }[] = [
  { id: "upload", n: "01", label: "Upload" },
  { id: "cases", n: "02", label: "Cases" },
  { id: "run", n: "03", label: "Run" },
  { id: "runs", n: "04", label: "Runs" },
  { id: "admin", n: "05", label: "Admin" },
];

export function AppShell({
  tab,
  onTab,
  me,
  canRun = true,
  children,
}: {
  tab: Tab;
  onTab: (t: Tab) => void;
  me: Me;
  canRun?: boolean;
  children: ReactNode;
}) {
  const panelVariants = usePanelVariants();
  const tabs = TABS.filter((t) => {
    if (t.id === "admin") return me.role === "admin";
    return canRun || (t.id !== "upload" && t.id !== "run");
  });

  return (
    <>
      <div className="bg" />
      <motion.div
        className="app"
        initial="hidden"
        animate="visible"
        variants={panelVariants}
      >
        <div className="header">
          <div className="brand">
            <div className="brand-mark">OF</div>
            <div className="brand-name">
              OpenFOAM Batch <span>· cfd-lemnisca</span>
            </div>
          </div>
          <div className="tabs">
            {tabs.map((t) => (
              <button
                key={t.id}
                className={`tab${tab === t.id ? " on" : ""}`}
                onClick={() => onTab(t.id)}
              >
                <div className="tab-num">{t.n}</div>
                <span>{t.label}</span>
              </button>
            ))}
          </div>
          <div className="header-spacer" />
          <div className="header-meta">
            <span style={{ fontFamily: "var(--f-mono)" }}>{me.email}</span>
            <Badge variant="secondary">{me.role ?? "pending"}</Badge>
          </div>
        </div>
        <div className="stage">{children}</div>
      </motion.div>
    </>
  );
}
