"""Database-shared, atomic usage limits for the public demonstration."""

import hashlib
import hmac
from datetime import UTC, datetime

from fastapi import HTTPException, Request
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from acervo_ia import config
from acervo_ia.db.models import RuntimeSetting, UsageBucket
from acervo_ia.security import AuthenticationConfigurationError, get_auth_secret


def _hash_key(value: str) -> str:
    try:
        secret = get_auth_secret().encode("utf-8")
    except AuthenticationConfigurationError:
        raise HTTPException(status_code=503, detail="Limites indisponíveis.") from None
    return hmac.new(secret, value.encode("utf-8"), hashlib.sha256).hexdigest()


def _window(seconds: int) -> datetime:
    now = datetime.now(UTC)
    epoch = int(now.timestamp())
    return datetime.fromtimestamp(epoch - epoch % seconds, tz=UTC)


def _consume(session: Session, scope: str, key: str, start: datetime, limit: int) -> None:
    if limit < 1:
        raise HTTPException(status_code=429, detail="Limite de uso da demonstração atingido.")
    try:
        dialect = session.get_bind().dialect.name
        insert = pg_insert if dialect == "postgresql" else sqlite_insert
        statement = insert(UsageBucket).values(
            scope=scope,
            key_hash=_hash_key(key),
            window_start=start,
            count=1,
        )
        statement = statement.on_conflict_do_update(
            index_elements=["scope", "key_hash", "window_start"],
            set_={"count": UsageBucket.count + 1, "updated_at": datetime.now(UTC)},
            where=UsageBucket.count < limit,
        ).returning(UsageBucket.id)
        allowed = session.execute(statement).scalar_one_or_none()
        session.commit()
    except SQLAlchemyError:
        session.rollback()
        raise HTTPException(status_code=503, detail="Limites indisponíveis.") from None
    if allowed is None:
        raise HTTPException(status_code=429, detail="Limite de uso da demonstração atingido.")


def _client_key(request: Request) -> str:
    # Do not trust forwarded headers here; configure a trusted proxy before relying
    # on client IP limits. The socket peer is safe but may be a shared proxy.
    return request.client.host if request.client else "unknown-client"


def reserve_demo_login(session: Session, request: Request) -> None:
    _consume(
        session,
        "demo_login",
        _client_key(request),
        _window(3600),
        config.DEMO_LOGIN_LIMIT_PER_IP,
    )


def reserve_demo_question(session: Session, request: Request) -> None:
    _consume(
        session,
        "demo_question",
        _client_key(request),
        _window(config.DEMO_QUESTION_WINDOW_SECONDS),
        config.DEMO_QUESTION_LIMIT_PER_IP,
    )


def reserve_gemini_call(session: Session) -> None:
    if not config.GEMINI_ENABLED:
        raise HTTPException(status_code=503, detail="O provedor de IA está desativado.")
    try:
        enabled = session.scalar(
            select(RuntimeSetting.value).where(RuntimeSetting.key == "gemini_enabled")
        )
    except SQLAlchemyError:
        raise HTTPException(status_code=503, detail="O provedor de IA está indisponível.") from None
    if enabled != "true":
        raise HTTPException(status_code=503, detail="O provedor de IA está desativado.")
    _consume(
        session,
        "gemini_daily",
        "all",
        _window(86400),
        config.GEMINI_DAILY_CALL_LIMIT,
    )


def require_public_demo_enabled(session: Session) -> None:
    if not config.DEMO_ENABLED:
        raise HTTPException(status_code=404, detail="Demonstração indisponível.")
    try:
        value = session.scalar(
            select(RuntimeSetting.value).where(RuntimeSetting.key == "public_demo_enabled")
        )
    except SQLAlchemyError:
        raise HTTPException(status_code=503, detail="Demonstração indisponível.") from None
    if value != "true":
        raise HTTPException(status_code=404, detail="Demonstração indisponível.")


def ip_bucket_key_for_tests(request: Request) -> str:
    """Expose only the opaque HMAC in tests and operational diagnostics."""
    return _hash_key(_client_key(request))
