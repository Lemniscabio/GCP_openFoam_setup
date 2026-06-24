import { useEffect, useState } from "react";
import { motion } from "framer-motion";
import { StlViewer } from "@/components/StlViewer";
import { Spinner } from "@/components/ui/Spinner";
import { Toast } from "@/components/ui/Toast";
import { Button } from "@/components/ui/button";
import { usePanelVariants } from "@/lib/motion";
import { api, type ProjectInfo } from "../lib/client";

type JsonObject = Record<string, any>;
type Physics = "single_phase" | "two_phase";
type Preview = { str_params: JsonObject; case_params: JsonObject; stls: Record<string, string>; files: Record<string, string> };

// Geometry inputs common to both physics modes. Optional fields (blade L/H, baffle
// width) are left blank by default so the backend fills them from correlations (D/4,
// D/5, T/12). type "opt-number" omits the field entirely when empty.
const GEOMETRY_FIELDS: [string, string, string, "number" | "opt-number" | "text"][] = [
  ["tank.diameter_m", "Tank diameter", "m", "number"],
  ["tank.height_m", "Tank height", "m", "number"],
  ["liquid.height_m", "Liquid height", "m", "number"],
  ["baffles.count", "Baffle count", "", "number"],
  ["baffles.width_m", "Baffle width (blank → tank dia ÷ 12)", "m", "opt-number"],
  ["baffles.height_m", "Baffle height", "m", "number"],
  ["baffles.arrangement", "Baffle arrangement", "", "text"],
  ["impellers.count", "Impeller count", "", "number"],
  ["impellers.blades", "Blades per impeller", "", "number"],
  ["impellers.diameter_ratio", "Impeller/tank diameter ratio (D/T)", "", "number"],
  ["impellers.blade_length_m", "Blade length (blank → impeller dia ÷ 4)", "m", "opt-number"],
  ["impellers.blade_height_m", "Blade height (blank → impeller dia ÷ 5)", "m", "opt-number"],
  ["impellers.lowest_clearance_m", "Lowest clearance", "m", "number"],
  ["impellers.inter_impeller_clearance_m", "Inter-impeller clearance", "m", "number"],
];

const DEFAULT_SPEC: JsonObject = {
  family: "stirred_tank_reactor",
  tank: { diameter_m: 2.09, height_m: 9.6, bottom: "dished" },
  liquid: { height_m: 6.55 },
  baffles: { count: 4, width_m: "", height_m: 7.5, arrangement: "symmetric" },
  shaft: { central: true },
  impellers: {
    count: 4,
    type: "rushton",
    blades: 6,
    diameter_ratio: 0.3333333,
    blade_length_m: "",
    blade_height_m: "",
    lowest_clearance_m: 1.12,
    inter_impeller_clearance_m: 1.46,
  },
};

function projectError(project: string) {
  const value = project.trim();
  if (!value) return "Project is required.";
  if (value === "." || value === ".." || value.includes("/") || value.length > 128) {
    return "Use 1-128 characters without '/', '.' or '..'.";
  }
  return null;
}

function valueAt(source: JsonObject, path: string) {
  return path.split(".").reduce<any>((value, key) => value?.[key], source);
}

function withValue(source: JsonObject, path: string, value: unknown) {
  const keys = path.split(".");
  const root = structuredClone(source);
  let target = root;
  keys.slice(0, -1).forEach((key) => {
    target[key] = { ...target[key] };
    target = target[key];
  });
  target[keys[keys.length - 1]] = value;
  return root;
}

// Drop "" (blank optional inputs) so the backend applies correlations.
function prune(value: any): any {
  if (Array.isArray(value)) return value.map(prune);
  if (value && typeof value === "object") {
    const out: JsonObject = {};
    for (const [key, val] of Object.entries(value)) {
      if (val === "") continue;
      out[key] = prune(val);
    }
    return out;
  }
  return value;
}

