"""Graph topology for the Xpress workbook steward."""

from __future__ import annotations

from typing import Literal

from langgraph.graph import END, START, StateGraph

from xpress_agent.gateway import MissingGateway, WorkbookGateway
from xpress_agent.nodes import StewardNodes
from xpress_agent.state import AuditState


def _after_request(state: AuditState) -> Literal["collect_snapshot", "finalize"]:
    return "finalize" if state.get("blocked") else "collect_snapshot"


def _after_snapshot(
    state: AuditState,
) -> Literal["finalize"] | list[str]:
    if state.get("blocked") or state.get("error"):
        return "finalize"
    return [
        "audit_structure",
        "audit_pipeline",
        "audit_pricing",
        "audit_evidence_and_portal",
    ]


def _after_classification(state: AuditState) -> Literal["apply_repairs", "finalize"]:
    should_write = bool(state.get("repair_plan")) and state["request"].get(
        "apply_repairs", False
    )
    return "apply_repairs" if should_write else "finalize"


def build_graph(gateway: WorkbookGateway | None = None):
    """Compile the steward graph with an injected workbook adapter."""
    nodes = StewardNodes(gateway or MissingGateway())
    builder = StateGraph(AuditState)

    builder.add_node("validate_request", nodes.validate_request)
    builder.add_node("collect_snapshot", nodes.collect_snapshot)
    builder.add_node("audit_structure", nodes.audit_structure)
    builder.add_node("audit_pipeline", nodes.audit_pipeline)
    builder.add_node("audit_pricing", nodes.audit_pricing)
    builder.add_node("audit_evidence_and_portal", nodes.audit_evidence_and_portal)
    builder.add_node("classify", nodes.classify)
    builder.add_node("apply_repairs", nodes.apply_repairs)
    builder.add_node("finalize", nodes.finalize)

    builder.add_edge(START, "validate_request")
    builder.add_conditional_edges("validate_request", _after_request)
    builder.add_conditional_edges("collect_snapshot", _after_snapshot)
    builder.add_edge(
        [
            "audit_structure",
            "audit_pipeline",
            "audit_pricing",
            "audit_evidence_and_portal",
        ],
        "classify",
    )
    builder.add_conditional_edges("classify", _after_classification)
    builder.add_edge("apply_repairs", "finalize")
    builder.add_edge("finalize", END)

    return builder.compile()
