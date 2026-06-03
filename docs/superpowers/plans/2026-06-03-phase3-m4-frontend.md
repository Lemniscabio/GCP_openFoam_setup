# Phase 3 — M4: Frontend SPA — Implementation Plan

> **For agentic workers:** Driven via `codex exec`; use the **`designer`/frontend-design skill** for the visual components (port the `batch-launcher.html` aesthetic). Logic modules (auth, API client, upload pool) are testable with Vitest; views are built + manually verified. Orchestrator reviews between tasks.
>
> **Reference:** spec `docs/superpowers/specs/2026-06-01-phase3-run-app-design.md` §5; backend is live (`cfd-lemnisca`, Cloud Run `of-batch-app`, app-level Google auth). Existing prototype: `batch-launcher.html` (vanilla glassmorphism — reuse its CSS design tokens).

**Goal:** A static SPA — Google sign-in → drag-drop upload → browse cases → run on `c2d-highcpu-*` → watch runs — that talks to the live `/api/*` (Bearer Google ID token), built and **bundled into the backend image** so one Cloud Run service serves UI + API.

**Stack:** Vite + React + TypeScript; Vitest for the logic modules; Google Identity Services (GIS) for sign-in; CSS ported from `batch-launcher.html` (Manrope + JetBrains Mono, frosted-glass tokens). **Framework note:** React+Vite chosen for maintainability across the 3-phase product; the prototype's CSS ports as-is. (Vanilla-extend of `batch-launcher.html` is a faster but less-maintainable fallback if you prefer.)

**Auth model:** GIS gives a Google **ID token** for `OF_OAUTH_CLIENT_ID`; the API client attaches it as `Authorization: Bearer`. Backend already verifies it (`@lemnisca.bio`). Token kept in memory; re-prompt on expiry.

---

## File Structure
```
phase3-run-app/frontend/
  package.json  vite.config.ts  tsconfig.json  index.html
  src/
    main.tsx            # mount, sign-in gate
    styles.css          # ported batch-launcher.html design tokens + components
    lib/
      auth.ts           # GIS sign-in + ID-token access (Vitest)
      api.ts            # typed fetch client w/ Bearer (Vitest)
      upload.ts         # bounded-concurrency upload pool (Vitest)
    components/         # AppShell, Tabs, SignInGate, ...
    views/
      UploadView.tsx  CasesView.tsx  RunView.tsx  RunsView.tsx  RunDetailDrawer.tsx
    tests/ auth.test.ts api.test.ts upload.test.ts
phase3-run-app/backend/Dockerfile   # MODIFY → multi-stage (node build → copy dist into static)
```
Build output (`frontend/dist`) is copied into the image and served by FastAPI at `/`.

---

### Task 1: Scaffold Vite+React+TS + port the design system

- [ ] **Step 1:** `cd phase3-run-app && npm create vite@latest frontend -- --template react-ts`, then `cd frontend && npm install && npm install -D vitest`.
- [ ] **Step 2:** add to `package.json` scripts: `"test": "vitest run"`, `"build": "tsc -b && vite build"`.
- [ ] **Step 3:** Create `src/styles.css` by porting the `:root` design tokens + key component classes (`.panel`, `.tab`, `.drop`, `.segmented`, `.preset`, `.chip`, `.btn`, terminal footer) from `batch-launcher.html` (lines 10–828). Import the Manrope + JetBrains Mono Google Fonts. (Use the **designer skill** to adapt them into clean reusable classes.)
- [ ] **Step 4:** `npm run build` succeeds (produces `dist/`). Commit.

---

### Task 2: `lib/auth.ts` — Google sign-in + ID token

