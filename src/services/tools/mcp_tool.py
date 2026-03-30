"""
MCP (Model Context Protocol) server tool execution module.

Creates LangChain tools that connect to external MCP servers through
the Databricks MCP proxy using Unity Catalog connections.

Uses DatabricksMCPClient which handles the MCP Streamable HTTP transport
protocol internally. Thread isolation is required because DatabricksMCPClient
uses asyncio.run() internally, which conflicts with FastAPI's event loop.

The ``databricks-mcp`` package is imported lazily -- if not installed,
``build_mcp_tools`` raises a clear error at tool-build time rather than
at module import time.
"""

import concurrent.futures
import json
import logging
from typing import Any

from langchain_core.tools import StructuredTool
from pydantic import Field, create_model

from src.api.schemas.agent_config import MCPTool
from src.core.databricks_client import get_user_client

logger = logging.getLogger(__name__)


class MCPToolError(Exception):
    """Raised when MCP tool execution fails."""

    pass


# ---------------------------------------------------------------------------
# Thread-isolated helpers (DatabricksMCPClient uses asyncio.run internally)
# ---------------------------------------------------------------------------

def _call_mcp_in_clean_thread(
    server_url: str,
    tool_name: str,
    arguments: dict[str, Any],
    host: str,
    token: str,
) -> str:
    """
    Call MCP tool in a completely clean thread with no event loop.

    DatabricksMCPClient uses asyncio.run() internally, which requires
    no existing event loop. Running in a thread ensures isolation.

    Returns JSON string for compatibility.
    """
    try:
        from databricks_mcp import DatabricksMCPClient
        from databricks.sdk import WorkspaceClient
    except ImportError:
        raise MCPToolError(
            "databricks-mcp package not installed. "
            "Install with: pip install databricks-mcp"
        )

    logger.info("Calling MCP tool: %s at %s", tool_name, server_url)

    try:
        # Create a fresh workspace client in this thread
        ws_client = WorkspaceClient(host=host, token=token, auth_type="pat")

        mcp_client = DatabricksMCPClient(
            server_url=server_url,
            workspace_client=ws_client,
        )

        # Call the tool - this uses asyncio.run() internally
        response = mcp_client.call_tool(tool_name, arguments)

        # Parse the response
        result = None
        if hasattr(response, "content") and response.content:
            texts = []
            for item in response.content:
                if hasattr(item, "text"):
                    texts.append(item.text)
                elif isinstance(item, str):
                    texts.append(item)
            result = "\n".join(texts) if texts else str(response.content)
        elif hasattr(response, "data"):
            result = response.data
        else:
            result = str(response)

        logger.info("MCP tool %s completed successfully", tool_name)

        # Return as JSON string
        if isinstance(result, str):
            try:
                json.loads(result)
                return result
            except json.JSONDecodeError:
                return json.dumps({"result": result})
        else:
            return json.dumps({"result": result})

    except Exception as e:
        logger.error("MCP tool call failed: %s", e, exc_info=True)
        raise MCPToolError(f"MCP tool call failed: {e}") from e


def _list_mcp_in_clean_thread(
    server_url: str,
    host: str,
    token: str,
) -> list[dict]:
    """List MCP tools in a clean thread with no event loop."""
    try:
        from databricks_mcp import DatabricksMCPClient
        from databricks.sdk import WorkspaceClient
    except ImportError:
        return []

    try:
        ws_client = WorkspaceClient(host=host, token=token, auth_type="pat")

        mcp_client = DatabricksMCPClient(
            server_url=server_url,
            workspace_client=ws_client,
        )

        mcp_tools = mcp_client.list_tools()

        tools = []
        for tool in mcp_tools:
            tools.append(
                {
                    "name": tool.name,
                    "description": tool.description or "",
                    "input_schema": tool.inputSchema
                    if hasattr(tool, "inputSchema")
                    else {},
                }
            )
        return tools

    except Exception as e:
        logger.warning("Failed to list MCP tools: %s", e)
        return []


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------

def call_mcp_tool(
    connection_name: str,
    tool_name: str,
    arguments: dict[str, Any],
) -> str:
    """
    Call a tool on an MCP server via Databricks MCP proxy.

    Uses DatabricksMCPClient which handles the MCP Streamable HTTP
    transport protocol. Runs in a separate thread to avoid asyncio
    conflicts with FastAPI.

    Args:
        connection_name: Unity Catalog connection name for the MCP server
        tool_name: Name of the tool to call
        arguments: Tool arguments

    Returns:
        JSON string with tool result

    Raises:
        MCPToolError: If tool call fails
    """
    logger.info("Calling MCP tool: %s via connection: %s", tool_name, connection_name)

    try:
        client = get_user_client()
        host = client.config.host
        token = client.config.token

        server_url = f"{host}/api/2.0/mcp/external/{connection_name}"

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(
                _call_mcp_in_clean_thread,
                server_url,
                tool_name,
                arguments,
                host,
                token,
            )
            return future.result(timeout=120)

    except MCPToolError:
        raise
    except concurrent.futures.TimeoutError:
        raise MCPToolError("MCP tool call timed out after 120 seconds")
    except Exception as e:
        logger.error("MCP tool call failed: %s", e, exc_info=True)
        raise MCPToolError(f"MCP tool call failed: {e}") from e


