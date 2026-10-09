from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
    literal_column,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.types import JSON
from pgvector.sqlalchemy import VECTOR

from acervo_ia.config import EMBEDDING_DIMENSIONS


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    collections: Mapped[list["Collection"]] = relationship(
        back_populates="owner",
        cascade="all, delete-orphan",
    )


class Collection(Base):
    __tablename__ = "collections"
    __table_args__ = (
        UniqueConstraint("owner_id", "name", name="uq_collections_owner_name"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    owner_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    owner: Mapped["User"] = relationship(back_populates="collections")
    documents: Mapped[list["Document"]] = relationship(
        back_populates="collection",
        cascade="all, delete-orphan",
    )
    question_history: Mapped[list["QuestionHistory"]] = relationship(
        back_populates="collection",
        cascade="all, delete-orphan",
    )


class Document(Base):
    __tablename__ = "documents"
    __table_args__ = (
        UniqueConstraint(
            "collection_id",
            "content_sha256",
            name="uq_documents_collection_content_sha256",
        ),
        CheckConstraint(
            "processing_status IN ('pending', 'processing', 'completed', 'failed')",
            name="ck_documents_processing_status",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    collection_id: Mapped[UUID] = mapped_column(
        ForeignKey("collections.id", ondelete="CASCADE"), index=True
    )
    original_filename: Mapped[str] = mapped_column(Text)
    storage_key: Mapped[str] = mapped_column(String(32), unique=True)
    content_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    content_type: Mapped[str] = mapped_column(String(127))
    size_bytes: Mapped[int] = mapped_column(Integer)
    processing_status: Mapped[str] = mapped_column(
        String(20),
        default="pending",
        server_default="pending",
    )
    processing_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    collection: Mapped["Collection"] = relationship(back_populates="documents")
    chunks: Mapped[list["DocumentChunk"]] = relationship(
        back_populates="document",
        cascade="all, delete-orphan",
    )


class DocumentChunk(Base):
    __tablename__ = "document_chunks"
    __table_args__ = (
        UniqueConstraint(
            "document_id",
            "position",
            name="uq_document_chunks_document_position",
        ),
        CheckConstraint("position >= 0", name="ck_document_chunks_position"),
        CheckConstraint(
            "page_number IS NULL OR page_number > 0",
            name="ck_document_chunks_page_number",
        ),
        CheckConstraint(
            "(embedding IS NULL) = (embedding_model IS NULL)",
            name="ck_document_chunks_embedding_model_pair",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    document_id: Mapped[UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), index=True
    )
    position: Mapped[int] = mapped_column(Integer)
    page_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    content: Mapped[str] = mapped_column(Text)
    embedding: Mapped[list[float] | None] = mapped_column(
        VECTOR(EMBEDDING_DIMENSIONS).with_variant(
            JSON(none_as_null=True), "sqlite"
        ),
        nullable=True,
    )
    embedding_model: Mapped[str | None] = mapped_column(String(120), nullable=True)

    document: Mapped["Document"] = relationship(back_populates="chunks")


class QuestionHistory(Base):
    __tablename__ = "question_history"
    __table_args__ = (
        CheckConstraint(
            "strategy IN ('vector', 'text', 'hybrid')",
            name="ck_question_history_strategy",
        ),
        Index(
            "ix_question_history_collection_created_at",
            "collection_id",
            "created_at",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    collection_id: Mapped[UUID] = mapped_column(
        ForeignKey("collections.id", ondelete="CASCADE")
    )
    question: Mapped[str] = mapped_column(Text)
    strategy: Mapped[str] = mapped_column(String(10))
    document_ids: Mapped[list[str]] = mapped_column(
        JSON,
        nullable=False,
        default=list,
        server_default="[]",
    )
    answer: Mapped[str] = mapped_column(Text)
    sources: Mapped[list[dict[str, object]]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    collection: Mapped["Collection"] = relationship(back_populates="question_history")


Index(
    "ix_document_chunks_content_fts",
    func.to_tsvector(literal_column("'simple'"), DocumentChunk.content),
    postgresql_using="gin",
).ddl_if(dialect="postgresql")
