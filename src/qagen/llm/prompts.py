"""Prompt templates. Kept compact for a 4B model on CPU."""

ANALYSIS_SYSTEM = (
    "You are a senior QA analyst. Analyse ONE software requirement and reply with JSON only."
)

ANALYSIS_USER = """Requirement ID: {req_id}
Text:
{text}

Return JSON with exactly these keys:
{{
 "kind": "Functional" or "Non-Functional",
 "nfr_category": "Security|Performance|Usability|Reliability|Compliance|Accessibility|" or "",
 "acceptance_criteria": ["..."],   // criteria stated in the text; if none stated, derive up to 3 and prefix each with "[derived] "
 "missing_criteria": ["..."]       // important acceptance criteria that are absent (validation, error handling, limits, security)
}}"""

GENERATION_SYSTEM = (
    "You are a senior QA automation architect. Design precise, non-duplicate test cases. "
    "Reply with JSON only. Never invent features that are not in the requirement."
)

GENERATION_USER = """Requirement ID: {req_id}
Type: {kind}
Requirement:
{text}

Generate up to {max_tests} test cases covering these types where applicable:
{types}

Return JSON: {{"test_cases": [ {{
 "scenario": "short title",
 "description": "what is verified",
 "preconditions": "...",
 "steps": ["step 1", "step 2"],
 "test_data": "concrete values, e.g. username=abc; password=P@ss1",
 "expected_result": "specific, observable outcome",
 "priority": "High|Medium|Low",
 "test_type": "Positive|Negative|Boundary|Edge|Security|Validation",
 "automation": "Yes|Partial|No",
 "covers_criterion": "the acceptance criterion this test traces to"
}} ]}}

Rules: expected_result must be specific and observable. Boundary tests must use concrete min/max values."""

TESTDATA_SYSTEM = "You are a QA test data specialist. Reply with JSON only."

TESTDATA_USER = """Test scenario: {scenario}
Test type: {test_type}
Requirement: {text}

Return JSON: {{"valid": ["..."], "invalid": ["..."], "boundary": ["..."], "notes": "..."}}
Use concrete values (max 4 per list). Never use real personal data."""
