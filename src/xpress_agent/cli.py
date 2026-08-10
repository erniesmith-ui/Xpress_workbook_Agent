"""Small CLI for exercising the graph with a JSON snapshot."""

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


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Xpress steward graph")
    parser.add_argument("snapshot", type=Path, help="Normalized JSON workbook snapshot")
    parser.add_argument(
        "--trigger",
        choices=("scheduled", "handoff", "direct", "question"),
        default="direct",
    )
    args = parser.parse_args()

    request: AuditRequest = {
        "trigger": args.trigger,
        "spreadsheet_id": SPREADSHEET_ID,
        "apply_repairs": False,
    }
    result = build_graph(JsonGateway(args.snapshot)).invoke({"request": request})
    print(json.dumps(result["report"], indent=2, default=str))


if __name__ == "__main__":
    main()

