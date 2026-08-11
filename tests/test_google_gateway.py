from __future__ import annotations

from typing import Any

import pytest

from xpress_agent.contract import SPREADSHEET_ID
from xpress_agent.google_gateway import GoogleSheetsGateway


class Request:
    def __init__(self, response: dict[str, Any]) -> None:
        self.response = response

    def execute(self) -> dict[str, Any]:
        return self.response


class ValuesApi:
    def __init__(self) -> None:
        self.formulas: dict[str, object] = {}
        self.updates: list[dict[str, Any]] = []

    def get(self, **kwargs: Any) -> Request:
        cell_range = str(kwargs["range"])
        value = self.formulas.get(cell_range, "")
        return Request({"values": [[value]] if value != "" else []})

    def update(self, **kwargs: Any) -> Request:
        self.updates.append(kwargs)
        cell_range = str(kwargs["range"])
        value = kwargs["body"]["values"][0][0]
        self.formulas[cell_range] = value
        return Request({"updatedRange": cell_range})


class SpreadsheetsApi:
    def __init__(self) -> None:
        self.values_api = ValuesApi()

    def values(self) -> ValuesApi:
        return self.values_api


class FakeService:
    def __init__(self) -> None:
        self.api = SpreadsheetsApi()

    def spreadsheets(self) -> SpreadsheetsApi:
        return self.api


def gateway() -> tuple[GoogleSheetsGateway, FakeService]:
    service = FakeService()
    return GoogleSheetsGateway(service), service


def test_gateway_rejects_other_workbooks() -> None:
    with pytest.raises(ValueError, match="fixed Xpress workbook"):
        GoogleSheetsGateway(FakeService(), spreadsheet_id="not-the-xpress-workbook")


def test_repair_requires_snapshot_first() -> None:
    subject, _ = gateway()

    with pytest.raises(RuntimeError, match="snapshot must be captured"):
        subject.apply_repair(
            {
                "kind": "restore_builder_ready_formula",
                "sheet": "Builder Import",
                "range": "AD7",
            }
        )


def test_builder_repair_is_bounded_to_ad_column() -> None:
    subject, _ = gateway()
    subject._snapshot_captured = True

    with pytest.raises(ValueError, match="restricted to Builder Import!AD"):
        subject.apply_repair(
            {
                "kind": "restore_builder_ready_formula",
                "sheet": "Builder Import",
                "range": "AE7",
            }
        )


def test_price_repair_rejects_wrong_target_column() -> None:
    subject, _ = gateway()
    subject._snapshot_captured = True

    with pytest.raises(ValueError, match="does not match its field and sheet"):
        subject.apply_repair(
            {
                "kind": "restore_price_formula",
                "sheet": "On Order",
                "range": "S7",
                "field": "estimated_dealer_cost",
            }
        )


def test_price_repair_writes_one_cell_and_verifies() -> None:
    subject, service = gateway()
    subject._snapshot_captured = True
    service.api.values_api.formulas["'On Order'!R7"] = "=broken"

    change = subject.apply_repair(
        {
            "kind": "restore_price_formula",
            "sheet": "On Order",
            "range": "R7",
            "field": "estimated_dealer_cost",
        }
    )

    assert change["before"] == "=broken"
    assert change["after"] == '=IF(ISNUMBER(Q7),Q7*0.85,"")'
    assert len(service.api.values_api.updates) == 1
    assert service.api.values_api.updates[0]["range"] == "'On Order'!R7"
    assert subject.verify_repair(change) is True


def test_source_evidence_checks_ready_and_on_order() -> None:
    result = GoogleSheetsGateway._source_evidence(
        {
            "Ready to Order": [
                {
                    "source_build_id": "BUILD-READY",
                    "Notes": "Submitted build copy: https://drive.google.com/file/d/ready/view",
                }
            ],
            "On Order": [
                {
                    "source_build_id": "BUILD-ORDERED",
                    "Notes": "No source link yet",
                }
            ],
        }
    )

    assert [item["source_build_id"] for item in result] == ["BUILD-READY", "BUILD-ORDERED"]
    assert result[0]["link_present"] is True
    assert result[1]["link_present"] is False


def test_repair_range_must_be_single_bounded_cell() -> None:
    subject, _ = gateway()
    subject._snapshot_captured = True

    for invalid_range in ("R6", "R107", "R7:R8", "7", "R7 "):
        with pytest.raises(ValueError):
            subject.apply_repair(
                {
                    "kind": "restore_price_formula",
                    "sheet": "On Order",
                    "range": invalid_range,
                    "field": "estimated_dealer_cost",
                }
            )


def test_fixed_spreadsheet_id_constant_is_used() -> None:
    subject, _ = gateway()
    assert subject.spreadsheet_id == SPREADSHEET_ID
