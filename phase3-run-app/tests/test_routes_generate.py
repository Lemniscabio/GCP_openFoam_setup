import base64


GOLDEN_PARAMS = {
    "family": "stirred_tank_reactor",
    "tank": {"diameter_m": 2.09, "height_m": 9.6, "bottom": "dished"},
    "liquid": {"height_m": 6.55},
    "baffles": {
        "count": 4,
        "width_m": 0.167,
        "height_m": 7.5,
        "arrangement": "symmetric",
    },
    "shaft": {"central": True},
    "impellers": {
        "count": 4,
        "type": "rushton",
        "blades": 6,
        "diameter_ratio": 1 / 3,
        "blade_height_m": 0.14,
        "blade_length_m": 0.175,
        "lowest_clearance_m": 1.12,
        "inter_impeller_clearance_m": 1.46,
    },
}


def test_preview_from_params_returns_resolved_params_and_six_stls(client):
    response = client.post(
        "/api/generate/preview",
        json={"params": GOLDEN_PARAMS},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["str_params"]["tank"]["diameter_m"] == 2.09
    assert body["case_params"]["rpm"] == 90
    assert len(body["stls"]) == 6
    assert all(base64.b64decode(blob) for blob in body["stls"].values())


def test_create_commits_case_to_injected_repository(client, mem_case_records):
    response = client.post(
        "/api/generate/create",
        json={"project": "demo", "params": GOLDEN_PARAMS},
    )

    assert response.status_code == 200
    case_id = response.json()["case_id"]
    record = mem_case_records.get(case_id)
    assert record is not None
    assert record.project == "demo"
    assert record.uploaded_by == "dev@lemnisca.bio"


def test_chat_requires_a_model_key(client):
    from backend import deps
    client.app.dependency_overrides[deps.gemini_api_key] = lambda: None
    response = client.post("/api/generate/chat", json={"messages": [{"role": "user", "content": "hi"}]})
    assert response.status_code == 503


def test_chat_returns_reply_and_spec(client, monkeypatch):
    from backend import deps
    import backend.routes_generate as rg
    client.app.dependency_overrides[deps.gemini_api_key] = lambda: "test-key"
    monkeypatch.setattr(rg, "run_geometry_chat",
                        lambda messages, api_key: {"reply": "Building it.", "spec": GOLDEN_PARAMS})
    response = client.post(
        "/api/generate/chat",
        json={"messages": [{"role": "user", "content": "30kL dished tank"}]},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["reply"] == "Building it."
    assert body["spec"]["tank"]["diameter_m"] == 2.09


def test_preview_returns_editable_case_files(client):
    response = client.post("/api/generate/preview", json={"params": GOLDEN_PARAMS})
    assert response.status_code == 200
    files = response.json()["files"]
    assert "system/controlDict" in files
    assert "constant/MRFProperties" in files
    assert not any(key.startswith("constant/triSurface/") for key in files)


def test_create_applies_file_overlays(client):
    response = client.post(
        "/api/generate/create",
        json={
            "project": "demo",
            "params": GOLDEN_PARAMS,
            "files": {"system/controlDict": "EDITED BY TEST"},
        },
    )
    assert response.status_code == 200


def test_create_rejects_unknown_overlay_file(client):
    response = client.post(
        "/api/generate/create",
        json={
            "project": "demo",
            "params": GOLDEN_PARAMS,
            "files": {"system/doesNotExist": "x"},
        },
    )
    assert response.status_code == 400


def test_variations_creates_a_grid(client):
    response = client.post(
        "/api/generate/variations",
        json={"project": "demo", "params": GOLDEN_PARAMS, "axes": {"rpm": [50, 100]}},
    )
    assert response.status_code == 200
    assert len(response.json()["case_ids"]) == 2


def test_variations_rejects_no_axes(client):
    response = client.post(
        "/api/generate/variations",
        json={"project": "demo", "params": GOLDEN_PARAMS, "axes": {}},
    )
    assert response.status_code == 400


def test_preview_rejects_request_without_params(client):
    response = client.post("/api/generate/preview", json={})

    assert response.status_code == 400
