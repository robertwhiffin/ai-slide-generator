"""The brand-asset search a builder or fixer may call (deck style addendum A).

One :class:`BrandSearchAgentTool`, an ``AgentTool`` for the runtime's tool loop
(``DatabricksModelAdapter.invoke_with_tools``), over a search backend: a
``search_brand_assets`` ``StructuredTool`` whose ``func`` takes ``query`` and
``kind`` and returns ``build_ds_asset_tool``'s JSON.  Production's backend is
``build_ds_asset_tool`` scoped to the deck's design system (``builder_node`` and
``fixer_node``, through ``nodes._brand_search_toolset``).  The offline eval
harness passes a fake one over its asset index (``evals/harness/runner.py``).
Everything else is this module's, so both run the same tool through the same
loop:

* the tool keeps the backend's name and description and
  ``build_ds_asset_tool``'s arguments;
* it caps a result at :data:`BRAND_SEARCH_ROW_CAP` rows, so an unfiltered search
  stays valid JSON instead of being cut mid-row by spotlight's byte cap;
* it returns the result as ``spotlight("brand_assets", ...)``, since a tool's
  own return value is the tool's to spotlight;
* a failing search returns :data:`SEARCH_FAILED_TEXT`, which is code-owned. The
  exception's text (connection details, hostnames) never reaches the model. A
  database blip costs the model a search, not the slide;
* the toolset allows :data:`BRAND_SEARCH_MAX_CALLS` searches.

A toolset counts its calls, so it is per-invocation state: build a fresh one for
every run, the safety-gate retry included.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Final

from pydantic import BaseModel

from src.services.agent_tools.toolset import AgentToolset
from src.services.tools.ds_asset_tool import SearchBrandAssetsInput
from src.utils.spotlight import spotlight

logger = logging.getLogger(__name__)

#: The most searches one builder or fixer run may make.
BRAND_SEARCH_MAX_CALLS: Final = 3

#: The most rows one search hands the model.  The search itself has no cap (a
#: real library holds hundreds of images); capped rows stay valid JSON.
BRAND_SEARCH_ROW_CAP: Final = 20

#: The answer to a search that raised.  Code-owned, never the exception's text.
SEARCH_FAILED_TEXT: Final = (
    "search failed: the search could not be completed and returned no assets."
)

_SPOTLIGHT_SOURCE: Final = "brand_assets"


def _capped(found: str) -> str:
    """``found`` as is, or its first ``BRAND_SEARCH_ROW_CAP`` rows with a note."""
    rows = json.loads(found).get("assets") or []
    if len(rows) <= BRAND_SEARCH_ROW_CAP:
        return found
    return json.dumps(
        {
            "message": (
                f"Found {len(rows)} brand asset(s); showing the first "
                f"{BRAND_SEARCH_ROW_CAP}. Narrow the search with query or kind."
            ),
            "assets": rows[:BRAND_SEARCH_ROW_CAP],
        }
    )


class BrandSearchAgentTool:
    """``search_brand_assets`` as an ``AgentTool`` over one search backend."""

    args_schema = SearchBrandAssetsInput

    def __init__(self, search: Any) -> None:
        self._search = search
        self.name: str = search.name
        self.description: str = search.description

    def run(self, args: BaseModel, *, remaining_seconds: float) -> str:
        del remaining_seconds  # one quick database read; the loop owns the clock
        try:
            found = self._search.func(
                query=args.query,  # type: ignore[attr-defined]
                kind=args.kind,  # type: ignore[attr-defined]
            )
            result = _capped(found)
        except Exception:  # noqa: BLE001 - every search failure is told to the model
            logger.warning("brand-asset search failed; the model is told so", exc_info=True)
            return SEARCH_FAILED_TEXT
        return spotlight(_SPOTLIGHT_SOURCE, result)


def build_brand_search_toolset(search: Any) -> AgentToolset:
    """A fresh toolset holding one :class:`BrandSearchAgentTool` over ``search``."""
    return AgentToolset(
        tools=(BrandSearchAgentTool(search),),
        max_calls=BRAND_SEARCH_MAX_CALLS,
    )
