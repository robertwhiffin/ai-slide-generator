"""Resolution of prompts, styles and tools for a single generation/editing request.

Split out of ``agent_factory`` (ws4c C8) so the LangGraph path and the monolith
resolve from ONE implementation instead of two. ``agent_factory`` keeps agent
*construction* (``_create_model``, ``build_agent_for_request``) and re-exports the
names moved here; this module owns *resolution*:

* :func:`resolve_style_source` — the slide-style BRANCH (design system, else legacy
  slide style, else the default), and everything the branch produces;
* :func:`resolve_slide_style` — the model-facing style bytes alone, for callers that
  need only those (the graph's style seam);
* :func:`_get_prompt_content` — full prompt assembly on top of that branch;
* :func:`_design_system_is_active` — the AUTHORING question, failing CLOSED;
* :func:`_build_tools` — tool registration, including the brand-tool gate whose two
  halves must agree with the prompt branch's ``is_active`` filter.

WHY the branch is a separate function rather than inline in
:func:`_get_prompt_content`: the returned prompt dict's ``slide_style`` key is
``None`` on every path (a pinned contract — the assembled prompt is the only
output), so a second consumer of the resolved style could not read it back out of
the dict and would have had to re-implement the branch. A second copy is free to
regress independently, and this branch's tombstone case has already shipped a
defect once. There is now exactly one copy.
"""

import logging
from typing import Any, NamedTuple, Optional

from langchain_core.tools import StructuredTool

from src.api.schemas.agent_config import (
    AgentConfig, GenieTool, MCPTool, VectorIndexTool, ModelEndpointTool, AgentBricksTool,
)
from src.core.defaults import DEFAULT_SLIDE_STYLE
from src.core.prompt_modules import build_editing_system_prompt, build_generation_system_prompt
from src.services.image_tools import SearchImagesInput, search_images
from src.services.tools import (
    GenieQueryInput,
    build_genie_tool,
    build_vector_tool,
    build_mcp_tools,
    build_model_endpoint_tool,
    build_agent_bricks_tool,
    build_ds_asset_tool,
    initialize_genie_conversation,
    query_genie_space,
)

logger = logging.getLogger(__name__)


class ResolvedStyle(NamedTuple):
    """Everything the slide-style branch produces — not just the bytes.

    Immutable by construction (a ``NamedTuple``), because callers pass all FIVE of
    these facts on to prompt assembly and must not be able to disagree about them.
    Five, not four: ``image_guidelines`` is produced by the branch's legacy limb and
    an extraction that returns only the other four drops a legacy slide-style row's
    image guidance out of every prompt.

    Attributes:
        slide_style: The MODEL-FACING style text. Control sentinels stripped; a
            pinned template's SELECTED-TEMPLATE block already appended.
        design_system_active: True only when a design system actually resolved to
            compiled content. Gates the DS-only prompt blocks so the no-DS/legacy
            path stays byte-identical.
        design_system_compiled: The compiled artifact WITH its type-scale region
            sentinels intact, or None. The late re-assertion reads the region out
            of THIS copy — ``slide_style`` has had the sentinels stripped, so
            reading the region out of that instead yields nothing.
        template_pinned: True only when a pinned template's block actually made it
            into ``slide_style``; its own CSS title sizes then outrank the design
            system's ramp numbers in the late type-scale re-assertion.
        image_guidelines: Image guidance carried by a LEGACY slide-style row
            (``slide_style_library.image_guidelines``). Produced by the same branch
            — the legacy limb sets it alongside the style bytes — so it travels
            with them rather than being resolved a second time.
    """

    slide_style: str
    design_system_active: bool
    design_system_compiled: Optional[str]
    template_pinned: bool
    image_guidelines: Optional[str]


