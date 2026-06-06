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
});
