import os
from datetime import datetime, timedelta, timezone
from typing import Annotated
from uuid import UUID

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jwt.exceptions import InvalidTokenError
from pwdlib import PasswordHash
from sqlalchemy.orm import Session
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from acervo_ia import config
from acervo_ia.db.connection import get_db
from acervo_ia.db.models import Collection, Document, RuntimeSetting, User

ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30
AUTH_UNAVAILABLE_DETAIL = "Autenticação indisponível temporariamente."


class AuthenticationConfigurationError(RuntimeError):
    """Indicates that token signing cannot be used with the current configuration."""


def validate_demo_account(session: Session, user: User) -> bool:
    collections = session.scalars(
        select(Collection).where(Collection.owner_id == user.id)
    ).all()
    if len(collections) != 1 or collections[0].name != config.DEMO_COLLECTION_NAME:
        return False
    filenames = session.scalars(
        select(Document.original_filename).where(
            Document.collection_id == collections[0].id
        )
    ).all()
    return bool(filenames) and all(name.startswith("[DEMO FICTÍCIO] ") for name in filenames)

password_hash = PasswordHash.recommended()
dummy_password_hash = password_hash.hash("invalid-user-password-check")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/token")


def hash_password(password: str) -> str:
    return password_hash.hash(password)


def verify_password(password: str, hashed_password: str) -> bool:
    return password_hash.verify(password, hashed_password)


def get_auth_secret() -> str:
    secret = os.getenv("AUTH_SECRET_KEY")
    if secret is None or len(secret.encode("utf-8")) < 32:
        raise AuthenticationConfigurationError(
            "AUTH_SECRET_KEY precisa ter pelo menos 32 bytes."
        )
    return secret


def create_access_token(subject: str, *, expires_minutes: int = ACCESS_TOKEN_EXPIRE_MINUTES) -> str:
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=expires_minutes)
    return jwt.encode(
        {"sub": subject, "exp": expires_at},
        get_auth_secret(),
        algorithm=ALGORITHM,
    )


def get_current_user(
    token: Annotated[str, Depends(oauth2_scheme)],
    session: Annotated[Session, Depends(get_db)],
) -> User:
    credentials_error = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Não foi possível validar as credenciais.",
        headers={"WWW-Authenticate": "Bearer"},
    )

    user_id: UUID | None = None
    try:
        payload = jwt.decode(
            token,
            get_auth_secret(),
            algorithms=[ALGORITHM],
        )
        subject = payload.get("sub")
        if isinstance(subject, str):
            user_id = UUID(subject)
    except AuthenticationConfigurationError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=AUTH_UNAVAILABLE_DETAIL,
        ) from None
    except (InvalidTokenError, ValueError):
        pass

    if user_id is None:
        raise credentials_error from None
    user = session.get(User, user_id)
    if user is None:
        raise credentials_error
    if user.is_demo:
        try:
            enabled = session.scalar(
                select(RuntimeSetting.value).where(
                    RuntimeSetting.key == "public_demo_enabled"
                )
            )
            demo_account_valid = validate_demo_account(session, user)
        except SQLAlchemyError:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Demonstração indisponível.",
            ) from None
        if (
            not config.DEMO_ENABLED
            or enabled != "true"
            or not demo_account_valid
        ):
            raise HTTPException(status_code=404, detail="Demonstração indisponível.")
    return user
