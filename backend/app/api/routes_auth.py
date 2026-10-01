"""Login y sesion (doc 10). `POST /auth/login` es publico; el resto exige token."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_session
from app.core import auth as auth_service
from app.models.tables import User

router = APIRouter(tags=["auth"])


class LoginRequest(BaseModel):
    username: str
    password: str


class UserOut(BaseModel):
    id: str
    username: str
    org_id: str
    org_nombre: str
    role: str


class LoginResponse(BaseModel):
    token: str
    user: UserOut


def _user_out(user: User) -> UserOut:
    return UserOut(
        id=user.id,
        username=user.username,
        org_id=user.org_id,
        org_nombre=user.organization.nombre,
        role=user.role,
    )


@router.post("/auth/login", response_model=LoginResponse)
def login(body: LoginRequest, session: Session = Depends(get_session)) -> LoginResponse:
    user = session.query(User).filter_by(username=body.username).one_or_none()
    if user is None or not auth_service.verify_password(
        body.password, user.password_salt, user.password_hash
    ):
        # Mismo mensaje para usuario inexistente y contrasena incorrecta: no revelar cual fallo.
        raise HTTPException(status_code=401, detail="Usuario o contraseña incorrectos.")
    return LoginResponse(
        token=auth_service.create_token(user.id, user.org_id), user=_user_out(user)
    )


@router.get("/auth/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)) -> UserOut:
    return _user_out(user)
