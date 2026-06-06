const REQUIRED = ["command.sh", "metadata.json"];

export type CaseFiles = { name: string; files: string[] };
export type MissingReport = { name: string; missing: string[] };

export function missingRequiredFiles(cases: CaseFiles[]): MissingReport[] {
  const reports: MissingReport[] = [];
  for (const candidate of cases) {
    const basenames = new Set(candidate.files.map((file) => file.split("/").pop()));
    const missing = REQUIRED.filter((required) => !basenames.has(required));
    if (missing.length) {
      reports.push({ name: candidate.name, missing });
    }
  }
  return reports;
}
