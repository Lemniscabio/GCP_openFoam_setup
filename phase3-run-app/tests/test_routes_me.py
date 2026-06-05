def test_me_returns_role_and_status(client):
    r = client.get("/api/me")
    assert r.status_code == 200
    body = r.json()
    assert body["email"] == "dev@lemnisca.bio"
    assert body["role"] == "admin"
    assert body["status"] == "active"
