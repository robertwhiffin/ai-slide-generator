"""
Model Serving Endpoint tool execution module.

Creates LangChain tools for querying Databricks Model Serving endpoints
using the user's OAuth token (OBO authentication).

Supports three endpoint types via metadata-based auto-detection:

  Type              task field            Input Format
  ----------------  --------------------  ----------------------------------------
  Agent/Chat        agent/*               {"input": [{"role":"user","content":"..."}]}
  Foundation Model  llm/v1/chat           {"messages":[{"role":"user","content":"..."}]}
  Custom ML Model   None / other          {"dataframe_records": [{...}]}

Detection uses the endpoint's ``task`` metadata field (via GET /serving-endpoints/{name}),
cached in-memory with a 1-hour TTL. If detection fails, falls back to trial-and-error
across all three formats.

All calls go through the SDK's api_client.do() which handles authentication
(PAT, OAuth, service principal) and retries.
"""

import json
import logging
import time
from typing import Any

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from src.api.schemas.agent_config import ModelEndpointTool
from src.core.databricks_client import get_user_client

logger = logging.getLogger(__name__)

# Endpoint type constants
ENDPOINT_TYPE_AGENT = "agent"
ENDPOINT_TYPE_FOUNDATION = "foundation"
ENDPOINT_TYPE_CUSTOM_ML = "custom_ml"

# In-memory cache: endpoint_name -> (detected_type, timestamp)
_endpoint_type_cache: dict[str, tuple[str, float]] = {}
_CACHE_TTL_SECONDS = 3600  # 1 hour


class ModelEndpointError(Exception):
    """Raised when model endpoint query fails."""

    pass


class ModelEndpointInput(BaseModel):
    """Input schema for model endpoint tool."""

    query: str = Field(description="Question or input to send to the model endpoint")


# ---------------------------------------------------------------------------
# Endpoint type detection
# ---------------------------------------------------------------------------

def _detect_endpoint_type(client, endpoint_name: str) -> str | None:
    """Detect endpoint type from the serving endpoint's ``task`` metadata.

    Uses an in-memory cache with 1-hour TTL to avoid repeated metadata calls.
    Returns None if detection fails (caller should fall back to trial-and-error).
    """
    now = time.monotonic()
    cached = _endpoint_type_cache.get(endpoint_name)
    if cached and (now - cached[1]) < _CACHE_TTL_SECONDS:
        return cached[0]

    try:
        ep = client.serving_endpoints.get(endpoint_name)
        task = (ep.as_dict().get("task") or "").lower()

        if task.startswith("agent/"):
            ep_type = ENDPOINT_TYPE_AGENT
        elif task.startswith("llm/v1/chat") or task.startswith("llm/v1/completions"):
            ep_type = ENDPOINT_TYPE_FOUNDATION
        else:
            ep_type = ENDPOINT_TYPE_CUSTOM_ML

        _endpoint_type_cache[endpoint_name] = (ep_type, now)
        logger.info(
            "Detected endpoint type",
            extra={"endpoint": endpoint_name, "task": task, "type": ep_type},
        )
        return ep_type

    except Exception as exc:
        logger.warning("Failed to detect endpoint type for %s: %s", endpoint_name, exc)
        return None


# ---------------------------------------------------------------------------
# Response extractors -- one per endpoint type
# ---------------------------------------------------------------------------

def _extract_agent_response(result: dict) -> str:
    """Extract text from an Agent/Chat endpoint response.

    Expected structure::

        {"output": [{"type": "message",
                      "content": [{"type": "output_text", "text": "..."}]}]}
    """
    output = result.get("output", [])

    if isinstance(output, list):
        texts = []
        for item in output:
            if isinstance(item, dict) and item.get("type") == "message":
                for content in item.get("content", []):
                    if isinstance(content, dict) and content.get("text"):
                        texts.append(content["text"])
        if texts:
            return "\n\n".join(texts)

    if isinstance(output, str):
        return output

    return ""


def _extract_foundation_response(result: dict) -> str:
    """Extract text from a Foundation Model endpoint response.

    Expected structure::

        {"choices": [{"message": {"content": "..."}}]}
    """
    choices = result.get("choices", [])
    if isinstance(choices, list):
        texts = []
        for choice in choices:
            if not isinstance(choice, dict):
                continue
            msg = choice.get("message") or choice.get("delta") or {}
            if isinstance(msg, dict) and msg.get("content"):
                texts.append(msg["content"])
        if texts:
            return "\n\n".join(texts)

    return ""


# ---------------------------------------------------------------------------
# Query dispatchers -- one per endpoint type
# ---------------------------------------------------------------------------

