from qagen.models import Requirement, TestCase
from qagen.validation import validators as v
from qagen.services.test_data import boundary_values, extract_limits
from qagen.llm.ollama_client import extract_json, strip_think


def tc(i="TC-1", rid="REQ-1", **kw):
    vals = {"Test Case ID": i, "Requirement ID": rid, "Test Scenario": "Login ok", "Test Case Description": "d",
            "Test Steps": "1. a", "Expected Result": "User lands on the dashboard", "Priority": "High",
            "Test Type": "Positive", "Requirement Traceability": rid}
    vals.update(kw)
    return TestCase(values=vals)


def test_mandatory_and_vague():
    c = tc(**{"Expected Result": "works", "Test Steps": ""})
    assert any("Test Steps" in i for i in v.check_mandatory(c))
    assert v.check_expected_result(c)


def test_traceability_unknown_req():
    assert v.check_traceability(tc(rid="REQ-9"), {"REQ-1"})


def test_duplicate_ids_and_renumber():
    cases = [tc("TC-1"), tc("TC-1", **{"Test Scenario": "other"})]
    assert v.find_duplicate_ids(cases) == {"TC-1": 2}
    assert v.make_ids_unique(cases) == 1 and cases[1].tc_id == "TC-1-2"


def test_dedup_keeps_approved():
    a, b = tc("TC-1"), tc("TC-2")
    b.status = "Approved"
    kept, removed = v.deduplicate([a, b])
    assert len(kept) == 2 and not removed
    c = tc("TC-3")
    kept, removed = v.deduplicate([a, c])
    assert len(kept) == 1 and removed[0][1] == "TC-3"


def test_coverage():
    r = Requirement("REQ-1", acceptance_criteria=["User lands on the dashboard", "Account is locked after failures"])
    rep = v.compute_coverage([r, Requirement("REQ-2")], [tc()])
    assert rep.requirement_coverage_pct == 50.0
    assert rep.criteria_coverage_pct == 50.0
    assert ("REQ-1", "Account is locked after failures") in rep.uncovered_criteria


def test_limits_and_boundaries():
    assert extract_limits("between 8 and 20 characters") == [(8, 20)]
    assert boundary_values(8, 20)["boundary"] == [7, 8, 9, 19, 20, 21]
    assert extract_limits("at least 1 and at most 50000") == [(1, 50000)]


def test_json_helpers():
    assert strip_think("<think>x</think>{\"a\":1}") == '{"a":1}'
    assert extract_json("```json\n{\"a\": 1}\n```") == {"a": 1}
    assert extract_json("Sure! {\"a\": [1,2]} done") == {"a": [1, 2]}


def test_boundary_cases_differing_by_number_are_not_duplicates():
    a = tc("TC-1", **{"Test Scenario": "Password below minimum (7)", "Test Type": "Boundary", "Test Data": "password=Abcd#12 (7 chars)",
                      "Test Steps": "1. Enter a 7-character password", "Expected Result": "Validation says password must be 8 to 20 characters"})
    b = tc("TC-2", **{"Test Scenario": "Password above maximum (21)", "Test Type": "Boundary", "Test Data": "password=Abcdefgh#12345678901 (21 chars)",
                      "Test Steps": "1. Enter a 21-character password", "Expected Result": "Validation says password must be 8 to 20 characters"})
    assert v.find_duplicates([a, b]) == []
    kept, removed = v.deduplicate([a, b])
    assert len(kept) == 2 and not removed
