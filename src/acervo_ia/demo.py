"""Prepare and remove clearly marked, fictional local demo content."""

import json
import os
import re
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from acervo_ia.config import DOCUMENT_STORAGE_DIRECTORY
from acervo_ia.db.connection import get_engine
from acervo_ia.db.models import Collection, Document, User
from acervo_ia.security import hash_password

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEMO_SOURCE_DIRECTORY = PROJECT_ROOT / "data" / "demo"
DEMO_STATE_PATH = PROJECT_ROOT / "data" / ".acervoia-demo-state.json"
DEMO_SOURCE_FILES = (
    "manual-orion-b20-v1.txt",
    "manual-atlas-t30-v2.txt",
)
DEMO_COLLECTION_NAME = "[DEMO LOCAL] Manuais fictícios"
DEMO_COLLECTION_DESCRIPTION = (
    "Dado de desenvolvimento do AcervoIA. Equipamentos e procedimentos são "
    "totalmente fictícios e não devem ser usados em equipamentos reais."
)
DEMO_FILENAME_PREFIX = "[DEMO FICTÍCIO] "
MANIFEST_VERSION = 1
_STORAGE_KEY_PATTERN = re.compile(r"^[0-9a-f]{32}$")
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


class DemoDataError(RuntimeError):
    """A safe local demo operation failure."""


@dataclass(frozen=True)
class DemoSeedResult:
    email: str
    document_count: int


@dataclass(frozen=True)
class DemoCleanupResult:
    document_count: int
    file_count: int
    collection_removed: bool
    user_removed: bool


def _demo_email(user_id: UUID) -> str:
    return f"demo+{user_id.hex}@example.invalid"


def _write_exclusive(path: Path, content: bytes, mode: int) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
    except OSError:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass
        raise


def _read_manifest(path: Path) -> dict[str, object]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise DemoDataError("O manifesto local da demonstração não é válido.") from None

    if not isinstance(raw, dict) or raw.get("version") != MANIFEST_VERSION:
        raise DemoDataError("O manifesto local da demonstração não é válido.")
    try:
        user_id = UUID(str(raw["user_id"]))
        collection_id = UUID(str(raw["collection_id"]))
        documents_raw = raw["documents"]
    except (KeyError, TypeError, ValueError):
        raise DemoDataError("O manifesto local da demonstração não é válido.") from None
    if not isinstance(documents_raw, list) or len(documents_raw) != len(DEMO_SOURCE_FILES):
        raise DemoDataError("O manifesto local da demonstração não é válido.")

    documents: list[dict[str, object]] = []
    expected_filenames = {f"{DEMO_FILENAME_PREFIX}{name}" for name in DEMO_SOURCE_FILES}
    seen_ids: set[UUID] = set()
    seen_keys: set[str] = set()
    for item in documents_raw:
        if not isinstance(item, dict):
            raise DemoDataError("O manifesto local da demonstração não é válido.")
        try:
            document_id = UUID(str(item["id"]))
            filename = str(item["original_filename"])
            storage_key = str(item["storage_key"])
            content_sha256 = str(item["content_sha256"])
            size_bytes = int(item["size_bytes"])
        except (KeyError, TypeError, ValueError):
            raise DemoDataError("O manifesto local da demonstração não é válido.") from None
        if (
            document_id in seen_ids
            or filename not in expected_filenames
            or storage_key in seen_keys
            or not _STORAGE_KEY_PATTERN.fullmatch(storage_key)
            or not _SHA256_PATTERN.fullmatch(content_sha256)
            or size_bytes < 0
        ):
            raise DemoDataError("O manifesto local da demonstração não é válido.")
        seen_ids.add(document_id)
        seen_keys.add(storage_key)
        documents.append(
            {
                "id": document_id,
                "original_filename": filename,
                "storage_key": storage_key,
                "content_sha256": content_sha256,
                "size_bytes": size_bytes,
            }
        )

    if expected_filenames != {str(item["original_filename"]) for item in documents}:
        raise DemoDataError("O manifesto local da demonstração não é válido.")
    return {
        "user_id": user_id,
        "collection_id": collection_id,
        "documents": documents,
    }


