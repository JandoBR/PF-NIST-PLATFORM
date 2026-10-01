"""Cuentas precreadas para la demo (doc 10 §5).

El cliente no se registra: el proveedor crea organizacion + usuario. Para el prototipo se siembran
dos cuentas fijas al arrancar la API (idempotente). `SEED_DEMO_USERS=0` lo desactiva -- los tests
lo usan para no tocar la base real.
"""

from __future__ import annotations

import os

from sqlalchemy.orm import Session

from app.core.auth import hash_password
from app.models.tables import Organization, User

#: (username, password, nombre de la organizacion)
SEED_USERS: list[tuple[str, str, str]] = [
    ("demo", "demo123", "Organización Demo"),
    ("smoke", "smoke123", "Smoke E2E"),
]


def _get_or_create_organization(session: Session, nombre: str) -> Organization:
    org = session.query(Organization).filter_by(nombre=nombre).one_or_none()
    if org is None:
        org = Organization(nombre=nombre)
        session.add(org)
        session.flush()
    return org


def ensure_seed_users(session: Session) -> int:
    """Crea las cuentas precreadas que falten. Devuelve cuantas creo (0 si ya estaban)."""

    if os.environ.get("SEED_DEMO_USERS", "1") == "0":
        return 0

    created = 0
    for username, password, org_name in SEED_USERS:
        if session.query(User).filter_by(username=username).one_or_none() is not None:
            continue
        org = _get_or_create_organization(session, org_name)
        salt, digest = hash_password(password)
        session.add(
            User(
                org_id=org.id,
                username=username,
                password_salt=salt,
                password_hash=digest,
                role="client",
            )
        )
        created += 1
    if created:
        session.commit()
    return created
