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
- A Google Sheets gateway restricted to the fixed production workbook and bounded repairs.
- Contract constants for the fixed spreadsheet, managed tabs, statuses, tolerances, and parser.
- Unit tests, gateway safety tests, CI, and a scheduled read-only production audit.

## Graph

```text
validate_request -> collect_snapshot -> [structure | pipeline | pricing | evidence+portal]
                                         -> classify -> [apply+verify | finalize] -> END
```

See [docs/architecture.md](docs/architecture.md) for the routing and safety invariants.

## Local setup

```bash
uv sync --extra dev --extra google
uv run pytest
uv run ruff check .
```

The package requires Python 3.11 or newer. LangGraph 1.x is intentionally bounded below 2.0.

## Run against a normalized snapshot

```bash
uv run xpress-agent path/to/snapshot.json --trigger direct
```

Snapshot mode is read-only.

## Live production audit

The live CLI uses Google Application Default Credentials and is pinned by the contract to the
fixed Xpress workbook.

Read-only audit:

```bash
uv run xpress-agent --live --trigger direct
```

A live write requires both explicit flags:

```bash
uv run xpress-agent --live --apply-repairs --confirm-live-writes --trigger direct
```

Do not put the write flags in scheduled automation. Scheduled production auditing is intentionally
read-only; repairs should remain an attended action after reviewing the audit findings.

## GitHub Actions deployment

`.github/workflows/live-audit.yml` runs the live audit every day at 13:00 UTC and can also be
started manually with `workflow_dispatch`. It never passes the repair flags. Each run writes the
JSON report to the GitHub Actions step summary and retains it as an artifact for 30 days.

Create a dedicated Google service account for this agent, grant that account only the spreadsheet
access it needs, and add its JSON credential document to the repository Actions secret named
`XPRESS_GOOGLE_CREDENTIALS`. Do not commit credentials to this repository.

After the secret is configured, manually run **Live Workbook Audit** once and inspect the report
before relying on the schedule. A missing secret fails closed before workbook access.

## Production safety policy

- Scheduled jobs are read-only.
- The gateway accepts only the fixed Xpress spreadsheet ID.
- Repairs require a snapshot first and are restricted to recognized bounded cells/formulas.
- Each applied repair is re-read and verified.
- Live repair mode requires both `--apply-repairs` and `--confirm-live-writes`.
- Credential material stays in the deployment environment, never in source control.
