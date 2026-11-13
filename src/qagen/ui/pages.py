"""Streamlit pages. UI only: all logic lives in services/validation/ingestion."""
from __future__ import annotations

import logging

import pandas as pd
import streamlit as st
import yaml

from ..config import load_drive_config, load_settings
from ..ingestion.drive_loader import DriveError, load_from_drive, load_local
from ..ingestion.parsers import ParseError, parse_requirements, requirements_from_text
from ..models import AUTOMATION, PRIORITIES, STATUSES, TEST_TYPES
from ..services import exporter
from ..services.evaluation import scorecard
from ..services.requirement_analyzer import analyze_requirements
from ..services.test_data import format_for_cell, generate_test_data
from ..validation.validators import compute_coverage, deduplicate, make_ids_unique, validate_all
from . import state, theme

log = logging.getLogger(__name__)

PAGES = ["Dashboard", "Requirement Upload", "Requirement Analysis", "Test Case Generation",
         "Test Data Generation", "Review & Approval", "Coverage & Traceability",
         "Evaluation Dashboard", "Export Centre"]


# ------------------------------------------------------------------ helpers
def _need_reqs() -> bool:
    if not state.reqs():
        st.info("No requirements loaded yet. Go to **Requirement Upload** first.")
        return False
    return True


def _need_cases() -> bool:
    if not state.cases():
        st.info("No test cases yet. Generate them on **Test Case Generation**.")
        return False
    return True


def _require_ollama() -> bool:
    h = state.health()
    if not h.ok:
        st.error(h.message)
        return False
    return True


def sidebar() -> str:
    with st.sidebar:
        st.markdown("### QA Test Case Agent")
        st.caption("Runs fully on this machine")
        page = st.radio("Navigate", PAGES, label_visibility="collapsed")
        st.divider()
        h = state.health()
        st.markdown(theme.pill("Ollama online" if h.ok else "Ollama offline", "ok" if h.ok else "bad"),
                    unsafe_allow_html=True)
        st.caption(h.message)
        if st.button("Re-check Ollama"):
            state.health.clear()
            st.rerun()
    return page


# ------------------------------------------------------------------ 1 dashboard
def dashboard() -> None:
    theme.header("Dashboard", "Pipeline status for the current session, from requirements to approved test cases.")
    reqs, cases = state.reqs(), state.cases()
    sc = scorecard(cases, reqs, st.session_state.gen_stats) if cases else None
    approved = sum(1 for c in cases if c.status == "Approved")
    c = st.columns(5)
    c[0].metric("Requirements", len(reqs))
    c[1].metric("Test cases", len(cases))
    c[2].metric("Approved", approved)
    c[3].metric("Criteria coverage", f"{sc['validation']['coverage'].criteria_coverage_pct}%" if sc else "-")
    c[4].metric("Quality score", f"{sc['overall']}" if sc else "-")
    st.subheader("Pipeline")
    stages = [("Requirements loaded", bool(reqs), f"Source: {st.session_state.source_name or 'none'}"),
              ("Requirements analysed", st.session_state.analyzed, "Types, criteria and gaps identified"),
              ("Test cases generated", bool(cases), f"{len(cases)} cases"),
              ("Reviewed and approved", approved > 0, f"{approved} of {len(cases)} approved")]
    for name, done, note in stages:
        st.markdown(f'<div class="stage {"done" if done else ""}"><b>{name}</b>{note}</div>', unsafe_allow_html=True)
    if reqs and any(r.gaps for r in reqs):
        st.warning(f"{sum(1 for r in reqs if r.gaps)} requirement(s) have acceptance-criteria gaps. See Requirement Analysis.")


