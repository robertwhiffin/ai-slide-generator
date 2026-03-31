"""Tool discovery endpoints — returns available tools for agent configuration.

Provides per-type discovery endpoints that query the Databricks SDK to find
available Genie spaces, vector search endpoints/indexes, UC HTTP connections
(for MCP), model serving endpoints, and agent serving endpoints.
"""

import json
import logging
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError

from fastapi import APIRouter

from src.core.config_loader import load_config
from src.core.databricks_client import get_user_client

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/tools", tags=["tools"])


# ---------------------------------------------------------------------------
# Discovery helpers — each returns {"items": [...]} or {"items": []} on error
# ---------------------------------------------------------------------------


def _discover_genie_spaces() -> dict:
    """Discover available Genie spaces via Databricks SDK (paginated)."""
    try:
        client = get_user_client()
        items: list[dict] = []

        response = client.genie.list_spaces(page_size=100)
        if response.spaces:
            for s in response.spaces:
                items.append(
                    {
                        "id": s.space_id,
                        "name": s.title,
                        "description": getattr(s, "description", None),
                    }
                )

        while response.next_page_token:
            response = client.genie.list_spaces(
                page_token=response.next_page_token, page_size=100
            )
            if response.spaces:
                for s in response.spaces:
                    items.append(
                        {
                            "id": s.space_id,
                            "name": s.title,
                            "description": getattr(s, "description", None),
                        }
                    )

        return {"items": items}
    except Exception as e:
        logger.warning(f"Failed to discover Genie spaces: {e}")
        return {"items": []}


def _list_vector_endpoints_sync(client) -> list[dict]:
    """Run the SDK list_endpoints call. Separated for thread execution."""
    items: list[dict] = []
    for ep in client.vector_search_endpoints.list_endpoints():
        state = None
        if ep.endpoint_status and ep.endpoint_status.state:
            state = ep.endpoint_status.state.value
        if state != "ONLINE":
            continue
        num_indexes = getattr(ep, "num_indexes", None) or 0
        if num_indexes == 0:
            continue
        items.append(
            {
                "id": ep.name,
                "name": ep.name,
                "description": None,
                "metadata": {"state": state, "num_indexes": num_indexes},
            }
        )
    return items


def _discover_vector_endpoints() -> dict:
    """Discover ONLINE vector search endpoints via the SDK.

    Uses the SDK's ``vector_search_endpoints.list_endpoints()`` wrapped
    in a thread with a 15-second timeout. The timeout prevents the UI
    from hanging forever if the SDK retries on rate limits.
    """
    try:
        client = get_user_client()

        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(_list_vector_endpoints_sync, client)
            try:
                items = future.result(timeout=40)
            except FuturesTimeoutError:
                logger.warning("Vector endpoint discovery timed out after 40s")
                return {
                    "items": [],
                    "error": "Request timed out — the workspace may be busy. Please try again.",
                }

        return {"items": items}
    except Exception as e:
        error_msg = str(e)
        if "429" in error_msg or "rate limit" in error_msg.lower() or "REQUEST_LIMIT_EXCEEDED" in error_msg:
            logger.warning("Vector endpoint discovery rate limited")
            return {
                "items": [],
                "error": "Rate limited — please try again in a minute.",
            }
        logger.warning(f"Failed to discover vector endpoints: {e}")
        return {"items": []}


