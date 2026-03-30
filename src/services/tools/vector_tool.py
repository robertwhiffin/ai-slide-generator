"""
Vector search tool execution module.

Creates LangChain tools for querying Databricks Vector Search indexes
using the SDK's ``vector_search_indexes.query_index()`` method with
on-behalf-of authentication.
"""

import json
import logging
from typing import Any

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from src.api.schemas.agent_config import VectorIndexTool
from src.core.databricks_client import get_user_client

logger = logging.getLogger(__name__)


class VectorSearchError(Exception):
    """Raised when vector search fails."""

    pass


class VectorSearchInput(BaseModel):
    """Input schema for vector search tool."""

    query: str = Field(description="Search query text to find similar documents")
    num_results: int = Field(
        default=5,
        description="Number of results to return (default: 5)",
        ge=1,
        le=50,
    )


def _search_vector_index(
    index_name: str,
    query: str,
    columns: list[str],
    num_results: int = 5,
) -> str:
    """
    Search a Databricks Vector Search index using the SDK.

    Uses ``client.vector_search_indexes.query_index()`` which handles
    authentication (PAT / OAuth / SP) via the workspace client.

    Args:
        index_name: Full index name (catalog.schema.index)
        query: Search query text
        columns: List of columns to return
        num_results: Number of results to return

    Returns:
        JSON string with search results

    Raises:
        VectorSearchError: If search fails
    """
    logger.info(
        "Searching vector index",
        extra={
            "index": index_name,
            "query": query[:100],
            "num_results": num_results,
        },
    )

    try:
        # Get user client at query time for OBO authentication
        client = get_user_client()

        response = client.vector_search_indexes.query_index(
            index_name=index_name,
            columns=columns,
            query_text=query,
            num_results=num_results,
        )

        # Format results from the SDK response
        formatted_results = []
        resp_dict = response.as_dict() if hasattr(response, "as_dict") else {}
        result_data = resp_dict.get("result", {})
        data_array = result_data.get("data_array", [])
        manifest_columns = resp_dict.get("manifest", {}).get("columns", [])
        col_names = [col.get("name", f"col_{i}") for i, col in enumerate(manifest_columns)]

        for row in data_array:
            result_dict = {}
            for i, value in enumerate(row):
                col_name = col_names[i] if i < len(col_names) else f"col_{i}"
                result_dict[col_name] = value
            formatted_results.append(result_dict)

        logger.info(
            "Vector search completed",
            extra={"result_count": len(formatted_results)},
        )

        return json.dumps({
            "results": formatted_results,
            "count": len(formatted_results),
        })

    except VectorSearchError:
        raise
    except Exception as e:
        logger.error("Vector search failed: %s", e, exc_info=True)
        raise VectorSearchError(f"Vector search failed: {e}") from e


def build_vector_tool(config: VectorIndexTool, index: int = 1) -> StructuredTool:
    """
    Build a LangChain StructuredTool for vector search.

    Uses the Databricks SDK's ``vector_search_indexes.query_index()``
    for native integration, executing with the user's permissions (OBO).

    Args:
        config: VectorIndexTool config with index_name, columns, etc.
        index: 1-based index for unique tool naming when multiple vector tools

    Returns:
        LangChain StructuredTool instance
    """
    index_name = config.index_name
    columns = config.columns or []
    default_num_results = config.num_results

    # Build a custom input schema that uses the config's default num_results
    input_schema = type(
        "VectorSearchInput",
        (BaseModel,),
        {
            "__annotations__": {
                "query": str,
                "num_results": int,
            },
            "query": Field(description="Search query text to find similar documents"),
            "num_results": Field(
                default=default_num_results,
                description=f"Number of results to return (default: {default_num_results})",
                ge=1,
                le=50,
            ),
        },
    )

    def _search_wrapper(query: str, num_results: int = default_num_results) -> str:
        return _search_vector_index(
            index_name=index_name,
            query=query,
            columns=columns,
            num_results=num_results,
        )

    tool_name = "search_vector_index" if index == 1 else f"search_vector_index_{index}"

    description = config.description or f"Search the {index_name} vector index"
    description += (
        "\n\nUse this tool to find relevant documents or information. "
        "Returns a list of matching results with relevance scores."
    )

    return StructuredTool.from_function(
        func=_search_wrapper,
        name=tool_name,
        description=description,
        args_schema=input_schema,
    )
