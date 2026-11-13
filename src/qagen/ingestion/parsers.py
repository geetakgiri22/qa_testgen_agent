"""Parse requirement documents (PDF, DOCX, XLSX, CSV, TXT, MD) into Requirement objects."""
from __future__ import annotations

import io
import logging
import re
from pathlib import Path

import pandas as pd

from ..models import Requirement

log = logging.getLogger(__name__)

SUPPORTED = {".pdf", ".docx", ".xlsx", ".xls", ".csv", ".txt", ".md"}
DEFAULT_COLUMNS = {
    "requirement_id": "Requirement ID", "title": "Title", "description": "Description",
    "acceptance_criteria": "Acceptance Criteria", "priority": "Priority",
}
_ALIASES = {
    "requirement_id": ["requirement id", "req id", "id", "story id", "key", "issue key"],
    "title": ["title", "summary", "name", "requirement", "user story"],
    "description": ["description", "details", "requirement description", "story"],
    "acceptance_criteria": ["acceptance criteria", "acceptance", "ac", "criteria"],
    "priority": ["priority", "severity"],
}


class ParseError(ValueError):
    pass


# ---------------------------------------------------------------- entry
def parse_requirements(data: bytes, filename: str, cfg: dict | None = None) -> list[Requirement]:
    cfg = cfg or {}
    ext = Path(filename).suffix.lower()
    if ext not in SUPPORTED:
        raise ParseError(f"Unsupported file type '{ext}'. Supported: {', '.join(sorted(SUPPORTED))}")
    try:
        if ext in {".csv", ".xlsx", ".xls"}:
            df = _read_table(data, ext, cfg.get("spreadsheet", {}))
            reqs = requirements_from_table(df, cfg.get("spreadsheet", {}).get("columns", {}))
        else:
            text = _read_text(data, ext)
            reqs = requirements_from_text(text, cfg.get("text_parsing", {}))
    except ParseError:
        raise
    except Exception as exc:  # noqa: BLE001 - surface any parser failure cleanly
        log.exception("Parsing failed for %s", filename)
        raise ParseError(f"Could not read '{filename}': {exc}") from exc
    if not reqs:
        raise ParseError(f"No requirements could be extracted from '{filename}'.")
    _ensure_unique_ids(reqs)
    return reqs


# ---------------------------------------------------------------- tables
def _read_table(data: bytes, ext: str, sp_cfg: dict) -> pd.DataFrame:
    header = max(int(sp_cfg.get("header_row", 1)) - 1, 0)
    if ext == ".csv":
        return pd.read_csv(io.BytesIO(data), header=header, dtype=str).fillna("")
    sheet = sp_cfg.get("sheet_name") or 0
    return pd.read_excel(io.BytesIO(data), sheet_name=sheet, header=header, dtype=str).fillna("")


def _resolve_columns(df: pd.DataFrame, mapping: dict) -> dict[str, str | None]:
    lower = {str(c).strip().lower(): c for c in df.columns}
    out: dict[str, str | None] = {}
    for field, default in DEFAULT_COLUMNS.items():
        wanted = str(mapping.get(field) or default).strip().lower()
        col = lower.get(wanted)
        if col is None:
            col = next((lower[a] for a in _ALIASES[field] if a in lower), None)
        out[field] = col
    return out


def requirements_from_table(df: pd.DataFrame, mapping: dict) -> list[Requirement]:
    cols = _resolve_columns(df, mapping)
    if not (cols["description"] or cols["title"]):
        raise ParseError(
            "Could not find a Title/Description column. Set 'spreadsheet.columns' in drive_config.yaml. "
            f"Columns found: {list(df.columns)}")
    reqs: list[Requirement] = []
    for i, row in df.iterrows():
        get = lambda k: str(row[cols[k]]).strip() if cols[k] else ""  # noqa: E731
        title, desc = get("title"), get("description")
        if not (title or desc):
            continue
        rid = get("requirement_id") or f"REQ-{len(reqs) + 1:03d}"
        reqs.append(Requirement(
            req_id=rid, title=title, description=desc,
            acceptance_criteria=split_criteria(get("acceptance_criteria")),
            priority=_norm_priority(get("priority"))))
    return reqs