- [ ] **Step 1: failing test** (`src/tests/auth.test.ts`, Vitest) — pure token-store logic with an injected GIS stub:
```ts
import { describe, it, expect } from "vitest";
import { TokenStore } from "../lib/auth";
describe("TokenStore", () => {
  it("holds and returns the id token", () => {
    const s = new TokenStore();
    s.set("idtok-123", Date.now() + 3600_000);
    expect(s.get()).toBe("idtok-123");
  });
  it("returns null when expired", () => {
    const s = new TokenStore();
    s.set("idtok", Date.now() - 1000);
    expect(s.get()).toBeNull();
  });
});
```
- [ ] **Step 2: run → fail** `cd phase3-run-app/frontend && npx vitest run`.
- [ ] **Step 3: implement `src/lib/auth.ts`**
```ts
// src/lib/auth.ts
export class TokenStore {
  private token: string | null = null;
  private expMs = 0;
  set(token: string, expMs: number) { this.token = token; this.expMs = expMs; }
  get(): string | null { return this.token && Date.now() < this.expMs ? this.token : null; }
  clear() { this.token = null; this.expMs = 0; }
}
export const tokenStore = new TokenStore();

// GIS init (browser only). clientId = import.meta.env.VITE_OAUTH_CLIENT_ID
export function initGoogleSignIn(clientId: string, onSignedIn: (email: string) => void) {
  // @ts-expect-error google injected by GIS script
  google.accounts.id.initialize({
    client_id: clientId,
    callback: (resp: { credential: string }) => {
      const claims = JSON.parse(atob(resp.credential.split(".")[1]));
      tokenStore.set(resp.credential, (claims.exp ?? 0) * 1000);
      onSignedIn(claims.email);
    },
  });
  // @ts-expect-error
  google.accounts.id.prompt();
}
```
- [ ] **Step 4: run → pass.** Commit.
(The GIS `<script src="https://accounts.google.com/gsi/client" async>` goes in `index.html`. `VITE_OAUTH_CLIENT_ID` is baked at build time — set in the Dockerfile build arg = the client id.)

---

### Task 3: `lib/api.ts` — typed client with Bearer

- [ ] **Step 1: failing test** (inject a fake fetch + token getter):
```ts
import { describe, it, expect, vi } from "vitest";
import { ApiClient } from "../lib/api";
it("attaches bearer token and parses json", async () => {
  const fetchMock = vi.fn(async () => new Response(JSON.stringify({cases: []}), {status: 200}));
  const api = new ApiClient("", () => "tok-1", fetchMock as any);
  await api.listCases();
  const [, init] = fetchMock.mock.calls[0];
  expect((init.headers as any).Authorization).toBe("Bearer tok-1");
});
it("throws on 401", async () => {
  const fetchMock = vi.fn(async () => new Response("{}", {status: 401}));
  const api = new ApiClient("", () => null, fetchMock as any);
  await expect(api.listCases()).rejects.toThrow();
});
```
- [ ] **Step 2: fail → 3: implement `src/lib/api.ts`**
```ts
// src/lib/api.ts
export type CaseInfo = { case_id: string; ready: boolean };
export type RunSummary = { job_name: string; state: string; progress_pct: number | null };

export class ApiClient {
  constructor(private base: string, private token: () => string | null,
              private f: typeof fetch = fetch) {}
  private async req(method: string, path: string, body?: unknown) {
    const t = this.token();
    const r = await this.f(`${this.base}${path}`, {
      method,
      headers: { "Content-Type": "application/json", ...(t ? { Authorization: `Bearer ${t}` } : {}) },
      body: body ? JSON.stringify(body) : undefined,
    });
    if (!r.ok) throw new Error(`${method} ${path} -> ${r.status}`);
    return r.status === 204 ? null : r.json();
  }
  allocate(cases: { files: string[] }[]) { return this.req("POST", "/api/cases:allocate", { cases }); }
  finalize(caseId: string) { return this.req("POST", `/api/cases/${caseId}:finalize`, { openfoam_version: "12" }); }
  listCases(): Promise<{ cases: CaseInfo[] }> { return this.req("GET", "/api/cases"); }
  submit(case_ids: string[], machine_type: string, spot: boolean) {
    return this.req("POST", "/api/jobs", { case_ids, machine_type, spot });
  }
  listRuns(): Promise<{ runs: RunSummary[] }> { return this.req("GET", "/api/jobs"); }
  runDetail(job: string, caseId: string, variant: string) {
    return this.req("GET", `/api/jobs/${job}?case_id=${caseId}&variant=${variant}`);
  }
}
```
- [ ] **Step 4: pass.** Commit.

