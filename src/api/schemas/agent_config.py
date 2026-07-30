"""Pydantic models for agent_config JSON stored on sessions and profiles."""
from __future__ import annotations

import logging
from typing import Annotated, Any, Final, Literal, Optional, Union

from pydantic import BaseModel, Field, field_validator, model_validator

logger = logging.getLogger(__name__)

# The provenance values a STORED config may legitimately carry. Anything else is
# coerced on read (see ``resolve_agent_config``).
_VALID_STYLE_SOURCES: Final = frozenset({"seeded", "user"})

# Sentinel telling "key absent" apart from "key present and null". An explicit
# null is the LEGACY shape and must stay distinguishable from a malformed value.
_ABSENT: Final[Any] = object()


class GenieTool(BaseModel):
    """Native Genie space tool — registered directly as a LangChain tool."""
    type: Literal["genie"]
    space_id: str = Field(..., min_length=1)
    space_name: str = Field(..., min_length=1)
    description: Optional[str] = None
    conversation_id: Optional[str] = None


class MCPTool(BaseModel):
    """MCP server tool — tools discovered via UC HTTP connections."""
    type: Literal["mcp"]
    connection_name: str = Field(..., min_length=1)
    server_name: str = Field(..., min_length=1)
    description: Optional[str] = None
    config: dict = Field(default_factory=dict)


class VectorIndexTool(BaseModel):
    """Vector search index tool — similarity search over embeddings."""
    type: Literal["vector_index"]
    endpoint_name: str = Field(..., min_length=1)
    index_name: str = Field(..., min_length=1)
    description: Optional[str] = None
    columns: Optional[list[str]] = None
    num_results: int = Field(default=5, ge=1, le=50)


class ModelEndpointTool(BaseModel):
    """Model serving endpoint tool — foundation models and custom ML."""
    type: Literal["model_endpoint"]
    endpoint_name: str = Field(..., min_length=1)
    endpoint_type: Optional[str] = None
    description: Optional[str] = None


class AgentBricksTool(BaseModel):
    """Agent Bricks tool — knowledge assistants and supervisor agents."""
    type: Literal["agent_bricks"]
    endpoint_name: str = Field(..., min_length=1)
    description: Optional[str] = None


ToolEntry = Annotated[
    Union[GenieTool, MCPTool, VectorIndexTool, ModelEndpointTool, AgentBricksTool],
    Field(discriminator="type"),
]


