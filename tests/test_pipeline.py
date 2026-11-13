import io
from pathlib import Path

import openpyxl
import pandas as pd

from mock_ollama import start
from qagen.config import GenerationSettings, OllamaSettings
from qagen.ingestion.parsers import parse_requirements
from qagen.llm.ollama_client import OllamaClient
from qagen.services import exporter
from qagen.services.evaluation import scorecard
from qagen.services.generator import TestCaseGenerator
from qagen.services.requirement_analyzer import analyze_requirements
from qagen.validation.validators import validate_all

SAMPLE = Path(__file__).resolve().parents[1] / "data" / "sample_user_stories.md"


def _client():
    srv = start()
    s = OllamaSettings(base_url=f"http://127.0.0.1:{srv.server_port}", timeout=10)
    return OllamaClient(s)


def test_health_check_ok_and_down():
    assert _client().health_check().ok
    bad = OllamaClient(OllamaSettings(base_url="http://127.0.0.1:9", timeout=1))
    h = bad.health_check()
    assert not h.ok and not h.server_up


def test_parse_markdown_sample():
    reqs = parse_requirements(SAMPLE.read_bytes(), "sample.md")
    assert [r.req_id for r in reqs] == ["REQ-001", "REQ-002", "REQ-003", "REQ-004", "REQ-005"]
    assert len(reqs[0].acceptance_criteria) == 4 and reqs[2].acceptance_criteria == []


def test_parse_csv_and_xlsx_with_custom_columns():
    df = pd.DataFrame({"Story Key": ["A-1"], "Summary": ["Reset password"], "Details": ["via email link"],
                       "AC": ["Link expires in 30 minutes; Link is single use"]})
    cfg = {"spreadsheet": {"columns": {"requirement_id": "Story Key", "title": "Summary", "description": "Details",
                                       "acceptance_criteria": "AC"}}}
    r = parse_requirements(df.to_csv(index=False).encode(), "x.csv", cfg)[0]
    assert r.req_id == "A-1" and len(r.acceptance_criteria) == 2
    buf = io.BytesIO(); df.to_excel(buf, index=False)
    assert parse_requirements(buf.getvalue(), "x.xlsx", cfg)[0].req_id == "A-1"


def test_full_pipeline():
    client = _client()
    reqs = analyze_requirements(parse_requirements(SAMPLE.read_bytes(), "s.md"), client)
    assert any("No acceptance criteria" in g for g in reqs[2].gaps)       # REQ-003 gap detected
    assert reqs[3].kind == "Non-Functional"                                 # REQ-004 performance
    gen = TestCaseGenerator(client, GenerationSettings(max_req_chars=1800, max_tests_per_req=12))
    cases, info = gen.generate_all(reqs)
    assert not info["failures"]
    assert len(info["duplicates_removed"]) == 5                             # 1 injected dup per requirement
    assert len(cases) == 25 and len({c.tc_id for c in cases}) == 25
    rep = validate_all(cases, reqs)
    assert rep["with_issues"] == 5                                          # one vague result per requirement
    assert rep["coverage"].requirement_coverage_pct == 100.0
    sc = scorecard(cases, reqs, gen.stats)
    assert 0 < sc["overall"] <= 100
    # approve + regenerate keeps approved cases
    cases[0].status = "Approved"
    kept_id = cases[0].tc_id
    cases2, meta = gen.regenerate_requirement(reqs[0], cases)
    assert any(c.tc_id == kept_id and c.status == "Approved" for c in cases2)
    assert len({c.tc_id for c in cases2}) == len(cases2)
    # exports
    assert exporter.to_csv_bytes(cases2).startswith(b"\xef\xbb\xbfTest Case ID")
    wb = openpyxl.load_workbook(io.BytesIO(exporter.to_excel_bytes(cases2, reqs)))
    assert wb.sheetnames == ["Test Cases", "Requirements", "Traceability", "Coverage"]
    only = openpyxl.load_workbook(io.BytesIO(exporter.to_excel_bytes(cases2, reqs, approved_only=True)))
    assert only["Test Cases"].max_row == 2


def test_llm_down_degrades_gracefully():
    bad = OllamaClient(OllamaSettings(base_url="http://127.0.0.1:9", timeout=1))
    reqs = analyze_requirements(parse_requirements(SAMPLE.read_bytes(), "s.md"), bad)
    assert all(r.gaps for r in reqs[:3])
    cases, info = TestCaseGenerator(bad).generate_all(reqs[:1])
    assert cases == [] and "REQ-001" in info["failures"]


# ---------------------------------------------------------------- Google Drive loader (no network)
def test_drive_id_extraction_and_config_errors():
    from qagen.ingestion.drive_loader import DriveError, extract_file_id, load_from_drive
    fid = "1AbCdEfGhIjKlMnOpQrStUvWxYz"
    assert extract_file_id(fid) == fid
    assert extract_file_id(f"https://docs.google.com/spreadsheets/d/{fid}/edit#gid=0") == fid
    assert extract_file_id(f"https://drive.google.com/open?id={fid}") == fid
    assert extract_file_id(f"https://drive.google.com/file/d/{fid}/view?usp=sharing") == fid
    for bad in ({"google_drive": {"enabled": False}}, {"google_drive": {}},
                {"google_drive": {"file_id": fid, "auth_mode": "nope"}}):
        try:
            load_from_drive(bad)
            raise AssertionError("expected DriveError")
        except DriveError:
            pass


def test_drive_public_link_downloads_and_parses(monkeypatch=None):
    import requests
    from qagen.ingestion import drive_loader
    csv = b"Requirement ID,Title,Description,Acceptance Criteria\nR-1,Login,User logs in,Valid creds work; Bad creds fail\n"

    class R:  # minimal fake response
        status_code, content = 200, csv
        headers = {"Content-Type": "text/csv", "Content-Disposition": 'attachment; filename="reqs.csv"'}

    orig = requests.get
    drive_loader.requests.get = lambda *a, **k: R()
    try:
        f = drive_loader.load_from_drive({"google_drive": {"auth_mode": "public_link", "file_id": "1AbCdEfGhIjKlMnOpQrStUvWxYz",
                                                           "export_format_sheet": "csv"}})
    finally:
        drive_loader.requests.get = orig
    reqs = parse_requirements(f.data, "reqs.csv")
    assert reqs[0].req_id == "R-1" and len(reqs[0].acceptance_criteria) == 2


def test_default_drive_config_loads():
    from qagen.config import load_drive_config
    cfg = load_drive_config()
    assert cfg["google_drive"]["auth_mode"] in {"service_account", "oauth", "public_link"}
    assert "columns" in cfg["spreadsheet"]
