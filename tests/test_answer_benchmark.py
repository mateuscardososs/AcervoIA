import json
from uuid import UUID

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from acervo_ia.db.models import Base, User
from acervo_ia.services import question_answering
from acervo_ia.services.question_answering import AnswerSource
from acervo_ia.services.answer_evaluation import (
    AnswerEvaluationRecord,
    calculate_answer_metrics,
    source_matches_search_hit,
)
from acervo_ia.services.semantic_search import SearchHit


def make_record(
    *,
    answerable: bool,
    expected: set[str] | None = None,
    cited: set[str] | None = None,
    source_count: int = 0,
    sources_valid: bool = False,
    correct_abstention: bool = False,
    correction_failed: bool = False,
    error: bool = False,
    latency_ms: float = 0,
) -> AnswerEvaluationRecord:
    return AnswerEvaluationRecord(
        answerable=answerable,
        expected_sections=frozenset(expected or set()),
        cited_sections=frozenset(cited or set()),
        source_count=source_count,
        sources_valid=sources_valid,
        correct_abstention=correct_abstention,
        correction_failed=correction_failed,
        error=error,
        latency_ms=latency_ms,
    )


def test_answer_metrics_aggregate_abstentions_sources_corrections_errors_and_latency() -> None:
    metrics = calculate_answer_metrics(
        [
            make_record(
                answerable=True,
                expected={"ORION-02"},
                cited={"ORION-02"},
                source_count=1,
                sources_valid=True,
                latency_ms=10,
            ),
            make_record(
                answerable=True,
                expected={"ORION-05"},
                cited={"ORION-03"},
                source_count=1,
                sources_valid=False,
                latency_ms=20,
            ),
            make_record(
                answerable=False,
                correct_abstention=True,
                latency_ms=30,
            ),
            make_record(
                answerable=False,
                source_count=1,
                sources_valid=True,
                correction_failed=True,
                latency_ms=40,
            ),
            make_record(answerable=False, error=True, latency_ms=50),
        ]
    )

    assert metrics["question_count"] == 5
    assert metrics["answerable_questions"] == 2
    assert metrics["unanswerable_questions"] == 3
    assert metrics["correct_abstentions"] == 1
    assert metrics["correct_abstention_rate"] == pytest.approx(1 / 3)
    assert metrics["answers_with_valid_sources"] == 2
    assert metrics["answers_with_invalid_sources"] == 1
    assert metrics["answerable_with_expected_sources"] == 1
    assert metrics["correction_failures"] == 1
    assert metrics["errors"] == 1
    assert metrics["latency_ms"] == {
        "mean": 30,
        "p95": 50,
    }


def test_answer_metrics_reject_empty_input() -> None:
    with pytest.raises(ValueError, match="At least one"):
        calculate_answer_metrics([])


def test_a_source_counts_only_when_its_id_and_metadata_match_a_real_search_hit() -> None:
    hit = SearchHit(
        chunk_id=UUID(int=1),
        document_id=UUID(int=2),
        document_name="manual-fictional.txt",
        page_number=3,
        position=0,
        content="Trecho fictício.",
        score=0.8,
    )
    source = AnswerSource(
        source_id="S1",
        document_id=hit.document_id,
        document_name=hit.document_name,
        page_number=hit.page_number,
        snippet=hit.content,
    )

    assert source_matches_search_hit(source, [hit]) is True
    assert source_matches_search_hit(source, []) is False
    assert source_matches_search_hit(
        AnswerSource("S2", hit.document_id, hit.document_name, hit.page_number, hit.content),
        [hit],
    ) is False
    assert source_matches_search_hit(
        AnswerSource("S1", hit.document_id, hit.document_name, hit.page_number, "other"),
        [hit],
    ) is False


