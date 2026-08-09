# LangGraph Agent Core Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the single-agent HTML emitter with a LangGraph-based multi-agent system: architect supervisor, data analyst, parallel per-slide builders, reviewers, a deterministic foreman service, and a review/fix loop. Includes deck spec, incremental slide delivery, multi-target editing, and streaming attribution.

**Architecture:** A LangGraph state machine with 7 agent skills (in-repo, versioned) plus one deterministic orchestration service. State persists to Lakebase via `langgraph-checkpoint-postgres`. Two entry points: conversational (architect-driven, interruptible) and one-shot (prompt→deck, no interrupts, preserves MCP contracts). Reviewers write clean slides; builders never write rows. Foreman handles cap/dispatch/retry logic deterministically. Findings route to chat (deck-level) or drawer (per-slide). Incremental delivery via `slide_ready` events on SSE and slide-cursor on polling.

**Tech Stack:** Python 3.11, LangGraph 1.2.10, LangChain 1.3.14, langgraph-checkpoint-postgres 4.1.1, psycopg3, SQLAlchemy 2.0 (`postgresql+psycopg://` scheme), pytest, TypeScript/React.

## Global Constraints

- **Spec is the single source of truth** for the deck structure. Deck HTML is generated from spec, never spec inferred from HTML (except back-fill on adopt, §4.3).
- **No stored provenance flag.** Origin is known from code path: human HTML edits (WYSIWYG route) never re-trigger spec update; agent HTML changes (graph write) do not trigger spec update because spec already says what was intended.
- **Reviewers write rows, builders never do.** An unreviewed slide never persists to Lakebase (except terminal-failure placeholder).
- **One fix round maximum.** Survivors become surfaced findings. No infinite retry loop.
- **Verification is per-row, not a shared blob** (PR1 prerequisite: `session_slides` carries `verification_record` field keyed by content hash).
- **OBO tokens propagate to every agent's tool calls.** User context is visible to all workers (multi-process uvicorn).
- **In-repo skills only.** `system_prompt` and `slide_editing_instructions` columns are retired; agent behaviour lives in versioned skill files.
- **Tone is a consumption hook + in-repo default** (§5.2.1). User-authoring UI is separate later PR; graph only needs the hook.
- **Seven skills + one service:** architect, data_analyst, builder, fixer, build_reviewer, fix_reviewer, deck_reviewer (agents); foreman (deterministic service, no LLM).
- **Concurrency cap: 15 builders, ascending dispatch, lowest-outstanding-position on slot free, retries jump queue.**
- **Release timeout on stalled buffer:** if position *n* stalls, release later slides after timeout.
- **Terminal-failure placeholder** counts as committed for buffer release and deck-review trigger; never persists unreviewed content.
- **Foreman state persists to checkpointer** (Lakebase), not in-process memory. Multi-worker safe by construction.
- **No regex intent detection.** Architect parses natural language; multi-target references resolved against spec.
- **Streaming:** New `slide_ready` event with `{position, html, scripts}` (scripts is str, not dict); polling adds slide cursor alongside `after_message_id`.
- **Agent attribution:** `agent` field on `StreamEvent`; activity messages coalesced ("dispatching 10 builders"), not 1 per builder.
- **Input/output security:** `<untrusted-data>` + `cap_tool_output` on all gatherers; fixer output passes safety gate; reviewer input paths trusted (internal findings only).
- **One-shot path:** `create_deck` / `edit_deck` contracts unchanged; enters at architect with conversation skipped; runs to completion; returns deck + review summary.

---

## Dependencies on PR1 and PR2

### What PR1 provides (Row-per-slide schema)

**Assumed signatures and facts:**

- **`SessionSlide` model** at `src/database/models/session.py:XXX`:
  - Fields: `session_id`, `position` (int, 0-indexed), `html`, `scripts`, `slide_id`, `created_by`, `created_at`, `modified_by`, `modified_at`, `verification_record` (JSON, content-hash keyed, per-row, NOT shared blob)
  - Primary key: `(session_id, position)`
  - No optimistic lock on the slide row (contentious writes are OK because each reviewer writes one row); optimistic lock stays on `SessionSlideDeck` for deck-level mutations

- **`SlideWriter` write API** at `src/api/services/slide_repository.py` (authoritative signature):
  ```python
  class SlideWriter:
      def write_slide(
          self,
          session_id: str,
          position: int,
          html: str,
          scripts: str = "",
          verification_record: Optional[Dict[str, Any]] = None,
          deck_spec_slide: Optional[Dict[str, Any]] = None,
          modified_by: Optional[str] = None,
      ) -> None: ...
      
      def get_slide(self, session_id: str, position: int) -> Optional[Dict[str, Any]]: ...
      def list_slides_in_position_order(self, session_id: str, from_position: int = 0) -> List[Dict]: ...
      def delete_slide(self, session_id: str, position: int) -> None: ...
      def commit_placeholder(self, session_id: str, position: int, error_message: str = "") -> None: ...
  ```
  - Idempotent: position exists → update; else → insert
  - `scripts` is JavaScript source text (str), not dict
  - If `verification_record` is None, no verification field is written (field stays null or default)
  - `commit_placeholder` provided by PR1 specifically for terminal-failure placeholder path
  - No contention because one reviewer per slide writes one row
  - Instance methods: instantiate `SlideWriter()` before calling

- **`SessionSlideDeck` remains** for deck-level state (CSS, title, `version`, `locked_by/at`); `deck_json` loses source-of-truth status; `verification_map` (shared blob) is gone

- **`SlideDeckVersion` snapshot** at restore time includes deck spec (new column, added in PR1)

- **Knit function unchanged:** `slide_deck.py:323 knit()` stitches rows into HTML already; no changes needed

- **If any task expects `deck_json` field, PR1 PR contact is different.** Assume `knit()` reads rows directly.

### What PR2 provides (Dependency upgrade)

**Assumed signatures and facts:**

- **`langgraph==1.2.10`** is resolvable (no `ResolutionImpossible`); all transitive deps OK
- **`langgraph-checkpoint-postgres>=4.1.1`** is installed and `psycopg>=3.2.0` (psycopg3) compatible
- **`PostgresCheckpointer` class** from `langgraph_checkpoint_postgres.postgres` is importable:
  ```python
  from langgraph_checkpoint_postgres.postgres import PostgresCheckpointer
  # Usage: checkpointer = PostgresCheckpointer(connection, schema="public")
  ```
- **SQLAlchemy can connect via `postgresql+psycopg://` scheme** (no changes to `database.py` driver string needed; just works)
- **OBO token hook** (`database.py:306 provide_token`) still injects token into the connection and works with psycopg3
- **Lakebase endpoint is reachable from app** (prod + devloop forks); checkpointer writes land in same Lakebase catalog where session state lives
- **If any psycopg3 migration issue surfaces, PR2 contact is debug point.**

---

## File Structure

### New Files (Skills + Core)

| File | Responsibility |
|---|---|
| `src/core/skills/__init__.py` | Skill loader; registers all 7 skills by name |
| `src/core/skills/architect_skill.py` | Architect agent (supervisor, converses, routes) |
| `src/core/skills/data_analyst_skill.py` | Data analyst agent (structured requests, 3 outcomes) |
| `src/core/skills/builder_skill.py` | Builder agent (per-slide HTML generation) |
| `src/core/skills/fixer_skill.py` | Fixer agent (minimal edits to resolve findings) |
| `src/core/skills/build_reviewer_skill.py` | Build reviewer (strict multi-criteria schema, writes row) |
| `src/core/skills/fix_reviewer_skill.py` | Fix reviewer (diff-aware chooser, writes winner) |
| `src/core/skills/deck_reviewer_skill.py` | Deck reviewer (global checks, non-blocking) |
| `src/domain/deck_spec.py` | Deck spec model: deck-level + per-slide fields, schema, back-fill logic |
| `src/services/langgraph_agent.py` | Graph builder: state machine, edges, Send fan-out, scheduler |
| `src/services/foreman_service.py` | Foreman: deterministic dispatch, cap, retry queue, release timeout logic |
| `src/api/services/slide_repository.py` | SlideWriter: Write API for per-slide rows (wraps PR1 schema) |
| `tests/unit/test_deck_spec.py` | Deck spec model + back-fill tests |
| `tests/unit/test_foreman_orchestration.py` | Foreman dispatch/cap/retry/release/timeout tests (deterministic) |
| `tests/unit/test_graph_state_machine.py` | Graph transitions, parallel builders, findings routing |
| `tests/integration/test_build_chain.py` | Full build→review→fix→fix-review→deck-review chain |

### Modified Files (Core + API + DB)

| File | Changes |
|---|---|
| `src/core/prompt_modules.py` | Add tone consumption hook; add skill composition helpers |
| `src/core/defaults.py` | Add in-repo skill paths (can stay here or move to config) |
| `src/api/schemas/agent_config.py` | Add `tone_guideline` (string, optional, defaults to in-repo default); add `tool_manifest` computed property |
| `src/database/models/session.py` | Add `deck_spec_json` column to `SessionSlideDeck`; update `verification_map` removal docs |
| `src/database/models/slide.py` | Update `Slide` model to add `verification_record` field (or leave to PR1) |
| `src/api/routes/chat.py` | Update handlers to call new graph; wire SSE/polling for slide cursor + `slide_ready` event |
| `src/api/services/chat_service.py` | Delete intent regexes (`_detect_*`, `_parse_slide_references`); keep session store logic; add thin wrapper calling graph |
| `src/api/services/session_manager.py` | Add `msg_to_stream_event` support for `slide_ready` + `agent` field; keep existing logic |
| `src/api/mcp_server.py` | One-shot path: enter graph at architect with conversation skipped; no contract change |
| `src/api/schemas/streaming.py` | Add `slide_ready` event type; add optional `agent` and `slide_cursor` fields to `StreamEvent` |
| `frontend/src/services/api.ts` | Add slide cursor to polling; handle `slide_ready` event |
| `frontend/src/types/streaming.ts` | Add `slide_ready` event, `agent` field, update `StreamEventType` union |
| `frontend/src/views/SessionChat.tsx` | Add spec view toggle; wire context clearing (clears chat + transcript, keeps spec) |
| `frontend/src/components/FeedbackDrawer.tsx` | Wire findings to Apply/Discuss callbacks (stub was already there) |

