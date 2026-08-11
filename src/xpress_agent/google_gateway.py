"""Production Google Sheets adapter for the fixed Xpress workbook."""

from __future__ import annotations

import re
from typing import Any

from xpress_agent import contract
from xpress_agent.state import AuditRequest, ChangeRecord, Finding, WorkbookSnapshot

_SHEETS_SCOPE = "https://www.googleapis.com/auth/spreadsheets"
_DATA_END_ROW = contract.DATA_START_ROW + contract.PRIMARY_TABLE_CAPACITY - 1
_DRIVE_URL_RE = re.compile(r"https://drive\.google\.com/[^\s]+")
_SOURCE_RE = re.compile(r"'([^']+)'!")


class GoogleSheetsGateway:
    """Bounded, read-before-write adapter for the production workbook."""

    def __init__(self, service: Any, spreadsheet_id: str = contract.SPREADSHEET_ID) -> None:
        if spreadsheet_id != contract.SPREADSHEET_ID:
            raise ValueError("GoogleSheetsGateway is restricted to the fixed Xpress workbook")
        self.service = service
        self.spreadsheet_id = spreadsheet_id
        self._snapshot_captured = False

    @classmethod
    def from_default_credentials(cls) -> GoogleSheetsGateway:
        """Build a gateway from Application Default Credentials."""
        try:
            import google.auth
            from googleapiclient.discovery import build
        except ImportError as exc:  # pragma: no cover - depends on optional extra
            raise RuntimeError(
                "Install the google extra: uv sync --extra google"
            ) from exc

        credentials, _ = google.auth.default(scopes=[_SHEETS_SCOPE])
        service = build("sheets", "v4", credentials=credentials, cache_discovery=False)
        return cls(service)

    def read_snapshot(self, request: AuditRequest) -> WorkbookSnapshot:
        if request.get("spreadsheet_id") != self.spreadsheet_id:
            raise ValueError("Request spreadsheet_id does not match the fixed workbook")

        ranges = [
            f"'{sheet}'!A{contract.HEADER_ROW}:AJ{_DATA_END_ROW}"
            for sheet in ("Ready to Order", "On Order", "Master Tracker")
        ]
        ranges.extend(
            [
                f"'Builder Import'!A{contract.HEADER_ROW}:AF{_DATA_END_ROW}",
                "'Dashboard'!A1:Z30",
            ]
        )
        ranges.extend(
            f"'{location}'!A{contract.HEADER_ROW}:Z{_DATA_END_ROW}"
            for location in contract.LOCATIONS
        )

        response = (
            self.service.spreadsheets()
            .get(
                spreadsheetId=self.spreadsheet_id,
                ranges=ranges,
                includeGridData=True,
            )
            .execute()
        )
        sheet_names = [
            sheet.get("properties", {}).get("title", "")
            for sheet in response.get("sheets", [])
        ]
        grids = self._grid_map(response)

        records_by_stage = {
            stage: self._stage_records(stage, grids.get(stage, []))
            for stage in contract.ACTIVE_STAGES
        }
        pricing_records: list[dict[str, object]] = []
        for stage in contract.ACTIVE_STAGES:
            pricing_records.extend(self._pricing_records(stage, grids.get(stage, [])))

        snapshot: WorkbookSnapshot = {
            "sheet_names": sheet_names,
            "header_rows": {
                name: contract.HEADER_ROW for name in sheet_names if name in contract.MANAGED_SHEETS
            },
            "records_by_stage": records_by_stage,
            "formula_defects": self._formula_defects(grids),
            "validation_defects": [],
            "derived_view_sources": self._derived_view_sources(grids),
            "dashboard_ready_source": self._dashboard_ready_source(grids.get("Dashboard", [])),
            "pricing_records": pricing_records,
            "source_evidence": self._source_evidence(records_by_stage),
            "portal": {},
        }
        self._snapshot_captured = True
        return snapshot

    def apply_repair(self, repair: dict[str, object]) -> ChangeRecord:
        if not self._snapshot_captured:
            raise RuntimeError("A bounded snapshot must be captured before any repair")

        kind = str(repair.get("kind") or "")
        sheet = str(repair.get("sheet") or "")
        if sheet not in contract.MANAGED_SHEETS:
            raise ValueError(f"Repair targets unmanaged sheet: {sheet}")

        if kind == "restore_price_formula":
            cell_range = str(repair.get("range") or "")
            field = str(repair.get("field") or "")
            formula = self._price_formula(sheet, cell_range, field)
        elif kind == "restore_builder_ready_formula":
            cell_range = str(repair.get("range") or "")
            row = self._row_number(cell_range)
            formula = self._builder_ready_formula(row)
        elif kind == "restore_dashboard_ready_reference":
            cell_range = "B7"
            formula = (
                "=COUNTIFS('Ready to Order'!I7:I106,\"<>\","
                "'Ready to Order'!E7:E106,\"Ready to Order\")"
            )
        elif kind == "restore_derived_reference":
            cell_range = "A7"
            formula = self._derived_formula(sheet)
        else:
            raise ValueError(f"Unsupported repair kind: {kind}")

        before = self._read_formula(sheet, cell_range)
        self._write_formula(sheet, cell_range, formula)
        return {
            "sheet": sheet,
            "range": cell_range,
            "before": before,
            "after": formula,
            "reason": kind,
            "verified": False,
        }

    def verify_repair(self, change: ChangeRecord) -> bool:
        actual = self._read_formula(change["sheet"], change["range"])
        return actual == change["after"]

    @staticmethod
    def _grid_map(response: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
        result: dict[str, list[dict[str, Any]]] = {}
        for sheet in response.get("sheets", []):
            title = sheet.get("properties", {}).get("title")
            data = sheet.get("data", [])
            if title and data:
                result[str(title)] = data[0].get("rowData", [])
        return result

    def _stage_records(
        self, stage: str, rows: list[dict[str, Any]]
    ) -> list[dict[str, object]]:
        if not rows:
            return []
        headers = self._headers(rows[0])
        records: list[dict[str, object]] = []
        source_header = "Build #" if stage == "Builder Import" else "Source Build #"
        status_header = "Build Status" if stage == "Builder Import" else "Order Status"
        for offset, row in enumerate(rows[1:], start=contract.DATA_START_ROW):
            values = self._row_values(row, headers)
            source_id = str(values.get(source_header) or "").strip()
            order_id = str(values.get("Order ID") or "").strip()
            if not source_id and not order_id:
                continue
            values.update(
                {
                    "source_build_id": source_id,
                    "order_id": order_id,
                    "status": str(values.get(status_header) or "").strip(),
                    "sheet": stage,
                    "row": offset,
                }
            )
            records.append(values)
        return records

    def _pricing_records(
        self, sheet: str, rows: list[dict[str, Any]]
    ) -> list[dict[str, object]]:
        if not rows:
            return []
        headers = self._headers(rows[0])
        aliases = {
            "build_msrp": "Build MSRP",
            "estimated_dealer_cost": (
                "Dealer Cost Estimate" if sheet == "Builder Import" else "Est. Dealer Cost"
            ),
            "listed_msrp": "Listed MSRP",
            "dsrp": "DSRP",
        }
        source_header = "Build #" if sheet == "Builder Import" else "Source Build #"
        records: list[dict[str, object]] = []
        for row_number, row in enumerate(rows[1:], start=contract.DATA_START_ROW):
            values = self._row_values(row, headers)
            source_id = str(values.get(source_header) or "").strip()
            build_msrp = values.get(aliases["build_msrp"])
            if not source_id or not isinstance(build_msrp, int | float):
                continue
            item: dict[str, object] = {
                "source_build_id": source_id,
                "build_msrp": build_msrp,
            }
            for field, header in aliases.items():
                item[field] = values.get(header)
                column = headers.get(header)
                if column is not None:
                    item[f"{field}_cell"] = f"{sheet}!{self._column_name(column)}{row_number}"
            records.append(item)
        return records

    def _formula_defects(self, grids: dict[str, list[dict[str, Any]]]) -> list[Finding]:
        findings: list[Finding] = []
        rows = grids.get("Builder Import", [])
        if rows:
            headers = self._headers(rows[0])
            ready_col = headers.get("Master Row Ready?")
            if ready_col is not None:
                for row_number, row in enumerate(rows[1:], start=contract.DATA_START_ROW):
                    cells = row.get("values", [])
                    cell = cells[ready_col] if ready_col < len(cells) else {}
                    formula = cell.get("userEnteredValue", {}).get("formulaValue")
                    expected = self._builder_ready_formula(row_number)
                    if formula != expected:
                        findings.append(
                            {
                                "code": "builder_ready_formula",
                                "category": "formula",
                                "disposition": "clear_repair",
                                "message": f"Builder readiness formula is wrong at row {row_number}.",
                                "sheet": "Builder Import",
                                "range": f"AD{row_number}",
                                "expected": expected,
                                "actual": formula,
                                "repair": {
                                    "kind": "restore_builder_ready_formula",
                                    "sheet": "Builder Import",
                                    "range": f"AD{row_number}",
                                },
                            }
                        )
        return findings

    def _derived_view_sources(
        self, grids: dict[str, list[dict[str, Any]]]
    ) -> dict[str, str]:
        result: dict[str, str] = {}
        for sheet in ("Master Tracker", *contract.LOCATIONS):
            rows = grids.get(sheet, [])
            if len(rows) < 2:
                continue
            formula = self._cell_formula(rows[1], 0)
            match = _SOURCE_RE.search(formula or "")
            if match:
                result[sheet] = match.group(1)
        return result

    def _dashboard_ready_source(self, rows: list[dict[str, Any]]) -> str:
        if len(rows) < 7:
            return ""
        formula = self._cell_formula(rows[6], 1)
        match = _SOURCE_RE.search(formula or "")
        return match.group(1) if match else ""

    @staticmethod
    def _source_evidence(
        records_by_stage: dict[str, list[dict[str, object]]]
    ) -> list[dict[str, object]]:
        records = records_by_stage.get("On Order", []) or records_by_stage.get(
            "Ready to Order", []
        )
        result: list[dict[str, object]] = []
        for record in records:
            notes = str(record.get("Notes") or "")
            match = _DRIVE_URL_RE.search(notes)
            result.append(
                {
                    "source_build_id": record.get("source_build_id"),
                    "link_expected": bool(record.get("source_build_id")),
                    "link_present": bool(match),
                    "source_ref": match.group(0) if match else None,
                }
            )
        return result

    @staticmethod
    def _headers(row: dict[str, Any]) -> dict[str, int]:
        result: dict[str, int] = {}
        for index, cell in enumerate(row.get("values", [])):
            value = cell.get("formattedValue")
            if value:
                result[str(value)] = index
        return result

    def _row_values(
        self, row: dict[str, Any], headers: dict[str, int]
    ) -> dict[str, object]:
        cells = row.get("values", [])
        result: dict[str, object] = {}
        for header, index in headers.items():
            cell = cells[index] if index < len(cells) else {}
            result[header] = self._effective_value(cell)
        return result

    @staticmethod
    def _effective_value(cell: dict[str, Any]) -> object:
        value = cell.get("effectiveValue", {})
        for key in ("stringValue", "numberValue", "boolValue", "errorValue"):
            if key in value:
                return value[key]
        return ""

    @staticmethod
    def _cell_formula(row: dict[str, Any], column: int) -> str | None:
        cells = row.get("values", [])
        if column >= len(cells):
            return None
        return cells[column].get("userEnteredValue", {}).get("formulaValue")

    @staticmethod
    def _builder_ready_formula(row: int) -> str:
        return (
            f'=IF(AND(B{row}<>"",D{row}<>"",E{row}<>"",G{row}<>"",H{row}<>"",'
            f'I{row}<>"",COUNTA(K{row}:O{row})>0,S{row}<>"",W{row}<>""),"Yes","No")'
        )

    @staticmethod
    def _price_formula(sheet: str, cell_range: str, field: str) -> str:
        row = GoogleSheetsGateway._row_number(cell_range)
        if sheet == "Builder Import":
            formulas = {
                "estimated_dealer_cost": f'=IF(ISNUMBER(W{row}),W{row}*0.85,"")',
                "listed_msrp": f'=IF(ISNUMBER(X{row}),X{row}*(1+0.38),"")',
                "dsrp": f'=IF(ISNUMBER(X{row}),X{row}*(1+0.22),"")',
            }
        elif sheet in {"Ready to Order", "On Order"}:
            formulas = {
                "estimated_dealer_cost": f'=IF(ISNUMBER(Q{row}),Q{row}*0.85,"")',
                "listed_msrp": f'=IF(ISNUMBER(R{row}),R{row}*(1+0.38),"")',
                "dsrp": f'=IF(ISNUMBER(R{row}),R{row}*(1+0.22),"")',
            }
        else:
            raise ValueError(f"Price repair is not supported on {sheet}")
        try:
            return formulas[field]
        except KeyError as exc:
            raise ValueError(f"Unsupported price field: {field}") from exc

    @staticmethod
    def _derived_formula(sheet: str) -> str:
        if sheet == "Master Tracker":
            return '=IFERROR(FILTER(\'On Order\'!A7:AJ106,\'On Order\'!I7:I106<>""),"")'
        if sheet in contract.LOCATIONS:
            return (
                "=IFERROR(FILTER(CHOOSECOLS('On Order'!A7:AI106,"
                "1,2,4,5,6,7,8,9,12,13,14,16,18,19,20,22,24,26,27,33,35),"
                f"'On Order'!C7:C106=\"{sheet}\"),\"No orders entered for {sheet}\")"
            )
        raise ValueError(f"Unsupported derived view: {sheet}")

    @staticmethod
    def _row_number(cell_range: str) -> int:
        match = re.search(r"(\d+)$", cell_range)
        if not match:
            raise ValueError(f"Repair range must be a single A1 cell: {cell_range}")
        row = int(match.group(1))
        if not contract.DATA_START_ROW <= row <= _DATA_END_ROW:
            raise ValueError(f"Repair row is outside the bounded table: {row}")
        return row

    @staticmethod
    def _column_name(index: int) -> str:
        value = index + 1
        name = ""
        while value:
            value, remainder = divmod(value - 1, 26)
            name = chr(65 + remainder) + name
        return name

    def _read_formula(self, sheet: str, cell_range: str) -> object:
        response = (
            self.service.spreadsheets()
            .values()
            .get(
                spreadsheetId=self.spreadsheet_id,
                range=f"'{sheet}'!{cell_range}",
                valueRenderOption="FORMULA",
            )
            .execute()
        )
        values = response.get("values", [])
        return values[0][0] if values and values[0] else ""

    def _write_formula(self, sheet: str, cell_range: str, formula: str) -> None:
        (
            self.service.spreadsheets()
            .values()
            .update(
                spreadsheetId=self.spreadsheet_id,
                range=f"'{sheet}'!{cell_range}",
                valueInputOption="USER_ENTERED",
                body={"values": [[formula]]},
            )
            .execute()
        )
