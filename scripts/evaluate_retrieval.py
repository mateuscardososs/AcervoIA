"""Run the local retrieval benchmark against PostgreSQL and Ollama.

All database rows created by this command live in one transaction that is
always rolled back, including when retrieval or metric calculation fails.
"""

import json
import re
import sys
from pathlib import Path
from uuid import uuid4

from dotenv import load_dotenv
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[1]
SECTION_PATTERN = re.compile(r"(?m)^\[([A-Z0-9-]+)\].*$")


def load_corpus() -> tuple[list[dict[str, str]], list[dict[str, object]]]:
    sections: list[dict[str, str]] = []
    for path in sorted((ROOT / "data" / "demo").glob("manual-*.txt")):
        content = path.read_text(encoding="utf-8")
        headings = list(SECTION_PATTERN.finditer(content))
        for index, heading in enumerate(headings):
            end = (
                headings[index + 1].start()
                if index + 1 < len(headings)
                else len(content)
            )
            sections.append(
                {
                    "model": (
                        "Orion B20"
                        if heading.group(1).startswith("ORION")
                        else "Atlas T30"
                    ),
                    "section": heading.group(1),
                    "content": content[heading.start() : end].strip(),
                    "filename": path.name,
                }
            )
    questions = json.loads(
        (ROOT / "data" / "demo" / "questions.json").read_text(encoding="utf-8")
    )
    if len(questions) != 30 or sum(
        bool(item["answerable"]) for item in questions
    ) != 25:
        raise ValueError(
            "The benchmark corpus must contain 25 answerable and 5 unanswerable questions."
        )
    return sections, questions


def evaluate() -> dict[str, object]:
    load_dotenv(ROOT / ".env", override=False)
    from acervo_ia import config
    from acervo_ia.db.connection import get_engine
    from acervo_ia.db.models import Collection, Document, DocumentChunk, User
    from acervo_ia.services.embeddings import generate_embeddings
    from acervo_ia.services.retrieval_evaluation import (
        calculate_metrics,
        rollback_and_close,
    )
    from acervo_ia.services.semantic_search import (
        search_chunks,
        search_hybrid_chunks,
        search_text_chunks,
    )

    sections, questions = load_corpus()
    model = config.OLLAMA_EMBEDDING_MODEL
    texts = [section["content"] for section in sections]
    texts.extend(question["question"] for question in questions)
    vectors = generate_embeddings(texts, model=model)
    section_vectors = vectors[: len(sections)]
    question_vectors = vectors[len(sections) :]

    session = Session(get_engine(), autoflush=False, expire_on_commit=False)
    result: dict[str, object] | None = None
    try:
        user = User(
            email=f"retrieval-benchmark-{uuid4().hex}@example.invalid",
            password_hash="benchmark-only",
        )
        session.add(user)
        session.flush()
        collections = {
            equipment: Collection(owner_id=user.id, name=f"Benchmark {equipment}")
            for equipment in ("Orion B20", "Atlas T30")
        }
        session.add_all(collections.values())
        session.flush()
        documents = {
            equipment: Document(
                collection_id=collection.id,
                original_filename=next(
                    section["filename"]
                    for section in sections
                    if section["model"] == equipment
                ),
                storage_key=uuid4().hex,
                content_type="text/plain",
                size_bytes=0,
                processing_status="completed",
            )
            for equipment, collection in collections.items()
        }
        session.add_all(documents.values())
        session.flush()

        chunk_sections: dict[object, str] = {}
        positions = {equipment: 0 for equipment in collections}
        for section, vector in zip(sections, section_vectors, strict=True):
            equipment = section["model"]
            chunk = DocumentChunk(
                document_id=documents[equipment].id,
                position=positions[equipment],
                content=section["content"],
                embedding=vector,
                embedding_model=model,
            )
            positions[equipment] += 1
            session.add(chunk)
            session.flush()
            chunk_sections[chunk.id] = section["section"]

        ranked: dict[str, list[dict[str, object]]] = {
            strategy: [] for strategy in ("vector", "text", "hybrid")
        }
        unanswered_hits = {strategy: 0 for strategy in ranked}
        for question, query_vector in zip(questions, question_vectors, strict=True):
            equipment = question["filters"]["model"]
            collection_id = collections[equipment].id
            result_hits = {
                "vector": search_chunks(
                    session,
                    collection_id=collection_id,
                    embedding=query_vector,
                    embedding_model=model,
                    limit=5,
                ),
                "text": search_text_chunks(
                    session,
                    collection_id=collection_id,
                    query=question["question"],
                    limit=5,
                ),
                "hybrid": search_hybrid_chunks(
                    session,
                    collection_id=collection_id,
                    query=question["question"],
                    embedding=query_vector,
                    embedding_model=model,
                    limit=5,
                ),
            }
            expected = set(question["expected_sections"])
            for strategy, hits in result_hits.items():
                section_ids = [chunk_sections[hit.chunk_id] for hit in hits]
                ranked[strategy].append({"expected": expected, "ranked": section_ids})
                if not question["answerable"] and section_ids:
                    unanswered_hits[strategy] += 1

        result = {
            "embedding_model": model,
            "questions": len(questions),
            "answerable": 25,
            "unanswerable": 5,
            "metrics": {
                strategy: calculate_metrics(items)
                for strategy, items in ranked.items()
            },
            "unanswerable_with_results_at_5": unanswered_hits,
        }
    finally:
        # Never commit benchmark users, collections, documents, or vectors.
        rollback_and_close(session)
    assert result is not None
    return result


def main() -> int:
    from acervo_ia.db.connection import DatabaseUnavailableError
    from acervo_ia.services.embeddings import EmbeddingServiceError

    try:
        print(json.dumps(evaluate(), ensure_ascii=False, indent=2))
    except (
        DatabaseUnavailableError,
        SQLAlchemyError,
        EmbeddingServiceError,
        OSError,
        ValueError,
    ):
        # In particular, do not print driver errors or tracebacks that can include
        # the database URL or other local connection details.
        print(
            "Benchmark indisponível: verifique PostgreSQL, migrações e Ollama local.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
