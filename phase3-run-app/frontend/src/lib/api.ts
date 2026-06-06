// Typed API client. Attaches the Google ID token as a Bearer header.
export type CaseInfo = {
  case_id: string;
  name: string;
  project: string;
  uploaded_by: string;
  uploaded_at: string;
  ready: boolean;
};
export type ProjectInfo = { name: string; created_by: string; created_at: string };
export type ResultRun = {
  codename: string;
  project: string;
  state: string;
  case_ids: string[];
  case_names: string[];
  submitted_by: string;
  submitted_at: string;
};
export type ResultFile = { name: string; size: number };
export type DownloadLink = { object: string; url: string };
export type RunRecord = {
  batch_job_id: string;
  job_name: string;
  submitted_by: string;
  submitted_at: string;
  region: string;
  machine_type: string;
  mpi_ranks: number;
  spot: boolean;
  case_ids: string[];
  case_names: string[];
  state: string;
  finished_at: string | null;
  project: string;
};
export type RunSummary = { job_name: string; state: string; progress_pct: number | null };
export type Me = { email: string; role: string | null; status: string };
export type ManagedUser = { email: string; role: string | null; status: string; decided_by: string | null };

export class ApiClient {
  private base: string;
  private token: () => string | null;
  private f: typeof fetch;
  constructor(base: string, token: () => string | null, f: typeof fetch = fetch.bind(globalThis)) {
    this.base = base;
    this.token = token;
    this.f = f;
  }

  private async req(method: string, path: string, body?: unknown) {
    const t = this.token();
    const r = await this.f(`${this.base}${path}`, {
      method,
      headers: {
        "Content-Type": "application/json",
        ...(t ? { Authorization: `Bearer ${t}` } : {}),
      },
      body: body ? JSON.stringify(body) : undefined,
    });
    if (!r.ok) {
      let detail = "";
      try {
        const payload = await r.json();
        detail = typeof payload?.detail === "string" ? `: ${payload.detail}` : "";
      } catch {
        detail = "";
      }
      throw new Error(`${method} ${path} -> ${r.status}${detail}`);
    }
    return r.status === 204 ? null : r.json();
  }

  allocate(project: string, cases: { files: string[] }[]) {
    return this.req("POST", "/api/cases:allocate", { project, cases });
  }
  finalize(caseId: string, body: { name?: string; openfoam_version?: string; project: string }) {
    return this.req("POST", `/api/cases/${caseId}:finalize`, {
      openfoam_version: body.openfoam_version ?? "12",
      project: body.project,
      ...(body.name !== undefined ? { name: body.name } : {}),
    });
  }
  listCases(): Promise<{ cases: CaseInfo[] }> {
    return this.req("GET", "/api/cases");
  }
  submit(case_ids: string[], machine_type: string, spot: boolean, job_name: string) {
    return this.req("POST", "/api/jobs", { case_ids, machine_type, spot, job_name });
  }
  suggestJobName() {
    return this.req("GET", "/api/job-name/suggest");
  }
  listRuns(): Promise<{ runs: RunSummary[] }> {
    return this.req("GET", "/api/jobs");
  }
  runDetail(job: string, caseId: string, variant: string) {
    return this.req("GET", `/api/jobs/${job}?case_id=${caseId}&variant=${variant}`);
  }
  getMe(): Promise<Me> {
    return this.req("GET", "/api/me");
  }
  getProjects(): Promise<{ projects: ProjectInfo[] }> {
    return this.req("GET", "/api/projects");
  }
  getResults(): Promise<{ results: ResultRun[] }> {
    return this.req("GET", "/api/results");
  }
  getResultFiles(project: string, job: string, caseId: string): Promise<{ files: ResultFile[] }> {
    const query = new URLSearchParams({ project, job, case: caseId });
    return this.req("GET", `/api/results/files?${query}`);
  }
  postDownloads(objects: string[]): Promise<{ downloads: DownloadLink[]; missing: string[] }> {
    return this.req("POST", "/api/results/downloads", { objects });
  }
  getMyRuns(): Promise<{ runs: RunRecord[] }> {
    return this.req("GET", "/api/me/runs");
  }
  getAdminRuns(user?: string): Promise<{ runs: RunRecord[] }> {
    return this.req("GET", `/api/admin/runs${user ? `?user=${encodeURIComponent(user)}` : ""}`);
  }
  getCaseMetadata(project: string, caseId: string): Promise<{ metadata: unknown }> {
    const query = new URLSearchParams({ project });
    return this.req("GET", `/api/cases/${caseId}/metadata?${query}`);
  }
  listUsers(): Promise<{ users: ManagedUser[] }> {
    return this.req("GET", "/api/admin/users");
  }
  setUser(email: string, body: { role?: string; status?: string }): Promise<ManagedUser> {
    return this.req("POST", `/api/admin/users/${encodeURIComponent(email)}`, body);
  }
}
