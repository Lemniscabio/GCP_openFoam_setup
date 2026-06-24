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
  it("returns null after clear", () => {
    const s = new TokenStore();
    s.set("idtok", Date.now() + 3600_000);
    s.clear();
    expect(s.get()).toBeNull();
  });
  it("follows the Google token's own expiry (no artificial cap)", () => {
    const s = new TokenStore();
    const googleExp = Date.now() + 3600_000; // 1h google exp
    s.set("idtok", googleExp, "a@lemnisca.bio");
    expect(s.get()).toBe("idtok");
    expect(s.expiresAt()).toBe(googleExp);
  });
});
