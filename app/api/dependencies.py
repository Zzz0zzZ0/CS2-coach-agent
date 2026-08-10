"""Compatibility exports for FastAPI dependency imports."""

from app.core.providers import get_graph_client, get_kb_client, get_llm

__all__ = ["get_graph_client", "get_kb_client", "get_llm"]