def seed_demo(password: str) -> DemoSeedResult:
    """Add demo rows and files without modifying any existing records."""
    if not password:
        raise DemoDataError("A senha da demonstração não pode ficar vazia.")
    if DEMO_STATE_PATH.exists():
        raise DemoDataError(
            "A demonstração local já está preparada; limpe-a antes de criar outra."
        )

    try:
        fixture_contents = {
            name: (DEMO_SOURCE_DIRECTORY / name).read_bytes()
            for name in DEMO_SOURCE_FILES
        }
    except OSError:
        raise DemoDataError("Não foi possível ler os manuais fictícios locais.") from None

    user_id = uuid4()
    collection_id = uuid4()
    user = User(
        id=user_id,
        email=_demo_email(user_id),
        password_hash=hash_password(password),
    )
    demo_email = user.email
    collection = Collection(
        id=collection_id,
        owner_id=user_id,
        name=DEMO_COLLECTION_NAME,
        description=DEMO_COLLECTION_DESCRIPTION,
    )
    documents: list[Document] = []
    manifest_documents: list[dict[str, object]] = []
    for source_name, content in fixture_contents.items():
        storage_key = uuid4().hex
        original_filename = f"{DEMO_FILENAME_PREFIX}{source_name}"
        document_id = uuid4()
        digest = sha256(content).hexdigest()
        documents.append(
            Document(
                id=document_id,
                collection_id=collection_id,
                original_filename=original_filename,
                storage_key=storage_key,
                content_sha256=digest,
                content_type="text/plain",
                size_bytes=len(content),
                processing_status="pending",
            )
        )
        manifest_documents.append(
            {
                "id": str(document_id),
                "original_filename": original_filename,
                "storage_key": storage_key,
                "content_sha256": digest,
                "size_bytes": len(content),
            }
        )

    manifest = {
        "version": MANIFEST_VERSION,
        "user_id": str(user_id),
        "collection_id": str(collection_id),
        "documents": manifest_documents,
    }
    manifest_created = False
    created_paths: list[Path] = []
    session: Session | None = None
    try:
        DEMO_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        _write_exclusive(
            DEMO_STATE_PATH,
            json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8"),
            0o600,
        )
        manifest_created = True
        DOCUMENT_STORAGE_DIRECTORY.mkdir(
            parents=True,
            exist_ok=True,
            mode=0o700,
        )
        for item, source_name in zip(documents, fixture_contents, strict=True):
            path = DOCUMENT_STORAGE_DIRECTORY / item.storage_key
            _write_exclusive(path, fixture_contents[source_name], 0o600)
            created_paths.append(path)

        session = Session(get_engine())
        session.add_all([user, collection, *documents])
        session.commit()
    except FileExistsError:
        if session is not None:
            session.rollback()
        for path in created_paths:
            path.unlink(missing_ok=True)
        if manifest_created:
            DEMO_STATE_PATH.unlink(missing_ok=True)
        raise DemoDataError(
            "Já existe um manifesto ou arquivo no destino; nenhum dado foi substituído."
        ) from None
    except SQLAlchemyError:
        if session is not None:
            try:
                session.rollback()
            except SQLAlchemyError:
                pass
        # Commit outcomes can be ambiguous after a connection failure. Keep the
        # manifest and files so demo-clean can safely reconcile either state.
        raise DemoDataError(
            "Não foi possível confirmar a demonstração local; manifesto preservado. "
            "Execute demo-clean antes de tentar novamente."
        ) from None
    except (OSError, ValueError):
        if session is not None:
            try:
                session.rollback()
            except SQLAlchemyError:
                pass
        for path in created_paths:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass
        if manifest_created:
            try:
                DEMO_STATE_PATH.unlink(missing_ok=True)
            except OSError:
                pass
        raise DemoDataError(
            "Não foi possível preparar a demonstração local; nenhum dado existente foi alterado."
        ) from None
    finally:
        if session is not None:
            session.close()

    return DemoSeedResult(email=demo_email, document_count=len(documents))


def _matches_seeded_document(document: Document, expected: dict[str, object]) -> bool:
    return (
        document.id == expected["id"]
        and document.original_filename == expected["original_filename"]
        and document.storage_key == expected["storage_key"]
        and document.content_sha256 == expected["content_sha256"]
        and document.size_bytes == expected["size_bytes"]
        and document.content_type == "text/plain"
    )


