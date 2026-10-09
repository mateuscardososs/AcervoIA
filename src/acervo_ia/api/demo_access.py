from fastapi import HTTPException

from acervo_ia.db.models import User


def ensure_writable_user(user: User) -> None:
    if user.is_demo:
        raise HTTPException(
            status_code=403,
            detail="A conta de demonstração permite apenas consultar o acervo.",
        )
