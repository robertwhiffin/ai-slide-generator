"""``search_brand_assets`` tool for the slide generator agent (Phase 2 reset).

The agentic, on-demand path to a design system's brand IMAGE assets. Brand images
are NOT enumerated in the prompt (a real bundle ships hundreds); instead the
compiled style carries a CONTRACT (see ``design_system_compiler``) telling the
model to call this tool, which returns rows with a ready-to-use ``{{ds-asset:ID}}``
handle. The tool is bound to a single ``design_system_id`` via closure (mirroring
``build_genie_tool``) and reads through ``design_system_service.search_assets``.

This is a DISTINCT tool from ``search_images`` — that one searches the unrelated
``image_assets`` table (user uploads), never design-system assets.
"""

import html
import json
import logging
from typing import Optional

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class SearchBrandAssetsInput(BaseModel):
    """Input schema for the ``search_brand_assets`` tool."""

    query: Optional[str] = Field(
        None, description="Case-insensitive filename substring, e.g. 'logo'"
    )
    kind: Optional[str] = Field(
        None,
        description="Filter by kind: logo, lockup, icon, illustration, background",
    )


# Terse trigger surfaced to the model as the tool's schema description. This is NOT
# passed through the system-prompt brace-escape (``agent.py``), so the literal
# ``{{ds-asset:ID}}`` token is written directly (double braces = what the model
# must emit for the resolver to substitute it).
_SEARCH_BRAND_ASSETS_DESCRIPTION = (
    "Search this design system's brand image assets (logos, lockups, icons, "
    "illustrations, backgrounds) to embed in on-brand slides. Call this whenever "
    "you need a brand image — do NOT invent asset IDs. Each result includes a "
    "ready-to-use {{ds-asset:ID}} handle: embed it with "
    '<img src="{{ds-asset:ID}}" alt="..."/> or '
    "background-image: url('{{ds-asset:ID}}'); the system swaps it for the real "
    "image. Optionally filter by `query` (filename substring) or `kind`."
)


def build_ds_asset_tool(design_system_id: int) -> StructuredTool:
    """Build the ``search_brand_assets`` StructuredTool bound to a design system.

    ``design_system_id`` is captured in a closure (mirroring ``build_genie_tool``),
    so the tool only ever surfaces THIS design system's assets. Each call opens its
    own DB session and delegates to ``design_system_service.search_assets``; rows
    are shaped to ``{id, kind, filename, usage}`` where ``usage`` is a ready-to-use
    ``<img>`` snippet carrying the ``{{ds-asset:ID}}`` handle. Returns JSON.
    """

    def _search_brand_assets(
        query: Optional[str] = None, kind: Optional[str] = None
    ) -> str:
        # Import at call time so tests can patch ``get_db_session`` at its source.
        from src.core.database import get_db_session
        from src.services import design_system_service

        with get_db_session() as db:
            assets = design_system_service.search_assets(
                db, design_system_id, query=query, kind=kind
            )
            # Build rows INSIDE the session (avoid DetachedInstanceError), reading
            # only metadata columns — never the deferred asset bytes.
            rows = [
                {
                    "id": asset.id,
                    "kind": asset.kind,
                    "filename": asset.filename,
                    # HTML-escape the filename in the alt attribute so a crafted
                    # bundle filename can't inject markup if the model copies this
                    # snippet. The "filename" field above stays the raw value (data).
                    "usage": '<img src="{{ds-asset:%d}}" alt="%s"/>'
                    % (asset.id, html.escape(str(asset.filename or ""))),
                }
                for asset in assets
            ]

        if not rows:
            return json.dumps(
                {
                    "message": "No brand assets found for this design system.",
                    "assets": [],
                }
            )
        return json.dumps(
            {"message": f"Found {len(rows)} brand asset(s).", "assets": rows}
        )

    return StructuredTool.from_function(
        func=_search_brand_assets,
        name="search_brand_assets",
        description=_SEARCH_BRAND_ASSETS_DESCRIPTION,
        args_schema=SearchBrandAssetsInput,
    )
