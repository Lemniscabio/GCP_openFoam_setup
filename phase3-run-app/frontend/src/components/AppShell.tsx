import { type ReactNode } from "react";
import { motion } from "framer-motion";
import { Badge } from "@/components/ui/badge";

import { usePanelVariants } from "@/lib/motion";
import type { Me } from "@/lib/client";

export type Tab = "upload" | "cases" | "submit" | "status" | "results";
const TABS: { id: Tab; n: string; label: string }[] = [
  { id: "upload", n: "01", label: "Upload" },
  { id: "cases", n: "02", label: "Cases" },
  { id: "submit", n: "03", label: "Submit" },
  { id: "status", n: "04", label: "Status" },
  { id: "results", n: "05", label: "Results" },
];

export function AppShell({
  tab,
  onTab,
  onProfile,
  me,
  children,
}: {
  tab: Tab;
  onTab: (t: Tab) => void;
  onProfile: () => void;
  me: Me;
  children: ReactNode;
}) {
  const panelVariants = usePanelVariants();

  return (
    <>
      <div className="bg" />
      <motion.div
        className="app"
        initial="hidden"
        animate="visible"
        variants={panelVariants}
      >
        <header className="header">
          <div className="brand">
            <div className="brand-mark">OF</div>
            <div className="brand-name">
              OpenFOAM Batch <span>· cfd-lemnisca</span>
            </div>
          </div>
          <nav className="tabs" aria-label="Primary navigation">
            {TABS.map((t) => (
              <button
                key={t.id}
                className={`tab${tab === t.id ? " on" : ""}`}
                onClick={() => onTab(t.id)}
                aria-current={tab === t.id ? "page" : undefined}
              >
                <div className="tab-num">{t.n}</div>
                <span>{t.label}</span>
              </button>
            ))}
          </nav>
          <button className="profile cursor-pointer border-0 bg-transparent" title={me.email} onClick={onProfile}>
            <div className="profile-avatar" aria-hidden="true">
              <svg viewBox="0 0 24 24" role="img">
                <path d="M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8Zm7 8a7 7 0 0 0-14 0" />
              </svg>
            </div>
            <div className="profile-copy">
              <span className="profile-email">{me.email}</span>
              <span className="profile-label">Signed in</span>
            </div>
            <Badge className="profile-role" variant="secondary">
              {me.role ?? "pending"}
            </Badge>
          </button>
        </header>
        <div className="stage">{children}</div>
      </motion.div>
    </>
  );
}