### Deleted Files

| File | Reason |
|---|---|
| `src/services/agent.py` | Replaced by LangGraph system |
| `src/services/evaluation/llm_judge.py` | (If it exists; moved to skills in PR5) |

---

## Task Breakdown by Phase

### Phase 1: Foundation & Config

#### Task 1.1: Deck spec model and persistence

**Files:**
- Create: `src/domain/deck_spec.py`, `tests/unit/test_deck_spec.py`
- Modify: `src/database/models/session.py` (add `deck_spec_json` column)

**Interfaces:**

Produces:
```python
class DeckSpec(BaseModel):
    """Deck-level spec."""
    audience: str
    purpose: str
    narrative_arc: list[str]
    design_contract: DeckDesignContract
    resolved_data: ResolvedDataSummary
    slides: list[SlideSpec]

class SlideSpec(BaseModel):
    """Per-slide spec."""
    position: int
    purpose: str
    narrative_role: str
    content_brief: str
    assumes: str
    hands_off: str
    data_references: list[str]

def infer_deck_spec_from_html(deck_json: dict, session_id: str) -> DeckSpec:
    """Back-fill spec from existing deck HTML (one-shot, idempotent)."""

def persist_deck_spec(session_id: str, spec: DeckSpec) -> None:
    """Persist spec to SessionSlideDeck.deck_spec_json."""

def load_deck_spec(session_id: str) -> DeckSpec | None:
    """Load spec from Lakebase; return None if absent."""
```

- [ ] **Step 1: Write failing tests for spec model**

Create `tests/unit/test_deck_spec.py` with tests for:
- DeckSpec validation (required fields, schema enforcement)
- SlideSpec validation
- infer_deck_spec_from_html on a fixture deck (parses slide purposes from headers/context)
- persist + load round-trip

Expected failures: module not found.

- [ ] **Step 2: Implement DeckSpec model**

`src/domain/deck_spec.py`: Define Pydantic models for DeckSpec, SlideSpec, DeckDesignContract, ResolvedDataSummary. Include docstrings from spec §4.

- [ ] **Step 3: Implement infer_deck_spec_from_html**

Parse deck HTML, extract slide count, infer purposes from slide order. Heuristic: first slide = intro, last slide = conclusion, middle = supporting. (Simple for now; can be more sophisticated later.)

- [ ] **Step 4: Implement persist_deck_spec, load_deck_spec**

Store/retrieve JSON in `SessionSlideDeck.deck_spec_json`.

- [ ] **Step 5: Add deck_spec_json column to SessionSlideDeck**

Modify `src/database/models/session.py`:
```python
class SessionSlideDeck(Base):
    ...
    deck_spec_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
```

- [ ] **Step 6: Run tests**

Expected: PASS (spec model and round-trip work).

- [ ] **Step 7: Commit**

```bash
git add src/domain/deck_spec.py src/database/models/session.py tests/unit/test_deck_spec.py
git commit -m "feat(spec): deck spec model with persistence and back-fill"
```

---

#### Task 1.2: Tone consumption hook

**Files:**
- Modify: `src/core/prompt_modules.py`, `src/api/schemas/agent_config.py`

**Interfaces:**

Produces:
```python
# In agent_config.py:
class AgentConfig(BaseModel):
    ...
    tone_guideline: str | None = None  # optional; if absent, use default
    
    @computed_field
    @property
    def effective_tone(self) -> str:
        """Return tone_guideline or the in-repo default."""

# In prompt_modules.py:
TONE_DEFAULT = """...in-repo default tone guidelines..."""

def apply_tone(prompt: str, tone_guideline: str) -> str:
    """Append tone guideline to the prompt."""
```

- [ ] **Step 1: Add tone_guideline to AgentConfig**

Modify `src/api/schemas/agent_config.py`:
```python
class AgentConfig(BaseModel):
    ...
    tone_guideline: str | None = Field(None, description="Optional tone/communication guidelines")
    
    @computed_field
    @property
    def effective_tone(self) -> str:
        return self.tone_guideline or TONE_DEFAULT
```

- [ ] **Step 2: Define TONE_DEFAULT in prompt_modules.py**

```python
TONE_DEFAULT = """
Communicate with clarity and professionalism:
- Use active voice and concrete language.
- Avoid jargon; when necessary, define it.
- Be direct: state the recommendation before the reasoning.
- Acknowledge uncertainty and trade-offs.
- Speak to the audience's needs and constraints.
"""
```

- [ ] **Step 3: Add apply_tone helper**

```python
def apply_tone(prompt: str, tone_guideline: str) -> str:
    """Append tone guideline to the system prompt."""
    return f"{prompt}\n\n## Tone and Communication Style\n\n{tone_guideline}"
```

- [ ] **Step 4: Write tests**

`tests/unit/test_prompt_modules.py`: Test that effective_tone returns guideline or default; test that apply_tone appends without mangling.

- [ ] **Step 5: Commit**

```bash
git add src/api/schemas/agent_config.py src/core/prompt_modules.py tests/unit/test_prompt_modules.py
git commit -m "feat(config): tone as optional config axis with in-repo default"
```

---

#### Task 1.3: Skill loading system

**Files:**
- Create: `src/core/skills/__init__.py`, `src/core/skills/architect_skill.py` (stub), plus 6 others (stubs)

**Interfaces:**

Produces:
```python
# In src/core/skills/__init__.py:
class Skill:
    name: str
    system_prompt: str
    output_schema: dict  # JSON Schema
    tools: list[str]  # tool names this skill can call

def load_skill(name: str) -> Skill:
    """Load a skill by name (architect, data_analyst, builder, etc.)."""
    
def list_skills() -> dict[str, Skill]:
    """Return all registered skills."""
```

- [ ] **Step 1: Create skills directory and __init__.py**

```bash
mkdir -p src/core/skills
touch src/core/skills/__init__.py
```

- [ ] **Step 2: Define Skill class**

```python
# src/core/skills/__init__.py
from pydantic import BaseModel
from typing import ClassVar

class Skill(BaseModel):
    name: str
    system_prompt: str
    output_schema: dict
    tools: list[str]
    
    class Config:
        frozen = False  # Allow composition helpers to work with Skill instances
```

- [ ] **Step 3: Create stub skill files**

Create `src/core/skills/{architect,data_analyst,builder,fixer,build_reviewer,fix_reviewer,deck_reviewer}_skill.py` with minimal content:
```python
# e.g., architect_skill.py
ARCHITECT_SKILL = {
    "name": "architect",
    "system_prompt": "[To be filled in Phase 2]",
    "output_schema": {},
    "tools": [],
}
```

- [ ] **Step 4: Implement load_skill and list_skills**

```python
def load_skill(name: str) -> Skill:
    skills = {
        "architect": ...,
        "data_analyst": ...,
        ...
    }
    if name not in skills:
        raise ValueError(f"Unknown skill: {name}")
    return Skill(**skills[name])

def list_skills() -> dict[str, Skill]:
    return {name: load_skill(name) for name in [...]}
```

- [ ] **Step 5: Write tests**

`tests/unit/test_skills_loading.py`: Test load_skill, list_skills, schema validation.

- [ ] **Step 6: Commit**

```bash
git add src/core/skills/
git commit -m "feat(skills): in-repo skill loading system (stubs)"
```

---

#### Task 1.4: Checkpointer and state initialization

**Files:**
- Create: `src/services/langgraph_state.py`
- Modify: `src/core/database.py` (or new file: `src/core/checkpointer.py`)

**Interfaces:**

Produces:
```python
# In langgraph_state.py:
from typing_extensions import TypedDict

class GraphState(TypedDict):
    """LangGraph state dict."""
    session_id: str
    conversation: list[dict]  # [{role, content, agent?}]
    deck_spec: DeckSpec | None
    current_deck: dict  # {slides: [...], css: ...}
    findings: list[Finding]  # accumulated, routed later
    builder_queue: list[int]  # outstanding slide positions
    landed_positions: set[int]  # committed to Lakebase
    fix_map: dict[int, dict]  # position -> {original_html, finding}
    error_state: dict | None

# In checkpointer.py:
from langgraph_checkpoint_postgres.postgres import PostgresCheckpointer

def get_checkpointer(ws: WorkspaceClient, session_id: str) -> PostgresCheckpointer:
    """Return a PostgresCheckpointer configured for the session."""
    # Connect to Lakebase, create checkpointer
```

- [ ] **Step 1: Define GraphState TypedDict**

`src/services/langgraph_state.py`:
```python
from typing_extensions import TypedDict
from src.domain.deck_spec import DeckSpec

class GraphState(TypedDict):
    session_id: str
    conversation: list[dict]
    deck_spec: DeckSpec | None
    current_deck: dict
    findings: list[dict]
    builder_queue: list[int]
    landed_positions: set[int]
    fix_map: dict[int, dict]
    error_state: dict | None
```

- [ ] **Step 2: Write tests for state shape**

`tests/unit/test_langgraph_state.py`: Validate required fields, check that state can be serialized/deserialized for checkpointing.

- [ ] **Step 3: Implement checkpointer getter**

`src/core/checkpointer.py`:
```python
from langgraph_checkpoint_postgres.postgres import PostgresCheckpointer
from src.core.database import get_engine, get_session_maker

def get_checkpointer(session_id: str) -> PostgresCheckpointer:
    """Return a PostgresCheckpointer for the session."""
    # Get Lakebase connection via existing database.py
    engine = get_engine()
    # Return checkpointer (schema="public", or config-driven)
    return PostgresCheckpointer(connection_string=..., schema="tellr_checkpoints")
```

- [ ] **Step 4: Test checkpointer construction**

Verify that checkpointer can be instantiated (mock DB if needed).

- [ ] **Step 5: Commit**

```bash
git add src/services/langgraph_state.py src/core/checkpointer.py tests/unit/test_langgraph_state.py
git commit -m "feat(graph): state dict and checkpointer init"
```

---

### Phase 2: Graph Core

#### Task 2.1: Architect agent (basic structure)

