from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from acervo_ia.db.connection import get_db
from acervo_ia.db.models import User
from acervo_ia.security import (
    AUTH_UNAVAILABLE_DETAIL,
    AuthenticationConfigurationError,
    create_access_token,
    dummy_password_hash,
    get_current_user,
    verify_password,
)

router = APIRouter(prefix="/auth", tags=["authentication"])


class AccessToken(BaseModel):
    access_token: str
    token_type: str


class AuthenticatedUser(BaseModel):
    id: UUID
    email: str


@router.post("/token", response_model=AccessToken)
def login(
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
    session: Annotated[Session, Depends(get_db)],
) -> AccessToken:
    user = session.scalar(select(User).where(User.email == form_data.username))
    stored_hash = user.password_hash if user is not None else dummy_password_hash
    password_matches = verify_password(form_data.password, stored_hash)

    if user is None or not password_matches:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="E-mail ou senha incorretos.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        access_token = create_access_token(str(user.id))
    except AuthenticationConfigurationError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=AUTH_UNAVAILABLE_DETAIL,
        ) from None
    return AccessToken(access_token=access_token, token_type="bearer")


@router.get("/me", response_model=AuthenticatedUser)
def read_authenticated_user(
    user: Annotated[User, Depends(get_current_user)],
) -> AuthenticatedUser:
    return AuthenticatedUser(id=user.id, email=user.email)
