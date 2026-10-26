"""The one OpenAI-compatible client for app LLM calls through Unity AI Gateway (ws2a)."""

from __future__ import annotations

from typing import Any


def gateway_openai_client(workspace_client: Any) -> Any:
    """``DatabricksOpenAI`` bound to ``{host}/ai-gateway/mlflow/v1`` with the caller's identity."""
    from databricks_openai import DatabricksOpenAI

    return DatabricksOpenAI(workspace_client=workspace_client, use_ai_gateway=True)