def _query_agent(client, path: str, message: list[dict]) -> str:
    """Send agent/chat format and extract response."""
    result = client.api_client.do("POST", path, body={"input": message})
    return _extract_agent_response(result)


def _query_foundation(client, path: str, message: list[dict]) -> str:
    """Send foundation model format and extract response."""
    result = client.api_client.do("POST", path, body={"messages": message})
    return _extract_foundation_response(result)


def _query_custom_ml(client, path: str, input_data: dict) -> str:
    """Send dataframe_records format and return raw JSON."""
    result = client.api_client.do(
        "POST", path, body={"dataframe_records": [input_data]},
    )
    return json.dumps(result)


def _query_with_fallback(
    client, path: str, message: list[dict], input_data: dict,
) -> str:
    """Trial-and-error fallback when metadata detection is unavailable."""
    from databricks.sdk.errors import BadRequest, InvalidParameterValue

    for label, fn, args in [
        ("agent", _query_agent, (client, path, message)),
        ("foundation", _query_foundation, (client, path, message)),
        ("custom_ml", _query_custom_ml, (client, path, input_data)),
    ]:
        try:
            text = fn(*args)
            if text:
                logger.info("Fallback query successful (%s)", label)
                return text
        except (InvalidParameterValue, BadRequest) as exc:
            logger.info("Fallback: %s format rejected: %s", label, exc)
            continue
    raise ModelEndpointError("All query formats rejected by endpoint")


# ---------------------------------------------------------------------------
# Main query function
# ---------------------------------------------------------------------------

def _query_model_endpoint(
    endpoint_name: str,
    query: str,
) -> str:
    """
    Query a Databricks Model Serving endpoint.

    Detection strategy:
      1. Read the endpoint's ``task`` metadata (cached 1 hour) to determine
         the type: ``agent``, ``foundation``, or ``custom_ml``.
      2. Route directly to the correct format -- one invocation call.
      3. If metadata detection fails, fall back to trial-and-error.

    Args:
        endpoint_name: Name of the serving endpoint
        query: The query text to send

    Returns:
        Text string with model response

    Raises:
        ModelEndpointError: If query fails
    """
    logger.info(
        "Querying model endpoint",
        extra={"endpoint": endpoint_name, "query": query[:100]},
    )

    try:
        client = get_user_client()
        path = f"/serving-endpoints/{endpoint_name}/invocations"
        message = [{"role": "user", "content": query}]
        input_data = {"input": query}

        ep_type = _detect_endpoint_type(client, endpoint_name)

        if ep_type == ENDPOINT_TYPE_AGENT:
            text = _query_agent(client, path, message)
            if text:
                logger.info("Query successful (agent)", extra={"endpoint": endpoint_name})
                return text

        elif ep_type == ENDPOINT_TYPE_FOUNDATION:
            text = _query_foundation(client, path, message)
            if text:
                logger.info("Query successful (foundation)", extra={"endpoint": endpoint_name})
                return text

        elif ep_type == ENDPOINT_TYPE_CUSTOM_ML:
            text = _query_custom_ml(client, path, input_data)
            logger.info("Query successful (custom_ml)", extra={"endpoint": endpoint_name})
            return text

        # Detection returned None or the detected format returned empty --
        # fall back to trying all formats.
        logger.info("Falling back to trial-and-error for %s", endpoint_name)
        return _query_with_fallback(client, path, message, input_data)

    except ModelEndpointError:
        raise
    except Exception as e:
        logger.error("Model endpoint query failed: %s", e, exc_info=True)
        raise ModelEndpointError(
            f"Failed to query model endpoint {endpoint_name}: {e}"
        ) from e


def build_model_endpoint_tool(
    config: ModelEndpointTool, index: int = 1,
) -> StructuredTool:
    """
    Build a LangChain StructuredTool for a Model Serving endpoint.

    Args:
        config: ModelEndpointTool config with endpoint_name, etc.
        index: 1-based index for unique tool naming

    Returns:
        LangChain StructuredTool instance
    """
    endpoint_name = config.endpoint_name

    def _wrapper(query: str) -> str:
        return _query_model_endpoint(
            endpoint_name=endpoint_name,
            query=query,
        )

    tool_name = "query_model_endpoint" if index == 1 else f"query_model_endpoint_{index}"

    description = config.description or f"Query the {endpoint_name} model serving endpoint"
    description += (
        f"\n\nThis queries the Databricks Model Serving endpoint: {endpoint_name}. "
        "Send a natural language question and get a response from the model."
    )

    return StructuredTool.from_function(
        func=_wrapper,
        name=tool_name,
        description=description,
        args_schema=ModelEndpointInput,
    )
