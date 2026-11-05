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
from typing import Final

REQUEST_TAGS_HEADER: Final[str] = "Databricks-Ai-Gateway-Request-Tags"
_REQUEST_TAGS: Final[str] = json.dumps({"source": "tellr"})


def gateway_request_headers() -> dict[str, str]:
    """A new dict of the tag header and the User-Agent for one Gateway client.

    The OpenAI SDK lets a caller's ``User-Agent`` replace its own default
    (``OpenAI/Python <version>``), which is kept here as the UA's suffix.
    """
    import openai

    from src.core.databricks_client import _get_package_version

    return {
        REQUEST_TAGS_HEADER: _REQUEST_TAGS,
        "User-Agent": f"tellr/{_get_package_version()} OpenAI/Python {openai.__version__}",
    }