# ------------------------------------------------------------------ 2 upload
def upload() -> None:
    theme.header("Requirement Upload",
                 "Pull the specification from Google Drive using drive_config.yaml, upload a file, or paste user stories.")
    tab_drive, tab_file, tab_text = st.tabs(["Google Drive", "Upload file", "Paste text"])

    with tab_drive:
        cfg_path = load_settings().drive_config_path
        try:
            cfg = load_drive_config()
            gd = cfg["google_drive"]
            st.write(f"Config: `{cfg_path.name}` | mode **{gd.get('auth_mode')}** | "
                     f"file **{gd.get('file_id') or gd.get('file_url') or gd.get('file_name') or 'not set'}**")
        except (FileNotFoundError, ValueError, yaml.YAMLError) as exc:
            cfg = None
            st.error(f"Cannot read drive config: {exc}")
        with st.expander("Edit drive_config.yaml"):
            text = st.text_area("YAML", cfg_path.read_text(encoding="utf-8") if cfg_path.exists() else "", height=360,
                                label_visibility="collapsed")
            if st.button("Save config"):
                try:
                    yaml.safe_load(text)
                    cfg_path.write_text(text, encoding="utf-8")
                    st.success("Config saved.")
                    st.rerun()
                except yaml.YAMLError as exc:
                    st.error(f"Invalid YAML, not saved: {exc}")
        if cfg and st.button("Load from Google Drive", type="primary"):
            with st.spinner("Downloading from Google Drive..."):
                try:
                    f = load_from_drive(cfg)
                    _ingest(f.data, f.name, cfg)
                except (DriveError, ParseError) as exc:
                    log.error("Drive load failed: %s", exc)
                    st.error(str(exc))
                    fb = cfg.get("local_fallback_path")
                    if fb:
                        st.caption(f"Tip: the local sample at `{fb}` can be loaded from the Upload tab.")
        if cfg and cfg.get("local_fallback_path") and st.button("Load local sample instead"):
            try:
                f = load_local(cfg["local_fallback_path"])
                _ingest(f.data, f.name, cfg)
            except (DriveError, ParseError) as exc:
                st.error(str(exc))

    with tab_file:
        up = st.file_uploader("PDF, DOCX, XLSX, CSV, TXT or MD", type=["pdf", "docx", "xlsx", "xls", "csv", "txt", "md"])
        if up and st.button("Parse uploaded file", type="primary"):
            try:
                cfg = load_drive_config() if load_settings().drive_config_path.exists() else {}
            except (ValueError, yaml.YAMLError):
                cfg = {}
            try:
                _ingest(up.getvalue(), up.name, cfg)
            except ParseError as exc:
                st.error(str(exc))

    with tab_text:
        txt = st.text_area("User stories / requirements", height=240,
                           placeholder="REQ-001: User login\nAs a user I want to...\nAcceptance Criteria:\n- ...")
        if st.button("Use pasted text") and txt.strip():
            reqs = requirements_from_text(txt)
            if reqs:
                _set_reqs(reqs, "pasted text")
            else:
                st.error("No requirements found. Start each one with an ID such as REQ-001: or US-12:")

    if state.reqs():
        st.subheader(f"Loaded: {len(state.reqs())} requirements from {st.session_state.source_name}")
        st.dataframe(exporter.requirements_to_df(state.reqs())[["Requirement ID", "Title", "Description", "Acceptance Criteria"]])


def _ingest(data: bytes, name: str, cfg: dict) -> None:
    _set_reqs(parse_requirements(data, name, cfg), name)


def _set_reqs(reqs, source: str) -> None:
    st.session_state.requirements = reqs
    st.session_state.source_name = source
    state.reset_downstream()
    st.success(f"Loaded {len(reqs)} requirements from {source}.")


