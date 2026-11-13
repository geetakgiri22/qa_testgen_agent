"""Requirement analysis: FR/NFR classification, acceptance-criteria extraction, gap detection.

Deterministic heuristics always run; the LLM enriches them. If the LLM fails the heuristic
result is kept, so the pipeline never blocks on a model error.
"""
from __future__ import annotations

import logging
import re
from typing import Callable

from ..llm.ollama_client import LLMError, OllamaClient
from ..llm.prompts import ANALYSIS_SYSTEM, ANALYSIS_USER
from ..models import Requirement

log = logging.getLogger(__name__)

NFR_KEYWORDS = {
    "Performance": r"\b(within \d+|response time|latency|throughput|concurrent|load|seconds?|ms\b|scal)",
    "Security": r"\b(encrypt|authenticat|authoriz|password|token|session|mfa|2fa|rbac|injection|xss|csrf|lockout|audit)",
    "Usability": r"\b(usab|user[- ]friendly|intuitive|responsive|mobile)",
    "Reliability": r"\b(availab|uptime|recover|backup|failover|retry)",
    "Compliance": r"\b(gdpr|hipaa|pci|sox|iso ?\d+|compliance|regulat)",
    "Accessibility": r"\b(wcag|accessib|screen reader|keyboard navigation)",
}
INPUT_HINT = re.compile(r"\b(enter|input|field|form|upload|submit|password|email|phone|amount|quantity|date|search)\b", re.I)
ERROR_HINT = re.compile(r"\b(invalid|error|reject|fail|not allowed|denied|incorrect|blocked|lock|message)\b", re.I)
LIMIT_HINT = re.compile(r"\b(min|max|minimum|maximum|at least|at most|between|characters?|digits?|\d+)\b", re.I)
SEC_HINT = re.compile(r"\b(password|login|auth|token|payment|card|personal|upload|admin|session|role)\b", re.I)


def heuristic_gaps(req: Requirement) -> list[str]:
    gaps: list[str] = []
    text = req.full_text()
    if not req.acceptance_criteria:
        gaps.append("No acceptance criteria provided")
    if INPUT_HINT.search(text) and not ERROR_HINT.search(text):
        gaps.append("No invalid-input / error-handling criterion")
    if INPUT_HINT.search(text) and not LIMIT_HINT.search(text):
        gaps.append("No limits or boundary values specified for inputs")
    if SEC_HINT.search(text) and "secur" not in text.lower() and req.kind != "Non-Functional":
        gaps.append("No security criterion (authorisation, data protection, abuse handling)")
    return gaps


def heuristic_classify(req: Requirement) -> None:
    text = req.full_text().lower()
    for cat, pat in NFR_KEYWORDS.items():
        if re.search(pat, text) and not re.search(r"\b(as an?|i want|user can|shall allow)\b", text):
            req.kind, req.nfr_category = "Non-Functional", cat
            return
    req.kind = "Functional"


def analyze_requirements(reqs: list[Requirement], client: OllamaClient | None = None,
                         progress: Callable[[int, int, str], None] | None = None) -> list[Requirement]:
    for i, req in enumerate(reqs, 1):
        heuristic_classify(req)
        heuristic_nfr = req.kind == "Non-Functional"
        gaps = heuristic_gaps(req)
        if client is not None:
            try:
                out = client.chat_json(ANALYSIS_SYSTEM, ANALYSIS_USER.format(req_id=req.req_id, text=req.full_text()[:1800]))
                if isinstance(out, dict):
                    kind = str(out.get("kind", "")).strip()
                    # The LLM may promote Functional -> Non-Functional, but never overrides a
                    # strong rule-based NFR match (small models misclassify these often).
                    if kind in {"Functional", "Non-Functional"} and not (heuristic_nfr and kind == "Functional"):
                        req.kind = kind
                    req.nfr_category = str(out.get("nfr_category") or req.nfr_category or "")
                    if not req.acceptance_criteria:
                        req.acceptance_criteria = [str(a) for a in out.get("acceptance_criteria", []) if str(a).strip()][:5]
                    gaps += [f"Missing: {m}" for m in out.get("missing_criteria", []) if str(m).strip()][:4]
            except LLMError as exc:
                log.warning("LLM analysis failed for %s: %s", req.req_id, exc)
                gaps.append("LLM analysis unavailable - heuristic result only")
        req.gaps = list(dict.fromkeys(gaps))
        if progress:
            progress(i, len(reqs), req.req_id)
    return reqs