**Files:**
- Modify: `src/core/skills/architect_skill.py`
- Create: `tests/integration/test_architect_agent.py`

**Interfaces:**

Produces:
```python
# Architect skill system prompt focuses on:
# - conversation, brainstorming, understanding intent
# - data requests (structured to analyst)
# - deck spec authoring (structured output)
# - finding routing (deck-level vs. slide-level)

ARCHITECT_SKILL = {
    "name": "architect",
    "system_prompt": "[full prompt from spec §5.2.1]",
    "output_schema": {
        "type": "object",
        "properties": {
            "intent": {"enum": ["discuss", "build", "ask_data", "review_spec"]},
            "response": {"type": "string"},  # conversational prose
            "spec_update": {"type": "object"},  # partial DeckSpec
            "data_request": {"type": "object"},  # structured request
        }
    },
    "tools": ["data_analyst", "find_slides"],
}
```

- [ ] **Step 1: Write the architect skill prompt**

Based on spec §5.2.1, PRD §5, and existing `prompt_modules.py` generation material:
- Brainstorming partner (engage with purpose, offer structure, push back, remember decisions)
- Implicit mode (no toggle; infer intent from language)
- Deck spec output (structured form for sub-agents)
- Tool awareness (architect knows tool manifest; can request specific tools)
- Two output types (prose + structured)

- [ ] **Step 2: Define output schema**

```python
{
    "type": "object",
    "properties": {
        "intent": {
            "type": "string",
            "enum": ["discuss", "build", "ask_data", "edit"],
            "description": "What the user intends this turn"
        },
        "response": {
            "type": "string",
            "description": "Conversational reply to the user"
        },
        "spec_update": {
            "type": "object",
            "description": "Partial deck spec to apply (only if intent=build or intent=edit)"
        },
        "data_request": {
            "type": "object",
            "description": "Structured request to data analyst (only if intent=ask_data)"
        },
        "edited_slides": {
            "type": "array",
            "items": {"type": "integer"},
            "description": "Slide positions affected (only if intent=edit)"
        }
    },
    "required": ["intent", "response"]
}
```

- [ ] **Step 3: Implement architect_skill.py**

```python
from src.core.skills import Skill

ARCHITECT_SKILL = Skill(
    name="architect",
    system_prompt="""...[full prompt]...""",
    output_schema={...},
    tools=[]  # tools are provided by the graph at invocation time
)
```

- [ ] **Step 4: Update skill loader**

Modify `src/core/skills/__init__.py` to load architect_skill properly.

- [ ] **Step 5: Write integration tests**

`tests/integration/test_architect_agent.py`:
- Test that architect responds conversationally to a greeting
- Test that architect detects build intent and returns partial spec
- Test that architect detects data requests
- (Use LLM calls; mark as `@pytest.mark.live`)

- [ ] **Step 6: Commit**

```bash
git add src/core/skills/architect_skill.py tests/integration/test_architect_agent.py
git commit -m "feat(skills): architect agent with intent detection and spec output"
```

---

#### Task 2.2: Data analyst agent (basic structure)

**Files:**
- Modify: `src/core/skills/data_analyst_skill.py`
- Create: `tests/integration/test_data_analyst_agent.py`

**Interfaces:**

Produces:
```python
# Data analyst receives:
# {metric, time_bound, grouping, units, tool_preferences}

# Data analyst returns one of three outcomes:
# {outcome: "success", synthesis: "...", sources: [...]}
# {outcome: "missing_data", gap: "...", tried_tools: [...]}
# {outcome: "no_tool", reason: "..."}

DATA_ANALYST_SKILL = {
    "name": "data_analyst",
    "system_prompt": "[prompt from spec §5.2.2]",
    "output_schema": {
        "type": "object",
        "oneOf": [
            {"properties": {"outcome": {"const": "success"}, "synthesis": {...}, "sources": {...}}},
            {"properties": {"outcome": {"const": "missing_data"}, "gap": {...}, "tried_tools": {...}}},
            {"properties": {"outcome": {"const": "no_tool"}, "reason": {...}}},
        ]
    },
    "tools": ["genie", "vector_search", "mcp", "model_endpoints"],
}
```

- [ ] **Step 1: Write data analyst skill prompt**

Spec §5.2.2: synthesis not analysis; single source pass-through; multi-source synthesis only; structured request contract.

- [ ] **Step 2: Define three-outcome schema**

OneOf: success (synthesis + sources), missing_data (gap + tried), no_tool (reason).

- [ ] **Step 3: Implement data_analyst_skill.py**

- [ ] **Step 4: Update skill loader**

- [ ] **Step 5: Write integration tests**

`tests/integration/test_data_analyst_agent.py`:
- Test success (mock Genie tool, return synthesized result)
- Test missing_data
- Test no_tool (tool not available)
- Test single-source pass-through (no re-summarisation)

- [ ] **Step 6: Commit**

```bash
git add src/core/skills/data_analyst_skill.py tests/integration/test_data_analyst_agent.py
git commit -m "feat(skills): data analyst with three-outcome schema"
```

---

#### Task 2.3: Graph topology and state machine (skeleton)

**Files:**
- Create: `src/services/langgraph_agent.py`
- Create: `tests/unit/test_graph_state_machine.py`

**Interfaces:**

Produces:
```python
def build_graph(config: AgentConfig) -> StateGraph:
    """Build the LangGraph state machine."""
    
    graph = StateGraph(GraphState)
    graph.add_node("architect", architect_node)
    graph.add_node("data_analyst", data_analyst_node)
    # ... add other nodes ...
    graph.add_node("foreman", foreman_node)
    
    # Conditional edges
    graph.add_conditional_edges("architect", architect_router, {"discuss": END, "build": "foreman", ...})
    
    return graph.compile(checkpointer=...)
```

- [ ] **Step 1: Sketch the graph topology**

Nodes:
- architect (entry)
- data_analyst (stateless)
- foreman (dispatch + orchestrate)
- builder (×N parallel)
- build_reviewer (×N parallel)
- fixer (×M sequential)
- fix_reviewer (×M sequential)
- deck_reviewer (after all)
- END

Conditional edges:
- architect → discuss/data/build/edit/error
- foreman → dispatch N builders in parallel
- builder → build_reviewer (direct, no foreman round-trip)
- build_reviewer → foreman (findings back)
- foreman → fixer/deck_review/END based on findings

- [ ] **Step 2: Implement architect_node**

```python
def architect_node(state: GraphState, config: AgentConfig) -> dict:
    """Architect processes user message, returns intent + spec/response."""
    # Call architect skill via LLM
    # Parse output_schema
    # Add message to conversation
    # Return partial state update (response, spec_update, intent, etc.)
```

- [ ] **Step 3: Implement architect_router**

Route based on intent: "discuss" → END, "build" → "foreman", "ask_data" → "data_analyst", "edit" → resolve references → "foreman", etc.

- [ ] **Step 4: Implement data_analyst_node**

```python
def data_analyst_node(state: GraphState, config: AgentConfig) -> dict:
    """Data analyst processes structured request, returns success/missing/no_tool."""
    # Extract data_request from state
    # Dispatch to tools
    # Return outcome state update
```

- [ ] **Step 5: Implement foreman_node (skeleton)**

```python
def foreman_node(state: GraphState, config: AgentConfig) -> dict:
    """Foreman dispatcher: queue builders, enforce cap, return Send list."""
    # Extract spec and positions to build
    # Determine which positions are outstanding (not in landed_positions)
    # Return Send([Send(("builder", idx, spec_slide) for each idx in ascending order)])
```

- [ ] **Step 6: Implement builder_node (skeleton)**

```python
def builder_node(state: GraphState, config: AgentConfig, idx: int) -> dict:
    """Build one slide."""
    # Receive spec_slide + current_deck CSS
    # Call builder skill
    # Return {html, scripts}
    # Forward to build_reviewer (direct edge, not via foreman)
```

- [ ] **Step 7: Implement build_reviewer_node (skeleton)**

```python
def build_reviewer_node(state: GraphState, config: AgentConfig, idx: int) -> dict:
    """Review builder output; route findings or write row."""
    # Receive {html, scripts} from builder
    # Call build_reviewer skill
    # If clean: write row via SlideWriter; mark position as landed
    # If findings: return findings back to foreman
```

- [ ] **Step 8: Write tests**

`tests/unit/test_graph_state_machine.py`:
- Test architect node output shape
- Test architect_router paths
- Test foreman dispatch of N builders
- Test builder node produces HTML
- Test build_reviewer node produces findings

(Use mocks for LLM calls.)

- [ ] **Step 9: Commit**

```bash
git add src/services/langgraph_agent.py tests/unit/test_graph_state_machine.py
git commit -m "feat(graph): topology skeleton with architect → foreman → builder → reviewer"
```

---

### Phase 3: Builder and Reviewers

#### Task 3.1: Builder skill

**Files:**
- Modify: `src/core/skills/builder_skill.py`

**Interfaces:**

Produces:
```python
# Builder receives:
{
    "position": 0,
    "slide_spec": SlideSpec,
    "css_contract": str,
    "deck_spec": DeckSpec,
    "resolved_data": dict
}

# Builder returns:
{
    "html": "<div>...</div>",
    "scripts": "/* JavaScript source for Chart.js etc */",
    "metadata": {}
}
```

- [ ] **Step 1: Write builder skill prompt**

Spec §5.2.3: Generate slide body HTML given spec; emit only body (no `<style>`); respect CSS contract; handle images and charts. Incorporate existing `prompt_modules.py` material (GENERATION_GOALS, CHART_JS_RULES, IMAGE_SUPPORT).

- [ ] **Step 2: Define builder skill schema**

Output schema: `{html, scripts, metadata}`.

- [ ] **Step 3: Implement builder_skill.py**

- [ ] **Step 4: Test with a fixture**

`tests/unit/test_builder_skill.py`:
- Test HTML generation (mock LLM, parse output)
- Test canvas ID deduplication (each builder call gets unique suffix)
- Test that output satisfies schema

- [ ] **Step 5: Commit**

```bash
git add src/core/skills/builder_skill.py tests/unit/test_builder_skill.py
git commit -m "feat(skills): builder agent with canvas ID deduplication"
```