# ------------------------------------------------------------------ 3 analysis
def analysis() -> None:
    theme.header("Requirement Analysis",
                 "Classify requirements, extract acceptance criteria and find what is missing before generating tests.")
    if not _need_reqs():
        return
    use_llm = st.toggle("Use Qwen3 for deeper analysis (slower)", value=state.health().ok)
    if st.button("Analyse requirements", type="primary"):
        bar = st.progress(0.0, text="Starting...")
        analyze_requirements(state.reqs(), state.client() if use_llm and _require_ollama() else None,
                             lambda i, n, rid: bar.progress(i / n, text=f"Analysed {rid}"))
        st.session_state.analyzed = True
        bar.empty()
    reqs = state.reqs()
    df = pd.DataFrame([{"ID": r.req_id, "Type": r.kind, "NFR category": r.nfr_category, "Priority": r.priority,
                        "Criteria": len(r.acceptance_criteria), "Gaps": len(r.gaps)} for r in reqs])
    c = st.columns(4)
    c[0].metric("Functional", sum(r.kind == "Functional" for r in reqs))
    c[1].metric("Non-functional", sum(r.kind == "Non-Functional" for r in reqs))
    c[2].metric("Without criteria", sum(not r.acceptance_criteria for r in reqs))
    c[3].metric("With gaps", sum(bool(r.gaps) for r in reqs))
    st.dataframe(df)
    for r in reqs:
        with st.expander(f"{r.req_id}  {r.title[:70]}" + ("   (gaps)" if r.gaps else "")):
            st.write(r.description or "_No description_")
            new_ac = st.text_area("Acceptance criteria (one per line)", "\n".join(r.acceptance_criteria),
                                  key=f"ac_{r.req_id}", height=110)
            if r.gaps:
                st.markdown("**Missing / weak criteria**")
                for g in r.gaps:
                    st.markdown(f"- {g}")
            if st.button("Save criteria", key=f"sv_{r.req_id}"):
                r.acceptance_criteria = [l.strip() for l in new_ac.splitlines() if l.strip()]
                st.success("Saved. Re-run analysis to refresh gap detection.")


# ------------------------------------------------------------------ 4 generation
def generation() -> None:
    theme.header("Test Case Generation",
                 "Generates positive, negative, boundary, edge, security and validation cases mapped to each requirement.")
    if not _need_reqs():
        return
    if not st.session_state.analyzed:
        st.caption("Tip: analyse requirements first so gaps are covered defensively.")
    reqs = state.reqs()
    chosen = st.multiselect("Requirements to generate for", [r.req_id for r in reqs], default=[r.req_id for r in reqs])
    st.caption("On CPU-only hardware expect roughly 1 to 3 minutes per requirement with Qwen3:4B.")
    if st.button("Generate test cases", type="primary", disabled=not chosen):
        if _require_ollama():
            bar = st.progress(0.0, text="Starting...")
            gen = state.generator()
            sel = [r for r in reqs if r.req_id in chosen]
            keep = [c for c in state.cases() if c.values.get("Requirement ID") not in chosen or c.status == "Approved"]
            new, info = gen.generate_all(sel, lambda i, n, rid: bar.progress(min(i / n, 1.0), text=f"Generating for {rid}"))
            merged, _ = deduplicate(keep + new)
            make_ids_unique(merged)
            st.session_state.cases = merged
            st.session_state.gen_stats = gen.stats
            st.session_state.last_gen_info = info
            bar.empty()
    info = st.session_state.last_gen_info
    if info:
        if info["failures"]:
            for rid, msg in info["failures"].items():
                st.error(f"{rid}: {msg}")
        if info["duplicates_removed"]:
            st.info(f"Removed {len(info['duplicates_removed'])} duplicate test case(s).")
    if state.cases():
        rep = validate_all(state.cases(), reqs)
        c = st.columns(3)
        c[0].metric("Generated", rep["total"])
        c[1].metric("Pass validation", f"{rep['pass_rate_pct']}%")
        c[2].metric("Need attention", rep["with_issues"])
        st.dataframe(exporter.cases_to_df(state.cases()))


# ------------------------------------------------------------------ 5 test data
def test_data_page() -> None:
    theme.header("Test Data Generation",
                 "Boundary values are derived from the requirement text with Python; Qwen3 adds realistic examples.")
    if not (_need_reqs() and _need_cases()):
        return
    by_id = {r.req_id: r for r in state.reqs()}
    cases = state.cases()
    tc_id = st.selectbox("Test case", [c.tc_id for c in cases],
                         format_func=lambda i: f"{i}  {next(c.values['Test Scenario'] for c in cases if c.tc_id == i)[:60]}")
    tc = next(c for c in cases if c.tc_id == tc_id)
    req = by_id.get(tc.values.get("Requirement ID"))
    if req is None:
        st.error("This test case points to a requirement that is no longer loaded.")
        return
    use_llm = st.toggle("Add LLM suggestions", value=state.health().ok)
    if st.button("Generate test data", type="primary"):
        with st.spinner("Generating..."):
            st.session_state.test_data[tc_id] = generate_test_data(
                tc, req, state.client() if use_llm and state.health().ok else None)
    data = st.session_state.test_data.get(tc_id)
    st.write("**Current test data:**", tc.values.get("Test Data") or "_empty_")
    if data:
        cols = st.columns(4)
        for col, key in zip(cols, ["valid", "invalid", "boundary", "security"]):
            col.markdown(f"**{key.capitalize()}**")
            col.write(", ".join(map(str, data[key])) or "-")
        st.caption(f"Source: {data['source']}. {data['notes']}")
        if st.button("Append to this test case"):
            existing = tc.values.get("Test Data", "")
            tc.values["Test Data"] = (existing + "\n" if existing else "") + format_for_cell(data)
            st.success("Test data updated.")
            st.rerun()


