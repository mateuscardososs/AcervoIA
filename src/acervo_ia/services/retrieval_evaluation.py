from collections.abc import Mapping, Sequence
from typing import Any

from sqlalchemy.orm import Session


def rollback_and_close(session: Session) -> None:
    """Discard all uncommitted benchmark rows and release the connection."""
    try:
        session.rollback()
    finally:
        session.close()


def calculate_metrics(
    queries: Sequence[Mapping[str, Any]], *, cutoff: int = 5
) -> dict[str, float]:
    """Calculate query-level hit Recall@k and MRR over answerable questions."""
    answerable = [query for query in queries if query.get("expected")]
    if not answerable:
        raise ValueError("At least one answerable question is required.")

    recall_hits = 0
    reciprocal_ranks = 0.0
    for query in answerable:
        expected = set(query["expected"])
        ranked = list(query.get("ranked", []))
        if expected.intersection(ranked[:cutoff]):
            recall_hits += 1
        reciprocal_ranks += next(
            (1.0 / rank for rank, section in enumerate(ranked, start=1) if section in expected),
            0.0,
        )

    count = len(answerable)
    return {
        f"recall_at_{cutoff}": recall_hits / count,
        "mrr": reciprocal_ranks / count,
    }