---

#### Task 3.2: Build reviewer skill

**Files:**
- Modify: `src/core/skills/build_reviewer_skill.py`

**Interfaces:**

Produces:
```python
# Receives:
{
    "html": "<div>...</div>",
    "scripts": "/* JavaScript source */",
    "deck_spec": DeckSpec,
    "slide_spec": SlideSpec
}

# Returns:
{
    "verdict": "clean" | "findings",
    "findings": [
        {
            "category": "content" | "design" | "narrative",
            "severity": "high" | "medium" | "low",
            "description": "...",
            "auto_fixable": true | false
        }
    ]
}
```

- [ ] **Step 1: Write build reviewer skill prompt**

Spec §5.2.4: Multiple criteria (content, design, narrative). Each finding self-classified as objective/subjective. Return structured findings only if any issues; if clean, no findings list.

- [ ] **Step 2: Define multi-criteria schema**

```python
{
    "verdict": {"enum": ["clean", "findings"]},
    "findings": {
        "type": "array",
        "items": {
            "properties": {
                "category": {"enum": ["content", "design", "narrative"]},
                "severity": {"enum": ["high", "medium", "low"]},
                "description": {"type": "string"},
                "auto_fixable": {"type": "boolean"}
            }
        }
    }
}
```

- [ ] **Step 3: Implement build_reviewer_skill.py**

- [ ] **Step 4: Implement write_slide helper**

When verdict is "clean", call `SlideWriter.write_slide(session_id, position, html, scripts, verification_record)`.

```python
def write_reviewed_slide(session_id: str, position: int, html: str, scripts: str = "", 
                         verification_record: dict = None) -> None:
    """Write a clean slide to Lakebase."""
    from src.api.services.slide_repository import SlideWriter
    writer = SlideWriter()
    writer.write_slide(session_id, position, html, scripts, verification_record)
```

- [ ] **Step 5: Test build reviewer**

`tests/unit/test_build_reviewer_skill.py`:
- Test clean verdict (no findings)
- Test multiple findings with different auto_fixable flags
- Test write_slide called on clean verdict

- [ ] **Step 6: Commit**

```bash
git add src/core/skills/build_reviewer_skill.py tests/unit/test_build_reviewer_skill.py
git commit -m "feat(skills): build reviewer with multi-criteria findings and write path"
```

---

#### Task 3.3: Fixer and fix reviewer

**Files:**
- Modify: `src/core/skills/fixer_skill.py`, `src/core/skills/fix_reviewer_skill.py`

**Interfaces:**

Fixer receives:
```python
{
    "original_html": "<div>...</div>",
    "original_scripts": "/* JavaScript source */",
    "finding": {finding from build reviewer},
    "css_contract": str
}
```

Fixer returns:
```python
{
    "fixed_html": "<div>...</div>",
    "fixed_scripts": "/* JavaScript source */"
}
```

Fix reviewer receives:
```python
{
    "original_html": "...",
    "fixed_html": "...",
    "finding": {...},
    "deck_spec": DeckSpec
}
```

Fix reviewer returns:
```python
{
    "choice": "original" | "fixed",
    "reason": "...",
    "new_findings": [...]  # if choice=original, surface the original finding
}
```

- [ ] **Step 1: Write fixer skill prompt**

Spec §5.2.5: Disposition is minimal change; hand an authoring agent broken HTML and it re-authors (bad). Fixer focuses on targeted edits. Tone: "make the minimal change."

- [ ] **Step 2: Implement fixer_skill.py**

- [ ] **Step 3: Write fix reviewer skill prompt**

Spec §5.2.6: Receives original + new + finding. Decides fixed vs. original. Can detect diff, scope. If fix is worse, keep original.

- [ ] **Step 4: Implement fix_reviewer_skill.py**

Include: diff computation, scope check (is diff roughly the finding size or did it rewrite the whole slide?), decision logic.

- [ ] **Step 5: Implement write_reviewed_slide for fix reviewer**

When fix reviewer chooses, write the winning version to Lakebase.

- [ ] **Step 6: Test fixer and fix reviewer**

`tests/unit/test_fixer_skill.py`:
- Test minimal edits (text change, not re-author)

`tests/unit/test_fix_reviewer_skill.py`:
- Test choice=original when fix is worse
- Test choice=fixed when fix is good
- Test scope detection (unchanged → did nothing)

- [ ] **Step 7: Commit**

```bash
git add src/core/skills/fixer_skill.py src/core/skills/fix_reviewer_skill.py tests/unit/test_fixer_skill.py tests/unit/test_fix_reviewer_skill.py
git commit -m "feat(skills): fixer and fix reviewer with choice logic"
```

---

#### Task 3.4: Deck reviewer skill

**Files:**
- Modify: `src/core/skills/deck_reviewer_skill.py`

**Interfaces:**

Receives:
```python
{
    "current_deck": {slides: [...], css: "..."},
    "deck_spec": DeckSpec,
    "findings_so_far": [...]  # from build loop
}
```

Returns:
```python
{
    "findings": [
        {
            "category": "narrative",
            "severity": "high",
            "description": "...",
            "scope": "global"
        }
    ]
}
```

- [ ] **Step 1: Write deck reviewer skill prompt**

Spec §5.2.7: Global checks (arc, conclusion, cross-deck repetition). Per-slide reviewers cannot see these. Non-fatal (runs after deck is usable).

- [ ] **Step 2: Implement deck_reviewer_skill.py**

- [ ] **Step 3: Test deck reviewer**

`tests/unit/test_deck_reviewer_skill.py`:
- Test detection of missing conclusion
- Test arc flow assessment

- [ ] **Step 4: Commit**

```bash
git add src/core/skills/deck_reviewer_skill.py tests/unit/test_deck_reviewer_skill.py
git commit -m "feat(skills): deck reviewer for global narrative checks"
```

---

### Phase 4: Foreman Service

#### Task 4.1: Foreman deterministic orchestration

**Files:**
- Create: `src/services/foreman_service.py`
- Create: `tests/unit/test_foreman_orchestration.py`

**Interfaces:**

Produces:
```python
class ForemanState:
    """Foreman turn state (persisted to checkpointer)."""
    outstanding_positions: list[int]  # positions not yet landed, in order
    builder_queue: deque[int]  # dispatch queue (ascending by position)
    fix_map: dict[int, dict]  # position → {original_html, finding}
    landed_positions: set[int]  # committed positions
    concurrent_builders: int = 0

class ForemanService:
    def __init__(self, cap: int = 15, release_timeout: int = 300):
        self.cap = cap
        self.release_timeout = release_timeout
    
    def dispatch_builders(self, spec: DeckSpec, current_landed: set[int]) -> list[Send]:
        """Return list of Send() calls to dispatch up to `cap` builders."""
        
    def on_builder_complete(self, position: int, html: str, scripts: str) -> dict:
        """Builder finished; send to reviewer. Route findings if clean."""
        
    def on_review_complete(self, position: int, findings: list | None) -> dict:
        """Review finished; route findings or mark landed."""
        
    def on_fix_complete(self, position: int, choice: str, html: str) -> dict:
        """Fix review finished; mark landed."""
        
    def get_releasable_slides(self, current_landed: set[int]) -> list[int]:
        """Return positions that are now releasable (all prior ones landed)."""
```

- [ ] **Step 1: Write deterministic dispatch tests**

`tests/unit/test_foreman_orchestration.py`:
- Test dispatch: cap=15, positions 0–30 → first dispatch is 0–14 in order
- Test release: dispatch 0–14, complete 0–10, release only 0–10; complete 11, release 11; complete 15–19, not released (12–14 missing)
- Test retry queue: position 5 failed → retry; when slot frees, take 5, not 20
- Test release timeout: position 10 blocks 11–14 for 300s → release after timeout, mark 10 as placeholder

- [ ] **Step 2: Implement ForemanService**

```python
class ForemanService:
    def __init__(self, cap: int = 15, release_timeout: int = 300):
        self.cap = cap
        self.release_timeout = release_timeout
    
    def dispatch_builders(self, spec: DeckSpec, current_landed: set[int]) -> list[Send]:
        outstanding = [s.position for s in spec.slides if s.position not in current_landed]
        to_dispatch = []
        for pos in sorted(outstanding)[:self.cap]:
            to_dispatch.append(Send(("builder", pos, spec.slides[pos])))
        return to_dispatch
    
    def get_releasable_slides(self, all_positions: list[int], landed: set[int]) -> list[int]:
        releasable = []
        for pos in sorted(all_positions):
            if pos not in landed:
                break
            releasable.append(pos)
        return releasable
```

- [ ] **Step 3: Implement retry queue logic**

When a builder fails, re-enter the position at the head of the queue (lowest position gets next slot).

- [ ] **Step 4: Implement release timeout**

Track when each position entered outstanding. If timeout reached and position not landed, treat as placeholder; release later slides.

- [ ] **Step 5: Run tests**

All deterministic tests should pass (no LLM).

- [ ] **Step 6: Commit**

```bash
git add src/services/foreman_service.py tests/unit/test_foreman_orchestration.py
git commit -m "feat(orchestration): foreman with cap/dispatch/retry/timeout logic"
```

---

### Phase 5: Build Chain Integration

#### Task 5.1: Full build chain in graph

**Files:**
- Modify: `src/services/langgraph_agent.py`
- Create: `tests/integration/test_build_chain.py`

**Interfaces:**

Connect the nodes:
- foreman_node dispatches N builders via Send()
- builder_node feeds directly to build_reviewer_node
- build_reviewer_node routes findings to foreman or lands slide
- foreman_node routes objective findings to fixer_node, surfaces subjective ones
- fixer_node feeds to fix_reviewer_node
- fix_reviewer_node writes winner and returns to foreman
- foreman_node counts landed slides; when all done, triggers deck_reviewer_node
- deck_reviewer_node runs and returns findings

- [ ] **Step 1: Implement builder_node (complete)**

```python
def builder_node(state: GraphState, config: AgentConfig, position: int) -> dict:
    slide_spec = state["deck_spec"].slides[position]
    css = state["current_deck"]["css"]
    output = call_skill_with_llm(
        "builder",
        input={
            "position": position,
            "slide_spec": slide_spec,
            "css_contract": css,
            "deck_spec": state["deck_spec"],
            "resolved_data": state["deck_spec"].resolved_data
        }
    )
    return {
        "html": output["html"],
        "scripts": output["scripts"],
        "position": position
    }
```

