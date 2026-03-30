"""Tool discovery endpoints — returns available tools for agent configuration.

Provides per-type discovery endpoints that query the Databricks SDK to find
available Genie spaces, vector search endpoints/indexes, UC HTTP connections
(for MCP), model serving endpoints, and agent serving endpoints.
"""

import json
import logging

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


import concurrent.futures
import time as _time

# Cache for vector endpoint discovery (parallel checking is expensive)
_vector_endpoints_cache: dict | None = None
_vector_endpoints_cache_time: float = 0
_VECTOR_ENDPOINTS_CACHE_TTL = 300  # 5 minutes


def _check_endpoint_has_embedding_index(client, endpoint_name: str) -> bool:
    """Check if a vector endpoint has at least one embedding-supported index.

    Returns True (include) if any index has embedding_source_columns, or if
    we can't verify (fail-open). Returns False (exclude) only when we can
    confirm all indexes lack embedding support.
    """
    try:
        for idx in client.vector_search_indexes.list_indexes(endpoint_name=endpoint_name):
            try:
                detail = client.vector_search_indexes.get_index(index_name=idx.name)
                if detail.delta_sync_index_spec and detail.delta_sync_index_spec.embedding_source_columns:
                    return True
                if detail.direct_access_index_spec and detail.direct_access_index_spec.embedding_source_columns:
                    return True
            except Exception:
                return True  # Can't inspect — fail-open
        return False  # No indexes or none with embeddings
    except Exception:
        return True  # Can't list — fail-open


def _discover_vector_endpoints() -> dict:
    """Discover ONLINE vector search endpoints with embedding-compatible indexes.

    Only returns endpoints that have at least one index supporting text search
    (query_text). Uses parallel checking (max 5 threads) to keep latency low,
    and caches results for 5 minutes so subsequent opens are instant.
    """
    global _vector_endpoints_cache, _vector_endpoints_cache_time

    now = _time.monotonic()
    if _vector_endpoints_cache is not None and (now - _vector_endpoints_cache_time) < _VECTOR_ENDPOINTS_CACHE_TTL:
        return _vector_endpoints_cache

    try:
        client = get_user_client()

        # Step 1: List all ONLINE endpoints (single fast API call)
        online_endpoints = []
        for ep in client.vector_search_endpoints.list_endpoints():
            state = None
            if ep.endpoint_status and ep.endpoint_status.state:
                state = ep.endpoint_status.state.value
            if state == "ONLINE":
                online_endpoints.append(ep)

        if not online_endpoints:
            result = {"items": []}
            _vector_endpoints_cache = result
            _vector_endpoints_cache_time = now
            return result

        # Step 2: Check all endpoints in parallel (max 5 threads)
        items: list[dict] = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            future_to_ep = {
                executor.submit(_check_endpoint_has_embedding_index, client, ep.name): ep
                for ep in online_endpoints
            }
            for future in concurrent.futures.as_completed(future_to_ep):
                ep = future_to_ep[future]
                try:
                    has_valid = future.result(timeout=30)
                except Exception:
                    has_valid = True  # fail-open on thread error
                if has_valid:
                    items.append(
                        {
                            "id": ep.name,
                            "name": ep.name,
                            "description": None,
                            "metadata": {"state": "ONLINE"},
                        }
                    )
                else:
                    logger.debug(
                        "Skipping vector endpoint %s — no embedding-supported indexes",
                        ep.name,
                    )

        result = {"items": items}
        _vector_endpoints_cache = result
        _vector_endpoints_cache_time = now
        return result
    except Exception as e:
        logger.warning(f"Failed to discover vector search endpoints: {e}")
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
    """Discover columns/schema for a specific vector search index.

    Uses ``get_index`` to retrieve the full index spec and extracts column
    information from the delta-sync or direct-access spec.
    """
    try:
        client = get_user_client()
        index = client.vector_search_indexes.get_index(index_name)

        columns: list[dict] = []
        source_table: str | None = None
        primary_key = getattr(index, "primary_key", None)

        # Extract columns from the appropriate spec
        if index.delta_sync_index_spec:
            spec = index.delta_sync_index_spec
            source_table = getattr(spec, "source_table", None)
            if spec.embedding_source_columns:
                for col in spec.embedding_source_columns:
                    columns.append({"name": col.name, "type": "embedding_source"})
            if spec.embedding_vector_columns:
                for col in spec.embedding_vector_columns:
                    columns.append(
                        {
                            "name": col.name,
                            "type": "embedding_vector",
                        }
                    )
        elif index.direct_access_index_spec:
            spec = index.direct_access_index_spec
            if spec.schema_json:
                try:
                    schema = json.loads(spec.schema_json)
                    if isinstance(schema, dict):
                        for col_name, col_type in schema.items():
                            columns.append({"name": col_name, "type": str(col_type)})
                except (json.JSONDecodeError, TypeError):
                    pass
            if spec.embedding_source_columns:
                for col in spec.embedding_source_columns:
                    columns.append({"name": col.name, "type": "embedding_source"})
            if spec.embedding_vector_columns:
                for col in spec.embedding_vector_columns:
                    columns.append(
                        {
                            "name": col.name,
                            "type": "embedding_vector",
                        }
                    )

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
