import datetime
import logging

from fastapi import APIRouter, Depends, HTTPException

from backend.auth import User, current_user
from backend.deps import builder, case_record_repo, run_repo, status_service, storage, submitter
from backend.schemas import SubmitReq
from core.config import Settings
from core.machines import MachineCatalog
from core.naming import build_job_name, canonical_case_id
from core.run_repo import RunRecord
from core.validation import validate_case

router = APIRouter()


@router.post("/jobs")
def submit(
    req: SubmitReq,
    user: User = Depends(current_user),
    b=Depends(builder),
    store=Depends(storage),
    records=Depends(case_record_repo),
    runs=Depends(run_repo),
    sub=Depends(submitter),
):
    try:
        machine = MachineCatalog().get(req.machine_type)
    except KeyError:
        raise HTTPException(status_code=400, detail=f"unknown machine {req.machine_type}")

    case_ids = [canonical_case_id(case_id) for case_id in req.case_ids]
    errors = {}
    for case_id in case_ids:
        result = validate_case(store, case_id)
        if not result.ok:
            errors[case_id] = result.errors
    if errors:
        raise HTTPException(status_code=400, detail={"errors": errors})

    timestamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d%H%M%S")
    provisioning_model = "SPOT" if req.spot else "STANDARD"
    common = {
        "cpu_milli": machine["cpu_milli"],
        "memory_mib": machine["memory_mib"],
        "mpi_ranks": machine["default_mpi_ranks"],
        "provisioning_model": provisioning_model,
        "local_ssd_count": machine["local_ssd_count"],
    }

    if len(case_ids) == 1:
        job_name = build_job_name(case_ids[0], req.machine_type, timestamp)
        spec = b.build_single(
            case_id=case_ids[0],
            machine_type=req.machine_type,
            job_name=job_name,
            **common,
        )
    else:
        job_name = build_job_name(None, req.machine_type, timestamp, multi=True)
        spec = b.build_multi(
            case_ids=case_ids,
            machine_type=req.machine_type,
            job_name=job_name,
            **common,
        )

    name = sub.submit(job_name, spec)
    try:
        runs.create(
            RunRecord(
                batch_job_id=job_name,
                job_name=job_name,
                submitted_by=user.email,
                submitted_at=datetime.datetime.now(datetime.timezone.utc),
                region=Settings().region,
                machine_type=req.machine_type,
                mpi_ranks=machine["default_mpi_ranks"],
                spot=req.spot,
                case_ids=case_ids,
                case_names=records.names_for(case_ids),
            )
        )
    except Exception:
        logging.exception("failed to persist of_runs record for %s", job_name)
    return {"job_name": job_name, "batch_job_id": job_name, "name": name, "submitted_by": user.email}


@router.get("/jobs")
def list_runs(user: User = Depends(current_user), st=Depends(status_service)):
    return {"runs": [r.__dict__ for r in st.list_runs()]}


@router.get("/jobs/{job_name}")
def run_detail(
    job_name: str,
    case_id: str,
    variant: str,
    user: User = Depends(current_user),
    st=Depends(status_service),
):
    return st.get_status(job_name, case_id, variant)
