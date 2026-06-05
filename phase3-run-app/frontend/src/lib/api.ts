// Typed API client. Attaches the Google ID token as a Bearer header.
export type CaseInfo = { case_id: string; ready: boolean };
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
    if (!r.ok) throw new Error(`${method} ${path} -> ${r.status}`);
    return r.status === 204 ? null : r.json();
  }

  allocate(cases: { files: string[] }[]) {
    return this.req("POST", "/api/cases:allocate", { cases });
  }
  finalize(caseId: string, body: { name?: string; openfoam_version?: string } = {}) {
    return this.req("POST", `/api/cases/${caseId}:finalize`, {
      openfoam_version: body.openfoam_version ?? "12",
      ...(body.name !== undefined ? { name: body.name } : {}),
    });
  }
  listCases(): Promise<{ cases: CaseInfo[] }> {
    return this.req("GET", "/api/cases");
  }
  submit(case_ids: string[], machine_type: string, spot: boolean) {
    return this.req("POST", "/api/jobs", { case_ids, machine_type, spot });
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
  listUsers(): Promise<{ users: ManagedUser[] }> {
    return this.req("GET", "/api/admin/users");
  }
  setUser(email: string, body: { role?: string; status?: string }): Promise<ManagedUser> {
    return this.req("POST", `/api/admin/users/${encodeURIComponent(email)}`, body);
  }
}
