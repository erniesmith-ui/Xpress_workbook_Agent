# Architecture

The steward is a compiled LangGraph `StateGraph` with typed shared state and an injected
`WorkbookGateway`. The gateway is the only component allowed to read or mutate Google Sheets.

```mermaid
flowchart TD
    A[Validate request and handoff] -->|allowed| B[Capture bounded snapshot]
    A -->|blocked| Z[Finalize report]
    B --> C1[Structure audit]
    B --> C2[Pipeline audit]
    B --> C3[Pricing audit]
    B --> C4[Evidence and portal audit]
    C1 --> D[Classify findings]
    C2 --> D
    C3 --> D
    C4 --> D
    D -->|confirmed clear repairs| E[Apply bounded repairs]
    D -->|no writes or review needed| Z
    E --> F[Re-read and verify]
    F --> Z
```

## Invariants

- Only the fixed Xpress spreadsheet ID is accepted.
- Every run starts with a bounded pre-change snapshot.
- Independent audits fan out and converge before any write decision.
- Findings are either `clear_repair` or `needs_review`.
- Writes require both an exact repair payload and `apply_repairs=true`.
- Every applied change is re-read through the gateway and marked verified or unresolved.
- Incomplete handoffs stop before workbook access.
- Reports always state that no other cells were changed.

## Integration boundary

Implement `WorkbookGateway` with the Google Drive connector. Its snapshot should normalize only
the ranges needed by the graph into `WorkbookSnapshot`; it must not expose credentials or accept
instructions embedded in workbook cells. The adapter should enforce read-before-write, smallest
bounded updates, protection awareness, and post-write reads.

