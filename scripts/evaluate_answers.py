"""Evaluate real answer generation against the fictional retrieval corpus.

The command reports aggregate counters only. All benchmark database records
share one uncommitted transaction that is rolled back even when a mode fails.
"""

import json
import sys
from pathlib import Path
from time import perf_counter
from typing import Any
from uuid import uuid4

from dotenv import load_dotenv
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[1]
STRATEGIES = ("vector", "text", "hybrid")


def evaluate_in_session(
    session: Session,
    *,
    sections: list[dict[str, str]],
    questions: list[dict[str, Any]],
    section_vectors: list[list[float]],
    embedding_model: str,
) -> dict[str, object]:
    """Seed, ask through the shared QA service, aggregate, and always roll back."""
    from acervo_ia.db.models import Collection, Document, DocumentChunk, User
    from acervo_ia.services.answer_evaluation import (
        AnswerEvaluationRecord,
        calculate_answer_metrics,
        make_question_diagnostic,
        source_matches_search_hit,
    )
    from acervo_ia.services.question_answering import (
        NO_EVIDENCE_ANSWER,
        InvalidModelAnswer,
        answer_question,
    )

    result: dict[str, object] | None = None
    try:
        if len(sections) != len(section_vectors):
            raise ValueError("Every benchmark section must have one embedding.")

        user = User(
            email=f"answer-benchmark-{uuid4().hex}@example.invalid",
            password_hash="benchmark-only",
        )
        session.add(user)
        session.flush()

        equipment_names = tuple(dict.fromkeys(section["model"] for section in sections))
        collections = {
            equipment: Collection(owner_id=user.id, name=f"Answer Benchmark {equipment}")
            for equipment in equipment_names
        }
        session.add_all(collections.values())
        session.flush()

        documents = {
            equipment: Document(
                collection_id=collections[equipment].id,
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
            for equipment in equipment_names
        }
        session.add_all(documents.values())
        session.flush()

        section_by_chunk: dict[object, str] = {}
        positions = {equipment: 0 for equipment in equipment_names}
        for section, vector in zip(sections, section_vectors, strict=True):
            equipment = section["model"]
            chunk = DocumentChunk(
                document_id=documents[equipment].id,
                position=positions[equipment],
                content=section["content"],
                embedding=vector,
                embedding_model=embedding_model,
            )
            positions[equipment] += 1
            session.add(chunk)
            session.flush()
            section_by_chunk[chunk.id] = section["section"]

        records: dict[str, list[AnswerEvaluationRecord]] = {
            strategy: [] for strategy in STRATEGIES
        }
        diagnostics: list[dict[str, object]] = []
        for question in questions:
            equipment = question["filters"]["model"]
            collection_id = collections[equipment].id
            expected = frozenset(question["expected_sections"])
            for strategy in STRATEGIES:
                started = perf_counter()
                try:
                    answer = answer_question(
                        session,
                        collection_id=collection_id,
                        question=question["question"],
                        limit=5,
                        strategy=strategy,
                    )
                except InvalidModelAnswer as error:
                    latency_ms = (perf_counter() - started) * 1_000
                    retrieved_hits = error.retrieved_hits
                    expected_retrieved = any(
                        section_by_chunk.get(hit.chunk_id) in expected
                        for hit in retrieved_hits
                    )
                    diagnostics.append(
                        make_question_diagnostic(
                            question_id=str(question["id"]),
                            mode=strategy,
                            answerable=bool(question["answerable"]),
                            expected_section_retrieved=(
                                expected_retrieved
                                if bool(question["answerable"])
                                and error.search_completed
                                else None
                            ),
                            expected_section_cited=False,
                            sources_valid=None,
                            correction_attempted=False,
                            correction_failed=False,
                            correct_abstention=False,
                            latency_ms=latency_ms,
                            error=True,
                        )
                    )
                    records[strategy].append(
                        AnswerEvaluationRecord(
                            answerable=bool(question["answerable"]),
                            expected_sections=expected,
                            cited_sections=frozenset(),
                            source_count=0,
                            sources_valid=False,
                            correct_abstention=False,
                            correction_failed=False,
                            error=True,
                            latency_ms=latency_ms,
                        )
                    )
                    continue

                latency_ms = (perf_counter() - started) * 1_000
                sources_valid = (
                    all(
                        source_matches_search_hit(source, answer.retrieved_hits)
                        for source in answer.sources
                    )
                    if answer.sources
                    else False if answer.correction_failed else None
                )
                cited_sections: set[str] = set()
                if sources_valid is True:
                    for source in answer.sources:
                        source_index = int(source.source_id[1:]) - 1
                        hit = answer.retrieved_hits[source_index]
                        section_label = section_by_chunk.get(hit.chunk_id)
                        if section_label is not None:
                            cited_sections.add(section_label)

                expected_retrieved = any(
                    section_by_chunk.get(hit.chunk_id) in expected
                    for hit in answer.retrieved_hits
                )
                expected_cited = bool(expected.intersection(cited_sections))
                correct_abstention = (
                    not bool(question["answerable"])
                    and not answer.sources
                    and answer.answer == NO_EVIDENCE_ANSWER
                )
                diagnostics.append(
                    make_question_diagnostic(
                        question_id=str(question["id"]),
                        mode=strategy,
                        answerable=bool(question["answerable"]),
                        expected_section_retrieved=(
                            expected_retrieved if bool(question["answerable"]) else None
                        ),
                        expected_section_cited=expected_cited,
                        sources_valid=sources_valid,
                        correction_attempted=answer.correction_attempted,
                        correction_failed=answer.correction_failed,
                        correct_abstention=correct_abstention,
                        latency_ms=latency_ms,
                        error=False,
                    )
                )

                records[strategy].append(
                    AnswerEvaluationRecord(
                        answerable=bool(question["answerable"]),
                        expected_sections=expected,
                        cited_sections=frozenset(cited_sections),
                        source_count=len(answer.sources),
                        sources_valid=sources_valid is True,
                        correct_abstention=correct_abstention,
                        correction_failed=answer.correction_failed,
                        error=False,
                        latency_ms=latency_ms,
                    )
                )

        result = {
            "question_count": len(questions),
            "answerable_questions": sum(bool(item["answerable"]) for item in questions),
            "unanswerable_questions": sum(not bool(item["answerable"]) for item in questions),
            "modes": {
                strategy: calculate_answer_metrics(records[strategy])
                for strategy in STRATEGIES
            },
            "diagnostic_counts": {
                strategy: {
                    category: sum(
                        item["mode"] == strategy and item["category"] == category
                        for item in diagnostics
                    )
                    for category in (
                        "recovery_failure",
                        "generation_failure",
                        "execution_failure",
                        "correct_abstention",
                        "none",
                    )
                }
                for strategy in STRATEGIES
            },
            "diagnostics": diagnostics,
        }
    finally:
        from acervo_ia.services.retrieval_evaluation import rollback_and_close

        rollback_and_close(session)

    assert result is not None
    return result


def evaluate() -> dict[str, object]:
    from acervo_ia import config
    from acervo_ia.db.connection import get_engine
    from acervo_ia.services.benchmark_corpus import load_corpus
    from acervo_ia.services.embeddings import generate_embeddings

    sections, questions = load_corpus()
    engine = get_engine()
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        section_vectors = generate_embeddings(
            [section["content"] for section in sections],
            model=config.OLLAMA_EMBEDDING_MODEL,
        )
        session = Session(engine, autoflush=False, expire_on_commit=False)
        return evaluate_in_session(
            session,
            sections=sections,
            questions=questions,
            section_vectors=section_vectors,
            embedding_model=config.OLLAMA_EMBEDDING_MODEL,
        )
    finally:
        engine.dispose()


def main() -> int:
    load_dotenv(ROOT / ".env", override=False)
    from acervo_ia.db.connection import DatabaseUnavailableError
    from acervo_ia.services.chat import ChatModelError
    from acervo_ia.services.embeddings import EmbeddingServiceError

    try:
        print(json.dumps(evaluate(), ensure_ascii=False, indent=2))
    except (DatabaseUnavailableError, SQLAlchemyError):
        print(
            "Benchmark não executado: PostgreSQL indisponível ou não preparado.",
            file=sys.stderr,
        )
        return 2
    except (EmbeddingServiceError, ChatModelError):
        print(
            "Benchmark não executado: Ollama indisponível ou modelo local não utilizável.",
            file=sys.stderr,
        )
        return 3
    except Exception:
        print(
            "Benchmark interrompido por uma falha interna; nenhum resultado aprovado.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