export function GenerateView({
  canRun,
  onCreated,
}: {
  canRun: boolean;
  onCreated: (project: string, caseIds: string[]) => void;
}) {
  const [physics, setPhysics] = useState<Physics>("single_phase");
  const [spec, setSpec] = useState<JsonObject>(structuredClone(DEFAULT_SPEC));
  const [rpm, setRpm] = useState("100");
  const [viscosity, setViscosity] = useState("1e-6");
  const [gasVvm, setGasVvm] = useState("0.5");
  const [varyRpm, setVaryRpm] = useState("");
  const [varyVisc, setVaryVisc] = useState("");
  const [varyGas, setVaryGas] = useState("");
  const [preview, setPreview] = useState<Preview | null>(null);
  const [caseFiles, setCaseFiles] = useState<Record<string, string>>({});
  const [selectedFile, setSelectedFile] = useState<string>("");
  const [expandedDirs, setExpandedDirs] = useState<Set<string>>(new Set());
  const toggleDir = (path: string) =>
    setExpandedDirs((current) => {
      const next = new Set(current);
      next.has(path) ? next.delete(path) : next.add(path);
      return next;
    });
  const [projects, setProjects] = useState<ProjectInfo[]>([]);
  const [project, setProject] = useState("");
  const [projectMode, setProjectMode] = useState<"existing" | "new">("existing");
  const [previewing, setPreviewing] = useState(false);
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [toast, setToast] = useState<string | null>(null);
  const panelVariants = usePanelVariants();
  const invalidProject = projectError(project);

  useEffect(() => {
    let alive = true;
    api.getProjects()
      .then((response) => {
        if (!alive) return;
        setProjects(response.projects);
        if (response.projects.length === 0) setProjectMode("new");
      })
      .catch((loadError) => { if (alive) setError(`Unable to load projects: ${String(loadError)}`); });
    return () => { alive = false; };
  }, []);

  // Assemble the STRParams spec + CaseParams from the form. rpm flows to BOTH
  // operating.rpm (geometry spec) and case_params.rpm (solver omega).
  function buildParams() {
    const operating: JsonObject = { rpm: Number(rpm) };
    if (physics === "two_phase") operating.gas_flow_vvm = Number(gasVvm);
    return prune({ ...spec, physics, operating });
  }
  function buildCaseParams() {
    const cp: JsonObject = { rpm: Number(rpm) };
    if (physics === "single_phase") cp.viscosity_m2_s = Number(viscosity);
    return cp;
  }

  async function generatePreview() {
    if (!canRun || previewing) return;
    setPreviewing(true);
    setError(null);
    try {
      const result = await api.generatePreview({ params: buildParams(), case_params: buildCaseParams() });
      setPreview(result);
      const files = result.files || {};
      setCaseFiles(files);
      const keys = Object.keys(files);
      setSelectedFile(keys.includes("system/controlDict") ? "system/controlDict" : (keys[0] ?? ""));
    } catch (generateError) {
      setError(String(generateError));
      setToast(String(generateError));
    } finally {
      setPreviewing(false);
    }
  }

  // Variation axes: comma-separated value lists. Geometry-fixed params only.
  function parseList(text: string): number[] {
    return text.split(",").map((x) => x.trim()).filter(Boolean).map(Number).filter((n) => Number.isFinite(n));
  }
  function buildAxes(): Record<string, number[]> {
    const axes: Record<string, number[]> = {};
    const rpmValues = parseList(varyRpm);
    if (rpmValues.length) axes.rpm = rpmValues;
    if (physics === "single_phase") {
      const v = parseList(varyVisc);
      if (v.length) axes.viscosity_m2_s = v;
    } else {
      const g = parseList(varyGas);
      if (g.length) axes.gas_flow_vvm = g;
    }
    return axes;
  }
  const axes = buildAxes();
  const variationCount = Object.keys(axes).length
    ? Object.values(axes).reduce((acc, list) => acc * list.length, 1)
    : 0;
  const _axisLabel: Record<string, string> = { rpm: "RPM", viscosity_m2_s: "viscosity", gas_flow_vvm: "gas-flow" };
  const variationBreakdown = Object.entries(axes).map(([key, list]) => `${list.length} ${_axisLabel[key]}`).join(" × ");

  async function createVariations() {
    if (!canRun || !preview || invalidProject || creating || variationCount === 0) return;
    const selectedProject = project.trim();
    setCreating(true);
    setError(null);
    try {
      const result = await api.generateVariations({
        project: selectedProject,
        params: buildParams(),
        case_params: buildCaseParams(),
        files: caseFiles,
        axes,
      });
      setToast(`Created ${result.case_ids.length} cases: ${result.case_ids.join(", ")}`);
      onCreated(selectedProject, result.case_ids);
    } catch (createError) {
      setError(String(createError));
      setToast(String(createError));
    } finally {
      setCreating(false);
    }
  }

  async function createCase() {
    if (!canRun || !preview || invalidProject || creating) return;
    const selectedProject = project.trim();
    setCreating(true);
    setError(null);
    try {
      const result = await api.generateCreate({
        project: selectedProject,
        params: buildParams(),
        case_params: buildCaseParams(),
        files: caseFiles,
      });
      setToast(`Case ${result.case_id} created`);
      onCreated(selectedProject, [result.case_id]);
    } catch (createError) {
      setError(String(createError));
      setToast(String(createError));
    } finally {
      setCreating(false);
    }
  }

  function updateField(path: string, value: unknown) {
    setSpec((current) => withValue(current, path, value));
    setPreview(null); // inputs changed — require a fresh preview before create
  }

  // Live-derived defaults for the optional fields, recomputed as their inputs change.
  // Shown as greyed placeholder text so the user sees what blank will auto-fill to.
  const num = (path: string) => Number(valueAt(spec, path));
  const impellerDia = num("tank.diameter_m") * num("impellers.diameter_ratio"); // D
  const derivedDefaults: Record<string, number> = {
    "baffles.width_m": num("tank.diameter_m") / 12,          // T/12
    "impellers.blade_length_m": impellerDia / 4,             // D/4
    "impellers.blade_height_m": impellerDia / 5,             // D/5
  };
  function placeholderFor(path: string): string | undefined {
    const v = derivedDefaults[path];
    return Number.isFinite(v) && v > 0 ? `auto: ${v.toFixed(4)}` : undefined;
  }

  // Client-side validation mirroring the schema's cross-field rules, so the user gets
  // immediate feedback instead of a slow backend round-trip / error.
  function specErrors(): string[] {
    const errs: string[] = [];
    const required: [string, string][] = [
      ["tank.diameter_m", "Tank diameter"], ["tank.height_m", "Tank height"],
      ["liquid.height_m", "Liquid height"], ["baffles.count", "Baffle count"],
      ["baffles.height_m", "Baffle height"], ["impellers.count", "Impeller count"],
      ["impellers.blades", "Blades per impeller"], ["impellers.diameter_ratio", "Diameter ratio"],
      ["impellers.lowest_clearance_m", "Lowest clearance"],
      ["impellers.inter_impeller_clearance_m", "Inter-impeller clearance"],
    ];
    for (const [path, label] of required) {
      const v = num(path);
      if (!Number.isFinite(v) || v <= 0) errs.push(`${label} must be a positive number.`);
    }
    if (!Number.isFinite(Number(rpm)) || Number(rpm) < 0) errs.push("RPM must be ≥ 0.");
    if (physics === "two_phase" && (!Number.isFinite(Number(gasVvm)) || Number(gasVvm) <= 0)) {
      errs.push("Gas flow (vvm) must be greater than 0 for two-phase.");
    }
    const tankH = num("tank.height_m"), liqH = num("liquid.height_m"), r = num("impellers.diameter_ratio");
    if (Number.isFinite(tankH) && Number.isFinite(liqH) && liqH > tankH) {
      errs.push("Liquid height must not exceed tank height.");
    }
    if (Number.isFinite(r) && (r <= 0 || r > 0.7)) {
      errs.push("Impeller/tank diameter ratio (D/T) should be between 0 and 0.7.");
    }
    const count = num("impellers.count"), lowC = num("impellers.lowest_clearance_m"), interC = num("impellers.inter_impeller_clearance_m");
    if ([count, lowC, interC, liqH].every(Number.isFinite)) {
      const highest = lowC + (count - 1) * interC;
      if (highest >= liqH) errs.push("Impellers don't fit below the liquid (lowest clearance + (count−1)·inter-impeller spacing must be < liquid height).");
    }
    return errs;
  }
  const errors = specErrors();
  const warnings: string[] = [];
  if (num("tank.diameter_m") > 10) {
    warnings.push("Large vessel (> 10 m): geometry preview and meshing will be slower and heavier.");
  }

  const resolved = preview?.str_params;

  return (
    <motion.div className="step" style={{ gridTemplateColumns: "1fr" }} initial="hidden" animate="visible" exit="exit" variants={panelVariants}>
      <div className="panel">
        <div className="panel-head">
          <div className="ph-num">01</div>
          <div className="ph-text">
            <div className="ph-title">Generate a stirred-tank case</div>
            <div className="ph-sub">Fill in the reactor spec, preview the geometry, then create the case.</div>
          </div>
        </div>
        <div className="panel-body">
          {!canRun && <div className="empty-state" style={{ fontStyle: "normal" }}>Your viewer role is read-only. Generation and case creation are disabled.</div>}

          <div className="field w-full">
            <div className="tabs" role="group" aria-label="Physics mode">
              <button type="button" className={`tab${physics === "single_phase" ? " on" : ""}`} disabled={!canRun} onClick={() => { setPhysics("single_phase"); setPreview(null); }}>
                <span>Single-phase</span>
              </button>
              <button type="button" className={`tab${physics === "two_phase" ? " on" : ""}`} disabled={!canRun} onClick={() => { setPhysics("two_phase"); setPreview(null); }}>
                <span>Two-phase (gas–liquid)</span>
              </button>
            </div>
          </div>

          <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
            <SelectField label="Tank bottom" value={valueAt(spec, "tank.bottom")} options={["dished", "flat"]} disabled={!canRun} onChange={(v) => updateField("tank.bottom", v)} />
            <SelectField label="Impeller type" value={valueAt(spec, "impellers.type")} options={["rushton"]} disabled={!canRun} onChange={(v) => updateField("impellers.type", v)} />
            {GEOMETRY_FIELDS.map(([path, label, unit, type]) => (
              <ParamField
                key={path}
                label={label}
                unit={unit}
                type="text"
                value={valueAt(spec, path)}
                placeholder={type === "opt-number" ? placeholderFor(path) : undefined}
                disabled={!canRun}
                onChange={(value) => updateField(path, value)}
              />
            ))}
            <ParamField label="RPM" unit="rpm" type="text" value={rpm} disabled={!canRun} onChange={(v) => { setRpm(v); setPreview(null); }} />
            {physics === "single_phase" ? (
              <ParamField label="Kinematic viscosity" unit="m²/s" type="text" value={viscosity} disabled={!canRun} onChange={(v) => { setViscosity(v); setPreview(null); }} />
            ) : (
              <ParamField label="Gas flow" unit="vvm" type="text" value={gasVvm} disabled={!canRun} onChange={(v) => { setGasVvm(v); setPreview(null); }} />
            )}
          </div>

          {canRun && errors.length > 0 && (
            <div style={{ color: "#dc2626", fontSize: 13, lineHeight: 1.5 }}>
              {errors.map((message) => <div key={message}>• {message}</div>)}
            </div>
          )}
          {canRun && errors.length === 0 && warnings.length > 0 && (
            <div className="empty-state" style={{ fontStyle: "normal", opacity: 0.7 }}>
              {warnings.map((message) => <div key={message}>⚠ {message}</div>)}
            </div>
          )}
          <div className="row-end">
            <Button disabled={!canRun || previewing || errors.length > 0} onClick={generatePreview}>
              {previewing && <Spinner size={16} label="Generating preview" />}
              {!canRun ? "Read-only" : previewing ? "Generating…" : errors.length > 0 ? "Fix errors to preview" : "Generate preview"}
            </Button>
          </div>
          {error && <div style={{ color: "#dc2626", fontSize: 13, lineHeight: 1.5 }}>ERROR: {error}</div>}
        </div>
      </div>

      {preview && (
        <>
          <div className="panel">
            <div className="panel-head">
              <div className="ph-num">3D</div>
              <div className="ph-text">
                <div className="ph-title">Geometry preview</div>
                <div className="ph-sub">Left-drag to orbit · scroll to zoom · right-drag (or shift-drag) to pan.</div>
              </div>
            </div>
            <div className="panel-body"><StlViewer stls={preview.stls} /></div>
          </div>

          <div className="panel">
            <div className="panel-head">
              <div className="ph-num">02</div>
              <div className="ph-text">
                <div className="ph-title">Case files</div>
                <div className="ph-sub">Inspect every generated OpenFOAM file. Edit any of them (solver, schemes, BCs…) — your changes are written into the case on Create.</div>
              </div>
            </div>
            <div className="panel-body">
              <div className="grid grid-cols-1 gap-3 md:grid-cols-[240px_1fr]">
                <div className="max-h-96 overflow-auto rounded-lg border border-black/10 bg-black/[0.02] p-2 text-xs">
                  <FileTree
                    nodes={buildFileTree(Object.keys(caseFiles))}
                    depth={0}
                    expanded={expandedDirs}
                    selected={selectedFile}
                    onToggle={toggleDir}
                    onSelect={setSelectedFile}
                  />
                </div>
                <div className="flex flex-col gap-1">
                  <div className="truncate font-mono text-xs text-[var(--ink-2)]">{selectedFile || "Select a file from the tree"}</div>
                  <textarea
                    className="input w-full font-mono text-xs"
                    style={{ minHeight: 384, whiteSpace: "pre", overflowWrap: "normal" }}
                    spellCheck={false}
                    disabled={!canRun || !selectedFile}
                    value={selectedFile ? (caseFiles[selectedFile] ?? "") : ""}
                    onChange={(event) => setCaseFiles((files) => ({ ...files, [selectedFile]: event.target.value }))}
                  />
                </div>
              </div>
            </div>
          </div>

          <div className="panel">
            <div className="panel-head">
              <div className="ph-num">03</div>
              <div className="ph-text">
                <div className="ph-title">Resolved &amp; derived parameters</div>
                <div className="ph-sub">Values the generator filled from your spec (correlations applied). Edit the spec above and re-preview to change them.</div>
              </div>
            </div>
            <div className="panel-body">
              <div className="grid grid-cols-2 gap-3 text-xs text-[var(--ink-2)] md:grid-cols-4">
                <ConfigValue label="Physics" value={String(resolved?.physics ?? physics)} />
                <ConfigValue label="Impeller Ø (D)" value={`${fmt(resolved?.impeller_diameter_m)} m`} />
                <ConfigValue label="Blade length" value={`${fmt(valueAt(resolved ?? {}, "impellers.blade_length_m"))} m`} />
                <ConfigValue label="Blade height" value={`${fmt(valueAt(resolved ?? {}, "impellers.blade_height_m"))} m`} />
                <ConfigValue label="Baffle width" value={`${fmt(valueAt(resolved ?? {}, "baffles.width_m"))} m`} />
                <ConfigValue label="RPM" value={String(preview.case_params?.rpm ?? "—")} />
                <ConfigValue label="Solver" value={physics === "two_phase" ? "multiphaseEuler" : "incompressibleFluid"} />
                <ConfigValue label="Turbulence" value={physics === "two_phase" ? "kEpsilon (liquid) / laminar (gas)" : "kEpsilon"} />
                {physics === "single_phase" && <ConfigValue label="Viscosity" value={`${preview.case_params?.viscosity_m2_s ?? "—"} m²/s`} />}
                {physics === "two_phase" && <ConfigValue label="Gas flow" value={`${gasVvm} vvm`} />}
              </div>

              <div className="field w-full">
                <label className="lbl" htmlFor="generate-project"><span>Project</span></label>
                <div className="tabs" role="group" aria-label="Project mode">
                  <button type="button" className={`tab${projectMode === "existing" ? " on" : ""}`} onClick={() => { setProjectMode("existing"); setProject(""); }}>
                    <span>Select existing</span>
                  </button>
                  <button type="button" className={`tab${projectMode === "new" ? " on" : ""}`} onClick={() => { setProjectMode("new"); setProject(""); }}>
                    <span>+ Create new</span>
                  </button>
                </div>
                {projectMode === "existing" ? (
                  <select id="generate-project" className="input w-full" value={project} onChange={(event) => setProject(event.target.value)} disabled={!canRun || projects.length === 0}>
                    {projects.length === 0 ? <option value="">No projects yet</option> : (
                      <>
                        <option value="" disabled>Select a project</option>
                        {projects.map((item) => <option key={item.name} value={item.name}>{item.name}</option>)}
                      </>
                    )}
                  </select>
                ) : (
                  <input id="generate-project" className="input w-full" value={project} onChange={(event) => setProject(event.target.value)} placeholder="Type a new project name" disabled={!canRun} aria-invalid={Boolean(invalidProject)} />
                )}
                {invalidProject && <div style={{ color: "#dc2626", fontSize: 13, lineHeight: 1.5, marginTop: 4 }}>{invalidProject}</div>}
              </div>

              <details className="rounded-xl border border-black/10 bg-black/[0.025] p-4">
                <summary className="cursor-pointer text-sm font-semibold text-[var(--ink)]">
                  Variations (optional) — spin multiple cases from this base
                </summary>
                <div className="mt-3 grid grid-cols-1 gap-3 md:grid-cols-2">
                  <ParamField label="RPM values" unit="rpm" type="text" value={varyRpm} disabled={!canRun} placeholder="e.g. 50, 100, 150" onChange={setVaryRpm} />
                  {physics === "single_phase" ? (
                    <ParamField label="Viscosity values" unit="m²/s" type="text" value={varyVisc} disabled={!canRun} placeholder="e.g. 1e-6, 1e-5" onChange={setVaryVisc} />
                  ) : (
                    <ParamField label="Gas-flow values" unit="vvm" type="text" value={varyGas} disabled={!canRun} placeholder="e.g. 0.3, 0.5, 0.8" onChange={setVaryGas} />
                  )}
                </div>
                <div className="mt-2" style={{ fontWeight: 600, color: variationCount > 0 ? "var(--ink)" : "var(--ink-2)" }}>
                  {variationCount > 0
                    ? `→ ${variationBreakdown} = ${variationCount} case${variationCount === 1 ? "" : "s"}`
                    : "Enter one or more comma-separated values per axis to sweep."}
                </div>
                <div className="ph-sub mt-1">
                  Discrete values per axis (like singlephase), combined as a Cartesian product. Geometry stays fixed; your edits carry into every case.
                </div>
              </details>

              <div className="row-end" style={{ gap: 12 }}>
                <Button disabled={!canRun || Boolean(invalidProject) || creating} onClick={createCase}>
                  {creating && <Spinner size={16} label="Creating case" />}
                  {!canRun ? "Read-only" : creating ? "Creating…" : "Create case"}
                </Button>
                {variationCount > 0 && (
                  <Button disabled={!canRun || Boolean(invalidProject) || creating} onClick={createVariations}>
                    {creating ? "Creating…" : `Create ${variationCount} variations`}
                  </Button>
                )}
              </div>
            </div>
          </div>
        </>
      )}
      <Toast message={toast} onDismiss={() => setToast(null)} />
    </motion.div>
  );
}