def clean_demo() -> DemoCleanupResult:
    """Remove only objects listed in a validated local demo manifest."""
    if not DEMO_STATE_PATH.exists():
        return DemoCleanupResult(0, 0, False, False)
    manifest = _read_manifest(DEMO_STATE_PATH)
    user_id = manifest["user_id"]
    collection_id = manifest["collection_id"]
    expected_documents = manifest["documents"]
    assert isinstance(user_id, UUID)
    assert isinstance(collection_id, UUID)
    assert isinstance(expected_documents, list)

    session: Session | None = None
    deleted_document_ids: set[UUID] = set()
    collection_removed = False
    user_removed = False
    try:
        session = Session(get_engine())
        user = session.get(User, user_id)
        if user is not None and user.email != _demo_email(user_id):
            raise DemoDataError(
                "A conta do manifesto não tem a identificação esperada; limpeza cancelada."
            )

        collection = session.scalar(
            select(Collection).where(
                Collection.id == collection_id,
                Collection.owner_id == user_id,
            )
        )
        if collection is not None:
            for expected in expected_documents:
                assert isinstance(expected, dict)
                document_id = expected["id"]
                assert isinstance(document_id, UUID)
                document = session.get(Document, document_id)
                if document is None:
                    continue
                if (
                    document.collection_id != collection_id
                    or not _matches_seeded_document(document, expected)
                ):
                    raise DemoDataError(
                        "Um documento registrado no manifesto mudou; limpeza cancelada."
                    )
                stored_path = DOCUMENT_STORAGE_DIRECTORY / str(expected["storage_key"])
                if stored_path.exists():
                    try:
                        file_digest = sha256(stored_path.read_bytes()).hexdigest()
                    except OSError:
                        raise DemoDataError(
                            "Não foi possível verificar um arquivo da demonstração; limpeza cancelada."
                        ) from None
                    if file_digest != expected["content_sha256"]:
                        raise DemoDataError(
                            "Um arquivo registrado no manifesto mudou; limpeza cancelada."
                        )
                session.delete(document)
                deleted_document_ids.add(document_id)

            session.flush()
            remaining_document = session.scalar(
                select(Document.id)
                .where(Document.collection_id == collection_id)
                .limit(1)
            )
            if (
                remaining_document is None
                and collection.name == DEMO_COLLECTION_NAME
                and collection.description == DEMO_COLLECTION_DESCRIPTION
            ):
                session.delete(collection)
                collection_removed = True

        session.flush()
        if user is not None:
            remaining_collection = session.scalar(
                select(Collection.id).where(Collection.owner_id == user_id).limit(1)
            )
            if remaining_collection is None:
                session.delete(user)
                user_removed = True
        session.commit()
    except DemoDataError:
        if session is not None:
            session.rollback()
        raise
    except SQLAlchemyError:
        if session is not None:
            try:
                session.rollback()
            except SQLAlchemyError:
                pass
        raise DemoDataError(
            "Não foi possível limpar a demonstração local; o manifesto foi preservado."
        ) from None
    finally:
        if session is not None:
            session.close()

    deleted_file_count = 0
    try:
        for expected in expected_documents:
            assert isinstance(expected, dict)
            storage_key = str(expected["storage_key"])
            path = DOCUMENT_STORAGE_DIRECTORY / storage_key
            if not path.exists():
                continue
            digest = sha256(path.read_bytes()).hexdigest()
            if digest != expected["content_sha256"]:
                raise DemoDataError(
                    "Um arquivo registrado no manifesto mudou; manifesto preservado."
                )
            path.unlink()
            deleted_file_count += 1
        DEMO_STATE_PATH.unlink(missing_ok=True)
    except OSError:
        raise DemoDataError(
            "Não foi possível concluir a limpeza dos arquivos; manifesto preservado para nova tentativa."
        ) from None

    return DemoCleanupResult(
        document_count=len(deleted_document_ids),
        file_count=deleted_file_count,
        collection_removed=collection_removed,
        user_removed=user_removed,
    )
