"""Autenticacion (doc 10): hashing de contrasenas y tokens firmados stateless.

Sin dependencias nuevas: `hashlib.pbkdf2_hmac` y `hmac` de la stdlib alcanzan. El token es
`base64url(payload).base64url(HMAC-SHA256(payload))` con `{sub, org, exp}` -- stateless para no
depender de Redis ni de una tabla de sesiones, y para que `api`/workers compartan el mismo secreto
sin estado compartido.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
from datetime import UTC, datetime, timedelta

#: Default solo para el prototipo (demo). En un despliegue real, `SECRET_KEY` es obligatoria: quien
#: tenga el secreto puede firmar tokens validos.
DEFAULT_SECRET_KEY = "pf-dev-insecure-secret-change-me"
DEFAULT_TOKEN_TTL_HOURS = 72
_PBKDF2_ITERATIONS = 200_000


def secret_key() -> str:
    return os.environ.get("SECRET_KEY", DEFAULT_SECRET_KEY)


def token_ttl_hours() -> int:
    return int(os.environ.get("AUTH_TOKEN_TTL_HOURS", str(DEFAULT_TOKEN_TTL_HOURS)))


def hash_password(password: str, salt: str | None = None) -> tuple[str, str]:
    """Devuelve `(salt_hex, hash_hex)`. Nunca se guarda la contrasena en claro."""

    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode(), bytes.fromhex(salt), _PBKDF2_ITERATIONS
    )
    return salt, digest.hex()


def verify_password(password: str, salt: str, expected_hash: str) -> bool:
    _, candidate = hash_password(password, salt)
    return hmac.compare_digest(candidate, expected_hash)


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unb64url(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _sign(body: str) -> str:
    return _b64url(hmac.new(secret_key().encode(), body.encode(), hashlib.sha256).digest())


def create_token(user_id: str, org_id: str, *, ttl_hours: int | None = None) -> str:
    expires_at = datetime.now(UTC) + timedelta(hours=ttl_hours or token_ttl_hours())
    payload = {"sub": user_id, "org": org_id, "exp": int(expires_at.timestamp())}
    body = _b64url(json.dumps(payload, separators=(",", ":")).encode())
    return f"{body}.{_sign(body)}"


def decode_token(token: str) -> dict | None:
    """`{"sub", "org", "exp"}` si la firma es valida y no expiro; `None` en cualquier otro caso."""

    try:
        body, signature = token.split(".")
    except ValueError:
        return None
    try:
        if not hmac.compare_digest(signature, _sign(body)):
            return None
    except (TypeError, ValueError):
        # `compare_digest` no acepta str con bytes no ASCII: un header manipulado es 401, no 500.
        return None
    try:
        payload = json.loads(_unb64url(body))
    except (TypeError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None

    exp = payload.get("exp")
    if not isinstance(exp, (int, float)) or isinstance(exp, bool):
        return None
    if exp < datetime.now(UTC).timestamp():
        return None
    sub = payload.get("sub")
    if not isinstance(sub, str) or not sub:
        return None
    org = payload.get("org")
    if org is not None and not isinstance(org, str):
        return None
    return payload
