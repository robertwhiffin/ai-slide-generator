"""The one place Tellr builds its Unity AI Gateway LLM clients (ws2a).

Every app LLM call goes to ``{host}/ai-gateway/mlflow/v1``, built here by one of
two builders over the same underlying ``DatabricksOpenAI`` client:

* :func:`gateway_chat_model` — the LangChain ``ChatDatabricks`` the graph agents
  and session titles use (tool binding, structured output, the tool loop);
* :func:`gateway_openai_client` — the raw OpenAI-compatible client the PPTX and
  Google Slides exports call ``chat.completions.create`` on (image generation
  also calls ``responses.create`` on it, built with ``max_retries=0``).

Both carry Tellr's attribution headers: a
``Databricks-Ai-Gateway-Request-Tags: {"source": "tellr"}`` tag and a
``tellr/<version>`` User-Agent, so Databricks can count Tellr's customer
Gateway usage per workspace from ``system.ai_gateway.usage`` (the same
convention Isaac CLI uses with ``source=isaac-cli``).  These headers go only on
these clients' requests; the Databricks SDK clients and their ``product=`` tags
(``src/core/databricks_client.py``) are deliberately untouched — those tags are
how installs are tracked.  ``tests/unit/test_gateway_clients.py`` fails if a
Gateway client is built anywhere else.
"""

from __future__ import annotations

import json
from functools import lru_cache
from importlib import metadata
from typing import Any, Final

REQUEST_TAGS_HEADER: Final[str] = "Databricks-Ai-Gateway-Request-Tags"
_REQUEST_TAGS: Final[str] = json.dumps({"source": "tellr"})
#: The wheel a deployed app installs (``packages/databricks-tellr-app``).
_APP_PACKAGE: Final[str] = "databricks-tellr-app"


@lru_cache(maxsize=1)
def _tellr_version() -> str:
    """The deployed release: the installed wheel's metadata, else the source tree's.

    The wheel's copied ``src/`` has no generated ``_version.py``, so
    ``_get_package_version`` alone reports ``src/__init__``'s placeholder there.
    """
    try:
        return metadata.version(_APP_PACKAGE)
    except metadata.PackageNotFoundError:
        from src.core.databricks_client import _get_package_version

        return _get_package_version()


def gateway_request_headers() -> dict[str, str]:
    """A new dict of the tag header and the User-Agent for one Gateway client.

    A caller's ``User-Agent`` replaces the OpenAI SDK's default, which for
    ``DatabricksOpenAI`` is ``DatabricksOpenAI/Python <openai version>``; that
    default is kept as the suffix.
    """
    import openai

    return {
        REQUEST_TAGS_HEADER: _REQUEST_TAGS,
        "User-Agent": f"tellr/{_tellr_version()} DatabricksOpenAI/Python {openai.__version__}",
    }


def gateway_chat_model(**kwargs: Any) -> Any:
    """A Gateway-routed ``ChatDatabricks``; ``kwargs`` are its own (model, identity, bounds).

    The headers ride in ``extra_params``, which ``ChatDatabricks`` spreads into
    every ``chat.completions.create`` call, where the OpenAI SDK sends
    ``extra_headers`` as request headers (never as body fields).  A per-call
    ``extra_headers`` would replace them, so callers must not pass one.
    """
    from databricks_langchain import ChatDatabricks  # type: ignore[import-untyped]

    return ChatDatabricks(
        use_ai_gateway=True,
        extra_params={"extra_headers": gateway_request_headers()},
        **kwargs,
    )


def gateway_openai_client(workspace_client: Any, **client_kwargs: Any) -> Any:
    """``DatabricksOpenAI`` bound to ``{host}/ai-gateway/mlflow/v1`` with the caller's identity.

    ``client_kwargs`` (for example ``max_retries`` or ``timeout``) are forwarded to the
    ``DatabricksOpenAI`` constructor; ``client.with_options()`` is broken on
    ``DatabricksOpenAI`` 0.17.1, so client-level options are set here instead.  The tag
    headers are always applied.
    """
    from databricks_openai import DatabricksOpenAI

    return DatabricksOpenAI(
        workspace_client=workspace_client,
        use_ai_gateway=True,
        default_headers=gateway_request_headers(),
        **client_kwargs,
    )