def resolve_style_source(config: AgentConfig) -> ResolvedStyle:
    """Resolve the slide-style source for *config*, with everything it produces.

    Precedence (Design System Library, spec §8):
        ``design_system_id`` (if set) -> ``slide_style_id`` -> ``DEFAULT_SLIDE_STYLE``.

    A **BRANCH, not a ladder.** A set ``design_system_id`` takes the first limb
    whatever happens inside it: an INACTIVE or unknown id lands on
    ``DEFAULT_SLIDE_STYLE`` and the ``slide_style_id`` limb is never evaluated. A
    legacy style is a fallback for "no design system selected", not for "the
    selected design system did not resolve".

    Each limb degrades to ``DEFAULT_SLIDE_STYLE`` on lookup failure rather than
    crashing generation.
    """
    slide_style = DEFAULT_SLIDE_STYLE
    image_guidelines: Optional[str] = None
    # True only when a design system actually resolves to compiled content — gates
    # the DS-only precedence/brand blocks so the no-DS/legacy path stays identical.
    design_system_active = False
    # The compiled artifact WITH its type-scale region sentinels intact. The
    # model-facing ``slide_style`` has them stripped, so the re-assertion reads
    # the region out of this copy instead.
    design_system_compiled: Optional[str] = None
    # True only when a pinned template's block actually made it into the prompt —
    # its own CSS title sizes then outrank the design system's ramp numbers in the
    # late type-scale re-assertion.
    template_pinned = False

    # Resolve the slide-style source. A design system (if selected) takes
    # precedence over a legacy slide style; each degrades to DEFAULT_SLIDE_STYLE
    # on lookup failure rather than crashing generation.
    if config.design_system_id is not None:
        try:
            from src.core.database import get_db_session
            from src.database.models import DesignSystem
            from src.services.design_system_compiler import (
                ensure_compiled_style_content_current,
                strip_type_scale_region_markers,
            )

            with get_db_session() as db:
                design_system = (
                    db.query(DesignSystem)
                    .filter_by(id=config.design_system_id, is_active=True)
                    .first()
                )
                if design_system is not None:
                    # compiled_style_content is the design system's drop-in
                    # equivalent of slide_style_library.style_content. A stale or
                    # missing artifact (persisted before the current compiler,
                    # e.g. pre-frame-guardrail rows) is recompiled in place from
                    # the row's persisted tokens/files/assets, so an ACTIVE
                    # design system always injects the current compiler's blocks;
                    # get_db_session commits on exit, persisting the refresh
                    # (lazy backfill-on-read, no batch machinery).
                    slide_style = ensure_compiled_style_content_current(design_system)
                    # The persisted artifact delimits the compiler-owned
                    # type-scale region with control-character sentinels so the
                    # late re-assertion can recover it unambiguously. They are
                    # bookkeeping, not content: extract first (below), then strip
                    # them before the text reaches the model.
                    design_system_compiled = slide_style
                    slide_style = strip_type_scale_region_markers(slide_style)
                    design_system_active = True
                    if config.template_id is not None:
                        # A pinned template appends its SELECTED-TEMPLATE block
                        # here, at prompt-assembly time — the persisted per-DS
                        # compiled artifact stays template-agnostic. An invalid
                        # pin (deleted, or another design system's template)
                        # resolves to None inside the helpers (logged) and the
                        # prompt is byte-identical to the no-template path.
                        from src.services.design_system_templates import (
                            build_selected_template_block,
                            get_template_for_generation,
                        )

                        template = get_template_for_generation(
                            design_system, config.template_id
                        )
                        block = (
                            build_selected_template_block(template)
                            if template is not None
                            else None
                        )
                        if block:
                            slide_style = f"{slide_style}\n\n{block}"
                            template_pinned = True
                else:
                    logger.warning(
                        "Design system not found, using default",
                        extra={"design_system_id": config.design_system_id},
                    )
        except Exception as e:
            logger.error(f"Failed to resolve design_system_id: {e}")
    # Resolve slide_style_id from library (legacy path — unchanged; used only when
    # no design system is selected).
    elif config.slide_style_id is not None:
        try:
            from src.core.database import get_db_session
            from src.database.models import SlideStyleLibrary

            with get_db_session() as db:
                style = (
                    db.query(SlideStyleLibrary)
                    .filter_by(id=config.slide_style_id, is_active=True)
                    .first()
                )
                if style:
                    slide_style = style.style_content
                    image_guidelines = style.image_guidelines
                else:
                    logger.warning(
                        "Slide style not found or inactive, using default",
                        extra={"slide_style_id": config.slide_style_id},
                    )
        except Exception as e:
            logger.error(f"Failed to resolve slide_style_id: {e}")

    return ResolvedStyle(
        slide_style=slide_style,
        design_system_active=design_system_active,
        design_system_compiled=design_system_compiled,
        template_pinned=template_pinned,
        image_guidelines=image_guidelines,
    )


