import { useEffect, useState } from "react";
import { motion } from "framer-motion";
import { StlViewer } from "@/components/StlViewer";
import { Spinner } from "@/components/ui/Spinner";
import { Toast } from "@/components/ui/Toast";
import { Button } from "@/components/ui/button";
import { usePanelVariants } from "@/lib/motion";
import { api, type ProjectInfo } from "../lib/client";

type JsonObject = Record<string, any>;
type Preview = { str_params: JsonObject; case_params: JsonObject; stls: Record<string, string> };

const STR_FIELDS = [
  ["tank.diameter_m", "Tank diameter", "m", "number"],
  ["tank.height_m", "Tank height", "m", "number"],
  ["liquid.height_m", "Liquid height", "m", "number"],
  ["baffles.count", "Baffle count", "", "number"],
  ["baffles.width_m", "Baffle width", "m", "number"],
  ["baffles.height_m", "Baffle height", "m", "number"],
  ["impellers.count", "Impeller count", "", "number"],
  ["impellers.type", "Impeller type", "", "text"],
  ["impellers.blades", "Blades per impeller", "", "number"],
  ["impellers.diameter_ratio", "Diameter ratio", "D", "number"],
  ["impellers.blade_length_m", "Blade length", "m", "number"],
  ["impellers.blade_height_m", "Blade height", "m", "number"],
  ["impellers.lowest_clearance_m", "Lowest clearance", "m", "number"],
  ["impellers.inter_impeller_clearance_m", "Inter-impeller clearance", "m", "number"],
] as const;

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

function withValue(source: JsonObject, path: string, value: string, numeric: boolean) {
  const keys = path.split(".");
  const root = structuredClone(source);
  let target = root;
  keys.slice(0, -1).forEach((key) => {
    target[key] = { ...target[key] };
    target = target[key];
  });
  target[keys[keys.length - 1]] = numeric ? Number(value) : value;
  return root;
}

export function GenerateView({
  canRun,
  onCreated,
}: {
  canRun: boolean;
  onCreated: (project: string, caseIds: string[]) => void;
}) {
  const [prompt, setPrompt] = useState("");
  const [preview, setPreview] = useState<Preview | null>(null);
  const [strParams, setStrParams] = useState<JsonObject>({});
  const [caseParams, setCaseParams] = useState<JsonObject>({});
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

  async function generatePreview() {
    if (!canRun || !prompt.trim() || previewing) return;
    setPreviewing(true);
    setError(null);
    try {
      const result = await api.generatePreview({ prompt: prompt.trim() });
      setPreview(result);
      setStrParams(structuredClone(result.str_params));
      setCaseParams(structuredClone(result.case_params));
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
        params: strParams,
        case_params: caseParams,
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

  function updateStrParam(path: string, value: string, numeric: boolean) {
    setStrParams((current) => withValue(current, path, value, numeric));
  }

  function updateCaseParam(path: string, value: string) {
    setCaseParams((current) => withValue(current, path, value, true));
  }

  return (
    <motion.div className="step" style={{ gridTemplateColumns: "1fr" }} initial="hidden" animate="visible" exit="exit" variants={panelVariants}>
      <div className="panel">
        <div className="panel-head">
          <div className="ph-num">01</div>
          <div className="ph-text">
            <div className="ph-title">Generate a stirred-tank case</div>
            <div className="ph-sub">Describe the reactor, review the generated geometry and parameters, then create the case.</div>
          </div>
        </div>
        <div className="panel-body">
          {!canRun && <div className="empty-state" style={{ fontStyle: "normal" }}>Your viewer role is read-only. Generation and case creation are disabled.</div>}
          <div className="field w-full">
            <label className="lbl" htmlFor="generate-prompt"><span>Reactor prompt</span></label>
            <textarea
              id="generate-prompt"
              className="input w-full min-h-28 resize-y"
              value={prompt}
              onChange={(event) => setPrompt(event.target.value)}
              placeholder="Describe the stirred-tank reactor…"
              disabled={!canRun || previewing}
            />
          </div>
          <div className="row-end">
            <Button disabled={!canRun || !prompt.trim() || previewing} onClick={generatePreview}>
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
                <div className="ph-sub">Drag to orbit, scroll to zoom, and right-drag to pan.</div>
              </div>
            </div>
            <div className="panel-body"><StlViewer stls={preview.stls} /></div>
          </div>

          <div className="panel">
            <div className="panel-head">
              <div className="ph-num">02</div>
              <div className="ph-text">
                <div className="ph-title">Resolved parameters</div>
                <div className="ph-sub">Edits below are used directly when the case is created.</div>
              </div>
            </div>
            <div className="panel-body">
              <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
                {STR_FIELDS.map(([path, label, unit, type]) => (
                  <ParamField
                    key={path}
                    label={label}
                    unit={unit}
                    type={type}
                    value={valueAt(strParams, path)}
                    disabled={!canRun}
                    onChange={(value) => updateStrParam(path, value, type === "number")}
                  />
                ))}
                <ParamField label="RPM" unit="rpm" type="number" value={caseParams.rpm} disabled={!canRun} onChange={(value) => updateCaseParam("rpm", value)} />
                <ParamField label="Kinematic viscosity" unit="m²/s" type="number" value={caseParams.viscosity_m2_s} disabled={!canRun} onChange={(value) => updateCaseParam("viscosity_m2_s", value)} />
              </div>

              <details className="rounded-xl border border-black/10 bg-black/[0.025] p-4">
                <summary className="cursor-pointer text-sm font-semibold text-[var(--ink)]">Case config</summary>
                <div className="mt-3 grid grid-cols-2 gap-3 text-xs text-[var(--ink-2)] md:grid-cols-4">
                  <ConfigValue label="RPM" value={String(caseParams.rpm ?? "—")} />
                  <ConfigValue label="Viscosity" value={`${caseParams.viscosity_m2_s ?? "—"} m²/s`} />
                  <ConfigValue label="Turbulence" value="kEpsilon" />
                  <ConfigValue label="Solver" value="incompressibleFluid" />
                </div>
              </details>

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

function ConfigValue({ label, value }: { label: string; value: string }) {
  return <div><div className="font-semibold text-[var(--ink)]">{label}</div><div className="mt-1 font-mono">{value}</div></div>;
}