---

### Task 4: `lib/upload.ts` — bounded-concurrency upload pool

- [ ] **Step 1: failing test** — N tasks, concurrency cap, all complete, retry on failure:
```ts
import { describe, it, expect, vi } from "vitest";
import { runPool } from "../lib/upload";
it("runs all tasks with bounded concurrency", async () => {
  let active = 0, maxActive = 0;
  const tasks = Array.from({length: 20}, (_,i) => async () => {
    active++; maxActive = Math.max(maxActive, active);
    await new Promise(r => setTimeout(r, 1)); active--; return i;
  });
  const res = await runPool(tasks, 5);
  expect(res.length).toBe(20);
  expect(maxActive).toBeLessThanOrEqual(5);
});
it("retries a failing task then succeeds", async () => {
  let n = 0;
  const t = async () => { if (n++ < 2) throw new Error("x"); return "ok"; };
  const res = await runPool([t], 1, 3);
  expect(res[0]).toBe("ok");
});
```
- [ ] **Step 2: fail → 3: implement `src/lib/upload.ts`**
```ts
// src/lib/upload.ts
export async function runPool<T>(tasks: Array<() => Promise<T>>, concurrency = 10, retries = 3): Promise<T[]> {
  const results: T[] = new Array(tasks.length);
  let next = 0;
  async function worker() {
    while (next < tasks.length) {
      const i = next++;
      let attempt = 0;
      for (;;) {
        try { results[i] = await tasks[i](); break; }
        catch (e) { if (++attempt >= retries) throw e; await new Promise(r => setTimeout(r, 300 * attempt)); }
      }
    }
  }
  await Promise.all(Array.from({ length: Math.min(concurrency, tasks.length) }, worker));
  return results;
}

// Upload one file to its signed PUT URL.
export async function putFile(url: string, file: File, f: typeof fetch = fetch): Promise<void> {
  const r = await f(url, { method: "PUT", body: file });
  if (!r.ok) throw new Error(`PUT ${r.status}`);
}
```
- [ ] **Step 4: pass.** Commit.
(Drag-drop folder walk via `webkitGetAsEntry`/`webkitdirectory` builds the `File[]` + relative paths; the Upload view flattens all cases' files into `runPool` tasks of `putFile(signedUrl, file)`, then calls `finalize` per case once its files succeed.)

---

### Task 5: App shell + Sign-in gate + Upload view

- [ ] Build `SignInGate` (shows Google button until `tokenStore.get()` is non-null), `AppShell` (header + `Upload · Cases · Run · Runs` tabs, frosted-glass styling), and `UploadView`:
  - drag-drop (bulk folder or single) → collect `{caseName, files:[{relPath, File}]}`
  - `api.allocate(cases.map(c => ({files: c.files.map(f=>f.relPath)})))` → per-case `uploads[]`
  - flatten to `runPool` of `putFile(upload.url, file)` (concurrency ~10) with per-case + overall progress bars
  - on each case's files done → `api.finalize(caseId)`
  - the dark terminal footer shows a live activity log + "Copy equivalent CLI".
- [ ] Manual check: `npm run dev`, sign in, drag a test case, watch it upload + finalize. Commit.
**Use the designer skill** for this view's polish (port the prototype's drop-zone, queue rows, progress styling).

---

### Task 6: Cases view

- [ ] `CasesView`: `api.listCases()` → table (case_id, READY/incomplete), multi-select checkboxes, filter, "Run selected" → routes to RunView with the selection. Glass-table styling from the prototype. Commit.

---

### Task 7: Run view (machine picker + submit)

