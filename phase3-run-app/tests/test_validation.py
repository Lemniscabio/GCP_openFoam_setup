from core.storage import InMemoryStorage
from core.validation import validate_case

def _seed_valid(s):
    s.upload_bytes("cases/case_0001/case/system/controlDict", b"x")
    s.upload_bytes("cases/case_0001/command.sh", b"mpirun -np ${MPI_RANKS} foamRun -parallel")
    s.upload_bytes("cases/case_0001/manifest.json", b'{"case_id":"case_0001"}')
    s.upload_bytes("cases/case_0001/READY", b"2026-06-01")

def test_valid_case_passes():
    s = InMemoryStorage(); _seed_valid(s)
    result = validate_case(s, "case_0001")
    assert result.ok is True and result.errors == []

def test_missing_ready_fails():
    s = InMemoryStorage(); _seed_valid(s)
    s._objs.pop("cases/case_0001/READY")
    result = validate_case(s, "case_0001")
    assert result.ok is False
    assert any("READY" in e for e in result.errors)

def test_command_without_mpi_ranks_warns():
    s = InMemoryStorage(); _seed_valid(s)
    s.upload_bytes("cases/case_0001/command.sh", b"mpirun -np 8 foamRun -parallel")
    result = validate_case(s, "case_0001")
    assert result.ok is True
    assert any("MPI_RANKS" in w for w in result.warnings)
