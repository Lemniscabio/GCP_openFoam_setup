import re

def canonical_case_id(value: str) -> str:
    value = value.strip()
    if value.isdigit():
        return f"case_{int(value):04d}"
    return value

def sanitize_job_part(value: str) -> str:
    value = value.lower()
    value = re.sub(r"[^a-z0-9-]", "-", value)
    value = re.sub(r"-+", "-", value).strip("-")
    return value

def variant_for_machine(machine_type: str) -> str:
    return sanitize_job_part(machine_type)
