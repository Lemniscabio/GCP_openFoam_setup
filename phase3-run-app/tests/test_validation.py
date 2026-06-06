from core.storage import InMemoryStorage
from core.validation import validate_case

def _seed_valid(s):
    base = "cases/turbine/case_0001"
    s.upload_bytes(f"{base}/case/system/controlDict", b"x")
    s.upload_bytes(f"{base}/case/command.sh", b"mpirun -np ${MPI_RANKS} foamRun -parallel")
    s.upload_bytes(f"{base}/case/metadata.json", b'{"author":"k"}')
    s.upload_bytes(f"{base}/manifest.json", b'{"case_id":"case_0001"}')
    s.upload_bytes(f"{base}/READY", b"2026-06-01")

def test_valid_case_passes():
    s = InMemoryStorage(); _seed_valid(s)
    result = validate_case(s, "turbine", "case_0001")
    assert result.ok is True and result.errors == []

def test_missing_ready_fails():
    s = InMemoryStorage(); _seed_valid(s)
    s._objs.pop("cases/turbine/case_0001/READY")
    result = validate_case(s, "turbine", "case_0001")
    assert result.ok is False
    assert any("READY" in e for e in result.errors)

def test_command_without_mpi_ranks_warns():
    s = InMemoryStorage(); _seed_valid(s)
    s.upload_bytes("cases/turbine/case_0001/case/command.sh", b"mpirun -np 8 foamRun -parallel")
    result = validate_case(s, "turbine", "case_0001")
    assert result.ok is True
    assert any("MPI_RANKS" in w for w in result.warnings)


def test_validate_requires_metadata_json_valid():
    s = InMemoryStorage()
    base = "cases/turbine/case_0001"
    s.upload_bytes(f"{base}/manifest.json", b"{}")
    s.upload_bytes(f"{base}/READY", b"x")
    s.upload_bytes(f"{base}/case/command.sh", b"mpirun -np ${MPI_RANKS} foamRun -parallel")
    result = validate_case(s, "turbine", "case_0001")
    assert not result.ok and any("metadata.json" in error for error in result.errors)
    s.upload_bytes(f"{base}/case/metadata.json", b"not json")
    assert not validate_case(s, "turbine", "case_0001").ok
    s.upload_bytes(f"{base}/case/metadata.json", b'{"author":"k"}')
    assert validate_case(s, "turbine", "case_0001").ok
