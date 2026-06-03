import { type ReactNode } from "react";

export type Tab = "upload" | "cases" | "run" | "runs";
const TABS: { id: Tab; n: string; label: string }[] = [
  { id: "upload", n: "01", label: "Upload" },
  { id: "cases", n: "02", label: "Cases" },
  { id: "run", n: "03", label: "Run" },
  { id: "runs", n: "04", label: "Runs" },
];

export function AppShell({
  tab,
  onTab,
  children,
}: {
  tab: Tab;
  onTab: (t: Tab) => void;
  children: ReactNode;
}) {
  return (
    <>
      <div className="bg" />
      <div className="app">
        <div className="header">
          <div className="brand">
            <div className="brand-mark">OF</div>
            <div className="brand-name">
              OpenFOAM Batch <span>· cfd-lemnisca</span>
            </div>
          </div>
          <div className="tabs">
            {TABS.map((t) => (
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
            <div className="dot" />
            <span style={{ fontFamily: "var(--f-mono)" }}>cfd-lemnisca-cases</span>
          </div>
        </div>
        <div className="stage">{children}</div>
      </div>
    </>
  );
}
