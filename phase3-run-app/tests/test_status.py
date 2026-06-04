from core.status import sim_progress_pct, parse_checkpoint_latest_timestep


def test_progress_pct():
    assert sim_progress_pct(latest_time=5.4, end_time=10.0) == 54
    assert sim_progress_pct(latest_time=0.0, end_time=10.0) == 0
    assert sim_progress_pct(latest_time=5.4, end_time=0.0) is None  # unknown endTime


def test_parse_latest_timestep_from_checkpoint_listing():
    paths = [
        "checkpoints/case_0001/c2d-highcpu-2/latest/processor0/5.4/p",
        "checkpoints/case_0001/c2d-highcpu-2/latest/processor0/2.0/p",
    ]
    assert parse_checkpoint_latest_timestep(paths) == 5.4
