"""CSV / Excel export (OpenPyXL) with formatted sheets."""
from __future__ import annotations

import io

import pandas as pd
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from ..models import TEST_CASE_FIELDS, Requirement, TestCase
from ..validation.validators import compute_coverage

HEADER_FILL = PatternFill("solid", fgColor="1F3A4D")
FONT = "Arial"


def cases_to_df(cases: list[TestCase], include_status: bool = True) -> pd.DataFrame:
    cols = TEST_CASE_FIELDS + (["Status"] if include_status else [])
    return pd.DataFrame([c.to_row() for c in cases], columns=cols)


def requirements_to_df(reqs: list[Requirement]) -> pd.DataFrame:
    return pd.DataFrame([{
        "Requirement ID": r.req_id, "Title": r.title, "Description": r.description, "Type": r.kind,
        "NFR Category": r.nfr_category, "Priority": r.priority,
        "Acceptance Criteria": "\n".join(r.acceptance_criteria), "Gaps": "\n".join(r.gaps)} for r in reqs])


def to_csv_bytes(cases: list[TestCase]) -> bytes:
    return cases_to_df(cases).to_csv(index=False).encode("utf-8-sig")  # BOM: opens cleanly in Excel


def traceability_matrix(reqs: list[Requirement], cases: list[TestCase]) -> pd.DataFrame:
    rows = []
    for r in reqs:
        ids = [c.tc_id for c in cases if c.values.get("Requirement ID") == r.req_id]
        rows.append({"Requirement ID": r.req_id, "Title": r.title, "Test Case Count": len(ids),
                     "Test Case IDs": ", ".join(ids)})
    return pd.DataFrame(rows)


def to_excel_bytes(cases: list[TestCase], reqs: list[Requirement], approved_only: bool = False) -> bytes:
    use = [c for c in cases if c.status == "Approved"] if approved_only else cases
    cov = compute_coverage(reqs, use)
    sheets = {
        "Test Cases": cases_to_df(use),
        "Requirements": requirements_to_df(reqs),
        "Traceability": traceability_matrix(reqs, use),
        "Coverage": pd.DataFrame(cov.per_requirement),
    }
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as xw:
        for name, df in sheets.items():
            df.to_excel(xw, sheet_name=name, index=False)
            _style(xw.book[name], df)
    return buf.getvalue()


def _style(ws, df: pd.DataFrame) -> None:
    for c in ws[1]:
        c.font = Font(name=FONT, bold=True, color="FFFFFF", size=10)
        c.fill = HEADER_FILL
        c.alignment = Alignment(vertical="center", wrap_text=True)
    for row in ws.iter_rows(min_row=2):
        for c in row:
            c.font = Font(name=FONT, size=10)
            c.alignment = Alignment(vertical="top", wrap_text=True)
    for i, col in enumerate(df.columns, 1):
        longest = max([len(str(col))] + [len(str(v).split("\n")[0]) for v in df[col].head(200)])
        ws.column_dimensions[get_column_letter(i)].width = min(max(12, longest + 2), 55)
    ws.freeze_panes = "B2"
    ws.auto_filter.ref = ws.dimensions