- [ ] **Step 2: Implement build_reviewer_node (complete)**

```python
def build_reviewer_node(state: GraphState, config: AgentConfig, position: int, 
                        html: str, scripts: str) -> dict:
    output = call_skill_with_llm(
        "build_reviewer",
        input={
            "html": html,
            "scripts": scripts,
            "deck_spec": state["deck_spec"],
            "slide_spec": state["deck_spec"].slides[position]
        }
    )
    if output["verdict"] == "clean":
        # Write row
        write_reviewed_slide(
            state["session_id"], position, html, scripts,
            verification_record={"timestamp": now(), ...}
        )
        return {"action": "land", "position": position}
    else:
        # Return findings to foreman
        return {
            "action": "findings",
            "position": position,
            "findings": output["findings"],
            "html": html,  # hold for fix reviewer
            "scripts": scripts
        }
```

- [ ] **Step 3: Implement router functions**

```python
def architect_router(state: GraphState) -> str:
    """Route architect output by intent."""
    intent = state.get("intent", "discuss")
    if intent == "discuss":
        return "discuss"
    elif intent == "build":
        return "build"
    elif intent == "ask_data":
        return "ask_data"
    elif intent == "edit":
        return "edit"
    else:
        return "discuss"

def reviewer_router(state: GraphState, position: int, findings: list | None) -> str:
    """Route build_reviewer output: clean lands, findings go to foreman."""
    if findings:
        return "findings"
    else:
        return "land"

def foreman_router(state: GraphState) -> str:
    """Route foreman: dispatch builders, fix findings, review deck, or end."""
    outstanding = state.get("builder_queue", [])
    fix_map = state.get("fix_map", {})
    landed = state.get("landed_positions", set())
    total_positions = len(state["deck_spec"].slides) if state.get("deck_spec") else 0
    
    # If there are unfixed findings, route to fixer
    if fix_map:
        return "fix"
    # If there are outstanding positions, dispatch builders
    elif outstanding:
        return "build"
    # If all positions landed, do deck review
    elif landed and len(landed) == total_positions:
        return "deck_review"
    else:
        return "end"
```

- [ ] **Step 3b: Implement fixer_node**

```python
def fixer_node(state: GraphState, config: AgentConfig, position: int, 
               finding: dict, html: str, scripts: str) -> dict:
    output = call_skill_with_llm(
        "fixer",
        input={
            "original_html": html,
            "original_scripts": scripts,
            "finding": finding,
            "css_contract": state["current_deck"]["css"],
            "deck_spec": state["deck_spec"]
        }
    )
    return {
        "position": position,
        "fixed_html": output["html"],
        "fixed_scripts": output["scripts"],
        "original_html": html
    }
```

- [ ] **Step 4: Implement fix_reviewer_node**

```python
def fix_reviewer_node(state: GraphState, config: AgentConfig, position: int,
                      finding: dict, original_html: str, fixed_html: str,
                      fixed_scripts: str) -> dict:
    output = call_skill_with_llm(
        "fix_reviewer",
        input={
            "original_html": original_html,
            "fixed_html": fixed_html,
            "finding": finding,
            "deck_spec": state["deck_spec"]
        }
    )
    choice_html = fixed_html if output["choice"] == "fixed" else original_html
    choice_scripts = fixed_scripts if output["choice"] == "fixed" else state["fix_map"][position]["scripts"]
    
    write_reviewed_slide(
        state["session_id"], position, choice_html, choice_scripts,
        verification_record={...}
    )
    
    if output["choice"] == "original":
        # Surface the finding
        return {"action": "surface_finding", "position": position, "finding": finding}
    else:
        return {"action": "land", "position": position}
```

- [ ] **Step 5: Implement foreman dispatch and routing**

```python
def foreman_node(state: GraphState, config: AgentConfig) -> dict:
    # Receive findings from build/fix reviewers
    # Dispatch builders in ascending order, respecting cap
    to_dispatch = foreman_service.dispatch_builders(
        state["deck_spec"], state["landed_positions"]
    )
    
    # Route findings
    for finding in state["findings"]:
        if finding["auto_fixable"]:
            # Send to fixer (added to Send list)
            pass
        else:
            # Surface (added to state["findings"])
            pass
    
    return {
        "builds_to_dispatch": to_dispatch,
        # ...
    }
```

- [ ] **Step 6: Hook all nodes into graph**

```python
def build_graph(config):
    graph = StateGraph(GraphState)
    
    graph.add_node("architect", architect_node)
    graph.add_node("data_analyst", data_analyst_node)
    graph.add_node("foreman", foreman_node)
    graph.add_node("builder", builder_node)
    graph.add_node("build_reviewer", build_reviewer_node)
    graph.add_node("fixer", fixer_node)
    graph.add_node("fix_reviewer", fix_reviewer_node)
    graph.add_node("deck_reviewer", deck_reviewer_node)
    
    # Edges
    graph.add_edge("START", "architect")
    graph.add_conditional_edges(
        "architect",
        architect_router,
        {"discuss": END, "build": "foreman", "ask_data": "data_analyst", "edit": "architect"}
    )
    graph.add_edge("data_analyst", "architect")  # back to architect for context
    graph.add_edge("foreman", "builder")  # via Send()
    graph.add_edge("builder", "build_reviewer")
    graph.add_conditional_edges(
        "build_reviewer",
        reviewer_router,
        {"land": "foreman", "findings": "foreman"}
    )
    graph.add_conditional_edges(
        "foreman",
        foreman_router,
        {"build": "builder", "fix": "fixer", "deck_review": "deck_reviewer", "end": END}
    )
    graph.add_edge("fixer", "fix_reviewer")
    graph.add_edge("fix_reviewer", "foreman")
    graph.add_edge("deck_reviewer", END)
    
    return graph.compile(checkpointer=get_checkpointer(...))
```

- [ ] **Step 7: Write integration tests**

`tests/integration/test_build_chain.py`:
- Test full build chain: architect → foreman → builder → reviewer → land (no findings)
- Test build chain with findings: builder → reviewer → foreman → fixer → fix_reviewer → land
- Test parallel builders (dispatch 3, all complete, all land)
- Test cap enforcement (dispatch 15, queue 16–30, as slots free take lowest outstanding)
- Test deck review triggers after all slides land

- [ ] **Step 8: Commit**

```bash
git add src/services/langgraph_agent.py tests/integration/test_build_chain.py
git commit -m "feat(graph): full build chain with builder → reviewer → fixer → fix_reviewer"
```

---

### Phase 6: Data Flow and Routing

#### Task 6.1: Multi-target editing and natural language resolution

**Files:**
- Create: `src/services/reference_resolver.py`
- Modify: `src/services/langgraph_agent.py` (architect logic)
- Create: `tests/unit/test_reference_resolver.py`

**Interfaces:**

Produces:
```python
def resolve_slide_references(text: str, spec: DeckSpec) -> list[int]:
    """Parse natural language references (slide 5, slides 2-4, the pricing slide) → positions."""
    
def parse_edit_intents(text: str, spec: DeckSpec) -> list[{positions: list[int], instruction: str}]:
    """Split multi-target edits into per-slide intents."""
```

- [ ] **Step 1: Write reference resolver**

Handle:
- Ordinal ("slide 5", "the 8th slide")
- Ranges ("slides 2-4", "slide 3 through 6")
- Slide titles ("the pricing slide", "revenue section")
- Relative ("after slide 3", "before the conclusion")

Test against spec.slides[*].purpose and spec.slides[*].narrative_role.

- [ ] **Step 2: Implement resolve_slide_references**

```python
def resolve_slide_references(text: str, spec: DeckSpec) -> list[int]:
    # Extract ordinal patterns: slide \d+, \d+(?:st|nd|rd|th) slide
    # Extract range patterns: slides \d+ to \d+
    # Extract title patterns: "the X slide" where X matches a slide purpose/role
    # Return sorted unique positions
```

- [ ] **Step 3: Implement parse_edit_intents**

```python
def parse_edit_intents(text: str, spec: DeckSpec) -> list[dict]:
    # Split on delimiters: "slide 5 X, slide 6 Y, slide 10 Z"
    # For each clause, resolve positions and extract instruction
    # Return [{positions: [...], instruction: "..."}, ...]
```

- [ ] **Step 4: Update architect to detect multi-target edits**

Modify architect skill output schema to include `edited_slides` list. When architect detects "edit" intent, it returns a list of (positions, instruction) pairs.

- [ ] **Step 5: Update architect_router**

When intent="edit", dispatch multiple foreman calls (or one foreman call with multiple spec updates).

- [ ] **Step 6: Test reference resolver**

`tests/unit/test_reference_resolver.py`:
- Test ordinal parsing ("slide 5" → [5])
- Test ranges ("slides 2-4" → [2, 3, 4])
- Test multi-target ("slide 5 X, slide 6 Y" → [{positions: [5], instruction: "X"}, {positions: [6], instruction: "Y"}])

- [ ] **Step 7: Commit**

```bash
git add src/services/reference_resolver.py tests/unit/test_reference_resolver.py
git commit -m "feat(architect): natural language reference resolution for multi-target edits"
```

---

#### Task 6.2: One-shot path (MCP + skills entry)

**Files:**
- Modify: `src/api/mcp_server.py`, `src/services/langgraph_agent.py`

**Interfaces:**

Produces:
```python
def run_one_shot_build(prompt: str, config: AgentConfig) -> {
    "deck": {...},
    "review_summary": "...",
    "status": "success" | "failure"
}
```

- [ ] **Step 1: Analyze create_deck / edit_deck contracts**

Current shape (from spec §9.2):
```python
create_deck(ctx, prompt, num_slides, slide_style_id, deck_prompt_id, correlation_id) -> {session_id, request_id, status}
edit_deck(ctx, session_id, instruction, slide_indices, correlation_id) -> {session_id, request_id, status}
```

Must remain unchanged (no signature changes).

