import { describe, expect, it } from "vitest";

import { missingRequiredFiles } from "../lib/casecheck";

describe("missingRequiredFiles", () => {
  it("flags cases missing command.sh or metadata.json", () => {
    const cases = [
      { name: "caseA", files: ["system/controlDict", "command.sh", "metadata.json"] },
      { name: "caseB", files: ["command.sh"] },
      { name: "caseC", files: ["0/U"] },
    ];
    expect(missingRequiredFiles(cases)).toEqual([
      { name: "caseB", missing: ["metadata.json"] },
      { name: "caseC", missing: ["command.sh", "metadata.json"] },
    ]);
  });

  it("returns [] when all good", () => {
    expect(
      missingRequiredFiles([{ name: "a", files: ["command.sh", "metadata.json"] }]),
    ).toEqual([]);
  });
});