def resolve_slide_style(config: AgentConfig) -> str:
    """The MODEL-FACING slide-style text for *config*.

    A thin wrapper over :func:`resolve_style_source` so a caller that needs only
    the bytes does not re-implement the branch. Deliberately NOT read back out of
    ``_get_prompt_content``'s returned dict: that dict's ``slide_style`` key is
    ``None`` on every path.
    """
    return resolve_style_source(config).slide_style


def _get_prompt_content(
    config: AgentConfig,
    mode: str = "generate",
) -> dict[str, Optional[str]]:
    """Resolve prompt content from AgentConfig, falling back to library lookups
    and then to backend defaults.

    prompt_modules builds a mode-specific system prompt so generation and editing
    each receive only the instructions they need. The per-profile
    ``system_prompt`` / ``slide_editing_instructions`` override fields are
    RETIRED, so ``pre_assembled`` is ALWAYS ``True`` in the returned dict and
    there is no path that hands ``agent.py`` unassembled parts.

    Resolution order for each prompt field:
    1. Library lookup by ID (design_system_id / slide_style_id, deck_prompt_id)
    2. Modular assembly via prompt_modules (mode-aware)
    3. Backend defaults from DEFAULT_SLIDE_STYLE (legacy)

    The slide-style half of that is :func:`resolve_style_source` — one branch, one
    copy, shared with every other consumer of the resolved style. Its docstring
    carries the precedence rules; what matters here is that all five of its
    outputs feed assembly: the model-facing bytes, the DS-active gate, the
    SENTINEL-BEARING compiled copy the late type-scale re-assertion is read out
    of, the pinned-template flag, and a legacy row's image guidelines.

    Args:
        config: The AgentConfig for this request
        mode: ``"generate"`` or ``"edit"``

    Returns:
        Dict with keys: system_prompt, slide_editing_instructions,
        deck_prompt, slide_style, image_guidelines, pre_assembled.
        ``system_prompt`` carries the fully assembled prompt and
        ``pre_assembled`` is always True; the other four are always None,
        retained because ``agent.py::_create_prompt`` reads the whole dict.
    """
    resolved = resolve_style_source(config)
    slide_style = resolved.slide_style
    image_guidelines = resolved.image_guidelines
    design_system_active = resolved.design_system_active
    design_system_compiled = resolved.design_system_compiled
    template_pinned = resolved.template_pinned

    deck_prompt: Optional[str] = None

    # Resolve deck_prompt_id from library
    if config.deck_prompt_id is not None:
        try:
            from src.core.database import get_db_session
            from src.database.models import SlideDeckPromptLibrary

            with get_db_session() as db:
                prompt = (
                    db.query(SlideDeckPromptLibrary)
                    .filter_by(id=config.deck_prompt_id, is_active=True)
                    .first()
                )
                if prompt:
                    deck_prompt = prompt.prompt_content
                else:
                    logger.warning(
                        "Deck prompt not found or inactive, skipping",
                        extra={"deck_prompt_id": config.deck_prompt_id},
                    )
        except Exception as e:
            logger.error(f"Failed to resolve deck_prompt_id: {e}")

    # --- Modular assembly is the ONLY path ---
    #
    # The per-profile ``system_prompt`` / ``slide_editing_instructions`` override
    # fields are RETIRED, so there is no longer a branch that returns
    # ``pre_assembled: False``. This function's RETURN KEYS keep those names —
    # they are the assembled-prompt contract ``agent.py::_create_prompt``
    # consumes — but no config field is read to produce them.
    if mode == "edit":
        assembled = build_editing_system_prompt(
            slide_style=slide_style,
            deck_prompt=deck_prompt,
            image_guidelines=image_guidelines,
        )
    else:
        # The compiled design system lands as prompt block #2, so its numeric
        # title contract is restated LAST (salience: the model measurably fell
        # back to its own heading sizes when the scale was only stated early).
        # The numbers are read back out of the text about to be injected, so the
        # re-assertion can never drift from what the model is shown.
        type_scale_reassertion: Optional[str] = None
        if design_system_active:
            from src.services.design_system_compiler import (
                build_type_scale_reassertion,
                extract_type_scale_block,
            )

            # Read the region out of the SENTINEL-BEARING copy: ``slide_style``
            # has had them stripped for the model.
            type_scale_block = extract_type_scale_block(design_system_compiled)
            if type_scale_block or template_pinned:
                type_scale_reassertion = build_type_scale_reassertion(
                    type_scale_block or "", template_pinned=template_pinned
                )
        assembled = build_generation_system_prompt(
            slide_style=slide_style,
            deck_prompt=deck_prompt,
            image_guidelines=image_guidelines,
            design_system_active=design_system_active,
            type_scale_reassertion=type_scale_reassertion,
        )

    return {
        "system_prompt": assembled,
        "slide_editing_instructions": None,
        "deck_prompt": None,
        "slide_style": None,
        "image_guidelines": None,
        "pre_assembled": True,
    }


