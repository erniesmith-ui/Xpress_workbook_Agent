"""Workbook I/O boundary used by graph nodes."""

from __future__ import annotations

from typing import Protocol

from xpress_agent.state import AuditRequest, ChangeRecord, WorkbookSnapshot


class WorkbookGateway(Protocol):
    """Read-before-write adapter for Google Sheets or a test double."""

    def read_snapshot(self, request: AuditRequest) -> WorkbookSnapshot:
        """Return only the bounded ranges needed for this run."""

    def apply_repair(self, repair: dict[str, object]) -> ChangeRecord:
        """Apply one smallest-possible repair and return its before/after record."""

    def verify_repair(self, change: ChangeRecord) -> bool:
        """Re-read the changed range and verify the intended value or formula."""


class MissingGateway:
    """Default adapter that prevents accidental workbook access."""

    def read_snapshot(self, request: AuditRequest) -> WorkbookSnapshot:
        raise RuntimeError("No WorkbookGateway configured")

    def apply_repair(self, repair: dict[str, object]) -> ChangeRecord:
        raise RuntimeError("No WorkbookGateway configured")

    def verify_repair(self, change: ChangeRecord) -> bool:
        raise RuntimeError("No WorkbookGateway configured")
