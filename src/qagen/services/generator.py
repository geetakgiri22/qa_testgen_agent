"""LLM-backed test case generation with deterministic post-processing."""
from __future__ import annotations

import logging
import re
import time
from typing import Callable

from ..config import GenerationSettings, load_settings
from ..llm.ollama_client import LLMError, OllamaClient
from ..llm.prompts import GENERATION_SYSTEM, GENERATION_USER
from ..models import AUTOMATION, PRIORITIES, TEST_TYPES, Requirement, TestCase
from ..validation.validators import deduplicate, make_ids_unique

log = logging.getLogger(__name__)


def _pick(value: str, allowed: list[str], default: str) -> str:
    v = str(value or "").strip().lower()
    return next((a for a in allowed if a.lower() == v), default)


def _steps(raw) -> str:
    items = raw if isinstance(raw, list) else re.split(r"\n+|(?<=\.)\s+(?=\d+\.)", str(raw or ""))
    items = [re.sub(r"^\s*\d+[.)]\s*", "", str(s)).strip() for s in items if str(s).strip()]
    return "\n".join(f"{i}. {s}" for i, s in enumerate(items, 1))


def _text(v) -> str:
    if isinstance(v, (list, tuple)):
        return "; ".join(str(x) for x in v)
    if isinstance(v, dict):
        return "; ".join(f"{k}={val}" for k, val in v.items())
    return str(v or "").strip()


def build_test_case(raw: dict, req: Requirement, seq: int) -> TestCase:
    crit = _text(raw.get("covers_criterion"))
    values = {
        "Test Case ID": f"TC-{req.req_id}-{seq:03d}",
        "Requirement ID": req.req_id,
        "Test Scenario": _text(raw.get("scenario")),
        "Test Case Description": _text(raw.get("description")),
        "Preconditions": _text(raw.get("preconditions")),
        "Test Steps": _steps(raw.get("steps")),
        "Test Data": _text(raw.get("test_data")),
        "Expected Result": _text(raw.get("expected_result")),
        "Priority": _pick(raw.get("priority"), PRIORITIES, req.priority if req.priority in PRIORITIES else "Medium"),
        "Test Type": _pick(raw.get("test_type"), TEST_TYPES, "Positive"),
        "Automation Suitability": _pick(raw.get("automation"), AUTOMATION, "Partial"),
        "Requirement Traceability": f"{req.req_id}" + (f" | AC: {crit}" if crit else ""),
    }
    return TestCase(values=values)


def _types_for(req: Requirement) -> str:
    base = ["Positive", "Negative", "Boundary", "Edge", "Validation", "Security"]
    if req.kind == "Non-Functional":
        base = ["Positive", "Boundary", "Negative", "Edge"] + (["Security"] if req.nfr_category == "Security" else [])
    return ", ".join(base)


class TestCaseGenerator:
    __test__ = False  # not a pytest class

    def __init__(self, client: OllamaClient | None = None, settings: GenerationSettings | None = None):
        self.client = client or OllamaClient()
        self.s = settings or load_settings().generation
        self.stats: list[dict] = []        # per-requirement run telemetry for the Evaluation page

    def generate_for_requirement(self, req: Requirement, start_seq: int = 1) -> list[TestCase]:
        text = req.full_text()[: self.s.max_req_chars]
        if req.gaps:
            text += "\nKnown gaps (cover defensively): " + "; ".join(req.gaps[:3])
        prompt = GENERATION_USER.format(req_id=req.req_id, kind=req.kind, text=text,
                                        max_tests=self.s.max_tests_per_req, types=_types_for(req))
        t0 = time.perf_counter()
        try:
            out = self.client.chat_json(GENERATION_SYSTEM, prompt)
            items = out.get("test_cases", []) if isinstance(out, dict) else out
            items = [i for i in items if isinstance(i, dict)][: self.s.max_tests_per_req]
            cases = [build_test_case(it, req, start_seq + n) for n, it in enumerate(items)]
            self.stats.append({"Requirement ID": req.req_id, "seconds": round(time.perf_counter() - t0, 1),
                               "generated": len(cases), "error": ""})
            return cases
        except LLMError as exc:
            log.error("Generation failed for %s: %s", req.req_id, exc)
            self.stats.append({"Requirement ID": req.req_id, "seconds": round(time.perf_counter() - t0, 1),
                               "generated": 0, "error": str(exc)})
            raise

    def generate_all(self, reqs: list[Requirement], progress: Callable[[int, int, str], None] | None = None
                     ) -> tuple[list[TestCase], dict]:
        all_cases: list[TestCase] = []
        failures: dict[str, str] = {}
        for i, req in enumerate(reqs, 1):
            if progress:
                progress(i - 1, len(reqs), req.req_id)
            try:
                all_cases += self.generate_for_requirement(req)
            except LLMError as exc:
                failures[req.req_id] = str(exc)
        all_cases, removed = deduplicate(all_cases)
        make_ids_unique(all_cases)
        if progress:
            progress(len(reqs), len(reqs), "done")
        return all_cases, {"failures": failures, "duplicates_removed": removed}

    def regenerate_requirement(self, req: Requirement, existing: list[TestCase]) -> tuple[list[TestCase], dict]:
        """Replace non-approved cases of one requirement; approved cases are preserved."""
        keep = [c for c in existing if not (c.values.get("Requirement ID") == req.req_id and c.status != "Approved")]
        used = {c.tc_id for c in keep}
        n = 1
        new = self.generate_for_requirement(req, start_seq=1)
        merged = keep + new
        merged, removed = deduplicate(merged)
        make_ids_unique(merged)
        # keep original order grouped by requirement
        return merged, {"duplicates_removed": removed, "replaced": len(existing) - len(keep), "added": len(new), "kept_ids": used}