def _design_system_is_active(design_system_id: int) -> bool:
    """True when that design system exists and is ACTIVE.

    The tool gate below needs the same verdict the prompt branch reaches at
    :func:`resolve_style_source` (``.filter_by(id=…, is_active=True)``, else
    *"Design system not found, using default"*), so both halves of a generation
    request agree about whether a design system is in play.

    NOT the same question as ``chat_service.resolve_active_design_system_id``,
    despite the name: that resolves the ``{{ds-asset:ID}}`` scope for a deck
    RESPONSE and deliberately still resolves a soft-deleted system's bytes, so
    already-generated decks keep their fonts and images (the D7 retention
    contract). This is the AUTHORING question — may new content be made against
    this brand — and a tombstone answers no.

    Fails CLOSED. A lookup error degrades exactly the way the prompt branch does
    (no brand material) rather than advertising a tool whose own lookup would fail
    in the same breath.
    """
    try:
        from src.core.database import get_db_session
        from src.database.models import DesignSystem

        with get_db_session() as db:
            return (
                db.query(DesignSystem.id)
                .filter_by(id=design_system_id, is_active=True)
                .first()
                is not None
            )
    except Exception as e:
        logger.error(
            f"Failed to resolve design_system_id for tool registration: {e}",
            extra={"design_system_id": design_system_id},
        )
        return False


