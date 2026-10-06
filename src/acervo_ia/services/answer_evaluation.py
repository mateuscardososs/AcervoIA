import math
import re
from collections.abc import Sequence
from dataclasses import dataclass

from acervo_ia.services.question_answering import AnswerSource
from acervo_ia.services.semantic_search import SearchHit

QUESTION_ID_PATTERN = re.compile(r"Q\d{2}\Z")
ANSWER_MODES = frozenset({"vector", "text", "hybrid"})


@dataclass(frozen=True)
class AnswerEvaluationRecord:
    answerable: bool
    expected_sections: frozenset[str]
    cited_sections: frozenset[str]
    source_count: int
    sources_valid: bool
    correct_abstention: bool
    correction_failed: bool
    error: bool
    latency_ms: float


def source_matches_search_hit(source: AnswerSource, hits: Sequence[SearchHit]) -> bool:
    """Return true only when the source ID and metadata match a returned hit."""
    if not source.source_id.startswith("S") or not source.source_id[1:].isdigit():
        return False
    index = int(source.source_id[1:]) - 1
    if index < 0 or index >= len(hits):
        return False
    hit = hits[index]
    return (
        source.source_id == f"S{index + 1}"
        and source.document_id == hit.document_id
        and source.document_name == hit.document_name
        and source.page_number == hit.page_number
        and source.snippet == hit.content
    )


def make_question_diagnostic(
    *,
    question_id: str,
    mode: str,
    answerable: bool,
    expected_section_retrieved: bool | None,
    expected_section_cited: bool,
    sources_valid: bool | None,
    correction_attempted: bool,
    correction_failed: bool,
    correct_abstention: bool,
    latency_ms: float,
    error: bool,
) -> dict[str, object]:
    """Build an allowlisted, content-free per-question diagnostic row."""
    if not QUESTION_ID_PATTERN.fullmatch(question_id) or mode not in ANSWER_MODES:
        raise ValueError("Question diagnostics require a synthetic ID and known mode.")

    if error and expected_section_retrieved is None:
        category = "execution_failure"
        expected_section_cited_value: bool | None = None
    elif not answerable:
        category = "correct_abstention" if correct_abstention and not error else "generation_failure"
        expected_section_retrieved = None
        expected_section_cited_value = None
    elif not expected_section_retrieved:
        category = "recovery_failure"
        expected_section_cited_value = expected_section_cited
    elif (
        error
        or not expected_section_cited
        or sources_valid is not True
        or correction_failed
    ):
        category = "generation_failure"
        expected_section_cited_value = expected_section_cited
    else:
        category = "none"
        expected_section_cited_value = expected_section_cited

    return {
        "question_id": question_id,
        "mode": mode,
        "category": category,
        "expected_section_retrieved": expected_section_retrieved,
        "expected_section_cited": expected_section_cited_value,
        "sources_valid": sources_valid,
        "correction_attempted": correction_attempted,
        "correction_failed": correction_failed,
        "latency_ms": round(latency_ms, 2),
    }


def _percentile(values: Sequence[float], percentile: float) -> float:
    ordered = sorted(values)
    rank = max(1, math.ceil(percentile * len(ordered)))
    return round(ordered[rank - 1], 2)


def calculate_answer_metrics(
    records: Sequence[AnswerEvaluationRecord],
) -> dict[str, object]:
    """Aggregate only non-sensitive counters and latency for one search mode."""
    if not records:
        raise ValueError("At least one answer evaluation record is required.")

    rows = list(records)
    answerable_count = sum(row.answerable for row in rows)
    unanswerable_count = len(rows) - answerable_count
    correct_abstentions = sum(
        not row.answerable and row.correct_abstention and row.source_count == 0
        for row in rows
    )
    answers_with_valid_sources = sum(
        row.source_count > 0 and row.sources_valid for row in rows
    )
    answerable_with_expected_sources = sum(
        row.answerable
        and row.source_count > 0
        and row.sources_valid
        and bool(row.expected_sections.intersection(row.cited_sections))
        for row in rows
    )
    latencies = [row.latency_ms for row in rows]

    return {
        "question_count": len(rows),
        "answerable_questions": answerable_count,
        "unanswerable_questions": unanswerable_count,
        "correct_abstentions": correct_abstentions,
        "correct_abstention_rate": (
            correct_abstentions / unanswerable_count if unanswerable_count else 0.0
        ),
        "answers_with_valid_sources": answers_with_valid_sources,
        "answers_with_invalid_sources": sum(
            row.source_count > 0 and not row.sources_valid for row in rows
        ),
        "answerable_with_expected_sources": answerable_with_expected_sources,
        "correction_failures": sum(row.correction_failed for row in rows),
        "errors": sum(row.error for row in rows),
        "latency_ms": {
            "mean": round(sum(latencies) / len(latencies), 2),
            "p95": _percentile(latencies, 0.95),
        },
    }
