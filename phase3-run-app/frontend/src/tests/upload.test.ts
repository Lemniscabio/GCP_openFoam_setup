import { describe, it, expect, vi } from "vitest";
import { ApiClient } from "../lib/api";
import { runPool } from "../lib/upload";

describe("runPool", () => {
  it("runs all tasks with bounded concurrency", async () => {
    let active = 0;
    let maxActive = 0;
    const tasks = Array.from({ length: 20 }, (_, i) => async () => {
      active++;
      maxActive = Math.max(maxActive, active);
      await new Promise((r) => setTimeout(r, 1));
      active--;
      return i;
    });
    const res = await runPool(tasks, 5);
    expect(res.length).toBe(20);
    expect(new Set(res).size).toBe(20);
    expect(maxActive).toBeLessThanOrEqual(5);
  });

  it("retries a failing task then succeeds", async () => {
    let n = 0;
    const t = async () => {
      if (n++ < 2) throw new Error("x");
      return "ok";
    };
    const res = await runPool([t], 1, 3);
    expect(res[0]).toBe("ok");
  });

  it("throws if a task keeps failing past retries", async () => {
    const t = async () => {
      throw new Error("always");
    };
    await expect(runPool([t], 1, 2)).rejects.toThrow("always");
  });

  it("sends the case name on finalize", async () => {
    const fetchMock = vi.fn(
      async () => new Response(JSON.stringify({ case_id: "case_0006", ready: true }), { status: 200 }),
    );
    const api = new ApiClient("", () => null, fetchMock as unknown as typeof fetch);

    await api.finalize("case_0006", { name: "Wind Tunnel v3", openfoam_version: "12" });

    const init = (fetchMock.mock.calls[0] as unknown as [string, RequestInit])[1];
    expect(JSON.parse(init.body as string).name).toBe("Wind Tunnel v3");
  });
});
