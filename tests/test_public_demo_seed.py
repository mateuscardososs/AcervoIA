from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from acervo_ia import config, demo
from acervo_ia.db.models import Base, Collection, Document, DocumentTask, User
from acervo_ia.services.public_demo import (
    PUBLIC_COLLECTION_NAME,
    PublicDemoSeedError,
    seed_public_demo,
)


@pytest.fixture
def demo_seed_session(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[Session]:
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    fixture_dir = tmp_path / "fictional"
    fixture_dir.mkdir()
    monkeypatch.setattr(demo, "DEMO_SOURCE_DIRECTORY", fixture_dir)
    monkeypatch.setattr(config, "DOCUMENT_STORAGE_DIRECTORY", tmp_path / "uploads")
    monkeypatch.setattr(config, "STORAGE_BACKEND", "local")
    monkeypatch.setattr(config, "DEMO_ACCOUNT_EMAIL", "portfolio-demo@example.test")
    with Session(engine, expire_on_commit=False) as session:
        for filename in demo.DEMO_SOURCE_FILES:
            (fixture_dir / filename).write_text(f"Conteúdo fictício de {filename}.", encoding="utf-8")
        yield session
    engine.dispose()


def test_public_demo_seed_is_idempotent_and_only_creates_fictional_data(
    demo_seed_session: Session,
) -> None:
    email, first_count = seed_public_demo(demo_seed_session)
    second_email, second_count = seed_public_demo(demo_seed_session)

    assert email == second_email == "portfolio-demo@example.test"
    assert first_count == 2
    assert second_count == 0
    user = demo_seed_session.scalar(select(User).where(User.email == email))
    assert user is not None and user.is_demo
    assert user.password_hash.startswith("$argon2")
    collection = demo_seed_session.scalar(
        select(Collection).where(Collection.owner_id == user.id)
    )
    assert collection is not None and collection.name == PUBLIC_COLLECTION_NAME
    documents = demo_seed_session.scalars(
        select(Document).where(Document.collection_id == collection.id)
    ).all()
    tasks = demo_seed_session.scalars(
        select(DocumentTask).where(DocumentTask.owner_id == user.id)
    ).all()
    assert len(documents) == len(tasks) == 2
    assert all("DEMO FICTÍCIO" in document.original_filename for document in documents)
    assert all(document.processing_status == "pending" for document in documents)


def test_public_demo_seed_never_marks_or_modifies_an_existing_regular_account(
    demo_seed_session: Session,
) -> None:
    regular = User(email="portfolio-demo@example.test", password_hash="unchanged")
    demo_seed_session.add(regular)
    demo_seed_session.commit()

    with pytest.raises(PublicDemoSeedError):
        seed_public_demo(demo_seed_session)

    assert regular.is_demo is False
    assert regular.password_hash == "unchanged"
    assert demo_seed_session.scalar(select(func.count()).select_from(Collection)) == 0