# ---------------------------------------------------------------- text
def _read_text(data: bytes, ext: str) -> str:
    if ext == ".pdf":
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(data))
        return "\n".join((p.extract_text() or "") for p in reader.pages)
    if ext == ".docx":
        import docx
        d = docx.Document(io.BytesIO(data))
        parts = [p.text for p in d.paragraphs]
        for t in d.tables:                                   # tables often hold AC
            for r in t.rows:
                parts.append(" | ".join(c.text.strip() for c in r.cells))
        return "\n".join(parts)
    return data.decode("utf-8", errors="replace")


def requirements_from_text(text: str, tp_cfg: dict | None = None) -> list[Requirement]:
    tp_cfg = tp_cfg or {}
    id_re = re.compile(tp_cfg.get("id_pattern") or r"(?:REQ|US|FR|NFR)[-_ ]?\d+", re.IGNORECASE)
    head_re = re.compile(rf"^\s*#{{0,4}}\s*\**\s*({id_re.pattern})\b\s*[:\-–.]?\s*(.*)$", re.IGNORECASE)
    blocks: list[tuple[str, list[str]]] = []
    for line in text.splitlines():
        m = head_re.match(line)
        if m and len(line.strip()) < 220:
            blocks.append((m.group(1).upper().replace(" ", "-").replace("_", "-"), [m.group(2).strip()]))
        elif blocks:
            blocks[-1][1].append(line)
        elif line.strip():
            blocks.append(("", [line]))
    if not any(b[0] for b in blocks):                         # no IDs: split on blank lines
        paras = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
        blocks = [(f"REQ-{i + 1:03d}", p.splitlines()) for i, p in enumerate(paras)]
    reqs = []
    for rid, lines in blocks:
        if not rid:
            continue
        title, desc, ac = _split_block(lines)
        if title or desc:
            reqs.append(Requirement(req_id=rid, title=title, description=desc, acceptance_criteria=ac))
    return reqs


_AC_HEAD = re.compile(r"^\s*[*_#]*\s*acceptance criteria\s*[*_]*\s*:?\s*[*_]*\s*(.*)$", re.IGNORECASE)
_BULLET = re.compile(r"^\s*(?:[-*•]|\d+[.)])\s+")
_GWT = re.compile(r"^\s*(given|when|then|and)\b", re.IGNORECASE)


def _split_block(lines: list[str]) -> tuple[str, str, list[str]]:
    lines = [l.rstrip() for l in lines]
    non_empty = [l for l in lines if l.strip()]
    if not non_empty:
        return "", "", []
    title = non_empty[0].strip(" *#")
    desc_lines: list[str] = []
    ac: list[str] = []
    in_ac = False
    for l in non_empty[1:]:
        m = _AC_HEAD.match(l)
        if m:
            in_ac = True
            if m.group(1).strip():
                ac.append(m.group(1).strip())
            continue
        if in_ac or _GWT.match(l):
            ac.append(_BULLET.sub("", l).strip())
        else:
            desc_lines.append(_BULLET.sub("", l).strip())
    return title, " ".join(desc_lines).strip(), [a for a in ac if a]


# ---------------------------------------------------------------- helpers
def split_criteria(raw: str) -> list[str]:
    if not raw:
        return []
    parts = re.split(r"\n+|;\s+|(?<=\.)\s+(?=[A-Z])", raw)
    return [_BULLET.sub("", p).strip() for p in parts if p and p.strip()]


def _norm_priority(p: str) -> str:
    p = (p or "").strip().lower()
    if p in {"high", "critical", "p0", "p1", "highest", "blocker"}:
        return "High"
    if p in {"low", "lowest", "p3", "p4", "minor"}:
        return "Low"
    return "Medium"


def _ensure_unique_ids(reqs: list[Requirement]) -> None:
    seen: dict[str, int] = {}
    for r in reqs:
        n = seen.get(r.req_id, 0)
        seen[r.req_id] = n + 1
        if n:
            r.req_id = f"{r.req_id}-{n + 1}"
