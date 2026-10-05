import sys
from collections.abc import Iterator
from getpass import GetPassWarning

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from acervo_ia import cli
from acervo_ia.db.models import Base, User
from acervo_ia.security import verify_password


@pytest.fixture
def user_cli(
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[Engine]:
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    monkeypatch.setattr(cli, "get_engine", lambda: engine)
    monkeypatch.setattr(cli, "load_dotenv", lambda _path: False)
    monkeypatch.setattr(sys, "argv", ["acervo-ia-create-user"])

    try:
        yield engine
    finally:
        engine.dispose()


def test_local_command_creates_user_with_hidden_password_hash(
    user_cli: Engine,
    monkeypatch: pytest.MonkeyPatch,
    capfd: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    engine = user_cli
    password = "private-password-for-cli-test"
    email_answers = iter(["person@example.test"])
    password_answers = iter([password, password])
    monkeypatch.setattr("builtins.input", lambda _prompt: next(email_answers))
    monkeypatch.setattr(cli, "getpass", lambda _prompt: next(password_answers))

    exit_code = cli.create_user()
    output = capfd.readouterr()

    assert exit_code == 0
    assert password not in output.out
    assert password not in output.err
    assert password not in caplog.text
    with Session(engine) as session:
        user = session.scalar(
            select(User).where(User.email == "person@example.test")
        )
    assert user is not None
    assert user.password_hash != password
    assert user.password_hash.startswith("$argon2")
    assert verify_password(password, user.password_hash)


def test_local_command_reports_duplicate_email_clearly(
    user_cli: Engine,
    monkeypatch: pytest.MonkeyPatch,
    capfd: pytest.CaptureFixture[str],
) -> None:
    engine = user_cli
    with Session(engine) as session:
        session.add(User(email="person@example.test", password_hash="existing-hash"))
        session.commit()

    monkeypatch.setattr(
        "builtins.input",
        lambda _prompt: "person@example.test",
    )
    monkeypatch.setattr(
        cli,
        "getpass",
        lambda _prompt: pytest.fail("Senha não deve ser solicitada para e-mail duplicado"),
    )

    exit_code = cli.create_user()
    output = capfd.readouterr()

    assert exit_code != 0
    assert "E-mail já cadastrado." in output.err
    with Session(engine) as session:
        assert session.scalar(select(User.id)) is not None
        assert session.scalar(select(User).where(User.email == "person@example.test"))
        assert len(session.scalars(select(User)).all()) == 1


def test_local_command_rejects_password_arguments_without_echoing_them(
    user_cli: Engine,
    monkeypatch: pytest.MonkeyPatch,
    capfd: pytest.CaptureFixture[str],
) -> None:
    password = "must-not-be-accepted-as-an-argument"
    monkeypatch.setattr(
        sys,
        "argv",
        ["acervo-ia-create-user", password],
    )

    exit_code = cli.create_user()
    output = capfd.readouterr()

    assert exit_code != 0
    assert password not in output.out
    assert password not in output.err


def test_local_command_aborts_when_terminal_cannot_hide_password(
    user_cli: Engine,
    monkeypatch: pytest.MonkeyPatch,
    capfd: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr("builtins.input", lambda _prompt: "person@example.test")

    def getpass_without_secure_terminal(_prompt: str) -> str:
        raise GetPassWarning("echo control unavailable")

    monkeypatch.setattr(cli, "getpass", getpass_without_secure_terminal)

    exit_code = cli.create_user()
    output = capfd.readouterr()

    assert exit_code != 0
    assert "sem exibi-la" in output.err
    assert "echo control unavailable" not in output.err
    with Session(user_cli) as session:
        assert session.scalar(select(User.id)) is None