# ------------------------------------------------------------------ 6 review
EDITABLE = ["Test Scenario", "Test Case Description", "Preconditions", "Test Steps", "Test Data", "Expected Result",
            "Priority", "Test Type", "Automation Suitability", "Requirement Traceability"]


def review() -> None:
    theme.header("Review & Approval", "Edit any cell, then approve or reject. Validation re-runs on every save.")
    if not (_need_reqs() and _need_cases()):
        return
    cases, reqs = state.cases(), state.reqs()
    validate_all(cases, reqs)
    f = st.columns(4)
    f_req = f[0].selectbox("Requirement", ["All"] + [r.req_id for r in reqs])
    f_type = f[1].selectbox("Type", ["All"] + TEST_TYPES)
    f_status = f[2].selectbox("Status", ["All"] + STATUSES)
    f_issue = f[3].checkbox("Only with issues")
    view = [c for c in cases if (f_req == "All" or c.values["Requirement ID"] == f_req)
            and (f_type == "All" or c.values["Test Type"] == f_type)
            and (f_status == "All" or c.status == f_status) and (not f_issue or c.issues)]
    st.caption(f"Showing {len(view)} of {len(cases)} test cases")
    df = exporter.cases_to_df(view)
    df.insert(1, "Issues", ["; ".join(c.issues) for c in view])
    edited = st.data_editor(
        df, key=f"editor_{f_req}_{f_type}_{f_status}_{f_issue}_{len(cases)}", num_rows="fixed",
        disabled=["Test Case ID", "Requirement ID", "Issues"],
        column_config={
            "Priority": st.column_config.SelectboxColumn(options=PRIORITIES),
            "Test Type": st.column_config.SelectboxColumn(options=TEST_TYPES),
            "Automation Suitability": st.column_config.SelectboxColumn(options=AUTOMATION),
            "Status": st.column_config.SelectboxColumn(options=STATUSES),
        })
    b = st.columns(4)
    if b[0].button("Save edits", type="primary"):
        lookup = {c.tc_id: c for c in cases}
        for _, row in edited.iterrows():
            c = lookup.get(row["Test Case ID"])
            if c:
                for fld in EDITABLE:
                    c.values[fld] = "" if pd.isna(row[fld]) else str(row[fld])
                c.status = row["Status"]
        st.success("Edits saved and re-validated.")
        st.rerun()
    if b[1].button("Approve all valid in view"):
        n = 0
        for c in view:
            if not c.issues and c.status != "Approved":
                c.status, n = "Approved", n + 1
        st.success(f"Approved {n} test case(s) with no validation issues.")
        st.rerun()
    if b[2].button("Reset view to Draft"):
        for c in view:
            c.status = "Draft"
        st.rerun()
    st.divider()
    st.subheader("Regenerate one requirement")
    rid = st.selectbox("Requirement", [r.req_id for r in reqs], key="regen_req")
    st.caption("Approved test cases are kept. Draft and rejected ones are replaced.")
    if st.button("Regenerate") and _require_ollama():
        with st.spinner(f"Regenerating {rid}..."):
            try:
                gen = state.generator()
                merged, meta = gen.regenerate_requirement(next(r for r in reqs if r.req_id == rid), cases)
                st.session_state.cases = merged
                st.session_state.gen_stats = gen.stats
                st.success(f"Replaced {meta['replaced']}, added {meta['added']} test case(s).")
                st.rerun()
            except Exception as exc:  # noqa: BLE001 - show any LLM failure to the user
                log.exception("Regeneration failed")
                st.error(str(exc))