def _build_tools(
    config: AgentConfig,
    session_data: dict[str, Any],
) -> list[StructuredTool]:
    """Build the list of LangChain tools from AgentConfig.

    Always includes search_images. Adds search_brand_assets ONLY when
    ``config.design_system_id`` is set AND that design system is ACTIVE — BOTH
    halves, see the comment on the gate itself for the tombstone defect the second
    half fixes. Handles all 5 config tool types: GenieTool, MCPTool,
    VectorIndexTool, ModelEndpointTool, AgentBricksTool.

    Args:
        config: AgentConfig with tool definitions
        session_data: Session dict for Genie conversation state

    Returns:
        List of StructuredTool instances
    """
    tools: list[StructuredTool] = []

    # Image search tool is always available
    def _search_images_spotlighted(query=None, category=None, tags=None) -> str:
        from src.utils.spotlight import spotlight
        result = search_images(query=query, category=category, tags=tags)
        return spotlight("image_search", str(result))

    image_search_tool = StructuredTool.from_function(
        func=_search_images_spotlighted,
        name="search_images",
        description=(
            "Search for uploaded images to include in slides. "
            "Use when user mentions images, logos, or branding. "
            "Returns image metadata with IDs. "
            'To embed an image, use: <img src="{{image:ID}}" alt="description" />'
        ),
        args_schema=SearchImagesInput,
    )
    tools.append(image_search_tool)

    # Brand-asset search tool — ONLY when a selected design system is ACTIVE.
    # Bound to the design_system_id via closure so it surfaces only that system's
    # assets; the compiled style's ASSET CONTRACT tells the model to call it. A
    # pinned template_id (Phase 4) shapes prompt assembly only and never changes
    # tool registration.
    #
    # The is_active half matters because a session keeps its pin after the design
    # system is soft-deleted: on the id alone, generation got a fully working brand
    # tool for a TOMBSTONE (measured: "Found 2 brand asset(s)" with embeddable
    # handles) while the prompt branch, which does filter is_active, supplied no
    # brand at all — so new content was authored against a deleted brand with none
    # of its instructions. Both halves now answer the same question.
    if config.design_system_id is not None and _design_system_is_active(
        config.design_system_id
    ):
        tools.append(build_ds_asset_tool(config.design_system_id))

    genie_index = 0
    vector_index = 0
    model_index = 0
    agent_index = 0

    for tool_entry in config.tools:
        if isinstance(tool_entry, GenieTool):
            genie_index += 1
            genie_tool = build_genie_tool(tool_entry, session_data, genie_index)
            tools.append(genie_tool)
            logger.info(
                "Added Genie tool",
                extra={
                    "space_id": tool_entry.space_id,
                    "space_name": tool_entry.space_name,
                    "tool_name": genie_tool.name,
                },
            )
        elif isinstance(tool_entry, VectorIndexTool):
            vector_index += 1
            vector_tool = build_vector_tool(tool_entry, vector_index)
            tools.append(vector_tool)
            logger.info(
                "Added Vector Index tool",
                extra={
                    "index_name": tool_entry.index_name,
                    "tool_name": vector_tool.name,
                },
            )
        elif isinstance(tool_entry, MCPTool):
            mcp_tools = build_mcp_tools(tool_entry)
            tools.extend(mcp_tools)
            logger.info(
                "Added MCP tools",
                extra={
                    "connection_name": tool_entry.connection_name,
                    "server_name": tool_entry.server_name,
                    "tool_count": len(mcp_tools),
                },
            )
        elif isinstance(tool_entry, ModelEndpointTool):
            model_index += 1
            model_tool = build_model_endpoint_tool(tool_entry, model_index)
            tools.append(model_tool)
            logger.info(
                "Added Model Endpoint tool",
                extra={
                    "endpoint_name": tool_entry.endpoint_name,
                    "tool_name": model_tool.name,
                },
            )
        elif isinstance(tool_entry, AgentBricksTool):
            agent_index += 1
            agent_tool = build_agent_bricks_tool(tool_entry, agent_index)
            tools.append(agent_tool)
            logger.info(
                "Added Agent Bricks tool",
                extra={
                    "endpoint_name": tool_entry.endpoint_name,
                    "tool_name": agent_tool.name,
                },
            )

    return tools


# ---------------------------------------------------------------------------
# Skill prompt assembly and model binding — C3
#
# These two functions are appended here (not inlined into src/core/skills/)
# because they depend on ResolvedStyle, DEFAULT_CONFIG, and the Databricks
# client path that already live in this module's sibling imports.  Placing
# them here avoids duplicating those imports and keeps the circular-import
# surface small: src.core.skills imports nothing from this module at module
# level, only locally inside call_skill.
# ---------------------------------------------------------------------------


