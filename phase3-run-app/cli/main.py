import datetime
import json
import subprocess

import click

from core.batch_jobs import BatchJobBuilder, BatchSubmitter
from core.cases import CaseRepository
from core.codenames import is_valid_codename, suggest_unused
from core.config import Settings
from core.machines import MachineCatalog
from core.naming import canonical_case_id
from core.storage import GcsStorage
from core.validation import validate_case


@click.group()
@click.pass_context
def cli(ctx):
    ctx.obj = Settings()


@cli.command(name="list")
@click.pass_obj
def list_cases(settings: Settings):
    """List all cases in the bucket."""
    repo = CaseRepository(GcsStorage(settings.bucket))
    for c in repo.list_cases():
        click.echo(f"{c.case_id}\t{'READY' if c.ready else 'incomplete'}")


@cli.command()
@click.argument("case_id")
@click.pass_obj
def validate(settings: Settings, case_id: str):
    """Validate an uploaded case (replaces check_case_prefix.sh)."""
    result = validate_case(GcsStorage(settings.bucket), case_id)
    for e in result.errors:
        click.echo(f"FAIL: {e}", err=True)
    for w in result.warnings:
        click.echo(f"WARN: {w}", err=True)
    if not result.ok:
        raise SystemExit(1)
    click.echo(f"OK: {case_id}")


@cli.command()
@click.option("--case-dir", required=True, type=click.Path(exists=True, file_okay=False))
@click.option("--command-sh", required=True, type=click.Path(exists=True, dir_okay=False))
@click.option("--case-id", default="AUTO", help="explicit id or AUTO")
@click.option("--openfoam-version", default="12")
@click.pass_obj
def upload(settings: Settings, case_dir, command_sh, case_id, openfoam_version):
    """Upload a local case as a file tree (no tar)."""
    storage = GcsStorage(settings.bucket)
    repo = CaseRepository(storage)
    cid = repo.allocate_ids(1)[0] if case_id.upper() == "AUTO" else canonical_case_id(case_id)
    base = f"gs://{settings.bucket}/cases/{cid}"
    # rsync the case tree (no tarring)
    subprocess.run(["gcloud", "storage", "rsync", "--recursive", case_dir, f"{base}/case/"], check=True)
    subprocess.run(["gcloud", "storage", "cp", command_sh, f"{base}/case/command.sh"], check=True)
    manifest = json.dumps({
        "case_id": cid, "solver_family": "openfoam", "openfoam_version": openfoam_version,
        "uploaded_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat() + "Z",
    })
    storage.upload_bytes(f"cases/{cid}/manifest.json", manifest.encode())
    storage.upload_bytes(f"cases/{cid}/READY", (datetime.datetime.now(datetime.timezone.utc).isoformat() + "Z").encode())
    click.echo(f"Uploaded {cid} to {base}")


@cli.command()
@click.option("--case", "cases", multiple=True, required=True, help="case id (repeatable)")
@click.option("--machine", required=True)
@click.option("--spot/--standard", default=False)
@click.option("--job-name", default=None, help="one-word codename (auto if omitted)")
@click.pass_obj
def run(settings: Settings, cases, machine, spot, job_name):
    """Submit a single-task (1 case) or multi-task (N cases) Batch job."""
    spec_machine = MachineCatalog().get(machine)
    prov = "SPOT" if spot else "STANDARD"
    ids = [canonical_case_id(c) for c in cases]
    job_name = (job_name or suggest_unused(set())).strip().lower()
    if not is_valid_codename(job_name):
        click.echo(f"invalid --job-name {job_name!r}", err=True)
        raise SystemExit(2)
    storage = GcsStorage(settings.bucket)
    errors = {}
    for case_id in ids:
        result = validate_case(storage, case_id)
        if not result.ok:
            errors[case_id] = result.errors
    if errors:
        for case_id, case_errors in errors.items():
            for error in case_errors:
                click.echo(f"FAIL {case_id}: {error}", err=True)
        raise SystemExit(1)

    builder = BatchJobBuilder(bucket=settings.bucket, image_uri=settings.image_uri)
    submitter = BatchSubmitter(settings.project_id, settings.region)
    common = dict(cpu_milli=spec_machine["cpu_milli"], memory_mib=spec_machine["memory_mib"],
                  mpi_ranks=spec_machine["default_mpi_ranks"], provisioning_model=prov,
                  local_ssd_count=spec_machine["local_ssd_count"])
    if len(ids) == 1:
        spec = builder.build_single(case_id=ids[0], machine_type=machine, job_name=job_name, **common)
    else:
        spec = builder.build_multi(case_ids=ids, machine_type=machine, job_name=job_name, **common)
    name = submitter.submit(job_name, spec)
    click.echo(f"Submitted {name}")
