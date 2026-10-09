import sys
import warnings
from getpass import GetPassWarning, getpass
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from acervo_ia import demo
from acervo_ia.db.connection import DatabaseUnavailableError, get_engine
from acervo_ia.db.models import Collection, Document, DocumentChunk, DocumentTask, RuntimeSetting, UsageBucket, User
from acervo_ia.security import hash_password, validate_demo_account
from acervo_ia import config
from acervo_ia.services.document_tasks import enqueue_document_task
from acervo_ia.services.public_demo import (
    PUBLIC_COLLECTION_NAME,
    PublicDemoSeedError,
    seed_public_demo,
)
from acervo_ia.services import storage


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


def _set_runtime_switch(name: str, enabled: bool) -> int:
    try:
        with Session(get_engine()) as session:
            if name == "public_demo_enabled" and enabled:
                demo_user = session.scalar(select(User.id).where(User.is_demo.is_(True)))
                demo_record = session.get(User, demo_user) if demo_user is not None else None
                if demo_record is None or not validate_demo_account(session, demo_record):
                    print("Prepare a conta fictícia antes de habilitar a demonstração.", file=sys.stderr)
                    return 1
            session.merge(RuntimeSetting(key=name, value="true" if enabled else "false"))
            session.commit()
    except (DatabaseUnavailableError, SQLAlchemyError):
        print("Não foi possível atualizar a configuração operacional.", file=sys.stderr)
        return 1
    state = "habilitada" if enabled else "desabilitada"
    print(f"Configuração operacional {state}.")
    return 0


def public_demo_seed() -> int:
    try:
        with Session(get_engine()) as session:
            email, created_count = seed_public_demo(session)
    except PublicDemoSeedError as error:
        print(str(error), file=sys.stderr)
        return 1
    except (DatabaseUnavailableError, SQLAlchemyError):
        print("Não foi possível preparar a demonstração pública.", file=sys.stderr)
        return 1
    print("Demonstração pública fictícia preparada; nenhum acesso por senha foi criado.")
    print(f"Conta técnica: {email}; documentos novos: {created_count}.")
    print("A ativação pública permanece desligada até o comando demo-public-enable.")
    return 0


def public_demo_reindex() -> int:
    provider = config.DEMO_EMBEDDING_PROVIDER
    model = config.GEMINI_EMBEDDING_MODEL if provider == "gemini" else config.OLLAMA_EMBEDDING_MODEL
    queued = 0
    try:
        with Session(get_engine()) as session:
            demo_user = session.scalar(select(User).where(User.is_demo.is_(True)))
            if demo_user is None:
                print("A conta fictícia não está preparada.", file=sys.stderr)
                return 1
            collections = session.scalars(
                select(Collection).where(
                    Collection.owner_id == demo_user.id,
                    Collection.name == PUBLIC_COLLECTION_NAME,
                )
            ).all()
            for collection in collections:
                documents = session.scalars(
                    select(Document).where(Document.collection_id == collection.id)
                ).all()
                for document in documents:
                    chunks = session.scalars(
                        select(DocumentChunk).where(DocumentChunk.document_id == document.id)
                    ).all()
                    if document.processing_status != "completed" or not chunks:
                        continue
                    if all(
                        chunk.embedding_provider == provider
                        and chunk.embedding_model == model
                        and chunk.embedding is not None
                        for chunk in chunks
                    ):
                        continue
                    enqueue_document_task(
                        session,
                        document=document,
                        collection=collection,
                        user=demo_user,
                        task_type="embeddings",
                    )
                    queued += 1
    except (DatabaseUnavailableError, SQLAlchemyError):
        print("Não foi possível enfileirar a reindexação fictícia.", file=sys.stderr)
        return 1
    print(f"Tarefas de reindexação fictícia enfileiradas: {queued}.")
    return 0


def migrate_local_files_to_s3() -> int:
    if config.STORAGE_BACKEND != "s3" or not config.S3_BUCKET:
        print("Configure STORAGE_BACKEND=s3 e o bucket privado antes da cópia.", file=sys.stderr)
        return 1
    copied = 0
    try:
        with Session(get_engine()) as session:
            documents = session.scalars(select(Document)).all()
            for document in documents:
                local_path = config.DOCUMENT_STORAGE_DIRECTORY / document.storage_key
                content = local_path.read_bytes()
                digest = sha256(content).hexdigest()
                if document.content_sha256 and digest != document.content_sha256:
                    print("A cópia foi interrompida: um arquivo local não passou na validação.", file=sys.stderr)
                    return 1
                storage.store(document.storage_key, content)
                with storage.open_file(document.storage_key) as remote:
                    if sha256(remote.read()).hexdigest() != digest:
                        print("A cópia foi interrompida: a verificação remota falhou.", file=sys.stderr)
                        return 1
                copied += 1
    except (OSError, storage.StorageUnavailable, DatabaseUnavailableError, SQLAlchemyError):
        print("Não foi possível concluir a cópia dos arquivos para o bucket privado.", file=sys.stderr)
        return 1
    print(f"Arquivos verificados e copiados para armazenamento privado: {copied}.")
    print("Os arquivos locais foram preservados; remova-os somente após backup e validação próprios.")
    return 0


def clean_usage_buckets() -> int:
    try:
        with Session(get_engine()) as session:
            result = session.execute(
                delete(UsageBucket).where(
                    UsageBucket.window_start < datetime.now(UTC) - timedelta(days=31)
                )
            )
            session.commit()
    except (DatabaseUnavailableError, SQLAlchemyError):
        print("Não foi possível limpar os contadores expirados.", file=sys.stderr)
        return 1
    print(f"Contadores expirados removidos: {result.rowcount or 0}.")
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
    if arguments == ["demo-public-seed"]:
        return public_demo_seed()
    if arguments == ["demo-public-enable"]:
        return _set_runtime_switch("public_demo_enabled", True)
    if arguments == ["demo-public-disable"]:
        return _set_runtime_switch("public_demo_enabled", False)
    if arguments == ["gemini-enable"]:
        configured_providers = (
            config.CHAT_PROVIDER,
            config.EMBEDDING_PROVIDER,
            config.DEMO_CHAT_PROVIDER,
            config.DEMO_EMBEDDING_PROVIDER,
        )
        if not config.GEMINI_API_KEY or "gemini" not in configured_providers:
            print("Configure um fluxo Gemini e a chave no ambiente do backend.", file=sys.stderr)
            return 1
        return _set_runtime_switch("gemini_enabled", True)
    if arguments == ["gemini-disable"]:
        return _set_runtime_switch("gemini_enabled", False)
    if arguments == ["demo-public-reindex"]:
        return public_demo_reindex()
    if arguments == ["storage-migrate"]:
        return migrate_local_files_to_s3()
    if arguments == ["usage-clean"]:
        return clean_usage_buckets()
    print(
        "Uso: python -m acervo_ia.cli [demo-seed|demo-clean|demo-public-seed|demo-public-enable|demo-public-disable|demo-public-reindex|gemini-enable|gemini-disable|storage-migrate|usage-clean]",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