- [ ] **Step 2: Implement one-shot entry point**

Add to `langgraph_agent.py`:
```python
def run_one_shot_build(prompt: str, config: AgentConfig, 
                       num_slides: int, slide_style_id: str,
                       deck_prompt_id: str) -> dict:
    """Run full build→review→remediate without conversation."""
    # Create a session
    # Initialize graph state with no conversation
    # Seed architect with: "Build a {num_slides}-slide deck: {prompt}"
    # Run graph to completion (no interrupts)
    # Extract final deck + review summary
    # Return {deck, review_summary, status}
```

- [ ] **Step 3: Modify MCP routes**

`create_deck` and `edit_deck` routes call `run_one_shot_build` and return the same contract (session_id, request_id, status).

- [ ] **Step 4: Test one-shot path**

`tests/integration/test_one_shot_build.py`:
- Test create_deck: prompt → deck returned in one call, no conversation
- Test that create_deck contracts are unchanged

- [ ] **Step 5: Commit**

```bash
git add src/api/mcp_server.py src/services/langgraph_agent.py tests/integration/test_one_shot_build.py
git commit -m "feat(mcp): one-shot path (create_deck / edit_deck contracts preserved)"
```

---

### Phase 7: Streaming and Incremental Delivery

#### Task 7.1: Incremental slide delivery and slide cursor

**Files:**
- Modify: `src/api/schemas/streaming.py`, `src/api/routes/chat.py`, `src/api/services/session_manager.py`
- Create: `tests/integration/test_incremental_delivery.py`

**Interfaces:**

Produces:
```python
# In streaming.py, new event type:
class SlideReadyEvent(StreamEvent):
    event_type: Literal["slide_ready"]
    position: int
    html: str
    scripts: str  # JavaScript source text, not dict
    
# New field on StreamEvent:
agent: str | None = None  # "architect", "builder", "reviewer", etc.
slide_cursor: int | None = None  # for polling: which slide position was most recently delivered

# Polling path updates:
def poll_chat(session_id: str, after_message_id: int, slide_cursor: int) -> list[StreamEvent]:
    # Return events after message_id AND slides with position > slide_cursor
```

- [ ] **Step 1: Update StreamEvent schema**

```python
class StreamEvent(BaseModel):
    event_type: StreamEventType
    content: str | None = None
    agent: str | None = None  # attribution
    position: int | None = None  # for slide_ready
    html: str | None = None  # for slide_ready
    scripts: str | None = None  # for slide_ready (JavaScript source text)
    slide_cursor: int | None = None  # for polling, hint at next expected position
    ...
```

- [ ] **Step 2: Add `slide_ready` event emission to streaming callback**

Modify `src/services/streaming_callback.py` (or update in Phase 7):
```python
def emit_slide_ready(position: int, html: str, scripts: str):
    event = StreamEvent(
        event_type="slide_ready",
        position=position,
        html=html,
        scripts=scripts
    )
    self.event_queue.put(event.to_sse())
```

- [ ] **Step 3: Update foreman to emit slide_ready events**

When a slide lands (build_reviewer writes row or fix_reviewer writes winner), foreman emits a `slide_ready` event via the callback handler.

- [ ] **Step 4: Add slide cursor to polling**

Modify `poll_chat` in `src/api/routes/chat.py`:
```python
@router.get("/chat/poll/{request_id}")
async def poll_chat(
    request_id: str,
    after_message_id: int = 0,
    slide_cursor: int = 0  # NEW: which slides have been delivered
):
    # Return messages after after_message_id
    # AND slides (from session_slides table) where position > slide_cursor
    messages = session_manager.list_messages(session_id, after=after_message_id)
    slides = session_manager.list_slides(session_id, after_position=slide_cursor)
    
    events = []
    for msg in messages:
        events.append(session_manager.msg_to_stream_event(msg))
    for slide in slides:
        events.append(StreamEvent(
            event_type="slide_ready",
            position=slide.position,
            html=slide.html,
            scripts=slide.scripts  # scripts is str from DB
        ))
    return events
```

- [ ] **Step 5: Update session_manager**

Add methods:
```python
def list_slides(session_id: str, after_position: int = -1) -> list[Slide]:
    """Return slides where position > after_position, in order."""
    # Query session_slides table (PR1 provides this)
    
def msg_to_stream_event(msg: SessionMessage) -> StreamEvent:
    """Update to handle agent attribution."""
    if msg.event_type == "slide_ready":
        return StreamEvent(..., agent="reviewer")  # or msg.data["agent"]
    ...
```

- [ ] **Step 6: Wire agent attribution**

When foreman emits a `slide_ready` event, tag it with agent="reviewer". When a builder completes, emit progress "dispatching builder on slide X", agent="foreman". Etc.

- [ ] **Step 7: Test incremental delivery**

`tests/integration/test_incremental_delivery.py`:
- Test SSE: builder emits HTML, slide_ready event streamed
- Test polling: slide_cursor query returns only new slides
- Test that slides appear in ascending position order
- Test agent attribution on events

- [ ] **Step 8: Commit**

```bash
git add src/api/schemas/streaming.py src/api/routes/chat.py src/api/services/session_manager.py tests/integration/test_incremental_delivery.py
git commit -m "feat(streaming): incremental slide_ready events and polling slide cursor"
```

---

#### Task 7.2: Agent activity attribution

**Files:**
- Modify: `src/services/streaming_callback.py`, `src/services/langgraph_agent.py`

**Interfaces:**

Produces:
```python
# Activity messages (coalesced):
def emit_activity(agent: str, action: str, details: dict):
    """Emit a progress message."""
    # "dispatching 10 builders" → one message, not 10
    # "reviewing slide 4" → per-slide message
    
# Tool call attribution:
class StreamEvent:
    ...
    tool_calls: list[dict]  # each has agent attribution
```

- [ ] **Step 1: Update streaming callback**

```python
class StreamingCallbackHandler:
    def emit_activity(self, agent: str, action: str, details: dict):
        event = StreamEvent(
            event_type="assistant",
            content=f"{agent}: {action} ({details})",
            agent=agent
        )
        self.event_queue.put(event.to_sse())
```

- [ ] **Step 2: Update foreman to emit activity**

When dispatching builders:
```python
def foreman_node(...):
    # "Dispatching 10 builders for slides 0-9"
    callback.emit_activity("foreman", f"dispatching {len(to_dispatch)} builders", {})
    return {"dispatch": to_dispatch}
```

- [ ] **Step 3: Update builder/reviewer to emit progress**

```python
def builder_node(...):
    callback.emit_activity("builder", f"building slide {position}", {})
    ...

def build_reviewer_node(...):
    callback.emit_activity("reviewer", f"reviewing slide {position}", {})
    ...
```

- [ ] **Step 4: Tag tool calls with agent**

Modify `on_tool_start` callback to add agent field.

- [ ] **Step 5: Test agent attribution**

`tests/integration/test_agent_attribution.py`:
- Test activity message coalesces builder dispatches
- Test tool calls are tagged with agent
- Test message count is reasonable (not one per builder, one per batch)

- [ ] **Step 6: Commit**

```bash
git add src/services/streaming_callback.py src/services/langgraph_agent.py tests/integration/test_agent_attribution.py
git commit -m "feat(streaming): agent activity attribution with coalesced progress messages"
```

---

### Phase 8: Error Handling and Resilience

#### Task 8.1: Builder retry, placeholder, buffer timeout

**Files:**
- Modify: `src/services/foreman_service.py`, `src/services/langgraph_agent.py`
- Create: `tests/unit/test_error_handling.py`

**Interfaces:**

Produces:
```python
# Foreman tracks retries:
class ForemanState:
    retry_count: dict[int, int] = {}  # position → attempt count

# Builder failure → placeholder (use SlideWriter.commit_placeholder):
def create_placeholder_slide(session_id: str, position: int, error: str) -> None:
    """Write a marked placeholder when builder exhausts retries."""
    from src.api.services.slide_repository import SlideWriter
    writer = SlideWriter()
    writer.commit_placeholder(session_id, position, error_message=error)

# Release timeout:
class ForemanState:
    position_start_time: dict[int, float] = {}  # position → when it entered outstanding
    
def check_release_timeout(self, now: float) -> list[int]:
    """Return positions that should release due to timeout (300s default)."""
```

- [ ] **Step 1: Implement retry logic**

```python
def builder_node(...):
    try:
        # Build
        return output
    except Exception as e:
        retry_count = state.get("retry_count", {}).get(position, 0)
        if retry_count < 1:  # one retry only
            # Retry
            return {"retry": True, "position": position}
        else:
            # Exhausted; create placeholder via SlideWriter
            create_placeholder_slide(session_id, position, str(e))
            return {"placeholder": True, "position": position}
```

- [ ] **Step 2: Implement placeholder creation using PR1's commit_placeholder**

```python
def create_placeholder_slide(session_id: str, position: int, error: str) -> None:
    """Write a marked placeholder when builder exhausts retries."""
    from src.api.services.slide_repository import SlideWriter
    writer = SlideWriter()
    # PR1 provides commit_placeholder specifically for this purpose
    writer.commit_placeholder(session_id, position, error_message=error)
```

- [ ] **Step 3: Implement release timeout**

```python
def foreman_node(...):
    now = time.time()
    released_by_timeout = []
    for pos in sorted(foreman_state.outstanding_positions):
        if pos not in foreman_state.position_start_time:
            foreman_state.position_start_time[pos] = now
        
        elapsed = now - foreman_state.position_start_time[pos]
        if elapsed > 300 and pos not in foreman_state.landed_positions:
            # Timeout; release later slides
            released_by_timeout.append(pos)
            # Create a timeout placeholder via SlideWriter.commit_placeholder
            from src.api.services.slide_repository import SlideWriter
            writer = SlideWriter()
            writer.commit_placeholder(session_id, pos, error_message="timeout: position did not complete")
    
    return {"released_by_timeout": released_by_timeout}
```

- [ ] **Step 4: Test retry and placeholder**

`tests/unit/test_error_handling.py`:
- Test builder fails first time, retries, succeeds
- Test builder fails twice, creates placeholder
- Test placeholder marked for user visibility
- Test timeout releases later slides
- Test placeholder counts as landed for buffer release and deck review

