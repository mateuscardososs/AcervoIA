from uuid import UUID

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from acervo_ia.db.models import Base, User
from acervo_ia.services.retrieval_evaluation import (
    calculate_metrics,
    rollback_and_close,
)
from acervo_ia.services.semantic_search import (
    SearchHit,
    build_full_text_statement,
    extract_literal_terms,
    fuse_rankings,
    normalize_literal,
)


def hit(index: int) -> SearchHit:
    return SearchHit(
        chunk_id=UUID(int=index),
        document_id=UUID(int=99),
        document_name="fictional.txt",
        page_number=None,
        position=index,
        content=f"Section {index}",
        score=1.0,
    )


def test_rrf_merges_ranked_lists_with_deterministic_ties() -> None:
    fused = fuse_rankings([[hit(1), hit(2)], [hit(2), hit(3)]], limit=3)

    assert [item.chunk_id for item in fused] == [UUID(int=2), UUID(int=1), UUID(int=3)]
    assert fused[0].score == pytest.approx(1 / 62 + 1 / 61)


def test_literal_normalization_and_term_extraction_match_codes_and_models() -> None:
    assert normalize_literal("E-17") == "e17"
    assert normalize_literal("CÓDIGO") == "codigo"
    terms = extract_literal_terms(
        "O que significa E-17 no Orion B20, AT-24, RS-232 e CELL?"
    )

    assert {"e17", "b20", "at24", "rs232", "cell"}.issubset(terms)
    assert "orion" not in terms
    assert "o" not in terms


def test_full_text_query_is_scoped_to_collection_and_uses_simple_configuration() -> None:
    statement = build_full_text_statement(
        collection_id=UUID(int=10), query="calibração E-17", limit=5
    )
    sql = str(statement.compile(dialect=postgresql.dialect()))

    assert "to_tsvector('simple', document_chunks.content)" in sql
    assert "websearch_to_tsquery('simple'," in sql
    assert "documents.collection_id" in sql
    assert "LIMIT" in sql


def test_retrieval_metrics_count_query_level_hits_and_first_relevant_rank() -> None:
    result = calculate_metrics(
        [
            {"expected": {"a"}, "ranked": ["x", "a"]},
            {"expected": {"b"}, "ranked": ["b"]},
            {"expected": {"c"}, "ranked": []},
        ]
    )

    assert result == {"recall_at_5": pytest.approx(2 / 3), "mrr": pytest.approx(0.5)}


def test_retrieval_metrics_reject_empty_answerable_set() -> None:
    with pytest.raises(ValueError, match="answerable"):
        calculate_metrics([])


def test_benchmark_session_helper_rolls_back_rows_even_on_failure() -> None:
    engine = create_engine("sqlite+pysqlite://")
    Base.metadata.create_all(engine)
    session = Session(engine)
    with pytest.raises(RuntimeError, match="simulated"):
        try:
            session.add(User(email="temporary-benchmark@example.test", password_hash="x"))
            session.flush()
            raise RuntimeError("simulated benchmark failure")
        finally:
            rollback_and_close(session)

    with Session(engine) as verification:
        assert verification.scalar(
            select(User).where(User.email == "temporary-benchmark@example.test")
        ) is None
    engine.dispose()


def test_benchmark_reuses_existing_thirty_question_fictional_corpus() -> None:
    from scripts.evaluate_retrieval import load_corpus

    sections, questions = load_corpus()

    assert len(sections) == 14
    assert len(questions) == 30
    assert sum(bool(item["answerable"]) for item in questions) == 25
    assert all(section["model"] in {"Orion B20", "Atlas T30"} for section in sections)