function fmt(value: unknown) {
  return typeof value === "number" ? value.toFixed(4) : "—";
}

function ParamField({ label, unit, type, value, disabled, placeholder, onChange }: {
  label: string;
  unit: string;
  type: "number" | "text";
  value: unknown;
  disabled: boolean;
  placeholder?: string;
  onChange: (value: string) => void;
}) {
  return (
    <label className="field">
      <span className="lbl" style={{ display: "flex", justifyContent: "space-between", gap: 8, alignItems: "baseline" }}>
        <span>{label}</span>
        {unit && <span style={{ color: "var(--ink-2)", fontWeight: 400 }}>{unit}</span>}
      </span>
      <input className="input w-full" type={type} step={type === "number" ? "any" : undefined} value={String(value ?? "")} placeholder={placeholder} disabled={disabled} onChange={(event) => onChange(event.target.value)} />
    </label>
  );
}

function SelectField({ label, value, options, disabled, onChange }: {
  label: string;
  value: unknown;
  options: string[];
  disabled: boolean;
  onChange: (value: string) => void;
}) {
  return (
    <label className="field">
      <span className="lbl"><span>{label}</span></span>
      <select className="input w-full" value={String(value ?? "")} disabled={disabled} onChange={(event) => onChange(event.target.value)}>
        {options.map((option) => <option key={option} value={option}>{option}</option>)}
      </select>
    </label>
  );
}