- [ ] **Step 5: Commit**

```bash
git add src/services/foreman_service.py src/services/langgraph_agent.py tests/unit/test_error_handling.py
git commit -m "feat(resilience): retry, placeholder, and release timeout for stalled positions"
```

---

#### Task 8.2: Security gates (input/output safety)

**Files:**
- Modify: `src/services/langgraph_agent.py`, `src/api/routes/chat.py`

**Interfaces:**

Produces:
```python
def gate_reviewer_input(html: str, scripts: str) -> None:
    """Apply safety checks to builder output before review."""
    # Wrap in <untrusted-data>
    # Cap output
    
def gate_fixer_output(html: str) -> None:
    """Apply safety checks to fixer output."""
    # Same gate as output safety gate
```

- [ ] **Step 1: Review existing safety infrastructure**

Check `src/api/routes/chat.py` for `_run_output_safety_gate` (line 97). Reuse that for fixer output.

- [ ] **Step 2: Wrap builder output in untrusted-data**

```python
def build_reviewer_node(..., html: str, scripts: str):
    # Wrap HTML in <untrusted-data>
    html_wrapped = f'<untrusted-data source="builder">{html}</untrusted-data>'
    
    # Apply safety gate
    try:
        _run_output_safety_gate(html_wrapped, scripts)
    except UnsafeContentError as e:
        return {"error": f"unsafe content: {e}", "position": position}
```

- [ ] **Step 3: Gate fixer output**

```python
def fixer_node(...) -> dict:
    fixed_html = output["html"]
    
    # Cap output
    from src.utils.text_caps import cap_tool_output
    fixed_html = cap_tool_output(fixed_html, limit=32768)
    
    # Gate it
    try:
        _run_output_safety_gate(fixed_html, output["scripts"])  # scripts is str
    except UnsafeContentError as e:
        # Return original (not the unsafe fixed version)
        return {"error": f"fixer produced unsafe content: {e}", "use_original": True}
```

- [ ] **Step 4: Gate data analyst output**

Wrap data analyst result in `<untrusted-data source="data_analyst">...</untrusted-data>`.

- [ ] **Step 5: Test security gates**

`tests/unit/test_security_gates.py`:
- Test that reviewer rejects unsafe HTML
- Test that fixer output is gated
- Test that data analyst output is wrapped

- [ ] **Step 6: Commit**

```bash
git add src/services/langgraph_agent.py tests/unit/test_security_gates.py
git commit -m "feat(security): gate reviewer input and fixer output through safety gate"
```

---

### Phase 9: Testing and Cleanup

#### Task 9.1: Comprehensive testing suite

**Files:**
- Create: `tests/integration/test_regression_checklist.py`, `tests/integration/test_concurrency.py`, `tests/integration/test_export_compatibility.py`

**Interfaces:**

Produces regression tests for retired regexes (RC10–RC15 and related):
```python
def test_rc10_ordinal_references():
    """Slide references like 'slide 5' are resolved correctly."""
    spec = DeckSpec(slides=[...])
    refs = resolve_slide_references("update slide 5", spec)
    assert 5 in refs

def test_rc11_range_references():
    """Slide ranges like 'slides 2-4' are resolved correctly."""
    refs = resolve_slide_references("slides 2-4", spec)
    assert refs == [2, 3, 4]

def test_rc12_relative_references():
    """Relative references like 'after slide 3' work."""
    refs = resolve_slide_references("add a slide after slide 3", spec)
    # Should affect position 4 and beyond

# ... RC13, RC14, RC15, etc.

def test_concurrency_no_lost_updates():
    """Parallel builders writing distinct rows do not collide."""
    # Simulate 15 builders writing simultaneously
    # Verify all 15 rows exist and are correct
    
def test_export_parity_pptx():
    """PPTX export produces same output as before."""
    # Generate a deck via graph
    # Export to PPTX
    # Compare with fixture (or at least verify no errors)
```

- [ ] **Step 1: Write regression checklist tests**

`tests/integration/test_regression_checklist.py`:
- RC10: ordinal references
- RC11: range references
- RC12: relative references
- RC13: add vs. replace
- RC14: multiple independent edits
- RC15: slide context awareness

(Copy exact semantics from the old regex rules.)

- [ ] **Step 2: Write concurrency tests**

`tests/integration/test_concurrency.py`:
- Test 15 concurrent builders write rows without contention
- Test optimistic lock on deck-level version counter
- Test multi-worker polling consistency

- [ ] **Step 3: Write export compatibility tests**

`tests/integration/test_export_compatibility.py`:
- Test PPTX export (call `html_to_pptx`, verify no errors)
- Test Google Slides export
- Test save-point restore (including deck spec)

- [ ] **Step 4: Run all tests**

```bash
pytest tests/unit/ -v  # Deterministic tests
pytest tests/integration/ -m live -v  # Live LLM tests
pytest tests/integration/ -k "export or regression" -v  # Specific suites
```

- [ ] **Step 5: Commit**

```bash
git add tests/integration/test_regression_checklist.py tests/integration/test_concurrency.py tests/integration/test_export_compatibility.py
git commit -m "test(integration): regression checklist, concurrency, export compatibility"
```

---

#### Task 9.2: Clean up old code

**Files:**
- Delete: `src/services/agent.py`, `src/services/evaluation/llm_judge.py` (if exists)
- Modify: `src/api/services/chat_service.py` (remove intent regexes and old logic)

**Interfaces:**

Produces:
```python
# chat_service.py now just:
def send_message(session_id: str, message: str) -> dict:
    """Forward to graph."""
    graph = get_or_create_graph(session_id)
    result = graph.invoke({"session_id": session_id, "user_message": message})
    return format_result(result)
```

- [ ] **Step 1: Remove old intent regex functions**

Delete from `chat_service.py`:
- `_detect_generation_intent`
- `_detect_edit_intent`
- `_detect_add_intent`
- `_parse_slide_references`
- `_detect_explicit_replace_intent`
- All related regex patterns

- [ ] **Step 2: Simplify chat_service to delegate to graph**

```python
def send_message(session_id: str, message: str) -> dict:
    """Forward to graph executor."""
    graph = get_or_create_graph(session_id, config)
    user_input = {"session_id": session_id, "new_message": message}
    result = graph.invoke(user_input)
    
    return {
        "session_id": session_id,
        "response": result.get("response", ""),
        "slides": result.get("slides"),
        "findings": result.get("findings"),
    }
```

- [ ] **Step 3: Delete agent.py**

```bash
git rm src/services/agent.py
```

- [ ] **Step 4: Verify imports**

Scan for remaining imports of old classes; update or delete.

- [ ] **Step 5: Run unit tests**

Ensure no broken imports or stale tests.

- [ ] **Step 6: Commit**

```bash
git add src/api/services/chat_service.py
git rm src/services/agent.py
git commit -m "refactor(agent): delete monolith and regex intent layer; delegate to graph"
```

---

### Phase 10: Frontend Integration

#### Task 10.1: Two-view toggle (spec view)

**Files:**
- Modify: `frontend/src/views/SessionChat.tsx`, `frontend/src/components/` (new tab)

**Interfaces:**

Produces:
```typescript
// SessionChat has a toggle: View Slides ↔ View Spec
// Spec view shows:
// {
//   "audience": "...",
//   "purpose": "...",
//   "narrative_arc": [...],
//   "slides": [
//     {"position": 0, "purpose": "...", "narrative_role": "...", ...},
//     ...
//   ]
// }
// Read-only + discuss affordance (edit stays conversational)
```

- [ ] **Step 1: Add toggle button to SessionChat**

```tsx
const [view, setView] = React.useState<"slides" | "spec">("slides");
// Button: "View {slides|spec}"
<button onClick={() => setView(view === "slides" ? "spec" : "slides")}>
  View {view === "slides" ? "Spec" : "Slides"}
</button>
```

- [ ] **Step 2: Create SpecView component**

`frontend/src/components/SpecView.tsx`:
```tsx
interface SpecViewProps {
  spec: DeckSpec | null;
}
export function SpecView({ spec }: SpecViewProps) {
  if (!spec) return <p>No spec yet.</p>;
  return (
    <div className="spec-view">
      <h2>{spec.purpose}</h2>
      <p>Audience: {spec.audience}</p>
      <ol>
        {spec.slides.map(slide => (
          <li key={slide.position}>
            <strong>{slide.narrative_role}</strong>: {slide.content_brief}
          </li>
        ))}
      </ol>
    </div>
  );
}
```

- [ ] **Step 3: Wire spec view toggle**

```tsx
{view === "slides" ? (
  <SlideViewer {...props} />
) : (
  <SpecView spec={deckSpec} />
)}
```

- [ ] **Step 4: Test spec view**

`frontend/src/views/__tests__/SessionChat.test.tsx`:
- Test toggle appears
- Test clicking toggle switches view
- Test spec view displays correctly

- [ ] **Step 5: Commit**

```bash
git add frontend/src/views/SessionChat.tsx frontend/src/components/SpecView.tsx frontend/src/views/__tests__/SessionChat.test.tsx
git commit -m "feat(ui): toggle between slides and spec views"
```

---

#### Task 10.2: Context clearing

**Files:**
- Modify: `frontend/src/views/SessionChat.tsx`, `src/api/routes/chat.py`

**Interfaces:**

Produces:
```python
# API endpoint:
POST /chat/clear-context
→ {success: true}

# Frontend:
onClick={() => clearContext(sessionId)}
// Clears chat transcript + agent context
// Keeps the deck spec
```

- [ ] **Step 1: Implement clear-context endpoint**

`src/api/routes/chat.py`:
```python
@router.post("/chat/clear-context")
async def clear_context(session_id: str):
    """Clear conversation history and agent context; keep spec."""
    session_manager.clear_transcript(session_id)
    # Graph checkpointer retains state, but architect's conversation is empty
    return {"success": True}
```

- [ ] **Step 2: Implement session_manager.clear_transcript**

```python
def clear_transcript(session_id: str) -> None:
    """Delete all SessionMessage rows for this session."""
    # SQL: DELETE FROM session_messages WHERE session_id = ?
```

