import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass, replace
from uuid import UUID

from sqlalchemy import Select, desc, func, literal_column, select
from sqlalchemy.orm import Session

from acervo_ia import config
from acervo_ia.db.models import Document, DocumentChunk


@dataclass(frozen=True)
class SearchHit:
    chunk_id: UUID
    document_id: UUID
    document_name: str
    page_number: int | None
    position: int
    content: str
    score: float


RRF_K = 60
_TOKEN_PATTERN = re.compile(
    r"(?<![A-Za-z0-9])[A-Za-z0-9]+(?:[-_/][A-Za-z0-9]+)*(?![A-Za-z0-9])"
)


def normalize_literal(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value.casefold())
    return "".join(
        character
        for character in decomposed
        if not unicodedata.combining(character) and character.isalnum()
    )


def extract_literal_terms(text: str) -> set[str]:
    terms: set[str] = set()
    for match in _TOKEN_PATTERN.finditer(text):
        raw = match.group(0)
        # A digit makes a token code/model-like. Uppercase abbreviations are
        # retained too, without treating every capitalized sentence word as one.
        if any(character.isdigit() for character in raw) or (
            raw.isupper() and 2 <= len(raw) <= 10
        ):
            normalized = normalize_literal(raw)
            if len(normalized) >= 2:
                terms.add(normalized)
    return terms


def _hit_from_row(chunk: DocumentChunk, document: Document, score: float) -> SearchHit:
    return SearchHit(
        chunk_id=chunk.id,
        document_id=document.id,
        document_name=document.original_filename,
        page_number=chunk.page_number,
        position=chunk.position,
        content=chunk.content,
        score=score,
    )


def build_search_statement(
    *,
    collection_id: UUID,
    embedding: list[float],
    embedding_model: str,
    embedding_provider: str | None = None,
    limit: int,
    document_ids: Sequence[UUID] | None = None,
) -> Select[tuple[DocumentChunk, Document, float]]:
    distance = DocumentChunk.embedding.cosine_distance(embedding).label("distance")
    statement = (
        select(DocumentChunk, Document, distance)
        .join(Document, Document.id == DocumentChunk.document_id)
        .where(
            Document.collection_id == collection_id,
            DocumentChunk.embedding.is_not(None),
            DocumentChunk.embedding_model == embedding_model,
            DocumentChunk.embedding_provider
            == (embedding_provider or config.EMBEDDING_PROVIDER),
        )
    )
    if document_ids:
        statement = statement.where(Document.id.in_(document_ids))
    return statement.order_by(distance).limit(limit)


def search_chunks(
    session: Session,
    *,
    collection_id: UUID,
    embedding: list[float],
    embedding_model: str,
    embedding_provider: str | None = None,
    limit: int,
    document_ids: Sequence[UUID] | None = None,
) -> list[SearchHit]:
    rows = session.execute(
        build_search_statement(
            collection_id=collection_id,
            embedding=embedding,
            embedding_model=embedding_model,
            embedding_provider=embedding_provider,
            limit=limit,
            document_ids=document_ids,
        )
    ).all()
    return [
        _hit_from_row(chunk, document, 1.0 - distance)
        for chunk, document, distance in rows
    ]


def build_full_text_statement(
    *,
    collection_id: UUID,
    query: str,
    limit: int,
    document_ids: Sequence[UUID] | None = None,
) -> Select[tuple[DocumentChunk, Document, float]]:
    config = literal_column("'simple'")
    vector = func.to_tsvector(config, DocumentChunk.content)
    tsquery = func.websearch_to_tsquery(config, query)
    rank = func.ts_rank_cd(vector, tsquery).label("rank")
    statement = (
        select(DocumentChunk, Document, rank)
        .join(Document, Document.id == DocumentChunk.document_id)
        .where(Document.collection_id == collection_id, vector.op("@@")(tsquery))
    )
    if document_ids:
        statement = statement.where(Document.id.in_(document_ids))
    return statement.order_by(desc(rank), DocumentChunk.position, DocumentChunk.id).limit(limit)