def list_mcp_tools(connection_name: str) -> list[dict]:
    """
    List available tools from an MCP server via Databricks proxy.

    Args:
        connection_name: Unity Catalog connection name for the MCP server

    Returns:
        List of tool definitions (each a dict with name, description, input_schema)
    """
    try:
        client = get_user_client()
        host = client.config.host
        token = client.config.token
        server_url = f"{host}/api/2.0/mcp/external/{connection_name}"

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(
                _list_mcp_in_clean_thread, server_url, host, token
            )
            return future.result(timeout=60)

    except Exception as e:
        logger.warning("Failed to list MCP tools: %s", e)
        return []


# ---------------------------------------------------------------------------
# Builder
# ---------------------------------------------------------------------------

def build_mcp_tools(config: MCPTool) -> list[StructuredTool]:
    """
    Build LangChain tools from an MCP server via Databricks proxy.

    An MCP server can expose multiple tools, so this returns a list.
    Uses Unity Catalog connections for secure authentication.
    Auto-discovers available tools from the MCP server and builds
    dynamic Pydantic input schemas for each.

    Args:
        config: MCPTool config with connection_name, server_name, description

    Returns:
        List of LangChain StructuredTool instances
    """
    connection_name = config.connection_name
    base_description = config.description

    tools = []
    tool_configs: list[dict] = []

    # Try to discover tools from MCP server
    try:
        discovered = list_mcp_tools(connection_name)
        if discovered:
            logger.info(
                "Discovered %d tools from MCP server %s",
                len(discovered),
                config.server_name,
            )
            tool_configs = discovered
    except Exception as e:
        logger.warning("Could not discover MCP tools: %s", e)

    # If no tools discovered, create a generic search tool
    if not tool_configs:
        tool_configs = [
            {
                "name": "search",
                "description": base_description or f"Search using {config.server_name}",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "The search query",
                        },
                    },
                    "required": ["query"],
                },
            }
        ]

    for tool_config in tool_configs:
        mcp_tool_name = tool_config.get("name", "search")
        tool_description = tool_config.get("description", "")
        input_schema = tool_config.get("input_schema", {})

        # Build Pydantic model from input schema
        fields = {}
        properties = (
            input_schema.get("properties", {}) if isinstance(input_schema, dict) else {}
        )
        required = (
            input_schema.get("required", []) if isinstance(input_schema, dict) else []
        )

        type_map = {
            "string": str,
            "integer": int,
            "int": int,
            "number": float,
            "float": float,
            "boolean": bool,
            "object": dict,
            "dict": dict,
            "array": list,
        }

        for param_name, param_spec in properties.items():
            if not isinstance(param_spec, dict):
                continue

            param_type = param_spec.get("type", "string")
            param_desc = param_spec.get("description", f"{param_name} parameter")
            py_type = type_map.get(param_type.lower(), str)

            if param_name in required:
                fields[param_name] = (py_type, Field(description=param_desc))
            else:
                fields[param_name] = (
                    py_type,
                    Field(default=None, description=param_desc),
                )

        if not fields:
            fields["query"] = (str, Field(description="Query or request"))

        InputSchema = create_model(f"{mcp_tool_name}Input", **fields)

        def _create_wrapper(tool_name: str, conn_name: str):
            def _wrapper(**kwargs) -> str:
                args = {k: v for k, v in kwargs.items() if v is not None}
                return call_mcp_tool(
                    connection_name=conn_name,
                    tool_name=tool_name,
                    arguments=args,
                )

            return _wrapper

        # Generate unique tool name
        safe_conn_name = connection_name.replace("-", "_").replace(".", "_").lower()
        langchain_tool_name = f"mcp_{safe_conn_name}_{mcp_tool_name}"

        tool = StructuredTool.from_function(
            func=_create_wrapper(mcp_tool_name, connection_name),
            name=langchain_tool_name,
            description=tool_description or f"Call {mcp_tool_name} on {config.server_name}",
            args_schema=InputSchema,
        )
        tools.append(tool)

    logger.info("Created %d MCP tools from %s", len(tools), config.server_name)
    return tools
