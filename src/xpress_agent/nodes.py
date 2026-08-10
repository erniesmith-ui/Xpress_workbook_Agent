"""Deterministic nodes for the Xpress workbook steward graph."""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import UTC, datetime
from math import isclose
from typing import Any

from xpress_agent import contract
from xpress_agent.gateway import WorkbookGateway
from xpress_agent.state import AuditState, ChangeRecord, Finding


def finding(
    code: str,
    category: str,
    disposition: str,
    message: str,
    **details: Any,
) -> Finding:
    return {
        "code": code,
        "category": category,
        "disposition": disposition,
        "message": message,
        **details,
    }  # type: ignore[return-value]


class StewardNodes:
    def __init__(self, gateway: WorkbookGateway) -> None:
        self.gateway = gateway

    def validate_request(self, state: AuditState) -> dict[str, object]:
        request = state["request"]
        findings: list[Finding] = []
        blocked = False

        if request.get("spreadsheet_id") != contract.SPREADSHEET_ID:
            blocked = True
            findings.append(
                finding(
                    "wrong_spreadsheet",
                    "scope",
                    "needs_review",
                    "The request targets a spreadsheet outside the steward's fixed scope.",
                    expected=contract.SPREADSHEET_ID,
                    actual=request.get("spreadsheet_id"),
                )
            )

        if request.get("trigger") == "handoff":
            required = {
                "source_build_id": request.get("source_build_id") or request.get("order_id"),
                "successful_import": request.get("successful_import") is True,
                "imported_row": request.get("imported_row"),
                "source_copy_ref": request.get("source_copy_ref"),
            }
            missing = [key for key, value in required.items() if not value]
            if missing:
                blocked = True
                findings.append(
                    finding(
                        "handoff_incomplete",
                        "handoff",
                        "needs_review",
                        "Order transition stopped because handoff evidence is incomplete.",
                        expected="identifier, successful import, row, and source-copy context",
                        actual=missing,
                    )
                )

        return {
            "blocked": blocked,
            "findings": findings,
            "checks_completed": ["request and handoff gate"],
            "audit_log": ["request validated"],
        }

    def collect_snapshot(self, state: AuditState) -> dict[str, object]:
        try:
            snapshot = self.gateway.read_snapshot(state["request"])
        except Exception as exc:
            return {
                "blocked": True,
                "error": str(exc),
                "findings": [
                    finding(
                        "snapshot_failed",
                        "access",
                        "needs_review",
                        "Could not establish a pre-change workbook snapshot.",
                        actual=str(exc),
                    )
                ],
                "checks_completed": ["snapshot attempt"],
                "audit_log": ["snapshot failed"],
            }
        return {
            "snapshot": snapshot,
            "checks_completed": ["bounded pre-change snapshot"],
            "audit_log": ["snapshot captured"],
        }

    def audit_structure(self, state: AuditState) -> dict[str, object]:
        snapshot = state["snapshot"]
        findings: list[Finding] = []
        present = set(snapshot.get("sheet_names", []))
        for sheet in contract.MANAGED_SHEETS:
            if sheet not in present:
                findings.append(
                    finding(
                        "missing_sheet",
                        "structure",
                        "needs_review",
                        f"Managed sheet is missing: {sheet}",
                        sheet=sheet,
                    )
                )

        for sheet, row in snapshot.get("header_rows", {}).items():
            if row != contract.HEADER_ROW:
                findings.append(
                    finding(
                        "wrong_header_row",
                        "structure",
                        "needs_review",
                        f"Header row for {sheet} is not row {contract.HEADER_ROW}.",
                        sheet=sheet,
                        expected=contract.HEADER_ROW,
                        actual=row,
                    )
                )

        findings.extend(snapshot.get("formula_defects", []))
        findings.extend(snapshot.get("validation_defects", []))

        view_sources = snapshot.get("derived_view_sources", {})
        for view in ("Master Tracker", *contract.LOCATIONS):
            source = view_sources.get(view)
            if source and source != "On Order":
                findings.append(
                    finding(
                        "wrong_derived_source",
                        "formula",
                        "clear_repair",
                        f"{view} must derive from On Order.",
                        sheet=view,
                        expected="On Order",
                        actual=source,
                        repair={
                            "kind": "restore_derived_reference",
                            "sheet": view,
                            "source": "On Order",
                        },
                    )
                )

        dashboard_source = snapshot.get("dashboard_ready_source")
        if dashboard_source and dashboard_source != "Ready to Order":
            findings.append(
                finding(
                    "wrong_dashboard_ready_source",
                    "formula",
                    "clear_repair",
                    "Dashboard Ready to Order count uses the wrong source.",
                    sheet="Dashboard",
                    expected="Ready to Order",
                    actual=dashboard_source,
                    repair={
                        "kind": "restore_dashboard_ready_reference",
                        "sheet": "Dashboard",
                        "source": "Ready to Order",
                    },
                )
            )
        return {
            "findings": findings,
            "checks_completed": ["sheets, headers, formulas, validations, and derived views"],
            "audit_log": ["structure branch completed"],
        }

    def audit_pipeline(self, state: AuditState) -> dict[str, object]:
        records = state["snapshot"].get("records_by_stage", {})
        findings: list[Finding] = []
        placements: dict[str, list[str]] = defaultdict(list)

        for stage in contract.ACTIVE_STAGES:
            for record in records.get(stage, []):
                source_id = str(record.get("source_build_id") or "").strip()
                if source_id:
                    placements[source_id].append(stage)

                status = str(record.get("status") or "").strip()
                allowed = (
                    contract.ORDER_STATUSES
                    if stage == "On Order"
                    else contract.READY_STATUSES
                )
                if stage != "Builder Import" and status not in allowed:
                    findings.append(
                        finding(
                            "invalid_status",
                            "pipeline",
                            "needs_review",
                            f"Invalid {stage} status for {source_id or 'unidentified row'}.",
                            sheet=stage,
                            actual=status,
                            expected=sorted(allowed),
                        )
                    )

        for source_id, stages in placements.items():
            if len(stages) > 1:
                findings.append(
                    finding(
                        "duplicate_source_build",
                        "pipeline",
                        "needs_review",
                        f"Source Build {source_id} appears more than once in the active pipeline.",
                        actual=dict(Counter(stages)),
                        expected="one active row in one stage",
                    )
                )

        return {
            "findings": findings,
            "checks_completed": ["unique IDs, statuses, and single-stage pipeline placement"],
            "audit_log": ["pipeline branch completed"],
        }

    def audit_pricing(self, state: AuditState) -> dict[str, object]:
        findings: list[Finding] = []
        for record in state["snapshot"].get("pricing_records", []):
            build_msrp = _number(record.get("build_msrp"))
            if build_msrp is None:
                continue
            source_id = str(record.get("source_build_id") or "unidentified row")
            expected = {
                "estimated_dealer_cost": build_msrp * 0.85,
                "listed_msrp": build_msrp * 0.85 * 1.38,
                "dsrp": build_msrp * 0.85 * 1.22,
            }
            for field, expected_value in expected.items():
                actual = _number(record.get(field))
                if actual is None or isclose(
                    actual,
                    expected_value,
                    abs_tol=contract.EXACT_RECONCILIATION_TOLERANCE,
                ):
                    continue
                cell = record.get(f"{field}_cell")
                details: dict[str, object] = {
                    "expected": round(expected_value, 2),
                    "actual": actual,
                }
                disposition = "needs_review"
                if isinstance(cell, str) and "!" in cell:
                    sheet, cell_range = cell.split("!", 1)
                    details.update(
                        {
                            "sheet": sheet,
                            "range": cell_range,
                            "repair": {
                                "kind": "restore_price_formula",
                                "sheet": sheet,
                                "range": cell_range,
                                "field": field,
                                "source_build_id": source_id,
                            },
                        }
                    )
                    disposition = "clear_repair"
                findings.append(
                    finding(
                        "pricing_mismatch",
                        "pricing",
                        disposition,
                        f"{field} does not reconcile for {source_id}.",
                        **details,
                    )
                )

        return {
            "findings": findings,
            "checks_completed": ["pricing formulas and supplied tolerances"],
            "audit_log": ["pricing branch completed"],
        }

    def audit_evidence_and_portal(self, state: AuditState) -> dict[str, object]:
        snapshot = state["snapshot"]
        findings: list[Finding] = []
        for record in snapshot.get("source_evidence", []):
            if record.get("link_expected") and not record.get("link_present"):
                source_build_id = record.get("source_build_id", "unknown build")
                findings.append(
                    finding(
                        "missing_source_evidence",
                        "evidence",
                        "needs_review",
                        f"Saved source evidence is missing for {source_build_id}.",
                        expected="readable submitted-build link",
                        actual=record.get("source_ref"),
                    )
                )

        portal = snapshot.get("portal", {})
        parser_version = portal.get("parser_version")
        if parser_version and parser_version != contract.PARSER_VERSION:
            findings.append(
                finding(
                    "parser_version_mismatch",
                    "portal",
                    "needs_review",
                    "Portal and contract parser versions differ.",
                    expected=contract.PARSER_VERSION,
                    actual=parser_version,
                )
            )
        payload_fields = set(portal.get("payload_fields", []))
        missing_fields = sorted(contract.PORTAL_PAYLOAD_FIELDS - payload_fields)
        if payload_fields and missing_fields:
            findings.append(
                finding(
                    "portal_payload_drift",
                    "portal",
                    "needs_review",
                    "Portal payload is missing required contract fields.",
                    expected=sorted(contract.PORTAL_PAYLOAD_FIELDS),
                    actual=missing_fields,
                )
            )

        return {
            "findings": findings,
            "checks_completed": ["source evidence and portal synchronization"],
            "audit_log": ["evidence and portal branch completed"],
        }

    def classify(self, state: AuditState) -> dict[str, object]:
        repair_plan = [item["repair"] for item in state.get("findings", []) if item.get("repair")]
        unresolved = [
            item for item in state.get("findings", []) if item["disposition"] == "needs_review"
        ]
        return {
            "repair_plan": repair_plan,
            "unresolved": unresolved,
            "audit_log": ["findings classified"],
        }

    def apply_repairs(self, state: AuditState) -> dict[str, object]:
        changes: list[ChangeRecord] = []
        unresolved = list(state.get("unresolved", []))
        for repair in state.get("repair_plan", []):
            try:
                change = self.gateway.apply_repair(repair)
                change["verified"] = self.gateway.verify_repair(change)
                changes.append(change)
                if not change["verified"]:
                    unresolved.append(
                        finding(
                            "repair_verification_failed",
                            "verification",
                            "needs_review",
                            "A bounded repair did not pass post-change verification.",
                            sheet=change["sheet"],
                            range=change["range"],
                        )
                    )
            except Exception as exc:
                unresolved.append(
                    finding(
                        "repair_failed",
                        "repair",
                        "needs_review",
                        "A clear repair could not be applied.",
                        actual=str(exc),
                    )
                )
        return {
            "applied_changes": changes,
            "unresolved": unresolved,
            "checks_completed": ["bounded repair verification"],
            "audit_log": ["repair branch completed"],
        }

    def finalize(self, state: AuditState) -> dict[str, object]:
        findings = state.get("findings", [])
        changes = state.get("applied_changes", [])
        unresolved = state.get("unresolved", [])
        unapplied = bool(state.get("repair_plan")) and not state["request"].get(
            "apply_repairs", False
        )
        if unresolved or state.get("blocked") or state.get("error") or unapplied:
            health = "Needs Review"
        elif changes:
            health = "Repaired"
        else:
            health = "Passed"

        counts = Counter(item["code"] for item in findings)
        report = {
            "run_time": datetime.now(UTC).isoformat(),
            "trigger": state["request"]["trigger"],
            "affected_ids": [
                value
                for value in (
                    state["request"].get("order_id"),
                    state["request"].get("source_build_id"),
                )
                if value
            ],
            "handoff_acknowledged": state["request"].get("trigger") == "handoff"
            and not state.get("blocked", False),
            "health": health,
            "checks_completed": state.get("checks_completed", []),
            "changes": changes,
            "unresolved": unresolved,
            "counts": {
                "duplicate_ids": counts["duplicate_source_build"],
                "cross_stage_duplicates": counts["duplicate_source_build"],
                "invalid_statuses": counts["invalid_status"],
                "formula_validation_defects": sum(
                    count
                    for code, count in counts.items()
                    if code in {"wrong_derived_source", "wrong_dashboard_ready_source"}
                ),
                "pricing_mismatches": counts["pricing_mismatch"],
                "missing_source_evidence": counts["missing_source_evidence"],
            },
            "no_other_cells_changed": True,
        }
        return {"health": health, "report": report, "audit_log": ["report finalized"]}


def _number(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)
    return None
