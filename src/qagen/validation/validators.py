"""Deterministic (non-LLM) quality controls for generated test cases."""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from difflib import SequenceMatcher

from ..models import MANDATORY_FIELDS, TestCase, Requirement

VAGUE_RESULTS = {"", "tbd", "n/a", "na", "none", "todo", "ok", "works", "success", "pass", "as expected",
                 "works as expected", "should work", "it works", "no error", "-"}
MIN_EXPECTED_LEN = 12
DUP_THRESHOLD = 0.88


# ------------------------------------------------------------ single-case checks
def check_mandatory(tc: TestCase) -> list[str]:
    return [f"Missing mandatory field: {f}" for f in MANDATORY_FIELDS if not str(tc.values.get(f, "")).strip()]


def check_expected_result(tc: TestCase) -> list[str]:
    er = str(tc.values.get("Expected Result", "")).strip()
    if not er:
        return []  # already reported as missing
    if er.lower().rstrip(".") in VAGUE_RESULTS:
        return ["Expected result is vague/placeholder"]
    if len(er) < MIN_EXPECTED_LEN:
        return [f"Expected result too short (<{MIN_EXPECTED_LEN} chars)"]
    return []


def check_traceability(tc: TestCase, known_ids: set[str]) -> list[str]:
    rid = str(tc.values.get("Requirement ID", "")).strip()
    issues = []
    if rid and rid not in known_ids:
        issues.append(f"Requirement ID '{rid}' does not exist in the loaded requirements")
    trace = str(tc.values.get("Requirement Traceability", ""))
    if rid and rid not in trace:
        issues.append("Requirement Traceability field does not reference the Requirement ID")
    return issues


# ------------------------------------------------------------ set-level checks
def find_duplicate_ids(cases: list[TestCase]) -> dict[str, int]:
    return {k: v for k, v in Counter(c.tc_id for c in cases if c.tc_id).items() if v > 1}


def _norm(s: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9 ]+", " ", str(s).lower()).split())


def signature(tc: TestCase) -> str:
    v = tc.values
    return " | ".join(_norm(v.get(k, "")) for k in
                      ("Requirement ID", "Test Type", "Test Scenario", "Test Steps", "Test Data", "Expected Result"))


def _numbers(tc: TestCase) -> list[str]:
    v = tc.values
    return re.findall(r"\d+", " ".join(str(v.get(k, "")) for k in ("Test Scenario", "Test Steps", "Test Data")))


def _is_dup(a: TestCase, b: TestCase) -> float:
    """Similarity if a and b are duplicates, else 0. Tests that differ in their numbers
    (e.g. boundary values 7 vs 21) are never duplicates."""
    if a.values.get("Test Type") != b.values.get("Test Type") or _numbers(a) != _numbers(b):
        return 0.0
    sa, sb = signature(a), signature(b)
    r = 1.0 if sa == sb else SequenceMatcher(None, sa, sb).ratio()
    return round(r, 2) if r >= DUP_THRESHOLD else 0.0


def find_duplicates(cases: list[TestCase]) -> list[tuple[str, str, float]]:
    """Pairs (kept_id, duplicate_id, similarity) within the same requirement."""
    by_req: dict[str, list[TestCase]] = defaultdict(list)
    for c in cases:
        by_req[c.values.get("Requirement ID", "")].append(c)
    out: list[tuple[str, str, float]] = []
    for group in by_req.values():
        for i in range(len(group)):
            for j in range(i + 1, len(group)):
                r = _is_dup(group[i], group[j])
                if r:
                    out.append((group[i].tc_id, group[j].tc_id, r))
    return out


def deduplicate(cases: list[TestCase]) -> tuple[list[TestCase], list[tuple[str, str, float]]]:
    """Drop later near-duplicates; approved cases are always kept."""
    kept: list[TestCase] = []
    removed: list[tuple[str, str, float]] = []
    for c in cases:
        dup_of = None
        for k in kept:
            if k.values.get("Requirement ID") != c.values.get("Requirement ID"):
                continue
            r = _is_dup(k, c)
            if r:
                dup_of = (k.tc_id, c.tc_id, r)
                break
        if dup_of and c.status != "Approved":
            removed.append(dup_of)
        else:
            kept.append(c)
    return kept, removed