class AgentConfig(BaseModel):
    """Agent configuration stored as JSON on sessions and profiles."""
    tools: list[ToolEntry] = Field(default_factory=list)
    slide_style_id: Optional[int] = None
    # PROVENANCE of the style slot: "seeded" = the server put this here (nobody
    # chose it), "user" = a person decided it — including deciding on NEITHER a
    # style nor a design system. Persisted so the client never has to infer it by
    # comparing the stored id to the current default, which cannot distinguish a
    # seeded value from a deliberate choice of that same value, and which made a
    # later `is_default` change retroactively reinterpret stored configs.
    # Optional: configs written before this field existed carry None and are
    # treated as seeded (what they in fact were).
    style_source: Optional[Literal["seeded", "user"]] = None
    # A selected design system compiles to prompt text and, when set, takes
    # precedence over slide_style_id (see agent_factory._get_prompt_content).
    design_system_id: Optional[int] = None
    # Optionally pins ONE of the selected design system's templates
    # (design_system_template.id). Meaningful only alongside design_system_id;
    # generation IGNORES it (with a log) unless the template exists and belongs
    # to that design system, so a stale pin can never fail a request.
    template_id: Optional[int] = None
    deck_prompt_id: Optional[int] = None
    system_prompt: Optional[str] = None
    slide_editing_instructions: Optional[str] = None

    @field_validator("system_prompt", "slide_editing_instructions")
    @classmethod
    def must_be_nonempty_if_set(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v.strip() == "":
            raise ValueError("Must be non-empty if provided")
        return v

    @model_validator(mode="after")
    def no_duplicate_tools(self) -> "AgentConfig":
        seen: set[str] = set()
        for tool in self.tools:
            if isinstance(tool, GenieTool):
                key = f"genie:{tool.space_id}"
            elif isinstance(tool, MCPTool):
                key = f"mcp:{tool.connection_name}"
            elif isinstance(tool, VectorIndexTool):
                key = f"vector_index:{tool.endpoint_name}:{tool.index_name}"
            elif isinstance(tool, ModelEndpointTool):
                key = f"model_endpoint:{tool.endpoint_name}"
            elif isinstance(tool, AgentBricksTool):
                key = f"agent_bricks:{tool.endpoint_name}"
            else:
                continue
            if key in seen:
                raise ValueError(f"Duplicate tool: {key}")
            seen.add(key)
        return self

    def model_dump(self, *args: Any, **kwargs: Any) -> dict:
        """Serialize, enforcing ONE style authority.

        THE CHOKEPOINT for style-source exclusivity. Every write path that persists
        an agent config — the agent-config PUT, PATCH /tools and the GET stale-pin
        heal, the three chat branches, MCP create, profile create/update, profile
        load, and session duplicate — produces its stored dict by calling this
        method, directly or through :func:`sanitize_agent_config_for_persist`. So
        normalizing HERE means every one of them inherits the rule, including a path
        added tomorrow that nobody remembers to annotate.

        This replaces per-route enforcement, which was the wrong altitude. Five
        routes were fixed one at a time (chat-create, chat-client-id, chat-update,
        agent-put, mcp-create) and three were still bypassing it — ``_save_agent_config``
        (reached by PATCH /tools and the GET heal), ``create_profile``, and
        ``duplicate_session`` — each persisting ``slide_style_id`` AND
        ``design_system_id``, which generation then silently disambiguated by
        design-system precedence: a stored row disagreeing with the deck it produced.
        Adding a fourth call would have left the same hole open for the fifth path.

        Semantics are unchanged from :func:`normalize_style_source_exclusivity`:
        DESIGN SYSTEM WINS and the slide style is dropped, never a 422 — a 422 would
        wedge legacy both-set rows on every save (the frontend PUTs the WHOLE config,
        so a user holding such a row could not save an unrelated edit). Legacy
        both-set rows therefore HEAL on write.

        The dump is normalized rather than the model mutated: serialization must not
        have side effects on the object being serialized (a GET that dumps for a
        RESPONSE would otherwise silently edit the caller's in-memory config).
        Routes that need the model itself normalized — the PUT, which must order this
        AFTER its DB reference validation — still call
        :func:`normalize_style_source_exclusivity` explicitly, and the two agree by
        construction: both drop exactly ``slide_style_id``.
        """
        dumped = super().model_dump(*args, **kwargs)
        # Guard the key lookups: a caller may dump a subset (``include=``/
        # ``exclude=``), in which case there is nothing to reconcile.
        if (
            dumped.get("slide_style_id") is not None
            and dumped.get("design_system_id") is not None
        ):
            logger.warning(
                "agent_config carried BOTH slide_style_id=%s and "
                "design_system_id=%s at persistence; the design system takes "
                "precedence, so the slide style is dropped to keep ONE style "
                "authority in the prompt",
                dumped["slide_style_id"],
                dumped["design_system_id"],
            )
            dumped["slide_style_id"] = None
        return dumped


def resolve_agent_config(raw: Optional[dict]) -> AgentConfig:
    """Parse agent_config JSON from DB, returning defaults if None.

    ``style_source`` FAILS SOFT. It is a ``Literal["seeded", "user"]``, so an
    unexpected stored value (hand-edited row, a different writer's version, a
    partial migration) used to raise ``ValidationError`` out of this function —
    which every config LOAD goes through — making the session unloadable over a
    piece of METADATA about a choice rather than the choice itself.

    An unrecognized value is coerced to ``"user"``, with a warning. That is the
    safe direction: ``"user"`` is the NON-OVERRIDING branch, so a config whose
    provenance cannot be read is never re-seeded with the org default over
    something a person may have deliberately selected. An explicit ``null`` (and
    an absent key) is NOT malformed — it is the legacy shape and is preserved, so
    the caller can apply the legacy rule to it.

    Only the READ path is lenient; constructing an ``AgentConfig`` directly still
    validates strictly, so the type stays meaningful in code.
    """
    if raw is None:
        return AgentConfig()
    style_source = raw.get("style_source", _ABSENT)
    if style_source is not _ABSENT and style_source is not None:
        # Membership is tested only for str: an UNHASHABLE stored value (a list,
        # a dict) would raise TypeError out of a set lookup, which is the very
        # failure mode this guard exists to prevent.
        if not isinstance(style_source, str) or style_source not in _VALID_STYLE_SOURCES:
            logger.warning(
                "Stored agent_config has an unrecognized style_source %r; "
                "treating it as user-chosen (the non-overriding reading) so the "
                "config still loads and no selection is silently replaced",
                style_source,
            )
            raw = {**raw, "style_source": "user"}
    return AgentConfig.model_validate(raw)


def normalize_style_source_exclusivity(
    config: AgentConfig, *, session_id: Optional[str] = None
) -> bool:
    """Enforce "a design system and a slide style are MUTUALLY EXCLUSIVE" on WRITE.

    Exclusivity used to live only in the browser, so an API or MCP caller could
    persist BOTH and generation silently applied design-system precedence — a
    stored row that disagreed with the deck it produced. Now that MCP sets
    ``design_system_id``, that path is real.

    NORMALISATION (design system wins, slide style dropped) rather than a 422:
      * generation has always resolved the design system first, so nothing about
        the rendered deck changes — the row just stops disagreeing with it;
      * a 422 would WEDGE the legacy rows this must not break. The frontend PUTs
        the WHOLE config, so a user sitting on a stored both-set row who changed
        only their deck prompt would fail every save — precisely the
        dangling-design-system bug fixed one round earlier;
      * design-system precedence is already the documented product rule.

    Called from the write path AFTER reference validation, never from a model
    validator. Ordering is load-bearing: a DANGLING design system can only be
    detected with a DB lookup, so normalising first would drop a perfectly good
    slide style and then clear the dead design system too, leaving the user with
    NEITHER. Reference validation clears the dangling id first; whatever survives
    is then made exclusive.

    Mutates *config* in place. Returns True when the slide style was dropped.
    """
    if config.slide_style_id is None or config.design_system_id is None:
        return False
    logger.warning(
        "agent_config carried BOTH slide_style_id=%s and design_system_id=%s "
        "(session_id=%s); the design system takes precedence, so the slide style "
        "is dropped to keep ONE style authority in the prompt",
        config.slide_style_id,
        config.design_system_id,
        session_id,
    )
    config.slide_style_id = None
    return True


def sanitize_agent_config_for_persist(
    raw: Optional[dict | AgentConfig],
) -> Optional[dict]:
    """Return agent_config safe to store on a new session or profile.

    Strips session-specific fields (e.g. Genie ``conversation_id``) so copies
    do not inherit another session's conversation state.
    """
    if raw is None:
        return None
    config = raw if isinstance(raw, AgentConfig) else resolve_agent_config(raw)
    for tool in config.tools:
        if isinstance(tool, GenieTool):
            tool.conversation_id = None
    return config.model_dump()
