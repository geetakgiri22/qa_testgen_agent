"""Evaluation scorecard computed from deterministic validation results + run telemetry."""
from __future__ import annotations

from collections import Counter

from ..models import TEST_TYPES, Requirement, TestCase
from ..validation.validators import validate_all


def scorecard(cases: list[TestCase], reqs: list[Requirement], gen_stats: list[dict] | None = None) -> dict:
    rep = validate_all(cases, reqs)
    cov = rep["coverage"]
    n = len(cases)
    types_present = {c.values.get("Test Type") for c in cases}
    type_diversity = round(100 * len(types_present & set(TEST_TYPES)) / len(TEST_TYPES), 1)
    dup_rate = round(100 * len(rep["near_duplicates"]) / n, 1) if n else 0.0
    traced = sum(1 for c in cases if c.values.get("Requirement ID") and c.values["Requirement ID"] in c.values.get("Requirement Traceability", ""))
    trace_pct = round(100 * traced / n, 1) if n else 0.0
    weights = {"Validity": (rep["pass_rate_pct"], .30), "Requirement coverage": (cov.requirement_coverage_pct, .20),
               "Criteria coverage": (cov.criteria_coverage_pct, .20), "Traceability": (trace_pct, .15),
               "Type diversity": (type_diversity, .10), "Uniqueness": (100 - dup_rate, .05)}
    overall = round(sum(v * w for v, w in weights.values()), 1) if n else 0.0
    statuses = Counter(c.status for c in cases)
    stats = gen_stats or []
    return {
        "overall": overall, "components": {k: v for k, (v, _) in weights.items()},
        "validation": rep, "statuses": dict(statuses),
        "approval_rate_pct": round(100 * statuses.get("Approved", 0) / n, 1) if n else 0.0,
        "avg_seconds_per_requirement": round(sum(s["seconds"] for s in stats) / len(stats), 1) if stats else None,
        "generation_failures": [s for s in stats if s["error"]],
    }
