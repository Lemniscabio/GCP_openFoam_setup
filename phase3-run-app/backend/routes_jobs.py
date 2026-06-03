import datetime

from fastapi import APIRouter, Depends, HTTPException

from backend.deps import builder, status_service, submitter
from backend.iap import User, current_user
from backend.schemas import SubmitReq
from core.machines import MachineCatalog
from core.naming import build_job_name, canonical_case_id

router = APIRouter()


@router.post("/jobs")
def submit(
    req: SubmitReq,
    user: User = Depends(current_user),
    b=Depends(builder),
    sub=Depends(submitter),
):
    try:
        machine = MachineCatalog().get(req.machine_type)
    except KeyError:
        raise HTTPException(status_code=400, detail=f"unknown machine {req.machine_type}")

    case_ids = [canonical_case_id(case_id) for case_id in req.case_ids]
    timestamp = datetime.datetime.utcnow().strftime("%Y%m%d%H%M%S")
    provisioning_model = "SPOT" if req.spot else "STANDARD"
    common = {
        "cpu_milli": machine["cpu_milli"],
        "memory_mib": machine["memory_mib"],
        "mpi_ranks": machine["default_mpi_ranks"],
        "provisioning_model": provisioning_model,
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
    return {"job_name": job_name, "name": name, "submitted_by": user.email}


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
