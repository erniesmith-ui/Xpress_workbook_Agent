"""Xpress workbook steward graph."""

from typing import Any

__all__ = ["build_graph"]


def build_graph(*args: Any, **kwargs: Any):
    """Import LangGraph only when a compiled graph is requested."""
    from xpress_agent.graph import build_graph as _build_graph

    return _build_graph(*args, **kwargs)
