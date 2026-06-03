import { describe, it, expect } from "vitest";
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
});
