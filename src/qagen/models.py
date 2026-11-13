"""Domain models shared across layers."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

TEST_TYPES = ["Positive", "Negative", "Boundary", "Edge", "Security", "Validation"]
PRIORITIES = ["High", "Medium", "Low"]
AUTOMATION = ["Yes", "Partial", "No"]
STATUSES = ["Draft", "Approved", "Rejected"]

TEST_CASE_FIELDS = [
    "Test Case ID", "Requirement ID", "Test Scenario", "Test Case Description",
    "Preconditions", "Test Steps", "Test Data", "Expected Result", "Priority",
    "Test Type", "Automation Suitability", "Requirement Traceability",
]
MANDATORY_FIELDS = [
    "Test Case ID", "Requirement ID", "Test Scenario", "Test Case Description",
    "Test Steps", "Expected Result", "Priority", "Test Type",
]


@dataclass
class Requirement:
    req_id: str
    title: str = ""
    description: str = ""
    acceptance_criteria: list[str] = field(default_factory=list)
    kind: str = "Functional"            # Functional | Non-Functional
    nfr_category: str = ""               # Security, Performance, ...
    priority: str = "Medium"
    gaps: list[str] = field(default_factory=list)   # missing-AC findings

    def full_text(self) -> str:
        ac = "\n".join(f"- {a}" for a in self.acceptance_criteria)
        return f"{self.title}\n{self.description}\nAcceptance criteria:\n{ac}".strip()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class TestCase:
    values: dict[str, str]
    status: str = "Draft"
    issues: list[str] = field(default_factory=list)

    @property
    def tc_id(self) -> str:
        return self.values.get("Test Case ID", "")

    def to_row(self) -> dict[str, str]:
        row = {f: self.values.get(f, "") for f in TEST_CASE_FIELDS}
        row["Status"] = self.status
        return row
