import json
import sys
from collections.abc import Iterator
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from acervo_ia import cli, demo
from acervo_ia.db.models import Base, Collection, Document, User
from acervo_ia.security import verify_password


@pytest.fixture
def demo_cli(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> Iterator[Engine]:
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    monkeypatch.setattr(demo, "get_engine", lambda: engine)
    monkeypatch.setattr(demo, "DEMO_STATE_PATH", tmp_path / "demo-state.json")
    monkeypatch.setattr(demo, "DOCUMENT_STORAGE_DIRECTORY", tmp_path / "uploads")
    monkeypatch.setattr(demo, "DEMO_SOURCE_DIRECTORY", Path("data/demo"))
    monkeypatch.setattr(cli, "load_dotenv", lambda _path: False)
    monkeypatch.setattr(sys, "argv", ["acervo-ia"])
    try:
        yield engine
    finally:
        engine.dispose()


def run_demo_seed(
    monkeypatch: pytest.MonkeyPatch,
    password: str = "demo-local-password-for-test",
) -> int:
    monkeypatch.setattr(sys, "argv", ["acervo-ia", "demo-seed"])
    answers = iter([password, password])
    monkeypatch.setattr(cli, "getpass", lambda _prompt: next(answers))
    return cli.main()


def test_demo_seed_creates_labeled_fictional_data_without_default_password(
    demo_cli: Engine,
    monkeypatch: pytest.MonkeyPatch,
    capfd: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    password = "demo-local-password-for-test"
    exit_code = run_demo_seed(monkeypatch, password)
    output = capfd.readouterr()

    assert exit_code == 0
    assert password not in output.out
    assert password not in output.err
    assert password not in caplog.text
    with Session(demo_cli) as session:
        user = session.scalar(
            select(User).where(User.email.like("demo+%@example.invalid"))
        )
        assert user is not None
        assert user.password_hash.startswith("$argon2")
        assert verify_password(password, user.password_hash)
        collection = session.scalar(
            select(Collection).where(Collection.owner_id == user.id)
        )
        assert collection is not None
        assert "DEMO LOCAL" in collection.name
        assert "fictício" in (collection.description or "").lower()
        documents = session.scalars(
            select(Document).where(Document.collection_id == collection.id)
        ).all()

    assert len(documents) == 2
    assert all("DEMO FICTÍCIO" in item.original_filename for item in documents)
    assert all(item.processing_status == "pending" for item in documents)
    assert all(
        (demo.DOCUMENT_STORAGE_DIRECTORY / item.storage_key).is_file()
        for item in documents
    )
    assert "@example.invalid" in output.out


def test_demo_seed_preserves_existing_account_collection_and_document(
    demo_cli: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    storage_key = uuid4().hex
    existing_user_id = uuid4()
    existing_collection_id = uuid4()
    existing_document_id = uuid4()
    with Session(demo_cli) as session:
        session.add_all(
            [
                User(
                    id=existing_user_id,
                    email="existing@example.test",
                    password_hash="existing-password-hash",
                ),
                Collection(
                    id=existing_collection_id,
                    owner_id=existing_user_id,
                    name="Coleção preexistente",
                    description="Não deve ser alterada pela demo.",
                ),
                Document(
                    id=existing_document_id,
                    collection_id=existing_collection_id,
                    original_filename="arquivo-existente.txt",
                    storage_key=storage_key,
                    content_type="text/plain",
                    size_bytes=8,
                ),
            ]
        )
        session.commit()

    assert run_demo_seed(monkeypatch) == 0

    with Session(demo_cli) as session:
        existing_user = session.get(User, existing_user_id)
        existing_collection = session.get(Collection, existing_collection_id)
        existing_document = session.get(Document, existing_document_id)
        assert existing_user is not None
        assert existing_user.email == "existing@example.test"
        assert existing_user.password_hash == "existing-password-hash"
        assert existing_collection is not None
        assert existing_collection.name == "Coleção preexistente"
        assert existing_collection.description == "Não deve ser alterada pela demo."
        assert existing_document is not None
        assert existing_document.storage_key == storage_key
        assert existing_document.original_filename == "arquivo-existente.txt"


def test_demo_clean_removes_only_seeded_data_and_files(
    demo_cli: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert run_demo_seed(monkeypatch) == 0
    state = json.loads(demo.DEMO_STATE_PATH.read_text(encoding="utf-8"))
    storage_paths = [
        demo.DOCUMENT_STORAGE_DIRECTORY / item["storage_key"]
        for item in state["documents"]
    ]

    monkeypatch.setattr(sys, "argv", ["acervo-ia", "demo-clean"])
    assert cli.main() == 0

    with Session(demo_cli) as session:
        assert session.scalar(
            select(func.count()).select_from(User).where(
                User.id == UUID(state["user_id"])
            )
        ) == 0
        assert session.scalar(
            select(func.count()).select_from(Collection).where(
                Collection.id == UUID(state["collection_id"])
            )
        ) == 0
        assert session.scalar(
            select(func.count()).select_from(Document).where(
                Document.id.in_([UUID(item["id"]) for item in state["documents"]])
            )
        ) == 0
    assert all(not path.exists() for path in storage_paths)
    assert not demo.DEMO_STATE_PATH.exists()


def test_demo_clean_preserves_extra_user_content(
    demo_cli: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert run_demo_seed(monkeypatch) == 0
    state = json.loads(demo.DEMO_STATE_PATH.read_text(encoding="utf-8"))
    custom_document_id = uuid4()
    with Session(demo_cli) as session:
        collection = session.get(Collection, UUID(state["collection_id"]))
        assert collection is not None
        session.add(
            Document(
                id=custom_document_id,
                collection_id=collection.id,
                original_filename="conteudo-adicionado-pelo-usuario.txt",
                storage_key=uuid4().hex,
                content_type="text/plain",
                size_bytes=18,
            )
        )
        session.commit()

    monkeypatch.setattr(sys, "argv", ["acervo-ia", "demo-clean"])
    assert cli.main() == 0

    with Session(demo_cli) as session:
        user = session.get(User, UUID(state["user_id"]))
        collection = session.get(Collection, UUID(state["collection_id"]))
        custom_document = session.get(Document, custom_document_id)
        assert user is not None
        assert collection is not None
        assert custom_document is not None
        assert custom_document.collection_id == collection.id
    assert not demo.DEMO_STATE_PATH.exists()


def test_demo_clean_refuses_manifest_pointing_to_non_demo_account(
    demo_cli: Engine,
    monkeypatch: pytest.MonkeyPatch,
    capfd: pytest.CaptureFixture[str],
) -> None:
    assert run_demo_seed(monkeypatch) == 0
    state = json.loads(demo.DEMO_STATE_PATH.read_text(encoding="utf-8"))
    with Session(demo_cli) as session:
        existing_user = User(email="person@example.test", password_hash="existing")
        session.add(existing_user)
        session.commit()
        existing_id = existing_user.id

    state["user_id"] = str(existing_id)
    demo.DEMO_STATE_PATH.write_text(json.dumps(state), encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["acervo-ia", "demo-clean"])

    exit_code = cli.main()

    assert exit_code != 0
    assert "person@example.test" not in capfd.readouterr().out
    with Session(demo_cli) as session:
        assert session.get(User, existing_id) is not None
        assert session.get(User, UUID(state["user_id"])) is not None
        assert session.get(Collection, UUID(state["collection_id"])) is not None
    assert demo.DEMO_STATE_PATH.exists()


def test_demo_seed_refuses_to_overwrite_an_existing_manifest(
    demo_cli: Engine,
    monkeypatch: pytest.MonkeyPatch,
    capfd: pytest.CaptureFixture[str],
) -> None:
    demo.DEMO_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    demo.DEMO_STATE_PATH.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["acervo-ia", "demo-seed"])
    monkeypatch.setattr(
        cli,
        "getpass",
        lambda _prompt: pytest.fail("não deve solicitar senha ao encontrar manifesto"),
    )

    assert cli.main() != 0
    assert "{}" in demo.DEMO_STATE_PATH.read_text(encoding="utf-8")
    assert "demo" in capfd.readouterr().err.lower()


def test_demo_seed_requires_matching_hidden_passwords(
    demo_cli: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sys, "argv", ["acervo-ia", "demo-seed"])
    answers = iter(["first-private-password", "different-private-password"])
    monkeypatch.setattr(cli, "getpass", lambda _prompt: next(answers))

    assert cli.main() != 0
    assert not demo.DEMO_STATE_PATH.exists()
    with Session(demo_cli) as session:
        assert session.scalar(select(func.count()).select_from(User)) == 0


def test_demo_seed_rejects_password_arguments_without_echoing_them(
    demo_cli: Engine,
    monkeypatch: pytest.MonkeyPatch,
    capfd: pytest.CaptureFixture[str],
) -> None:
    secret = "must-not-be-accepted-as-a-demo-argument"
    monkeypatch.setattr(sys, "argv", ["acervo-ia", "demo-seed", secret])

    assert cli.main() != 0
    output = capfd.readouterr()
    assert secret not in output.out
    assert secret not in output.err
    with Session(demo_cli) as session:
        assert session.scalar(select(func.count()).select_from(User)) == 0


def test_seed_database_failure_keeps_manifest_for_safe_cleanup(
    demo_cli: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_before_commit(_session: Session) -> None:
        raise SQLAlchemyError("synthetic local database failure")

    event.listen(Session, "before_commit", fail_before_commit, once=True)
    assert run_demo_seed(monkeypatch) != 0
    assert demo.DEMO_STATE_PATH.is_file()
    manifest = json.loads(demo.DEMO_STATE_PATH.read_text(encoding="utf-8"))
    files = [
        demo.DOCUMENT_STORAGE_DIRECTORY / document["storage_key"]
        for document in manifest["documents"]
    ]
    assert all(path.is_file() for path in files)

    monkeypatch.setattr(sys, "argv", ["acervo-ia", "demo-clean"])
    assert cli.main() == 0
    assert all(not path.exists() for path in files)
    assert not demo.DEMO_STATE_PATH.exists()
    with Session(demo_cli) as session:
        assert session.scalar(select(func.count()).select_from(User)) == 0
