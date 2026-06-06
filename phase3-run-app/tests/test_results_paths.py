from core.results_paths import results_prefix


def test_results_prefix():
    assert (
        results_prefix("turbine", "phoenix", "case_0006")
        == "results/turbine/phoenix/case_0006/"
    )