def test_shared_qa_service_reports_correction_failure_without_sources(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    hit = SearchHit(
        chunk_id=UUID(int=1),
        document_id=UUID(int=2),
        document_name="manual-fictional.txt",
        page_number=None,
        position=0,
        content="Conteúdo fictício.",
        score=0.8,
    )
    responses = iter(
        [
            json.dumps({"answer": "Resposta [S9]", "citations": ["S9"]}),
            json.dumps({"answer": "Resposta [S9]", "citations": ["S9"]}),
        ]
    )
    monkeypatch.setattr(
        question_answering,
        "search_text_chunks",
        lambda *args, **kwargs: [hit],
    )
    monkeypatch.setattr(
        question_answering,
        "generate_chat_completion",
        lambda _messages: next(responses),
    )

    answer = question_answering.answer_question(
        None,  # Text mode uses the mocked search and does not embed the query.
        collection_id=UUID(int=3),
        question="Pergunta privada que não entra no relatório",
        limit=5,
        strategy="text",
    )

    assert answer.correction_attempted is True
    assert answer.correction_failed is True
    assert answer.sources == ()
    assert answer.retrieved_hits == (hit,)


def test_answer_benchmark_rolls_back_seeded_rows_when_mode_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from scripts import evaluate_answers

    engine = create_engine("sqlite+pysqlite://")
    Base.metadata.create_all(engine)
    session = Session(engine, autoflush=False, expire_on_commit=False)

    def fail_answer(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("simulated local model failure")

    monkeypatch.setattr(
        question_answering,
        "answer_question",
        fail_answer,
    )

    with pytest.raises(RuntimeError, match="simulated"):
        evaluate_answers.evaluate_in_session(
            session,
            sections=[
                {
                    "model": "Orion B20",
                    "section": "ORION-02",
                    "content": "Conteúdo fictício.",
                    "filename": "manual-orion.txt",
                }
            ],
            questions=[
                {
                    "question": "Pergunta fictícia?",
                    "answerable": True,
                    "filters": {"model": "Orion B20"},
                    "expected_sections": ["ORION-02"],
                }
            ],
            section_vectors=[[0.0] * 768],
            embedding_model="simulated-embedding",
        )

    with Session(engine) as verification:
        assert verification.scalar(select(User)) is None
    engine.dispose()


def test_answer_benchmark_report_does_not_include_question_or_document_content(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from scripts import evaluate_answers
    from acervo_ia.services.question_answering import AnswerResult

    engine = create_engine("sqlite+pysqlite://")
    Base.metadata.create_all(engine)
    session = Session(engine, autoflush=False, expire_on_commit=False)
    monkeypatch.setattr(
        question_answering,
        "answer_question",
        lambda *_args, **_kwargs: AnswerResult(
            "Não encontrei evidência suficiente.", (), ()
        ),
    )
    private_question = "question-sentinel-must-not-be-reported"
    private_document = "document-sentinel-must-not-be-reported"
    report = evaluate_answers.evaluate_in_session(
        session,
        sections=[
            {
                "model": "Orion B20",
                "section": "ORION-02",
                "content": private_document,
                "filename": "fictional-manual.txt",
            }
        ],
        questions=[
            {
                "question": private_question,
                "answerable": True,
                "filters": {"model": "Orion B20"},
                "expected_sections": ["ORION-02"],
            }
        ],
        section_vectors=[[0.0] * 768],
        embedding_model="simulated-embedding",
    )
    serialized = json.dumps(report)

    assert report["question_count"] == 1
    assert private_question not in serialized
    assert private_document not in serialized
    engine.dispose()


def test_unavailable_ollama_is_reported_without_provider_details(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from scripts import evaluate_answers
    from acervo_ia.services.embeddings import EmbeddingServiceError

    monkeypatch.setattr(evaluate_answers, "load_dotenv", lambda *_args, **_kwargs: None)

    def unavailable() -> None:
        raise EmbeddingServiceError("private provider endpoint and credentials")

    monkeypatch.setattr(evaluate_answers, "evaluate", unavailable)

    assert evaluate_answers.main() == 3
    captured = capsys.readouterr()
    assert "Ollama indisponível" in captured.err
    assert "private provider" not in captured.err
    assert captured.out == ""


def test_unavailable_postgres_is_reported_without_connection_details(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from scripts import evaluate_answers
    from acervo_ia.db.connection import DatabaseUnavailableError

    monkeypatch.setattr(evaluate_answers, "load_dotenv", lambda *_args, **_kwargs: None)

    def unavailable() -> None:
        raise DatabaseUnavailableError("private database URL and password")

    monkeypatch.setattr(evaluate_answers, "evaluate", unavailable)

    assert evaluate_answers.main() == 2
    captured = capsys.readouterr()
    assert "PostgreSQL indisponível" in captured.err
    assert "private database" not in captured.err
    assert captured.out == ""
