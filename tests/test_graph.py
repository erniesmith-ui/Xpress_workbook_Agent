from __future__ import annotations

from copy import deepcopy

from xpress_agent import build_graph
from xpress_agent.contract import MANAGED_SHEETS, PARSER_VERSION, PORTAL_PAYLOAD_FIELDS, SPREADSHEET_ID
from xpress_agent.state import AuditRequest, ChangeRecord, WorkbookSnapshot


class FakeGateway:
    def __init__(self, snapshot: WorkbookSnapshot) -> None:
        self.snapshot = snapshot
        self.reads = 0
        self.repairs: list[dict[str, object]] = []

    def read_snapshot(self, request: AuditRequest) -> WorkbookSnapshot:
        self.reads += 1
        return deepcopy(self.snapshot)

    def apply_repair(self, repair: dict[str, object]) -> ChangeRecord:
        self.repairs.append(repair)
        return {
            "sheet": str(repair["sheet"]),
            "range": str(repair.get("range", "derived reference")),
            "before": "wrong",
            "after": repair.get("source", "restored formula"),
            "reason": str(repair["kind"]),
            "verified": False,
        }

    def verify_repair(self, change: ChangeRecord) -> bool:
        return True


def healthy_snapshot() -> WorkbookSnapshot:
    return {
        "sheet_names": list(MANAGED_SHEETS),
        "header_rows": {sheet: 6 for sheet in MANAGED_SHEETS},
        "records_by_stage": {
            "Builder Import": [],
            "Ready to Order": [],
            "On Order": [],
        },
        "derived_view_sources": {
            "Master Tracker": "On Order",
            "Grandlake": "On Order",
            "Eufaula": "On Order",
            "OKC": "On Order",
            "Central Crossing": "On Order",
            "Toons Table Rock": "On Order",
        },
        "dashboard_ready_source": "Ready to Order",
        "pricing_records": [],
        "source_evidence": [],
        "portal": {
            "parser_version": PARSER_VERSION,
            "payload_fields": sorted(PORTAL_PAYLOAD_FIELDS),
        },
    }


def request(**overrides: object) -> AuditRequest:
    value: AuditRequest = {
        "trigger": "scheduled",
        "spreadsheet_id": SPREADSHEET_ID,
        "apply_repairs": True,
    }
    value.update(overrides)  # type: ignore[typeddict-item]
    return value


def test_healthy_snapshot_passes_without_writes() -> None:
    gateway = FakeGateway(healthy_snapshot())
    result = build_graph(gateway).invoke({"request": request()})

    assert result["health"] == "Passed"
    assert gateway.reads == 1
    assert gateway.repairs == []
    assert len(result["checks_completed"]) == 6


def test_incomplete_handoff_stops_before_workbook_read() -> None:
    gateway = FakeGateway(healthy_snapshot())
    result = build_graph(gateway).invoke(
        {
            "request": request(
                trigger="handoff",
                source_build_id="BUILD-42",
                successful_import=False,
            )
        }
    )

    assert result["health"] == "Needs Review"
    assert result["report"]["handoff_acknowledged"] is False
    assert gateway.reads == 0


def test_parallel_findings_converge_and_clear_repair_is_verified() -> None:
    snapshot = healthy_snapshot()
    snapshot["dashboard_ready_source"] = "Builder Import"
    snapshot["records_by_stage"] = {
        "Builder Import": [{"source_build_id": "BUILD-1"}],
        "Ready to Order": [{"source_build_id": "BUILD-1", "status": "Ready to Order"}],
        "On Order": [],
    }
    gateway = FakeGateway(snapshot)
    result = build_graph(gateway).invoke({"request": request()})

    assert result["health"] == "Needs Review"
    assert len(gateway.repairs) == 1
    assert result["applied_changes"][0]["verified"] is True
    assert result["report"]["counts"]["duplicate_ids"] == 1


def test_unapplied_clear_repair_is_reported_for_review() -> None:
    snapshot = healthy_snapshot()
    snapshot["dashboard_ready_source"] = "Builder Import"
    gateway = FakeGateway(snapshot)
    result = build_graph(gateway).invoke({"request": request(apply_repairs=False)})

    assert result["health"] == "Needs Review"
    assert result["repair_plan"]
    assert gateway.repairs == []

