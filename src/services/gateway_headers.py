"""Headers that attribute Tellr's Unity AI Gateway LLM calls to Tellr.

Every model call Tellr sends through the Gateway carries a
``Databricks-Ai-Gateway-Request-Tags: {"source": "tellr"}`` tag and a
``tellr/<version>`` User-Agent, so Databricks can count Tellr's customer
Gateway usage per workspace from ``system.ai_gateway.usage`` (the same
convention Isaac CLI uses with ``source=isaac-cli``).  These headers go only on
OpenAI-client requests to ``/ai-gateway/...``; the Databricks SDK clients and
their ``product=`` tags (``src/core/databricks_client.py``) are deliberately
untouched — those tags are how installs are tracked.
"""

from __future__ import annotations

import json
from functools import lru_cache
from importlib import metadata
from typing import Final

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
