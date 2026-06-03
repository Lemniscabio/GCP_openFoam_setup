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
});
