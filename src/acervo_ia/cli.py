import sys
import warnings
from getpass import GetPassWarning, getpass
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from acervo_ia import demo
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


def seed_demo() -> int:
    if demo.DEMO_STATE_PATH.exists():
        print(
            "A demonstração local já está preparada; execute demo-clean antes de recriá-la.",
            file=sys.stderr,
        )
        return 1

    password = _read_hidden_password("Senha da conta de demonstração: ")
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

    try:
        result = demo.seed_demo(password)
    except demo.DemoDataError as error:
        print(str(error), file=sys.stderr)
        return 1
    except (DatabaseUnavailableError, SQLAlchemyError):
        print(
            "Não foi possível preparar a demonstração local; verifique o banco.",
            file=sys.stderr,
        )
        return 1
    finally:
        password = ""
        confirmation = ""

    print("Demonstração local preparada com dados fictícios.")
    print(f"Conta para entrar: {result.email}")
    print("A senha foi escolhida no prompt e não foi armazenada em texto puro.")
    return 0


def clean_demo() -> int:
    try:
        result = demo.clean_demo()
    except demo.DemoDataError as error:
        print(str(error), file=sys.stderr)
        return 1
    except (DatabaseUnavailableError, SQLAlchemyError):
        print(
            "Não foi possível limpar a demonstração local; manifesto preservado.",
            file=sys.stderr,
        )
        return 1

    if result.document_count == 0 and result.file_count == 0:
        print("Nenhuma demonstração local foi encontrada.")
        return 0
    print(
        "Dados fictícios da demonstração removidos: "
        f"{result.document_count} documento(s), {result.file_count} arquivo(s)."
    )
    if not result.collection_removed or not result.user_removed:
        print(
            "A conta ou coleção foi preservada para proteger dados ou alterações "
            "adicionais; revise antes de qualquer exclusão manual."
        )
    else:
        print("Conta e coleção da demonstração também foram removidas.")
    return 0


def main() -> int:
    project_root = Path(__file__).resolve().parents[2]
    load_dotenv(project_root / ".env")

    arguments = sys.argv[1:]
    if not arguments:
        return create_user()
    if arguments == ["demo-seed"]:
        return seed_demo()
    if arguments == ["demo-clean"]:
        return clean_demo()
    print(
        "Uso: python -m acervo_ia.cli [demo-seed|demo-clean]",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
