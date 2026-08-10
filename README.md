# Xpress Workbook Agent

A graph-engineered steward for the fixed Xpress boat-orders Google Sheet. The project uses
[LangGraph](https://docs.langchain.com/oss/python/langgraph/overview) to make state, audit nodes,
routing, write gates, and verification explicit.

## What is included

- Typed shared state for requests, snapshots, findings, repairs, changes, and reports.
- A hard handoff gate requiring an identifier, successful server import, workbook row, and
  source-copy context before an order transition can proceed.
- Parallel structure, pipeline, pricing, and evidence/portal audit branches.
- Deterministic classification into clear repairs and owner-review findings.
- A read-before-write `WorkbookGateway` boundary with post-change verification.
- Contract constants for the fixed spreadsheet, managed tabs, statuses, tolerances, and parser.
- Unit tests and GitHub Actions CI.

## Graph

```text
validate_request -> collect_snapshot -> [structure | pipeline | pricing | evidence+portal]
                                         -> classify -> [apply+verify | finalize] -> END
```

See [docs/architecture.md](docs/architecture.md) for the routing and safety invariants.

## Local setup

```bash
uv sync --extra dev
uv run pytest
uv run ruff check .
```

The package requires Python 3.11 or newer. LangGraph 1.x is intentionally bounded below 2.0.

## Run against a normalized snapshot

```bash
uv run xpress-agent path/to/snapshot.json --trigger direct
```

The included JSON gateway is read-only. Production workbook access must be implemented behind
`WorkbookGateway`; the graph does not contain credentials and cannot write unless an adapter is
explicitly injected and the request sets `apply_repairs` to `true`.

## Next integration step

Add a Google Drive implementation of `WorkbookGateway` that reads the contract's bounded ranges,
returns a normalized `WorkbookSnapshot`, performs only exact repair payloads, and re-reads each
changed range. Keep connector-specific code out of graph nodes so routing and audit logic remain
testable without a live workbook.
