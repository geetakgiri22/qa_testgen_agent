"""Test data generation: deterministic boundary values from requirement text + LLM suggestions."""
from __future__ import annotations

import logging
import re

from ..llm.ollama_client import LLMError, OllamaClient
from ..llm.prompts import TESTDATA_SYSTEM, TESTDATA_USER
from ..models import Requirement, TestCase

log = logging.getLogger(__name__)

_BETWEEN = re.compile(r"between\s+(\d+)\s+(?:and|to|-)\s+(\d+)", re.I)
_MIN = re.compile(r"(?:at least|minimum(?: of)?|min(?:imum)?\.?)\s*(\d+)", re.I)
_MAX = re.compile(r"(?:at most|maximum(?: of)?|max(?:imum)?\.?|up to|no more than)\s*(\d+)", re.I)

SECURITY_PAYLOADS = ["' OR '1'='1' --", "<script>alert(1)</script>", "../../etc/passwd", "A" * 256]


def extract_limits(text: str) -> list[tuple[int, int | None, int | None]]:
    """Return (min, max) pairs found in text, derived deterministically."""
    limits = []
    for m in _BETWEEN.finditer(text):
        limits.append((int(m.group(1)), int(m.group(2))))
    lo = [int(m.group(1)) for m in _MIN.finditer(text)]
    hi = [int(m.group(1)) for m in _MAX.finditer(text)]
    if not limits and (lo or hi):
        limits.append((lo[0] if lo else None, hi[0] if hi else None))
    return limits


def boundary_values(lo: int | None, hi: int | None) -> dict[str, list]:
    b: list = []
    inv: list = []
    val: list = []
    if lo is not None:
        b += [lo - 1, lo, lo + 1]
        inv.append(lo - 1)
        val.append(lo)
    if hi is not None:
        b += [hi - 1, hi, hi + 1]
        inv.append(hi + 1)
        val.append(hi)
    return {"boundary": sorted(set(b)), "invalid": inv, "valid": val}


def generate_test_data(tc: TestCase, req: Requirement, client: OllamaClient | None = None) -> dict:
    result = {"valid": [], "invalid": [], "boundary": [], "security": [], "notes": "", "source": "deterministic"}
    for lo, hi in extract_limits(req.full_text()):
        bv = boundary_values(lo, hi)
        for k in ("valid", "invalid", "boundary"):
            result[k] += bv[k]
    if tc.values.get("Test Type") == "Security":
        result["security"] = SECURITY_PAYLOADS
    if client is not None:
        try:
            out = client.chat_json(TESTDATA_SYSTEM, TESTDATA_USER.format(
                scenario=tc.values.get("Test Scenario", ""), test_type=tc.values.get("Test Type", ""),
                text=req.full_text()[:900]))
            if isinstance(out, dict):
                for k in ("valid", "invalid", "boundary"):
                    result[k] += [str(x) for x in out.get(k, [])][:4]
                result["notes"] = str(out.get("notes", ""))
                result["source"] = "deterministic + LLM"
        except LLMError as exc:
            log.warning("LLM test data failed: %s", exc)
            result["notes"] = "LLM unavailable - deterministic values only."
    for k in ("valid", "invalid", "boundary"):
        result[k] = list(dict.fromkeys(result[k]))
    return result


def format_for_cell(data: dict) -> str:
    parts = []
    for k in ("valid", "invalid", "boundary", "security"):
        if data.get(k):
            parts.append(f"{k.capitalize()}: " + ", ".join(str(x)[:60] for x in data[k]))
    return "\n".join(parts)