def assemble_skill_prompt(skill: Any, payload: dict, design_system_active: bool) -> str:
    """Assemble the full system prompt for a single skill invocation.

    Both conditionals are decided from ``design_system_active`` for this
    request, not from the skill definition.  The payload is serialised as JSON
    and appended so every skill receives its task-specific data — without this
    the builder never receives its section brief, the reviewer never receives
    the HTML it is reviewing, and the fixer never receives the finding.

    Why a ``bool``, not a ``ResolvedStyle`` (Ruling C-21):

    The function reads **exactly one field** of ``ResolvedStyle`` at two lines.
    The style *prose* already reaches the skill through ``json.dumps(payload)``,
    which is what the plan intended when ``build_branch_payload`` copies
    ``resolved_style`` text into the payload.  Passing the whole NamedTuple as a
    parameter would force every call site to construct three dummy values it does
    not have; and a ``ResolvedStyle`` in checkpointed ``GraphState`` is on a
    deprecation path — langgraph warns on deserialisation of unregistered types
    and will block in a future version.  A plain ``bool`` never crosses a
    checkpoint boundary as an object.

    Three style cases (§L5 / brief table) — collapsed to one flag:

    * **Case 1 — design system active** (``design_system_active=True``): the
      compiler already emits ``_SLIDE_FRAME_CONSTRAINTS`` inside the compiled
      style.  Do **not** inject them again.  Inject ``DESIGN_SYSTEM_PRECEDENCE``
      so the model follows the brand.
    * **Cases 2 and 3** (``design_system_active=False``): either
      ``DEFAULT_SLIDE_STYLE`` (no safe-area numbers at all) or a legacy library
      style (opaque, usually no numbers).  Inject ``_SLIDE_FRAME_CONSTRAINTS``.

    Cases 2 and 3 both have ``design_system_active == False``, so the three-case
    table collapses to one boolean.  A content sniff of the style text would be
    more robust against a library style that happens to carry the numbers, but
    the plan does not ask for that; a false negative costs a duplicated block,
    not a wrong prompt.

    Not injecting in case 1 is not cosmetic: ``overflow`` is on the build
    reviewer's objective criteria and the criterion instructs it to judge
    against these exact numbers.  A builder that never received them would be
    judged against numbers it was never shown — unfair by construction.

    ``_SLIDE_FRAME_CONSTRAINTS`` is imported under its private name — reading a
    private constant is legal and changes no existing file.  Retyping the
    numbers would create exactly the divergence the ``COMPILER_VERSION``
    currency contract exists to prevent.

    Args:
        skill: The loaded :class:`~src.core.skills.Skill` for this invocation.
        payload: Task-specific dict — builder section brief, reviewer HTML,
            fixer finding, etc.  Serialised as JSON and appended.
        design_system_active: ``True`` when a design system resolved to compiled
            content for this request.  Written to
            :attr:`~src.services.graph.state.GraphState.design_system_active`
            by ``architect_node`` from ``resolve_style_source(...).design_system_active``.

    Returns:
        Assembled prompt string ready for the structured model.
    """
    import json

    from src.core.prompt_modules import DESIGN_SYSTEM_PRECEDENCE
    from src.services.design_system_compiler import _SLIDE_FRAME_CONSTRAINTS

    parts: list[str] = [skill.instructions]

    # Inject frame constraints when the resolved style does NOT already carry
    # them.  The design-system compiler emits them; the default style and legacy
    # library styles do not.
    if not design_system_active:
        parts.append(_SLIDE_FRAME_CONSTRAINTS)

    # Design-system precedence only when a design system is active — it
    # declares that the compiled brand tokens override any generic aesthetic.
    if design_system_active:
        parts.append(DESIGN_SYSTEM_PRECEDENCE)

    # Serialise the payload so the skill receives its task-specific inputs.
    parts.append(json.dumps(payload, indent=2, default=str))

    return "\n\n".join(parts)


def get_structured_model(schema: type[Any]):
    """Return a ChatDatabricks model bound to *schema* for structured output.

    Follows the same client path as ``_create_model`` in
    ``src.services.agent_factory`` — system client, ``DEFAULT_CONFIG["llm"]``
    endpoint — so the structured and monolith paths point at the same backend.
    Do **not** invent a new client here.

    Args:
        schema: A pydantic ``BaseModel`` subclass.  The returned runnable's
            ``.invoke()`` returns a *schema* instance.

    Returns:
        A LangChain runnable (``ChatDatabricks.with_structured_output(schema)``)
        whose invocation parses model output into *schema*.
    """
    from databricks_langchain import ChatDatabricks

    from src.core.databricks_client import get_system_client
    from src.core.defaults import DEFAULT_CONFIG

    llm_config = DEFAULT_CONFIG["llm"]
    system_client = get_system_client()
    model = ChatDatabricks(
        endpoint=llm_config["endpoint"],
        temperature=llm_config["temperature"],
        max_tokens=llm_config["max_tokens"],
        top_p=0.95,
        workspace_client=system_client,
    )
    return model.with_structured_output(schema)
