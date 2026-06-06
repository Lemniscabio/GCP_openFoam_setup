import { describe, it, expect, vi } from "vitest";
import { ApiClient } from "../lib/api";

describe("ApiClient", () => {
  it("attaches bearer token and parses json", async () => {
    const fetchMock = vi.fn(
      async () => new Response(JSON.stringify({ cases: [] }), { status: 200 }),
    );
    const api = new ApiClient("", () => "tok-1", fetchMock as unknown as typeof fetch);
    await api.listCases();
    const init = (fetchMock.mock.calls[0] as unknown as [string, RequestInit])[1];
    expect((init.headers as Record<string, string>).Authorization).toBe("Bearer tok-1");
  });

  it("omits Authorization when no token", async () => {
    const fetchMock = vi.fn(async () => new Response("{}", { status: 200 }));
    const api = new ApiClient("", () => null, fetchMock as unknown as typeof fetch);
    await api.listCases();
    const init = (fetchMock.mock.calls[0] as unknown as [string, RequestInit])[1];
    expect((init.headers as Record<string, string>).Authorization).toBeUndefined();
  });

  it("throws on 401", async () => {
    const fetchMock = vi.fn(async () => new Response("{}", { status: 401 }));
    const api = new ApiClient("", () => null, fetchMock as unknown as typeof fetch);
    await expect(api.listCases()).rejects.toThrow();
  });

  it("getMe GETs /api/me and setUser POSTs the role/status", async () => {
    const calls: { url: string; method?: string; body?: BodyInit | null }[] = [];
    const fetchMock = vi.fn(async (url: RequestInfo | URL, init?: RequestInit) => {
      calls.push({ url: String(url), method: init?.method, body: init?.body });
      return new Response(JSON.stringify({ email: "x@lemnisca.bio", role: "viewer", status: "active" }), { status: 200 });
    });
    const api = new ApiClient("", () => "tok", fetchMock as unknown as typeof fetch);
    await api.getMe();
    await api.setUser("x@lemnisca.bio", { role: "runner", status: "active" });
    const me = calls.find((c) => c.url.includes("/api/me"));
    const set = calls.find((c) => c.url.includes("/api/admin/users/"));
    expect(me?.method).toBe("GET");
    expect(set?.method).toBe("POST");
    expect(JSON.parse(String(set?.body))).toEqual({ role: "runner", status: "active" });
  });

  it("submit sends job_name; suggestJobName GETs the suggest endpoint", async () => {
    const calls: { url: string; method?: string; body?: BodyInit | null }[] = [];
    const fetchMock = vi.fn(async (url: RequestInfo | URL, init?: RequestInit) => {
      calls.push({ url: String(url), method: init?.method, body: init?.body });
      return new Response(JSON.stringify({ name: "phoenix", job_name: "phoenix" }), { status: 200 });
    });
    const api = new ApiClient("", () => "tok", fetchMock as unknown as typeof fetch);
    await api.suggestJobName();
    await api.submit(["case_0006"], "c2d-highcpu-8", false, "phoenix");
    const suggest = calls.find((c) => c.url.includes("/api/job-name/suggest"));
    const submit = calls.find((c) => c.url.endsWith("/api/jobs") && c.method === "POST");
    expect(suggest?.method).toBe("GET");
    expect(JSON.parse(String(submit?.body)).job_name).toBe("phoenix");
  });

  it("v2 endpoints: project on allocate/finalize + new reads", async () => {
    const calls: { url: string; method?: string; body?: BodyInit | null }[] = [];
    globalThis.fetch = vi.fn(async (url: RequestInfo | URL, init?: RequestInit) => {
      calls.push({ url: String(url), method: init?.method, body: init?.body });
      return new Response(JSON.stringify({ ok: true }), { status: 200 });
    }) as unknown as typeof fetch;
    const { ApiClient: V2ApiClient } = await import("../lib/api");
    const api = new V2ApiClient("", () => "tok");
    await api.allocate("turbine", [{ files: ["0/U"] }]);
    await api.finalize("case_0006", { name: "WT", project: "turbine" });
    await api.getProjects();
    await api.getResults();
    await api.getResultFiles("turbine", "phoenix", "case_0006");
    await api.postDownloads(["results/turbine/phoenix/case_0006/result.tar.gz"]);
    await api.getMyRuns();
    await api.getCaseMetadata("turbine", "case_0006");
    const find = (fragment: string) => calls.find((call) => call.url.includes(fragment));
    expect(JSON.parse(String(find(":allocate")?.body)).project).toBe("turbine");
    expect(JSON.parse(String(find(":finalize")?.body)).project).toBe("turbine");
    expect(find("/api/projects")?.method).toBe("GET");
    expect(find("/api/results/files")?.url).toContain("project=turbine");
    expect(find("/api/results/downloads")?.method).toBe("POST");
    expect(find("/api/me/runs")?.method).toBe("GET");
    expect(find("/metadata")?.url).toContain("project=turbine");
  });
});
