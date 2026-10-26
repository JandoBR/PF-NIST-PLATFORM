"""Login y aislamiento por organizacion (doc 10). Usa `anon_client` (sin `get_current_user`
sobreescrito) para ejercitar el token real."""

from tests.conftest import TEST_ORG_NAME, TEST_PASSWORD, TEST_USERNAME


def _login(client, password: str = TEST_PASSWORD) -> str:
    response = client.post("/auth/login", json={"username": TEST_USERNAME, "password": password})
    assert response.status_code == 200
    return response.json()["token"]


def test_protected_route_without_token_is_401(anon_client):
    assert anon_client.get("/assessments").status_code == 401


def test_login_with_valid_credentials_returns_token(anon_client, auth_user):
    response = anon_client.post(
        "/auth/login", json={"username": TEST_USERNAME, "password": TEST_PASSWORD}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["token"]
    assert body["user"]["username"] == TEST_USERNAME
    assert body["user"]["org_nombre"] == TEST_ORG_NAME


def test_login_with_wrong_password_is_401(anon_client, auth_user):
    response = anon_client.post(
        "/auth/login", json={"username": TEST_USERNAME, "password": "incorrecta"}
    )
    assert response.status_code == 401


def test_login_unknown_user_is_401(anon_client):
    response = anon_client.post("/auth/login", json={"username": "fantasma", "password": "x"})
    assert response.status_code == 401


def test_valid_token_grants_access(anon_client, auth_user):
    token = _login(anon_client)
    response = anon_client.get("/assessments", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    assert response.json() == []


def test_me_returns_current_user(anon_client, auth_user):
    token = _login(anon_client)
    response = anon_client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    assert response.json()["org_id"] == auth_user.org_id


def test_invalid_token_is_401(anon_client):
    response = anon_client.get("/assessments", headers={"Authorization": "Bearer token-invalido"})
    assert response.status_code == 401


def test_unknown_user_still_runs_the_password_hash(anon_client, monkeypatch):
    """Un usuario inexistente no puede responder mas rapido (enumeracion por tiempo)."""

    from app.core import auth

    llamadas = []

    def espia(password, salt, expected):
        llamadas.append((password, salt, expected))
        return False

    monkeypatch.setattr(auth, "verify_password", espia)

    response = anon_client.post("/auth/login", json={"username": "fantasma", "password": "x"})

    assert response.status_code == 401
    assert len(llamadas) == 1


def test_non_ascii_signature_is_rejected_not_500():
    from app.core import auth

    assert auth.decode_token("cuerpo.firma-ñ") is None


def test_token_with_a_malformed_payload_is_rejected():
    import json

    from app.core import auth

    for payload in (
        {"sub": "u1", "exp": "no-es-numero"},
        {"sub": ["u1"], "exp": 9_999_999_999},
        {"sub": "u1", "exp": 9_999_999_999, "org": ["o1"]},
    ):
        body = auth._b64url(json.dumps(payload).encode())
        assert auth.decode_token(f"{body}.{auth._sign(body)}") is None
