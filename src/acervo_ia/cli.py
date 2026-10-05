import sys
import warnings
from getpass import GetPassWarning, getpass
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from acervo_ia.db.connection import DatabaseUnavailableError, get_engine
from acervo_ia.db.models import User
from acervo_ia.security import hash_password


def _read_hidden_password(prompt: str) -> str | None:
    with warnings.catch_warnings():
        warnings.simplefilter("error", GetPassWarning)
        try:
            return getpass(prompt)
        except GetPassWarning:
            print(
                "Este terminal não permite digitar a senha sem exibi-la.",
                file=sys.stderr,
            )
            return None


def create_user() -> int:
    if len(sys.argv) > 1:
        print(
            "Este comando não aceita argumentos; informe a senha apenas no prompt.",
            file=sys.stderr,
        )
        return 2

    project_root = Path(__file__).resolve().parents[2]
    load_dotenv(project_root / ".env")

    try:
        email = input("E-mail: ").strip()
    except EOFError:
        print("Não foi possível ler o e-mail no terminal.", file=sys.stderr)
        return 2

    if not email or "@" not in email:
        print("Informe um e-mail válido.", file=sys.stderr)
        return 2

    try:
        with Session(get_engine()) as session:
            existing_user = session.scalar(
                select(User.id).where(User.email == email)
            )
    except (DatabaseUnavailableError, SQLAlchemyError):
        print("Não foi possível acessar o banco de dados.", file=sys.stderr)
        return 1

    if existing_user is not None:
        print("E-mail já cadastrado.", file=sys.stderr)
        return 1

    password = _read_hidden_password("Senha: ")
    if password is None:
        return 2
    confirmation = _read_hidden_password("Confirme a senha: ")
    if confirmation is None:
        return 2
    if not password:
        print("A senha não pode ficar vazia.", file=sys.stderr)
        return 2
    if password != confirmation:
        print("As senhas não coincidem.", file=sys.stderr)
        return 2

    password_hash = hash_password(password)
    password = ""
    confirmation = ""

    try:
        with Session(get_engine()) as session:
            session.add(User(email=email, password_hash=password_hash))
            session.commit()
    except IntegrityError:
        print("E-mail já cadastrado.", file=sys.stderr)
        return 1
    except (DatabaseUnavailableError, SQLAlchemyError):
        print("Não foi possível acessar o banco de dados.", file=sys.stderr)
        return 1

    print(f"Usuário criado: {email}")
    return 0


if __name__ == "__main__":
    raise SystemExit(create_user())
