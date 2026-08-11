"""CLI for JSON snapshots and guarded live Xpress workbook audits."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from xpress_agent.contract import SPREADSHEET_ID
from xpress_agent.graph import build_graph
from xpress_agent.state import AuditRequest, ChangeRecord, WorkbookSnapshot


class JsonGateway:
    def __init__(self, snapshot_path: Path) -> None:
        self.snapshot_path = snapshot_path

    def read_snapshot(self, request: AuditRequest) -> WorkbookSnapshot:
        return json.loads(self.snapshot_path.read_text(encoding="utf-8"))

    def apply_repair(self, repair: dict[str, object]) -> ChangeRecord:
        raise RuntimeError("JSON gateway is read-only; do not request repairs")

    def verify_repair(self, change: ChangeRecord) -> bool:
        return False


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the Xpress steward graph")
    parser.add_argument(
        "snapshot",
        nargs="?",
        type=Path,
        help="Normalized JSON snapshot. Omit when using --live.",
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="Read the fixed production Google Sheet using Application Default Credentials.",
    )
    parser.add_argument(
        "--apply-repairs",
        action="store_true",
        help="Allow bounded live repairs. Requires --live and --confirm-live-writes.",
    )
    parser.add_argument(
        "--confirm-live-writes",
        action="store_true",
        help="Explicit acknowledgement required before any production workbook write.",
    )
    parser.add_argument(
        "--trigger",
        choices=("scheduled", "handoff", "direct", "question"),
        default="direct",
    )
    return parser


def main() -> None:
    parser = _parser()
    args = parser.parse_args()

    if args.live and args.snapshot is not None:
        parser.error("use either a JSON snapshot or --live, not both")
    if not args.live and args.snapshot is None:
        parser.error("provide a JSON snapshot or use --live")
    if args.apply_repairs and not args.live:
        parser.error("--apply-repairs is supported only with --live")
    if args.apply_repairs and not args.confirm_live_writes:
        parser.error("--apply-repairs requires --confirm-live-writes")
    if args.confirm_live_writes and not args.apply_repairs:
        parser.error("--confirm-live-writes is valid only with --apply-repairs")

    if args.live:
        from xpress_agent.google_gateway import GoogleSheetsGateway

        gateway = GoogleSheetsGateway.from_default_credentials()
    else:
        gateway = JsonGateway(args.snapshot)

    request: AuditRequest = {
        "trigger": args.trigger,
        "spreadsheet_id": SPREADSHEET_ID,
        "apply_repairs": bool(args.apply_repairs),
    }
    result = build_graph(gateway).invoke({"request": request})
    print(json.dumps(result["report"], indent=2, default=str))


if __name__ == "__main__":
    main()
