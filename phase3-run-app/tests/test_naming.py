from core.naming import canonical_case_id, sanitize_job_part, variant_for_machine, build_job_name

def test_numeric_id_zero_padded():
    assert canonical_case_id("42") == "case_0042"

def test_already_canonical_passthrough():
    assert canonical_case_id("case_0042") == "case_0042"

def test_sanitize_lowercases_and_dashes():
    assert sanitize_job_part("C2D-Highcpu_56") == "c2d-highcpu-56"

def test_variant_is_machine_type():
    assert variant_for_machine("c2d-highcpu-56") == "c2d-highcpu-56"

def test_build_job_name_single():
    assert build_job_name("case_0042", "c2d-highcpu-56", "20260601120000") \
        == "of-case-0042-c2d-highcpu-56-20260601120000"

def test_build_job_name_multi():
    assert build_job_name(None, "c2d-highcpu-32", "20260601120000", multi=True) \
        == "of-multi-c2d-highcpu-32-20260601120000"