def _discover_vector_indexes(endpoint_name: str) -> dict:
    """Discover vector search indexes for a given endpoint.

    Only returns indexes that have embedding_source_columns configured,
    since our vector_tool.py uses query_text= which requires an embedded
    model. Indexes without embedding support only accept raw query_vector
    input and are not usable for text-based LLM agent queries.
    """
    try:
        client = get_user_client()
        items: list[dict] = []

        for idx in client.vector_search_indexes.list_indexes(endpoint_name=endpoint_name):
            # Filter: only include indexes that support text queries
            try:
                index_detail = client.vector_search_indexes.get_index(index_name=idx.name)
                has_embedding = False
                if index_detail.delta_sync_index_spec:
                    has_embedding = bool(
                        index_detail.delta_sync_index_spec.embedding_source_columns
                    )
                elif index_detail.direct_access_index_spec:
                    has_embedding = bool(
                        index_detail.direct_access_index_spec.embedding_source_columns
                    )
                if not has_embedding:
                    continue  # Skip indexes that don't support text search
            except Exception:
                pass  # If we can't check, include it anyway

            index_type = None
            if idx.index_type:
                index_type = idx.index_type.value
            items.append(
                {
                    "id": idx.name,
                    "name": idx.name,
                    "description": None,
                    "metadata": {
                        "index_type": index_type,
                        "primary_key": idx.primary_key,
                    },
                }
            )

        return {"items": items}
    except Exception as e:
        logger.warning(f"Failed to discover vector indexes for {endpoint_name}: {e}")
        return {"items": []}


def _discover_vector_columns(endpoint_name: str, index_name: str) -> dict:
    """Discover columns for a vector search index.

    First tries to read ALL columns from the source table (gives the full
    picture of returnable columns). Falls back to embedding spec columns
    if the source table is not accessible.
    """
    try:
        client = get_user_client()
        index = client.vector_search_indexes.get_index(index_name)

        columns: list[dict] = []
        source_table: str | None = None
        primary_key = getattr(index, "primary_key", None)

        # Get source table name from spec
        spec = index.delta_sync_index_spec or index.direct_access_index_spec
        if spec:
            source_table = getattr(spec, "source_table", None)

        # Primary approach: read columns from the source table schema
        # This gives ALL returnable columns (not just embedding columns)
        if source_table:
            try:
                table_info = client.tables.get(source_table)
                if table_info.columns:
                    columns = [
                        {
                            "name": col.name,
                            "type": str(col.type_name.value) if col.type_name else "unknown",
                        }
                        for col in table_info.columns
                    ]
                    logger.info(
                        "Resolved %d columns from source table %s",
                        len(columns), source_table,
                    )
            except Exception as e:
                logger.warning(
                    "Could not read source table %s, falling back to index spec: %s",
                    source_table, e,
                )

        # Fallback: read from the index spec (embedding columns only)
        if not columns and spec:
            if spec.embedding_source_columns:
                for col in spec.embedding_source_columns:
                    columns.append({"name": col.name, "type": "embedding_source"})
            if spec.embedding_vector_columns:
                for col in spec.embedding_vector_columns:
                    columns.append({"name": col.name, "type": "embedding_vector"})

        return {
            "columns": columns,
            "source_table": source_table,
            "primary_key": primary_key,
        }
    except Exception as e:
        logger.warning(
            f"Failed to discover columns for {index_name} on {endpoint_name}: {e}"
        )
        return {"columns": [], "source_table": None, "primary_key": None}


def _discover_mcp_connections() -> dict:
    """Discover UC HTTP connections (usable as MCP servers)."""
    try:
        client = get_user_client()
        items: list[dict] = []

        for conn in client.connections.list():
            conn_type = None
            if conn.connection_type:
                conn_type = conn.connection_type.value
            if conn_type != "HTTP":
                continue
            items.append(
                {
                    "id": conn.name,
                    "name": conn.name,
                    "description": getattr(conn, "comment", None),
                }
            )

        return {"items": items}
    except Exception as e:
        logger.warning(f"Failed to discover MCP connections: {e}")
        return {"items": []}


def _discover_model_endpoints() -> dict:
    """Discover non-agent model serving endpoints."""
    try:
        client = get_user_client()
        items: list[dict] = []

        for ep in client.serving_endpoints.list():
            task = getattr(ep, "task", None) or ""
            # Exclude agent endpoints (handled by Agent Bricks discovery)
            if task.startswith("agent/"):
                continue
            # Exclude embedding endpoints (return vectors, not usable by LLM agent)
            if task.startswith("llm/v1/embeddings"):
                continue
            endpoint_type = (
                "foundation"
                if task.startswith(("llm/v1/chat", "llm/v1/completions"))
                else "custom"
            )
            items.append(
                {
                    "id": ep.name,
                    "name": ep.name,
                    "description": getattr(ep, "description", None),
                    "metadata": {
                        "task": task,
                        "endpoint_type": endpoint_type,
                    },
                }
            )

        return {"items": items}
    except Exception as e:
        logger.warning(f"Failed to discover model endpoints: {e}")
        return {"items": []}


