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
type Preview = { str_params: JsonObject; case_params: JsonObject; stls: Record<string, string> };

// Geometry inputs common to both physics modes. Optional fields (blade L/H, baffle
// width) are left blank by default so the backend fills them from correlations (D/4,
// D/5, T/12). type "opt-number" omits the field entirely when empty.
const GEOMETRY_FIELDS: [string, string, string, "number" | "opt-number" | "text"][] = [
  ["tank.diameter_m", "Tank diameter", "m", "number"],
  ["tank.height_m", "Tank height", "m", "number"],
  ["liquid.height_m", "Liquid height", "m", "number"],
  ["baffles.count", "Baffle count", "", "number"],
  ["baffles.width_m", "Baffle width (blank → T/12)", "m", "opt-number"],
  ["baffles.height_m", "Baffle height", "m", "number"],
  ["baffles.arrangement", "Baffle arrangement", "", "text"],
  ["impellers.count", "Impeller count", "", "number"],
  ["impellers.blades", "Blades per impeller", "", "number"],
  ["impellers.diameter_ratio", "Diameter ratio D/T", "", "number"],
  ["impellers.blade_length_m", "Blade length (blank → D/4)", "m", "opt-number"],
  ["impellers.blade_height_m", "Blade height (blank → D/5)", "m", "opt-number"],
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
  const [preview, setPreview] = useState<Preview | null>(null);
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
    } catch (generateError) {
      setError(String(generateError));
      setToast(String(generateError));
    } finally {
      setPreviewing(false);
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
                type={type === "text" ? "text" : "number"}
                value={valueAt(spec, path)}
                disabled={!canRun}
                onChange={(value) => updateField(path, type === "number" || type === "opt-number" ? (value === "" ? "" : Number(value)) : value)}
              />
            ))}
            <ParamField label="RPM" unit="rpm" type="number" value={rpm} disabled={!canRun} onChange={(v) => { setRpm(v); setPreview(null); }} />
            {physics === "single_phase" ? (
              <ParamField label="Kinematic viscosity" unit="m²/s" type="number" value={viscosity} disabled={!canRun} onChange={(v) => { setViscosity(v); setPreview(null); }} />
            ) : (
              <ParamField label="Gas flow" unit="vvm" type="number" value={gasVvm} disabled={!canRun} onChange={(v) => { setGasVvm(v); setPreview(null); }} />
            )}
          </div>

          <div className="row-end">
            <Button disabled={!canRun || previewing} onClick={generatePreview}>
              {previewing && <Spinner size={16} label="Generating preview" />}
              {!canRun ? "Read-only" : previewing ? "Generating…" : "Generate preview"}
            </Button>
          </div>
          {error && <div className="empty-state" style={{ fontStyle: "normal" }}>ERROR: {error}</div>}
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
                {invalidProject && <div className="empty-state" style={{ fontStyle: "normal" }}>{invalidProject}</div>}
              </div>
              <div className="row-end">
                <Button disabled={!canRun || Boolean(invalidProject) || creating} onClick={createCase}>
                  {creating && <Spinner size={16} label="Creating case" />}
                  {!canRun ? "Read-only" : creating ? "Creating…" : "Create case"}
                </Button>
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

function ParamField({ label, unit, type, value, disabled, onChange }: {
  label: string;
  unit: string;
  type: "number" | "text";
  value: unknown;
  disabled: boolean;
  onChange: (value: string) => void;
}) {
  return (
    <label className="field">
      <span className="lbl"><span>{label}</span>{unit && <span>{unit}</span>}</span>
      <input className="input w-full" type={type} step={type === "number" ? "any" : undefined} value={String(value ?? "")} disabled={disabled} onChange={(event) => onChange(event.target.value)} />
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