- [ ] `RunView`: selected case chips; machine picker = all `c2d-highcpu-*` (from a static catalog mirroring `core/config.MACHINE_CATALOG`); **Spot toggle** (off default); advanced (MPI ranks, disk); **suggested machine** panel (calls a future metrics endpoint, degrades gracefully — show "based on prior runs" or "no data yet"); single vs multi auto-decided by selection count. **Run** → `api.submit(...)` → toast + jump to Runs. Job-preview panel mirrors the prototype's right panel. Commit.

---

### Task 8: Runs view + detail drawer (polling)

- [ ] `RunsView`: `api.listRuns()` polled every ~4s → rows (job, state, progress %). Row → `RunDetailDrawer`: `api.runDetail()` → state, status-event timeline, sim-progress %, checkpoint freshness, failure summary; deep links to Cloud Console + Logging. No live log streaming (per design). Commit.

---

### Task 9: Multi-stage Docker build + deploy 0.3.0

- [ ] **Step 1:** rewrite `backend/Dockerfile` as multi-stage:
```dockerfile
# --- build frontend ---
FROM node:20-slim AS fe
WORKDIR /fe
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
ARG VITE_OAUTH_CLIENT_ID
ENV VITE_OAUTH_CLIENT_ID=$VITE_OAUTH_CLIENT_ID
RUN npm run build           # -> /fe/dist
# --- backend ---
FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml requirements-backend.txt ./
RUN pip install --no-cache-dir -e . && pip install --no-cache-dir -r requirements-backend.txt
COPY core ./core
COPY backend ./backend
COPY --from=fe /fe/dist ./backend/static    # built SPA replaces the placeholder
ENV PORT=8080
CMD ["sh","-c","uvicorn backend.main:app --host 0.0.0.0 --port ${PORT}"]
```
- [ ] **Step 2: build + push (amd64), passing the client id as a build arg** (single-line):
```
docker buildx build --platform linux/amd64 --build-arg VITE_OAUTH_CLIENT_ID=380489820300-4ja0tnm6p2em05qgpg5krtac6e0f155c.apps.googleusercontent.com -f phase3-run-app/backend/Dockerfile -t us-central1-docker.pkg.dev/cfd-lemnisca/openfoam/of-backend:0.3.0 --push phase3-run-app
```
- [ ] **Step 3: deploy** (single-line):
```
gcloud run deploy of-batch-app --image us-central1-docker.pkg.dev/cfd-lemnisca/openfoam/of-backend:0.3.0 --region us-central1 --service-account of-batch-backend@cfd-lemnisca.iam.gserviceaccount.com --allow-unauthenticated --update-env-vars OF_OAUTH_CLIENT_ID=380489820300-4ja0tnm6p2em05qgpg5krtac6e0f155c.apps.googleusercontent.com,OF_ALLOWED_DOMAIN=lemnisca.bio --project cfd-lemnisca
```
- [ ] **Step 4: verify** — open the service URL as a `lemnisca.bio` account → Google sign-in → the real SPA → drag-drop a case → it uploads → run it → watch in Runs. `/health` → `{"ok":true}`.

---

## Self-Review
- Sign-in (GIS) → Bearer token on `/api/*` → Tasks 2,3,5. ✓
- Drag-drop → allocate (per-case file lists) → concurrent PUT → finalize → Tasks 4,5. ✓
- Cases / Run (c2d-highcpu only, Spot toggle, suggested) / Runs+detail (polling, no live logs) → Tasks 6,7,8. ✓
- batch-launcher.html aesthetic via ported tokens + designer skill → Tasks 1,5. ✓
- One Cloud Run service (SPA bundled into backend image) → Task 9. ✓
- Logic modules unit-tested (auth/api/upload); views manually verified. ✓
- `VITE_OAUTH_CLIENT_ID` baked at build; `OF_OAUTH_CLIENT_ID` on the backend — same value. ✓

## Hand-off
After M4: any `lemnisca.bio` member opens the URL, signs in, drag-drops cases, runs them, watches status — the original goal. Then: CI (the `.github/workflows/deploy.yml` already exists — point it at `0.x` tags and add the `--build-arg`), the suggested-machine metrics endpoint (needs Agent O metadata), and Phases 1–2.