def _discover_agent_bricks() -> dict:
    """Discover agent serving endpoints (task starts with 'agent/')."""
    try:
        client = get_user_client()
        items: list[dict] = []

        for ep in client.serving_endpoints.list():
            task = getattr(ep, "task", None) or ""
            if not task.startswith("agent/"):
                continue
            items.append(
                {
                    "id": ep.name,
                    "name": ep.name,
                    "description": getattr(ep, "description", None),
                    "metadata": {"task": task},
                }
            )

        return {"items": items}
    except Exception as e:
        logger.warning(f"Failed to discover agent bricks: {e}")
        return {"items": []}


# ---------------------------------------------------------------------------
# Legacy helpers (kept for deprecated /api/tools/available)
# ---------------------------------------------------------------------------


def _list_genie_spaces() -> list[dict]:
    """Discover available Genie spaces via Databricks SDK (legacy format)."""
    try:
        client = get_user_client()
        results: list[dict] = []

        response = client.genie.list_spaces(page_size=100)
        if response.spaces:
            for s in response.spaces:
                results.append(
                    {
                        "type": "genie",
                        "space_id": s.space_id,
                        "space_name": s.title,
                        "description": getattr(s, "description", None),
                    }
                )

        while response.next_page_token:
            response = client.genie.list_spaces(
                page_token=response.next_page_token, page_size=100
            )
            if response.spaces:
                for s in response.spaces:
                    results.append(
                        {
                            "type": "genie",
                            "space_id": s.space_id,
                            "space_name": s.title,
                            "description": getattr(s, "description", None),
                        }
                    )

        return results
    except Exception as e:
        logger.warning(f"Failed to list Genie spaces: {e}")
        return []


def _list_mcp_servers() -> list[dict]:
    """List MCP servers from application config."""
    try:
        config = load_config()
        servers = config.get("mcp_servers", [])
        return [
            {
                "type": "mcp",
                "connection_name": s["uri"],
                "server_name": s["name"],
                "config": s.get("config", {}),
            }
            for s in servers
        ]
    except Exception as e:
        logger.warning(f"Failed to list MCP servers: {e}")
        return []


# ---------------------------------------------------------------------------
# Route definitions
# ---------------------------------------------------------------------------


@router.get("/available")
def get_available_tools():
    """Return all available tools (Genie spaces + MCP servers).

    .. deprecated::
        Use the per-type ``/api/tools/discover/*`` endpoints instead.
    """
    logger.warning(
        "GET /api/tools/available is deprecated. "
        "Use /api/tools/discover/* endpoints instead."
    )
    return _list_genie_spaces() + _list_mcp_servers()


@router.get("/discover/genie")
def discover_genie():
    """List available Genie spaces."""
    return _discover_genie_spaces()


@router.get("/discover/vector")
def discover_vector():
    """List ONLINE vector search endpoints."""
    return _discover_vector_endpoints()


@router.get("/discover/vector/{endpoint_name}/indexes")
def discover_vector_indexes(endpoint_name: str):
    """List vector search indexes for a given endpoint."""
    return _discover_vector_indexes(endpoint_name)


@router.get("/discover/vector/{endpoint_name}/{index_name:path}/columns")
def discover_vector_columns(endpoint_name: str, index_name: str):
    """List columns/schema for a specific vector search index."""
    return _discover_vector_columns(endpoint_name, index_name)


@router.get("/discover/mcp")
def discover_mcp():
    """List UC HTTP connections usable as MCP servers."""
    return _discover_mcp_connections()


@router.get("/discover/model-endpoints")
def discover_model_endpoints():
    """List non-agent model serving endpoints."""
    return _discover_model_endpoints()


@router.get("/discover/agent-bricks")
def discover_agent_bricks():
    """List agent serving endpoints."""
    return _discover_agent_bricks()
