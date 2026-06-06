def results_prefix(project: str, codename: str, case_id: str) -> str:
    """Bucket-relative prefix for one case's results. MIRROR of the runtime's
    RESULT_PREFIX in runtime/run_case_in_batch.sh - if one changes, change both."""
    return f"results/{project}/{codename}/{case_id}/"