- [ ] **Step 3: Add clear button to frontend**

```tsx
<button onClick={() => clearContext(sessionId)}>
  Clear Context (keep deck)
</button>
```

- [ ] **Step 4: Wire API call**

```typescript
async function clearContext(sessionId: string) {
  const res = await fetch(`/chat/clear-context?session_id=${sessionId}`, {
    method: "POST"
  });
  if (res.ok) {
    // Refresh chat view (clear messages)
    setMessages([]);
  }
}
```

- [ ] **Step 5: Test context clearing**

`tests/integration/test_context_clearing.py`:
- Test clear-context deletes transcript
- Test clear-context keeps deck spec
- Test deck remains editable after clear

- [ ] **Step 6: Commit**

```bash
git add src/api/routes/chat.py frontend/src/views/SessionChat.tsx tests/integration/test_context_clearing.py
git commit -m "feat(ux): context clearing (transcript + agent state; keeps deck spec)"
```

---

#### Task 10.3: Findings in drawer

**Files:**
- Modify: `frontend/src/components/FeedbackDrawer.tsx`, `src/api/routes/chat.py`

**Interfaces:**

Produces:
```typescript
// FeedbackDrawer receives findings:
{
  position: 0,
  findings: [
    {
      category: "content",
      severity: "high",
      description: "...",
      auto_fixable: false,  // subjective
      apply_callback: () => dispatch to builder,
      dismiss_callback: () => remove finding,
      discuss_callback: () => pull into chat
    }
  ]
}
```

- [ ] **Step 1: Parse findings from stream**

`frontend/src/services/api.ts`:
When a `slide_ready` event lands, check if findings exist in state. Route findings to the drawer for that slide.

- [ ] **Step 2: Implement drawer callbacks**

`frontend/src/components/FeedbackDrawer.tsx`:
- Apply: dispatch the finding to the builder (how? → chat message or direct API call?)
- Dismiss: remove finding from state
- Discuss: pull finding into main chat as a message

- [ ] **Step 3: Test findings display**

`frontend/src/__tests__/FeedbackDrawer.test.tsx`:
- Test findings render
- Test Apply button works
- Test Dismiss button works
- Test Discuss pulls finding into chat

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/FeedbackDrawer.tsx frontend/src/services/api.ts frontend/src/__tests__/FeedbackDrawer.test.tsx
git commit -m "feat(ui): findings in drawer with Apply/Dismiss/Discuss callbacks"
```

---

### Phase 11: Big-Bang Release & Flag Strategy

#### Task 11.1: Feature flags and gradual rollout

**Files:**
- Create: `src/core/flags.py`
- Modify: `src/api/routes/chat.py`, `src/api/services/chat_service.py`, `src/core/dependencies.py`

**Interfaces:**

Produces:
```python
# flags.py
class FeatureFlags:
    LANGGRAPH_ENABLED: bool  # if False, use old agent
    
def should_use_langgraph(config: AgentConfig) -> bool:
    """Check if graph is enabled for this session."""
    return FeatureFlags.LANGGRAPH_ENABLED or config.use_experimental_graph
```

- [ ] **Step 1: Create flags module**

```python
# src/core/flags.py
import os

class FeatureFlags:
    LANGGRAPH_ENABLED = os.getenv("TELLR_LANGGRAPH_ENABLED", "false").lower() == "true"
```

- [ ] **Step 2: Add flag check to chat routes**

```python
@router.post("/chat")
async def send_message(...):
    if should_use_langgraph(config):
        return await langgraph_path(...)
    else:
        return await legacy_path(...)
```

- [ ] **Step 3: Add to release notes**

Document the flag and how to enable.

- [ ] **Step 4: Commit**

```bash
git add src/core/flags.py
git commit -m "feat(flags): LANGGRAPH_ENABLED flag for gradual rollout"
```

---

#### Task 11.2: Integration and dogfood

**Files:**
- Modify: CI/CD configuration

**Interfaces:**

Produces:
```bash
# In CI, run full test suite:
pytest tests/unit -v
pytest tests/integration -k "not live" -v
# Dogfood deployment on flag-enabled branch
```

- [ ] **Step 1: Verify all tests pass**

Run full suite locally and in CI.

- [ ] **Step 2: Deploy on flag-enabled branch**

Deploy to a devloop with `LANGGRAPH_ENABLED=true`.

- [ ] **Step 3: Manual QA**

Test create_deck, edit_deck, multi-target editing, findings, export, etc.

- [ ] **Step 4: Documentation**

Write migration guide for existing users.

- [ ] **Step 5: Release**

Flip flag to default=true; release to all workspaces.

---

## Handoff & Assumptions

### What PR1 Must Provide (Critical Path)

If PR1 differs from these assumptions, Phase 1 needs adjustment:

1. **`SessionSlide` row model** with fields: `session_id`, `position` (int), `html`, `scripts`, `slide_id`, `created_by`, `created_at`, `modified_by`, `modified_at`, `verification_record` (JSON, per-row, content-hash keyed).
2. **`SlideWriter.write_slide(session_id, position, html, scripts: str, verification_record)` API** (at `src/api/services/slide_repository.py`) — idempotent, no per-slide lock. Instance methods: instantiate `SlideWriter()` before calling.
3. **`SessionSlideDeck.deck_spec_json` column** added (can be in PR1 or PR3, but must exist before Phase 1.1 completes).
4. **Row-per-slide schema migration** completed; `knit()` reads rows, not `deck_json`.

### What PR2 Must Provide (Critical Path)

If PR2 differs, Phase 1.4 needs adjustment:

1. **`langgraph==1.2.10`** resolvable (verified against Databricks pip proxy).
2. **`langgraph-checkpoint-postgres>=4.1.1` + `psycopg>=3.2.0`** both installed.
3. **`PostgresCheckpointer` importable** from `langgraph_checkpoint_postgres.postgres`.
4. **SQLAlchemy connection works via `postgresql+psycopg://` scheme** (no code change needed; just works).
5. **OBO token hook (`database.py:306`) still injects token** into psycopg3 connections.

### What Future Workstreams Can Assume (PR3 Hands Off)

- **Deck spec structure** is defined and versioned in `src/domain/deck_spec.py`. Workstreams 5+ can extend it (add fields), but cannot remove/rename existing fields.
- **Architect skill system** is in place (`src/core/skills/architect_skill.py`). Workstream 5+ adds review skills alongside it.
- **Graph state machine** persists to Lakebase. State shape is locked (`src/services/langgraph_state.py`).
- **Foreman service** is deterministic and testable. Workstream 5+ plugs findings routing into its existing edges.
- **Tone consumption hook** exists on `AgentConfig.tone_guideline` + `effective_tone` property. Workstream 8+ builds the user-facing UI/library.
- **MCP contracts** (`create_deck`, `edit_deck`) are unchanged. Workstream 5+ can extend, but not break them.
- **Streaming events** include `slide_ready` and `agent` attribution. Workstream 7+ builds observability/dashboard on these events.

### One-Shot Release Note

**"The agentification rebuild is live behind a flag.** Set `TELLR_LANGGRAPH_ENABLED=true` to opt into the new multi-agent system:

- Conversational brainstorming with the architect (no separate toggle)
- Multi-target editing: update any slides in one turn, independently
- Automatic review + fixing of objective defects before you see them
- Per-slide and deck-level findings surfaced in the new feedback drawer
- Faster iteration with incremental slide delivery

**Existing decks and sessions are adopted seamlessly.** Export, sharing, and save points work as before.

**Known limitations (coming soon):**
- Inline WYSIWYG editing (workstream 8)
- Per-agent model routing (post-PR5)
- Tone authoring UI (post-PR3)

Questions? #tellr-support"

---

## Self-Review Checklist

Spec coverage:
- [ ] Architect (conversational, tool manifest, tone hook, structured output) — Phase 2.1
- [ ] Data analyst (three outcomes, synthesis logic) — Phase 2.2
- [ ] Builder (per-slide HTML, canvas dedup) — Phase 3.1
- [ ] Build reviewer (multi-criteria, write row) — Phase 3.2
- [ ] Fixer (minimal edits) — Phase 3.3
- [ ] Fix reviewer (diff-aware chooser) — Phase 3.3
- [ ] Deck reviewer (global checks) — Phase 3.4
- [ ] Foreman (cap, dispatch, retry, timeout) — Phase 4, 8.1
- [ ] Deck spec (model, persistence, back-fill) — Phase 1.1
- [ ] Interactive build turn — Phase 5, 6.1, 6.2
- [ ] One-shot path (MCP contracts preserved) — Phase 6.2
- [ ] Multi-target editing (reference resolution) — Phase 6.1
- [ ] Incremental delivery (slide_ready, cursor) — Phase 7.1
- [ ] Agent attribution — Phase 7.2
- [ ] Error handling (retry, placeholder, timeout) — Phase 8.1
- [ ] Security gates (untrusted-data, safety gate) — Phase 8.2
- [ ] Testing (regression checklist, concurrency, export) — Phase 9
- [ ] UI (spec view toggle, context clearing, findings drawer) — Phase 10
- [ ] Feature flag (gradual rollout) — Phase 11

Placeholder scan: None — all steps have concrete code or test cases.

Type consistency: Checked across phases (e.g., `DeckSpec`, `GraphState`, `SlideWriter.write_slide` signatures; `scripts: str` throughout).

No gaps identified.

---

## Files Changed Summary

**Created:** ~18 files (skills, graph, foreman, tests, frontend components)  
**Modified:** ~12 files (schemas, routes, models, services)  
**Deleted:** 1 file (`src/services/agent.py`)  
**Total estimated LOC:** ~6,000 new, ~2,000 deleted, ~1,500 modified

---

## Risks & Mitigations

| Risk | Mitigation |
|---|---|
| Checkpointer multi-worker safety | Lakebase persists state; verified in tests before dogfood |
| Streaming latency with many events | Coalesce activity messages; test streaming performance |
| Regression on deck quality (deck spec inference) | Include existing deck tests in regression suite; eval harness validates |
| Regex retirement missing cases | RC10–RC15 checklist is exhaustive and tested |
| Feature flag complexity | Start with flag=false; enable only in devloop; flip to default=true at release |

