from core.machines import MachineCatalog, Recommender

def test_lookup_returns_specs():
    m = MachineCatalog().get("c2d-highcpu-56")
    assert m["vcpus"] == 56 and m["cpu_milli"] == 56000 and m["memory_mib"] == 114688

def test_unknown_machine_raises():
    import pytest
    with pytest.raises(KeyError):
        MachineCatalog().get("n2-standard-4")

def test_recommender_returns_none_without_metrics():
    # metadata file (cells/size/volume) is delegated to Agent O; degrade gracefully
    assert Recommender().suggest(prior_runs=[]) is None

def test_recommender_picks_machine_of_largest_prior_run():
    prior = [{"machine_type": "c2d-highcpu-16"}, {"machine_type": "c2d-highcpu-56"}]
    assert Recommender().suggest(prior_runs=prior) == "c2d-highcpu-56"
