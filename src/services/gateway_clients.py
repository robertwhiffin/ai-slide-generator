"""The one place Tellr builds its Unity AI Gateway LLM clients (ws2a).

Every app LLM call goes to ``{host}/ai-gateway/mlflow/v1``, built here by one of
two builders over the same underlying ``DatabricksOpenAI`` client:

* :func:`gateway_chat_model` — the LangChain ``ChatDatabricks`` the graph agents
  and session titles use (tool binding, structured output, the tool loop);
* :func:`gateway_openai_client` — the raw OpenAI-compatible client the PPTX and
  Google Slides exports call ``chat.completions.create`` on (image generation
  also calls ``responses.create`` on it, built with ``max_retries=0``).

Both carry Tellr's attribution headers: a ``Databricks-Ai-Gateway-Request-Tags``
tag and a ``tellr/<version>`` User-Agent, so Databricks can count Tellr's customer
Gateway usage per workspace from ``system.ai_gateway.usage`` (the same
convention Isaac CLI uses with ``source=isaac-cli``).  The tag is a JSON object
that always carries ``"source": "tellr"``, and two optional keys, each from a
fixed list: ``component``, the feature the client is built for (one of
:data:`COMPONENTS`), and ``entrypoint``, how the chat turn that built it reached
Tellr (one of ``attribution.ENTRYPOINTS``).  A value off its list adds no key, so
the tag never carries free text, and no value makes it raise.  These headers go
only on these clients' requests; the Databricks SDK clients and their
``product=`` tags (``src/core/databricks_client.py``) are deliberately untouched
— those tags are how installs are tracked.  ``tests/unit/test_gateway_clients.py``
fails if a Gateway client is built anywhere else.
"""

from __future__ import annotations

import json
from typing import Any, Final

REQUEST_TAGS_HEADER: Final[str] = "Databricks-Ai-Gateway-Request-Tags"

#: The fixed feature names a tag may carry.  A value outside the set is dropped,
#: so a tag can never carry free text.
COMPONENTS: Final[frozenset[str]] = frozenset({"generation", "title", "export", "image"})


def _tellr_version() -> str:
    """The deployed release (``attribution.package_version``)."""
    from src.core.attribution import package_version

    return package_version()


def _request_tags(component: str | None = None) -> str:
    """The tag header's JSON object: ``source``, then each optional key that is on its list.

    ``entrypoint`` is the current context's (``attribution.get_entrypoint``), read when
    the headers are built, so a client carries the entrypoint of the turn that built it.
    Only a plain ``str`` on its list counts.  Any other value, ``None``, an unhashable
    value or a ``str`` stand-in included, adds no key and never raises.
    """
    from src.core.attribution import ENTRYPOINTS, get_entrypoint

    tags: dict[str, str] = {"source": "tellr"}
    if type(component) is str and component in COMPONENTS:
        tags["component"] = component
    entrypoint = get_entrypoint()
    if type(entrypoint) is str and entrypoint in ENTRYPOINTS:
        tags["entrypoint"] = entrypoint
    return json.dumps(tags)


def gateway_request_headers(component: str | None = None) -> dict[str, str]:
    """A new dict of the tag header and the User-Agent for one Gateway client.

    ``component`` names the feature the client is built for; a value off
    :data:`COMPONENTS` (or ``None``) adds no ``component`` key to the tag.
    A caller's ``User-Agent`` replaces the OpenAI SDK's default, which for
    ``DatabricksOpenAI`` is ``DatabricksOpenAI/Python <openai version>``; that
    default is kept as the suffix.
    """
    import openai

    return {
        REQUEST_TAGS_HEADER: _request_tags(component),
        "User-Agent": f"tellr/{_tellr_version()} DatabricksOpenAI/Python {openai.__version__}",
    }


def gateway_chat_model(*, component: str | None = None, **kwargs: Any) -> Any:
    """A Gateway-routed ``ChatDatabricks``; ``kwargs`` are its own (model, identity, bounds).

    The headers ride in ``extra_params``, which ``ChatDatabricks`` spreads into
    every ``chat.completions.create`` call, where the OpenAI SDK sends
    ``extra_headers`` as request headers (never as body fields).  A per-call
    ``extra_headers`` would replace them, so callers must not pass one.
    ``component`` goes on the tag (see :func:`gateway_request_headers`), never to
    ``ChatDatabricks``.
    """
    from databricks_langchain import ChatDatabricks  # type: ignore[import-untyped]

    return ChatDatabricks(
        use_ai_gateway=True,
        extra_params={"extra_headers": gateway_request_headers(component)},
        **kwargs,
    )


def gateway_openai_client(
    workspace_client: Any, *, component: str | None = None, **client_kwargs: Any
) -> Any:
    """``DatabricksOpenAI`` bound to ``{host}/ai-gateway/mlflow/v1`` with the caller's identity.

    ``client_kwargs`` (for example ``max_retries`` or ``timeout``) are forwarded to the
    ``DatabricksOpenAI`` constructor; ``client.with_options()`` is broken on
    ``DatabricksOpenAI`` 0.17.1, so client-level options are set here instead.  The tag
    headers are always applied.  ``component`` goes on the tag (see
    :func:`gateway_request_headers`), never to ``DatabricksOpenAI``.
    """
    from databricks_openai import DatabricksOpenAI

    return DatabricksOpenAI(
        workspace_client=workspace_client,
        use_ai_gateway=True,
        default_headers=gateway_request_headers(component),
        **client_kwargs,
    )