# ------------------------------------------------------------------ 7 coverage
def coverage() -> None:
    theme.header("Coverage & Traceability", "Which requirements and acceptance criteria are covered, and by which tests.")
    if not (_need_reqs() and _need_cases()):
        return
    cov = compute_coverage(state.reqs(), state.cases())
    c = st.columns(3)
    c[0].metric("Requirement coverage", f"{cov.requirement_coverage_pct}%")
    c[1].metric("Acceptance-criteria coverage", f"{cov.criteria_coverage_pct}%")
    c[2].metric("Uncovered criteria", len(cov.uncovered_criteria))
    st.subheader("Per requirement")
    st.dataframe(pd.DataFrame(cov.per_requirement))
    st.subheader("Test types")
    st.bar_chart(pd.Series(cov.by_type, name="Test cases"))
    if cov.uncovered_criteria:
        st.subheader("Criteria without a matching test")
        st.dataframe(pd.DataFrame(cov.uncovered_criteria, columns=["Requirement ID", "Acceptance criterion"]))
    st.subheader("Traceability matrix")
    st.dataframe(exporter.traceability_matrix(state.reqs(), state.cases()))
    df = exporter.cases_to_df(state.cases())
    st.subheader("Requirement x test type")
    st.dataframe(pd.crosstab(df["Requirement ID"], df["Test Type"]))


# ------------------------------------------------------------------ 8 evaluation
def evaluation() -> None:
    theme.header("Evaluation Dashboard", "Objective quality measures computed by deterministic checks, not by the LLM.")
    if not (_need_reqs() and _need_cases()):
        return
    sc = scorecard(state.cases(), state.reqs(), st.session_state.gen_stats)
    v = sc["validation"]
    c = st.columns(4)
    c[0].metric("Overall quality", sc["overall"])
    c[1].metric("Validation pass rate", f"{v['pass_rate_pct']}%")
    c[2].metric("Approval rate", f"{sc['approval_rate_pct']}%")
    c[3].metric("Avg s / requirement", sc["avg_seconds_per_requirement"] or "-")
    st.subheader("Score components (0-100)")
    st.bar_chart(pd.Series(sc["components"], name="Score"))
    st.caption("Weights: validity 30%, requirement coverage 20%, criteria coverage 20%, traceability 15%, type diversity 10%, uniqueness 5%.")
    if v["issue_counts"]:
        st.subheader("Issues found")
        st.dataframe(pd.DataFrame(list(v["issue_counts"].items()), columns=["Issue", "Count"]))
    if v["near_duplicates"]:
        st.subheader("Near-duplicates")
        st.dataframe(pd.DataFrame(v["near_duplicates"], columns=["Kept", "Duplicate", "Similarity"]))
    if st.session_state.gen_stats:
        st.subheader("Generation telemetry")
        st.dataframe(pd.DataFrame(st.session_state.gen_stats))


# ------------------------------------------------------------------ 9 export
def export() -> None:
    theme.header("Export Centre", "Download test cases as Excel (with requirements, traceability and coverage sheets) or CSV.")
    if not (_need_reqs() and _need_cases()):
        return
    cases, reqs = state.cases(), state.reqs()
    rep = validate_all(cases, reqs)
    approved = [c for c in cases if c.status == "Approved"]
    if rep["with_issues"]:
        st.warning(f"{rep['with_issues']} test case(s) still have validation issues. Fix them on Review & Approval before sharing.")
    c = st.columns(3)
    c[0].download_button("Excel: all test cases", exporter.to_excel_bytes(cases, reqs), "test_cases_all.xlsx",
                         "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    c[1].download_button(f"Excel: approved only ({len(approved)})", exporter.to_excel_bytes(cases, reqs, approved_only=True),
                         "test_cases_approved.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                         disabled=not approved)
    c[2].download_button("CSV: all test cases", exporter.to_csv_bytes(cases), "test_cases_all.csv", "text/csv")
    st.subheader("Preview")
    st.dataframe(exporter.cases_to_df(cases))


ROUTES = {"Dashboard": dashboard, "Requirement Upload": upload, "Requirement Analysis": analysis,
          "Test Case Generation": generation, "Test Data Generation": test_data_page,
          "Review & Approval": review, "Coverage & Traceability": coverage,
          "Evaluation Dashboard": evaluation, "Export Centre": export}
