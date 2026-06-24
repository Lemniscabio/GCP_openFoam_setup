from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable


Runner = Callable[[list[str]], str]
LogFetcher = Callable[[str, str], str]


@dataclass
class SmokeResult:
    meshed: bool
    fields_read: bool
    time_advanced: bool
    exit_ok: bool
    errors: list[str]
    case_id: str | None = None
    job_name: str | None = None
    raw_markers: dict | None = None

    @property
    def ok(self) -> bool:
        return (
            self.meshed
            and self.fields_read
            and self.time_advanced
            and self.exit_ok
            and not self.errors
        )


def parse_smoke_log(text: str) -> SmokeResult:
    meshed = "End" in text and (
        "Finished meshing" in text
        or "Finalising parallel run" in text
        or "Mesh Information" in text
    )
    fields_read = any(
        marker in text
        for marker in ("Create mesh", "Reading field", "Selecting ", "Constructing")
    )
    time_steps = len(re.findall(r"(?m)^Time = ", text))
    time_advanced = time_steps > 0

    fatal_snippet = _fatal_snippet(text)
    exit_ok = fatal_snippet is None
    errors = [] if fatal_snippet is None else [fatal_snippet]

    raw_markers = {
        "meshed": meshed,
        "fields_read": fields_read,
        "time_advanced": time_advanced,
        "exit_ok": exit_ok,
        "time_steps": time_steps,
    }
    if fatal_snippet is not None:
        raw_markers["fatal_snippet"] = fatal_snippet

    return SmokeResult(
        meshed=meshed,
        fields_read=fields_read,
        time_advanced=time_advanced,
        exit_ok=exit_ok,
        errors=errors,
        raw_markers=raw_markers,
    )


def submit_smoke(
    case_dir,
    project: str = "cfd-lemnisca",
    machine: str = "c2d-highcpu-8",
    *,
    runner: Runner | None = None,
    log_fetcher: LogFetcher | None = None,
) -> SmokeResult:
    case_path = Path(case_dir)
    run = runner or _default_runner
    fetch_logs = log_fetcher or _default_log_fetcher

    upload_stdout = run(
        [
            "of",
            "upload",
            "--case-dir",
            str(case_path),
            "--command-sh",
            str(case_path / "command.sh"),
            "--case-id",
            "AUTO",
            "--openfoam-version",
            "12",
            "--project",
            project,
        ]
    )
    case_id = _parse_uploaded_case_id(upload_stdout)

    run_stdout = run(
        [
            "of",
            "run",
            "--case",
            case_id,
            "--machine",
            machine,
            "--project",
            project,
        ]
    )
    job_name = _parse_submitted_job_name(run_stdout)

    result = parse_smoke_log(fetch_logs(project, case_id))
    result.case_id = case_id
    result.job_name = job_name
    return result


def _default_runner(args: list[str]) -> str:
    return subprocess.run(
        args,
        capture_output=True,
        text=True,
        check=True,
    ).stdout


def _default_log_fetcher(project: str, case_id: str) -> str:
    bucket = f"{project}-cases"
    uri = f"gs://{bucket}/results/{project}/*/{case_id}/**.log"
    return _default_runner(["gcloud", "storage", "cat", uri])


def _parse_uploaded_case_id(stdout: str) -> str:
    match = re.search(r"(?m)^Uploaded\s+(\S+)\s+to\b", stdout)
    if not match:
        raise ValueError("could not parse uploaded case id from of upload output")
    return match.group(1)


def _parse_submitted_job_name(stdout: str) -> str:
    match = re.search(r"(?m)^Submitted\s+(\S+)", stdout)
    if not match:
        raise ValueError("could not parse job name from of run output")
    return match.group(1).rstrip("/").split("/")[-1]


def _fatal_snippet(text: str) -> str | None:
    lines = text.splitlines()
    for idx, line in enumerate(lines):
        if "FOAM FATAL ERROR" in line or "FOAM FATAL IO ERROR" in line:
            return "\n".join(lines[idx : idx + 4])
    return None