def search_full_text_chunks(
    session: Session,
    *,
    collection_id: UUID,
    query: str,
    limit: int,
    document_ids: Sequence[UUID] | None = None,
) -> list[SearchHit]:
    rows = session.execute(
        build_full_text_statement(
            collection_id=collection_id,
            query=query,
            limit=limit,
            document_ids=document_ids,
        )
    ).all()
    return [_hit_from_row(chunk, document, float(rank)) for chunk, document, rank in rows]


def search_literal_chunks(
    session: Session,
    *,
    collection_id: UUID,
    query: str,
    limit: int,
    document_ids: Sequence[UUID] | None = None,
) -> list[SearchHit]:
    query_terms = extract_literal_terms(query)
    if not query_terms:
        return []
    rows = session.execute(
        build_literal_statement(
            collection_id=collection_id,
            document_ids=document_ids,
        )
    ).all()
    matches: list[SearchHit] = []
    for chunk, document in rows:
        overlap = query_terms & extract_literal_terms(chunk.content)
        if overlap:
            matches.append(
                _hit_from_row(chunk, document, len(overlap) / len(query_terms))
            )
    matches.sort(key=lambda hit: (-hit.score, hit.position, str(hit.chunk_id)))
    return matches[:limit]


def build_literal_statement(
    *, collection_id: UUID, document_ids: Sequence[UUID] | None = None
) -> Select[tuple[DocumentChunk, Document]]:
    statement = (
        select(DocumentChunk, Document)
        .join(Document, Document.id == DocumentChunk.document_id)
        .where(Document.collection_id == collection_id)
        .order_by(DocumentChunk.position, DocumentChunk.id)
    )
    if document_ids:
        statement = statement.where(Document.id.in_(document_ids))
    return statement


def fuse_rankings(
    rankings: list[list[SearchHit]], *, limit: int, rrf_k: int = RRF_K
) -> list[SearchHit]:
    accumulated: dict[UUID, float] = {}
    representatives: dict[UUID, SearchHit] = {}
    for ranking in rankings:
        seen: set[UUID] = set()
        for rank, hit in enumerate(ranking, start=1):
            if hit.chunk_id in seen:
                continue
            seen.add(hit.chunk_id)
            representatives.setdefault(hit.chunk_id, hit)
            accumulated[hit.chunk_id] = accumulated.get(hit.chunk_id, 0.0) + 1.0 / (
                rrf_k + rank
            )
    ranked_ids = sorted(
        accumulated,
        key=lambda chunk_id: (
            -accumulated[chunk_id],
            representatives[chunk_id].position,
            str(chunk_id),
        ),
    )[:limit]
    return [
        replace(representatives[chunk_id], score=accumulated[chunk_id])
        for chunk_id in ranked_ids
    ]


def search_text_chunks(
    session: Session,
    *,
    collection_id: UUID,
    query: str,
    limit: int,
    document_ids: Sequence[UUID] | None = None,
) -> list[SearchHit]:
    # Oversample the component lists so RRF can still fill the requested page.
    component_limit = max(limit * 4, 20)
    return fuse_rankings(
        [
            search_full_text_chunks(
                session,
                collection_id=collection_id,
                query=query,
                limit=component_limit,
                document_ids=document_ids,
            ),
            search_literal_chunks(
                session,
                collection_id=collection_id,
                query=query,
                limit=component_limit,
                document_ids=document_ids,
            ),
        ],
        limit=limit,
    )


def search_hybrid_chunks(
    session: Session,
    *,
    collection_id: UUID,
    query: str,
    embedding: list[float],
    embedding_model: str,
    embedding_provider: str | None = None,
    limit: int,
    document_ids: Sequence[UUID] | None = None,
) -> list[SearchHit]:
    component_limit = max(limit * 4, 20)
    return fuse_rankings(
        [
            search_chunks(
                session,
                collection_id=collection_id,
                embedding=embedding,
                embedding_model=embedding_model,
                embedding_provider=embedding_provider,
                limit=component_limit,
                document_ids=document_ids,
            ),
            search_text_chunks(
                session,
                collection_id=collection_id,
                query=query,
                limit=component_limit,
                document_ids=document_ids,
            ),
        ],
        limit=limit,
    )