def make_ids_unique(cases: list[TestCase]) -> int:
    """Re-number colliding IDs deterministically. Returns number changed."""
    seen: set[str] = set()
    changed = 0
    for c in cases:
        base = c.tc_id or "TC"
        new, n = base, 1
        while new in seen:
            n += 1
            new = f"{base}-{n}"
        if new != c.tc_id:
            c.values["Test Case ID"] = new
            changed += 1
        seen.add(new)
    return changed


# ------------------------------------------------------------ coverage
def _tokens(s: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", s.lower()) if len(w) > 2}


def criterion_covered(criterion: str, tests: list[TestCase], threshold: float = 0.4) -> bool:
    ct = _tokens(criterion.replace("[derived]", ""))
    if not ct:
        return False
    for t in tests:
        blob = " ".join(str(t.values.get(k, "")) for k in
                        ("Requirement Traceability", "Test Scenario", "Test Case Description", "Expected Result"))
        if len(ct & _tokens(blob)) / len(ct) >= threshold:
            return True
    return False


@dataclass
class CoverageReport:
    requirement_coverage_pct: float
    criteria_coverage_pct: float
    uncovered_requirements: list[str]
    uncovered_criteria: list[tuple[str, str]]
    per_requirement: list[dict]
    by_type: dict[str, int] = field(default_factory=dict)


def compute_coverage(reqs: list[Requirement], cases: list[TestCase]) -> CoverageReport:
    by_req: dict[str, list[TestCase]] = defaultdict(list)
    for c in cases:
        by_req[c.values.get("Requirement ID", "")].append(c)
    rows, uncovered_reqs, uncovered_ac = [], [], []
    total_ac = covered_ac = 0
    for r in reqs:
        tests = by_req.get(r.req_id, [])
        cov = 0
        for ac in r.acceptance_criteria:
            total_ac += 1
            if criterion_covered(ac, tests):
                covered_ac += 1
                cov += 1
            else:
                uncovered_ac.append((r.req_id, ac))
        if not tests:
            uncovered_reqs.append(r.req_id)
        types = Counter(t.values.get("Test Type", "") for t in tests)
        rows.append({
            "Requirement ID": r.req_id, "Title": r.title, "Test Cases": len(tests),
            "Criteria": len(r.acceptance_criteria), "Criteria Covered": cov,
            "Criteria Coverage %": round(100 * cov / len(r.acceptance_criteria), 1) if r.acceptance_criteria else None,
            "Approved": sum(1 for t in tests if t.status == "Approved"),
            "Types": ", ".join(f"{k}:{v}" for k, v in sorted(types.items()) if k),
        })
    n = len(reqs)
    return CoverageReport(
        requirement_coverage_pct=round(100 * (n - len(uncovered_reqs)) / n, 1) if n else 0.0,
        criteria_coverage_pct=round(100 * covered_ac / total_ac, 1) if total_ac else 0.0,
        uncovered_requirements=uncovered_reqs, uncovered_criteria=uncovered_ac,
        per_requirement=rows, by_type=dict(Counter(c.values.get("Test Type", "") for c in cases)))


# ------------------------------------------------------------ orchestrator
def validate_all(cases: list[TestCase], reqs: list[Requirement]) -> dict:
    """Run every check, store per-case issues on the objects, return a summary."""
    known = {r.req_id for r in reqs}
    dup_ids = find_duplicate_ids(cases)
    dups = find_duplicates(cases)
    dup_flagged = {b for _, b, _ in dups}
    for c in cases:
        c.issues = (check_mandatory(c) + check_expected_result(c) + check_traceability(c, known))
        if c.tc_id in dup_ids:
            c.issues.append("Duplicate Test Case ID")
        if c.tc_id in dup_flagged:
            c.issues.append("Near-duplicate of another test case")
    cov = compute_coverage(reqs, cases)
    n = len(cases)
    clean = sum(1 for c in cases if not c.issues)
    return {
        "total": n, "clean": clean, "with_issues": n - clean,
        "pass_rate_pct": round(100 * clean / n, 1) if n else 0.0,
        "duplicate_ids": dup_ids, "near_duplicates": dups, "coverage": cov,
        "issue_counts": dict(Counter(i.split(":")[0] if i.startswith("Missing") else i for c in cases for i in c.issues)),
    }