function ConfigValue({ label, value }: { label: string; value: string }) {
  return <div><div className="font-semibold text-[var(--ink)]">{label}</div><div className="mt-1 font-mono">{value}</div></div>;
}

// ---- VS Code-style collapsible file tree -------------------------------------
type TreeNode = { name: string; path: string; isFile: boolean; children: TreeNode[] };

function buildFileTree(paths: string[]): TreeNode[] {
  const root: TreeNode = { name: "", path: "", isFile: false, children: [] };
  for (const full of paths) {
    const parts = full.split("/");
    let node = root;
    parts.forEach((part, index) => {
      const isFile = index === parts.length - 1;
      const path = parts.slice(0, index + 1).join("/");
      let child = node.children.find((c) => c.name === part);
      if (!child) {
        child = { name: part, path, isFile, children: [] };
        node.children.push(child);
      }
      node = child;
    });
  }
  const sortNode = (node: TreeNode) => {
    node.children.sort((a, b) => (a.isFile === b.isFile ? a.name.localeCompare(b.name) : a.isFile ? 1 : -1));
    node.children.forEach(sortNode);
  };
  sortNode(root);
  return root.children;
}

function FileTree({ nodes, depth, expanded, selected, onToggle, onSelect }: {
  nodes: TreeNode[];
  depth: number;
  expanded: Set<string>;
  selected: string;
  onToggle: (path: string) => void;
  onSelect: (path: string) => void;
}) {
  return (
    <>
      {nodes.map((node) => (
        <div key={node.path}>
          <button
            type="button"
            title={node.path}
            className={`flex w-full items-center gap-1 truncate rounded px-1.5 py-1 text-left font-mono ${
              node.isFile && node.path === selected ? "bg-black/10 font-semibold text-[var(--ink)]" : "text-[var(--ink-2)] hover:bg-black/5"
            }`}
            style={{ paddingLeft: 6 + depth * 14 }}
            onClick={() => (node.isFile ? onSelect(node.path) : onToggle(node.path))}
          >
            <span className="w-3 shrink-0 text-center">
              {node.isFile ? "·" : expanded.has(node.path) ? "▾" : "▸"}
            </span>
            <span className="truncate">{node.name}{node.isFile ? "" : "/"}</span>
          </button>
          {!node.isFile && expanded.has(node.path) && (
            <FileTree nodes={node.children} depth={depth + 1} expanded={expanded} selected={selected} onToggle={onToggle} onSelect={onSelect} />
          )}
        </div>
      ))}
    </>
  );
}
