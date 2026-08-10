"""Typed shared state for the steward graph."""

from __future__ import annotations

import operator
from typing import Annotated, Literal, NotRequired, TypedDict

Trigger = Literal["scheduled", "handoff", "direct", "question"]
Disposition = Literal["clear_repair", "needs_review"]
Health = Literal["Passed", "Repaired", "Needs Review"]


class AuditRequest(TypedDict):
    trigger: Trigger
    spreadsheet_id: str
    apply_repairs: NotRequired[bool]
    order_id: NotRequired[str]
    source_build_id: NotRequired[str]
    successful_import: NotRequired[bool]
    imported_row: NotRequired[int]
    source_copy_ref: NotRequired[str]


class Finding(TypedDict):
    code: str
    category: str
    disposition: Disposition
    message: str
    sheet: NotRequired[str]
    range: NotRequired[str]
    expected: NotRequired[object]
    actual: NotRequired[object]
    repair: NotRequired[dict[str, object]]


class ChangeRecord(TypedDict):
    sheet: str
    range: str
    before: object
    after: object
    reason: str
    verified: bool


class WorkbookSnapshot(TypedDict, total=False):
    sheet_names: list[str]
    header_rows: dict[str, int]
    records_by_stage: dict[str, list[dict[str, object]]]
    formula_defects: list[Finding]
    validation_defects: list[Finding]
    derived_view_sources: dict[str, str]
    dashboard_ready_source: str
    pricing_records: list[dict[str, object]]
    source_evidence: list[dict[str, object]]
    portal: dict[str, object]


class AuditState(TypedDict, total=False):
    request: AuditRequest
    snapshot: WorkbookSnapshot
    findings: Annotated[list[Finding], operator.add]
    checks_completed: Annotated[list[str], operator.add]
    audit_log: Annotated[list[str], operator.add]
    repair_plan: list[dict[str, object]]
    applied_changes: list[ChangeRecord]
    unresolved: list[Finding]
    health: Health
    report: dict[str, object]
    blocked: bool
    error: str

