"""
Composite DQ scorer — aggregates all five dimension checks into a single score.

Weighting:
- Completeness:           25%
- Uniqueness:             20%
- Validity:               25%
- Timeliness:             15%
- Referential Integrity:  15%

Pass threshold: configurable (default 85%).
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import text
from sqlalchemy.orm import Session

from src.config import settings
from src.logging_config import get_logger
from src.quality.checks import CheckResult, DQChecks

logger = get_logger("dq_scorer")

# Dimension weights (must sum to 1.0)
DIMENSION_WEIGHTS: dict[str, float] = {
    "completeness": 0.25,
    "uniqueness": 0.20,
    "validity": 0.25,
    "timeliness": 0.15,
    "referential_integrity": 0.15,
}


class DQScorer:
    """
    Runs all DQ checks and computes a weighted composite score.

    Persists individual and composite scores to the dq_results table
    for historical trending.
    """

    def __init__(self, session: Session, run_id: str):
        self.session = session
        self.run_id = run_id
        self.checks = DQChecks(session=session)
        self.threshold = settings.dq_pass_threshold

    def run_all_checks(self) -> float:
        """
        Execute all DQ checks, compute composite score, persist results.

        Returns:
            Composite DQ score (0-100).
        """
        all_results: dict[str, list[CheckResult]] = {}

        # Run each dimension
        all_results["completeness"] = self.checks.check_completeness()
        all_results["uniqueness"] = self.checks.check_uniqueness()
        all_results["validity"] = self.checks.check_validity()
        all_results["timeliness"] = self.checks.check_timeliness()
        all_results["referential_integrity"] = self.checks.check_referential_integrity()

        # Compute per-dimension average scores
        dimension_scores: dict[str, float] = {}
        for dimension, results in all_results.items():
            if results:
                avg = sum(r.score for r in results) / len(results)
            else:
                avg = 100.0
            dimension_scores[dimension] = avg

        # Compute weighted composite score
        composite_score = sum(dimension_scores[dim] * weight for dim, weight in DIMENSION_WEIGHTS.items())
        composite_score = round(composite_score, 2)
        passed = composite_score >= self.threshold

        # Persist results to dq_results table
        self._persist_results(all_results, composite_score, passed)

        logger.info(
            "dq_composite_score",
            score=composite_score,
            passed=passed,
            threshold=self.threshold,
            dimension_scores=dimension_scores,
        )

        return composite_score

    def _persist_results(
        self,
        all_results: dict[str, list[CheckResult]],
        composite_score: float,
        passed: bool,
    ) -> None:
        """Persist each check result and the composite score to dq_results."""
        now = datetime.now(timezone.utc)

        import json

        for dimension, results in all_results.items():
            weight = DIMENSION_WEIGHTS.get(dimension, 0.0)
            for result in results:
                self.session.execute(
                    text("""
                        INSERT INTO dq_results
                        (run_id, check_dimension, table_name, score, weight, details,
                         checked_at, composite_score, passed)
                        VALUES
                        (:run_id, :dim, :table, :score, :weight, CAST(:details AS jsonb),
                         :checked_at, :composite, :passed)
                    """),
                    {
                        "run_id": self.run_id,
                        "dim": dimension,
                        "table": result.table_name,
                        "score": result.score,
                        "weight": weight,
                        "details": json.dumps(result.details or {}),
                        "checked_at": now,
                        "composite": composite_score,
                        "passed": passed,
                    },
                )

        self.session.commit()
        logger.info("dq_results_persisted", run_id=self.run_id, check_count=sum(len(r) for r in all_results.values()))
