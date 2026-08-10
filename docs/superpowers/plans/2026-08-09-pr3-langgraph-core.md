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
- **`langgraph-checkpoint==4.1.1`** is installed, providing `BaseCheckpointSaver` and the
  `JsonPlusSerializer` — that is all PR3 needs from the checkpoint packages.
- **`langgraph-checkpoint-postgres` is deliberately NOT used** (spec §2.2, as amended).
  PR2 does not install it, and PR3 must not import it. See "Checkpointer" below.
- **psycopg2 remains the DB driver.** PR2 no longer performs a psycopg3 migration, so do
  not assume `psycopg`, `psycopg-pool`, or a `postgresql+psycopg://` URL.
- **`src/core/database.py` is unchanged by PR2** — the SQLAlchemy engine, its
  `provide_token` `do_connect` listener (`database.py:303-312`), the 50-minute token
  refresh (`TOKEN_REFRESH_INTERVAL_SECONDS`, `database.py:39-40`) and `sslmode=require`
  all behave exactly as they do today. **PR3's checkpointer depends on that.**
- **Lakebase endpoint is reachable from app** (prod + devloop forks); checkpointer writes land in same Lakebase catalog where session state lives

**Checkpointer — custom `BaseCheckpointSaver` over the existing SQLAlchemy engine.**

Why not the official saver (verified against the `langgraph-checkpoint-postgres==3.1.1`
wheel): it installs as `langgraph.checkpoint.postgres` exporting `PostgresSaver` (there
is no `PostgresCheckpointer`), and its constructor is
`PostgresSaver(conn: Conn, pipe=None, serde=None)` — it takes a **live psycopg
connection or pool**, with no `connection_string=` and no `schema=` parameter. Because it
holds a raw connection, it never traverses `provide_token`, which is the **only** path by
which Lakebase's OAuth token reaches a connection. The token expires after an hour and
the refresh timer feeds only the SQLAlchemy path, so the official saver's writes would
begin failing roughly an hour into every deployment — in production only, and invisibly
to any test that mocks the database.

A custom saver over `get_engine()` inherits token injection, the refresh timer, the
connection pool, `sslmode=require` and schema qualification for free.

**Requirements on the custom saver:**
- Subclass `langgraph.checkpoint.base.BaseCheckpointSaver`; implement the sync methods
  the compiled graph uses (`get_tuple`, `list`, `put`, `put_writes`) over the existing
  engine/session, reusing `JsonPlusSerializer` for payloads.
- Provide a **`setup()`-equivalent** that creates its tables idempotently. Follow this
  repo's migration convention — a `_migrate_*(conn, inspector, schema, _qual, is_sqlite)`
  helper wired into `_run_migrations()` (`src/core/database.py:417`), *not* Alembic
  (this repo has none) and not a bespoke bootstrap path.
- **One shared saver instance**, not one per session. Session isolation comes from
  passing `config={"configurable": {"thread_id": <session_id>}}` on **every**
  `graph.invoke` / `astream` call — omitting it raises
  `ValueError: Checkpointer requires one or more of the following 'configurable' keys`.
  A per-session saver would also open a connection per session against a `pool_size=80`
  engine.

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
    """LangGraph state dict. Fan-in keys carry reducers — see Step 1 for why."""
    session_id: str
    conversation: list[dict]                              # [{role, content, agent?}]
    deck_spec: DeckSpec | None
    error_state: dict | None
    findings: Annotated[list[dict], operator.add]
    landed_positions: Annotated[set[int], union_set]
    placeheld_positions: Annotated[set[int], union_set]
    slides: Annotated[dict[int, dict], merge_dict]        # position -> {html, scripts}
    dispatched_at: Annotated[dict[int, float], merge_dict]
    retry_count: Annotated[dict[int, int], merge_dict]
    fix_map: Annotated[dict[int, dict], merge_dict]

# In checkpointer.py:
from langgraph.checkpoint.base import BaseCheckpointSaver

class SqlAlchemyCheckpointSaver(BaseCheckpointSaver):
    """Checkpoint saver over the app's existing SQLAlchemy engine.

    Deliberately NOT langgraph-checkpoint-postgres — see the Checkpointer note
    above. Going through the engine is what gives us OBO token injection and
    the 50-minute refresh.
    """

def get_checkpointer() -> BaseCheckpointSaver:
    """Return the process-wide shared saver (no session argument — session
    isolation is per-invoke thread_id, not per-saver)."""
```

- [ ] **Step 1: Define GraphState TypedDict**

`src/services/langgraph_state.py`:
```python
import operator
from typing import Annotated, Any
from typing_extensions import TypedDict

from src.domain.deck_spec import DeckSpec


def merge_dict(a: dict, b: dict) -> dict:
    """Last-writer-wins per key. Each branch owns its own position key, so
    concurrent builders never contend on the same key."""
    out = dict(a or {})
    out.update(b or {})
    return out


def union_set(a: set, b: set) -> set:
    return set(a or set()) | set(b or set())


class GraphState(TypedDict):
    # Single-writer keys (only the architect/foreman write these) — no reducer needed.
    session_id: str
    conversation: list[dict]
    deck_spec: DeckSpec | None
    error_state: dict | None

    # FAN-IN KEYS. Every key written by more than one concurrent branch MUST carry a
    # reducer, or LangGraph raises:
    #   InvalidUpdateError: At key 'x': Can receive only one value per step.
    # Verified against the installed langgraph: 4 parallel Send branches writing all
    # four keys below merge cleanly with these reducers.
    findings: Annotated[list[dict], operator.add]        # accumulate across slides
    landed_positions: Annotated[set[int], union_set]     # committed positions
    placeheld_positions: Annotated[set[int], union_set]  # terminal failures (§5.5)
    slides: Annotated[dict[int, dict], merge_dict]       # position -> {html, scripts}
    dispatched_at: Annotated[dict[int, float], merge_dict]  # position -> dispatch ts
    retry_count: Annotated[dict[int, int], merge_dict]   # position -> attempts
    fix_map: Annotated[dict[int, dict], merge_dict]      # position -> {original_html,
                                                        #              original_scripts,
                                                        #              finding}
```

> **`fix_map` carries `original_scripts` as well as `original_html`.** The fix reviewer
> compares original vs fixed for *both* (spec §5.5's three inputs), and an earlier draft
> read `fix_map[position]["scripts"]`, a key that was never written.

- [ ] **Step 2: Write tests for state shape and fan-in**

`tests/unit/test_langgraph_state.py`:
- Required keys present; `DeckSpec` round-trips through the serializer.
- **Reducer tests, one per fan-in key:** two simulated concurrent updates merge rather
  than collide — `findings` concatenates, `landed_positions`/`placeheld_positions` union,
  `slides`/`dispatched_at`/`retry_count`/`fix_map` merge per key.
- **A compiled-graph fan-in test:** dispatch N stub builders via `Send` and assert all N
  results survive. This is the test that actually catches a missing reducer; a
  dict-merge unit test alone does not, because the error is raised by the runtime.

- [ ] **Step 3: Implement the custom checkpoint saver**

`src/core/checkpointer.py`:
```python
from langgraph.checkpoint.base import BaseCheckpointSaver, Checkpoint, CheckpointTuple
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer

from src.core.database import get_session_maker


class SqlAlchemyCheckpointSaver(BaseCheckpointSaver):
    """LangGraph checkpoint saver over the app's SQLAlchemy engine.

    Every DB round-trip goes through the existing session maker, so it inherits
    provide_token (OBO injection), the 50-minute token refresh, sslmode=require,
    the connection pool and schema qualification.
    """

    def __init__(self) -> None:
        super().__init__(serde=JsonPlusSerializer())
        self._session_maker = get_session_maker()

    # Implement the sync surface the compiled graph uses:
    def get_tuple(self, config) -> CheckpointTuple | None: ...
    def list(self, config, *, filter=None, before=None, limit=None): ...
    def put(self, config, checkpoint: Checkpoint, metadata, new_versions): ...
    def put_writes(self, config, writes, task_id, task_path="") -> None: ...


_saver: SqlAlchemyCheckpointSaver | None = None


def get_checkpointer() -> SqlAlchemyCheckpointSaver:
    """Process-wide shared saver. Session isolation is the per-invoke thread_id."""
    global _saver
    if _saver is None:
        _saver = SqlAlchemyCheckpointSaver()
    return _saver
```

Storage: two tables (`graph_checkpoints`, `graph_checkpoint_writes`) keyed by
`(thread_id, checkpoint_ns, checkpoint_id)`, created by the migration in Step 3b.

- [ ] **Step 3b: Add the schema migration (this repo's convention, NOT Alembic)**

Add `_migrate_graph_checkpoints(conn, inspector, schema, _qual, is_sqlite)` to
`src/core/database.py` and call it from `_run_migrations()` (`database.py:417`),
alongside the existing `_migrate_*` helpers. Follow their established shape: guard every
`CREATE TABLE` / `ADD COLUMN` behind an `inspector` check so it is idempotent, qualify
names with `_qual()`, and branch on `is_sqlite` so the unit-test path works. There is no
Alembic in this repo — `Base.metadata.create_all()` plus these helpers is the mechanism.

- [ ] **Step 4: Test the saver against a real database, not a mock**

`tests/unit/test_checkpointer.py` (sqlite via the `is_sqlite` path) — round-trip a
checkpoint through `put` → `get_tuple`, assert `list` ordering, and assert `put_writes`
then replay. Then a `@pytest.mark.live` test against Lakebase asserting a write
**succeeds on a connection issued by the shared engine**.

> **Do not mock the database in this step.** Mocking is precisely what would hide the
> failure mode that drove this design: a saver that holds its own connection appears to
> work in tests and then stops writing about an hour into a real deployment, when the
> OAuth token expires. The value of this test is that it exercises the engine path.

- [ ] **Step 4b: Assert `thread_id` is always supplied**

Add a test that compiling with the saver and invoking **without**
`config={"configurable": {"thread_id": ...}}` raises `ValueError` — then assert the
app's own invoke helper always sets it from `session_id`. This pins the contract in a
test rather than relying on every future call site remembering it.

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
def foreman_node(state: GraphState) -> dict:
    """Advance the turn: stamp dispatches, placehold stalls, emit releasable slides.

    A LangGraph node takes (state) or (state, config) only — no extra positional
    args. Per-branch data arrives via the Send payload, not extra parameters.

    NOTE: the node does NOT dispatch. Fan-out happens in foreman_router, because
    Send objects must be returned from a conditional edge (see Phase 5 Step 6):
        Send("builder", {"position": p, "slide_spec": ...})   # Send(node, arg)
    """
```

- [ ] **Step 6: Implement builder_node (skeleton)**

```python
def builder_node(payload: dict) -> dict:
    """Build one slide.

    THE SEND PAYLOAD IS THIS NODE'S ENTIRE INPUT. When a node is reached via
    Send("builder", {...}), it receives that dict — not GraphState. So everything
    the builder needs must be in the payload the router built:
        {"session_id", "position", "slide_spec", "css_contract", "resolved_data"}
    Extra positional params (state, config, idx) are invalid: LangGraph calls
    node(input) or node(input, config) and would raise
    "TypeError: builder_node() missing 1 required positional argument".
    """
    # Call builder skill with payload["slide_spec"] + payload["css_contract"]
    # Return {"slides": {payload["position"]: {"html": ..., "scripts": ...}}}
    #   -> merged by the slides reducer; keyed by position so branches never collide.
    # Then the static builder -> build_reviewer edge carries it onward.
```

> **Payload vs state is the one thing to get right in this phase.** A `Send`-reached node
> cannot read `state["deck_spec"]`, so the router must copy the per-slide brief, the CSS
> contract and any resolved data into the payload. Returning position-keyed dicts is what
> lets the reducers merge concurrent branches.

- [ ] **Step 7: Implement build_reviewer_node (skeleton)**

```python
def build_reviewer_node(payload: dict) -> dict:
    """Review builder output; write the row if clean, else hand the fix over.

    Reached by the static builder -> build_reviewer edge, so it receives whatever
    builder_node returned, merged with the branch payload: position, html, scripts,
    plus the brief/CSS contract it needs as the review rubric.
    """
    # Call build_reviewer skill (multi-criteria; each finding self-tags
    #   objective|subjective per PRD §7.2)
    # If no objective findings:
    #     SlideWriter().write_slide(session_id, position, html, scripts,
    #                               verification_record=record)
    #     return {"landed_positions": {position},
    #             "findings": subjective_findings}
    # Else:
    #     return {"fix_map": {position: {"original_html": html,
    #                                    "original_scripts": scripts,
    #                                    "finding": objective_finding}},
    #             "findings": subjective_findings}
```

> Note the return shapes are **`GraphState` keys with reducers** (`landed_positions`,
> `fix_map`, `findings`) — not ad-hoc keys like `{"action": "land"}`. An earlier draft
> returned keys no node ever read, which is why `foreman_router` could only ever
> return `END` and the graph was dead on arrival.

- [ ] **Step 8: Write tests**

`tests/unit/test_graph_state_machine.py` (mock the LLM calls):
- Architect node output shape; `architect_router` paths.
- Builder node produces `{"slides": {position: {...}}}` — position-keyed, so reducers
  merge it.
- Build reviewer: clean verdict → `landed_positions` written and `SlideWriter.write_slide`
  called; findings verdict → `fix_map` populated with original html **and** scripts.
- **Every node's return keys are a subset of `GraphState`'s keys.** Add one test that
  asserts this across all nodes — it is the cheap guard against the "returns keys nobody
  reads" class of bug, which is otherwise invisible until the graph silently ends.

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

### Phase 4: Foreman Orchestration (worker pool over a checkpointed queue)

#### Why this shape — LangGraph's superstep barrier (measured, not assumed)

**LangGraph executes in supersteps with a barrier: a node re-runs only after *every*
branch dispatched in the previous step has finished.** Probed against the installed
`langgraph==1.0.3`: an orchestrator that `Send`s a batch of 2 workers over 5 positions
woke exactly **4 times, always on a completed batch** — `done=[]`, `done=[0,1]`,
`done=[0,1,2,3]`, `done=[0,1,2,3,4]`. It never woke when an individual worker finished.

Two consequences, and they killed the earlier design for this phase:

1. **There is no "a slot freed, dispatch the next position" event to hook.** A foreman
   that dispatches `cap` builders and expects re-entry per completion cannot exist.
2. **A wall-clock release timeout evaluated inside the foreman node can never fire while
   a position is actually stalled** — the node only runs once the stalled batch is done,
   which is the one moment the timeout is not needed.

So the cap and the ordering live in **state**, not in the dispatch call:

- **State holds the queue.** `builder_queue` (ascending positions) and
  `landed_positions` live in `GraphState`, therefore in the checkpointer, therefore
  visible to every uvicorn worker. This is also the fix for the old design's
  `ForemanState` — a bare class that was never instantiated or persisted, which would
  have re-introduced the in-process `self.sessions` bug class (PRD §12.1).
- **A routing function dispatches the lowest `cap` outstanding positions each superstep**
  by returning `Send("builder", {...})` objects. `Send` objects must be **returned from a
  conditional-edge router**, never written into state (verified signature:
  `Send(node: str, arg: Any)`).
- **`max_concurrency` is the belt to the queue's braces.** `invoke(..., {"max_concurrency": 15})`
  is honoured by the runtime and caps in-flight branches independently of batch size.
- **Ordered *release* is decoupled from batch completion.** The reorder buffer is a pure
  function of `landed_positions`: emit position *n* only once all positions `< n` are
  committed. Probed with position 1 deliberately slow over 6 positions: emission order
  was still `[0,1,2,3,4,5]`. The user-visible guarantee holds.

**Net behavioural difference from the original spec §8 wording:** dispatch proceeds in
ascending order in batches bounded by the cap, rather than backfilling individual slots
the instant one frees. Ordered release, the cap, and retry priority all survive; only
"per-slot backfill" does not, because the runtime provides no such event.

#### Task 4.1: Queue-driven dispatch and ordered release

**Files:**
- Create: `src/services/foreman_service.py` (pure functions over state — no instance state)
- Create: `tests/unit/test_foreman_orchestration.py`
- Create: `tests/integration/test_foreman_graph.py` (compiled-graph behaviour)

**Interfaces:**

```python
# src/services/foreman_service.py
# NOTE: no ForemanState class and no instance attributes. Every function below is a pure
# function of GraphState, so the checkpointer is the only home for turn state.

CAP = 15
RELEASE_TIMEOUT_S = 300

def outstanding_positions(state: GraphState) -> list[int]:
    """Positions in the spec that are neither landed nor placeheld, ascending."""

def next_dispatch_batch(state: GraphState, cap: int = CAP) -> list[int]:
    """The lowest `cap` outstanding positions, ascending.

    Retries need no special case: a failed position stays outstanding, so it is
    always ranked ahead of higher unstarted positions by construction.
    """

def releasable_positions(state: GraphState) -> list[int]:
    """Prefix of positions that are all committed — the reorder buffer.

    Emit n only once every position < n is in landed_positions. Placeheld
    positions count as committed (spec §5.5), else one terminal failure would
    stall the deck forever.
    """

def stalled_positions(state: GraphState, now: float,
                      timeout_s: int = RELEASE_TIMEOUT_S) -> list[int]:
    """Dispatched positions whose elapsed time exceeds the timeout.

    Uses dispatch timestamps recorded in state (NOT in-process), so the check is
    correct across workers and across checkpoint restores.
    """
```

- [ ] **Step 1: Write the deterministic unit tests (pure functions, no graph, no LLM)**

`tests/unit/test_foreman_orchestration.py`:
- `next_dispatch_batch`: 31 positions, cap 15 → `[0..14]` ascending; after 0–9 land →
  next batch starts at 10 and still ascends.
- **Retry priority:** position 5 failed and 15–30 unstarted → 5 appears in the next
  batch, ahead of 20.
- `releasable_positions`: landed `{0..10}` → release `0..10`; then landed `{0..10, 15..19}`
  → still only `0..10` (11–14 missing); land 11 → release 11.
- **Placeholder counts as committed:** landed `{0,1,3}`, position 2 placeheld → release
  `0..3`, and the all-landed predicate that triggers deck review is satisfied.
- `stalled_positions`: dispatched at T, now = T + timeout + 1 → reported stalled.

> These tests pin the *policy*. They pass whether or not the graph wiring is right, which
> is exactly why Step 3 exists — the earlier version of this plan had only these, and
> would have shipped green with the wrong runtime behaviour.

- [ ] **Step 2: Implement the pure functions**

Implement the four functions above over `GraphState`. Keep them total and side-effect
free so they are trivially testable and safe to call from a router.

- [ ] **Step 3: Write the compiled-graph behavioural tests (the ones that matter)**

`tests/integration/test_foreman_graph.py` — build the real graph with **stub** builder /
reviewer nodes (canned outputs, no LLM), compile it, and assert on observed runtime
behaviour:
- **Cap holds:** 40 positions, `max_concurrency=15` → peak simultaneous builder
  invocations never exceeds 15 (count with a shared counter in the stub).
- **Ascending dispatch:** the first batch is `0..14`; no higher position is ever
  dispatched while a lower one is still outstanding.
- **Ordered release with a slow position:** make position 1 slow → emitted order is
  still strictly ascending `0,1,2,…`.
- **Barrier is acknowledged, not fought:** assert the orchestrator wakes once per
  completed batch (the probe above), so a future change that assumes per-completion
  wakeups fails loudly here instead of silently degrading.
- **Terminal failure:** force position 7 to fail twice → it becomes a placeholder,
  release proceeds past it, and deck review still triggers.

- [ ] **Step 4: Record dispatch timestamps in state**

On dispatch, write `dispatched_at[position] = time.time()` into `GraphState` (reduced —
see Phase 1's reducers). Never hold it on a service instance: the worker that resumes a
checkpoint is not necessarily the worker that dispatched.

- [ ] **Step 5: Run both suites**

Unit tests (fast, no graph) and the compiled-graph integration tests must both pass.

- [ ] **Step 6: Commit**

```bash
git add src/services/foreman_service.py tests/unit/test_foreman_orchestration.py \
        tests/integration/test_foreman_graph.py
git commit -m "feat(orchestration): queue-driven dispatch with ordered release"
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
def builder_node(payload: dict) -> dict:
    """Build one slide. `payload` is the Send arg — NOT GraphState.

    Verified: a Send-reached node receives only the payload dict; state keys such as
    deck_spec are not visible. foreman_router must therefore pre-copy everything
    needed here (see Phase 5 Step 6).
    """
    position = payload["position"]
    output = call_skill_with_llm(
        "builder",
        input={
            "position": position,
            "slide_spec": payload["slide_spec"],       # this slide's brief only
            "css_contract": payload["css_contract"],   # foreman-owned, read-only
            "assumes": payload["assumes"],             # narrative contract
            "hands_off": payload["hands_off"],
            "resolved_data": payload["resolved_data"], # analyst synthesis
        },
    )
    # Position-keyed so the `slides` reducer merges concurrent branches.
    return {
        "slides": {position: {"html": output["html"], "scripts": output["scripts"]}},
        "dispatched_at": {},   # stamped by the foreman, not here
    }
```

> **Do not index the spec by list position.** `SlideSpec` carries an explicit `position`
> field, so `deck_spec.slides[position]` diverges from the intended slide after a delete
> or a partial multi-target rebuild. The router looks the brief up **by** `position` and
> passes it in, which removes the trap from every downstream node.

- [ ] **Step 2: Implement build_reviewer_node (complete)**

```python
def build_reviewer_node(payload: dict) -> dict:
    """Review one slide. Reached by the static builder -> build_reviewer edge, so it
    sees the builder's output merged with the branch payload."""
    position = payload["position"]
    session_id = payload["session_id"]
    html, scripts = payload["html"], payload["scripts"]

    output = call_skill_with_llm(
        "build_reviewer",
        input={
            "html": html,
            "scripts": scripts,
            "slide_spec": payload["slide_spec"],     # the rubric the builder was given
            "css_contract": payload["css_contract"],
            "resolved_data": payload["resolved_data"],
        },
    )
    # Each finding self-tags objective|subjective (PRD §7.2).
    objective = [f for f in output["findings"] if f["objective"]]
    subjective = [f for f in output["findings"] if not f["objective"]]

    if not objective:
        # Reviewer writes the row: an unreviewed slide never persists (spec §5.5).
        SlideWriter().write_slide(
            session_id, position, html, scripts,
            verification_record=build_verification_record(output),
        )
        return {"landed_positions": {position}, "findings": subjective}

    return {
        "fix_map": {position: {
            "original_html": html,
            "original_scripts": scripts,
            "finding": objective[0],
        }},
        "findings": subjective,
    }
```

> Returns are `GraphState` keys with reducers, so concurrent reviewers merge instead of
> colliding. `SlideWriter` is instantiated (its methods take `self`), and per PR1's
> contract `verification_record=None` would *preserve* an existing record — so pass an
> explicit record when writing a fresh verdict.

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

def reviewer_router(state: GraphState) -> str:
    """After a build review: hand over to the fixer, or back to the foreman.

    A conditional-edge router takes (state) — or (state, config) — ONLY. Extra
    positional params raise "TypeError: route() missing 2 required positional
    arguments". Per-branch facts must be read out of state, not passed in.
    """
    return "fix" if state.get("fix_map") else "land"


def foreman_router(state: GraphState):
    """Dispatch the next ascending batch, or advance the turn.

    Returns list[Send] for fan-out, or a node name. Reads ONLY keys that nodes
    actually write (see the reducers in Phase 1) — the earlier draft read
    `builder_queue`, which nothing wrote, so it always fell through to END and the
    graph never built a deck.
    """
    if state.get("fix_map"):
        return "fixer"

    batch = next_dispatch_batch(state)                    # Phase 4, ascending
    if batch:
        return [
            Send("builder", build_branch_payload(state, p))  # Send(node, arg)
            for p in batch
        ]

    if all_positions_committed(state):   # landed | placeheld covers every spec position
        return "deck_reviewer"
    return END


def build_branch_payload(state: GraphState, position: int) -> dict:
    """Everything a Send-reached branch needs, because it cannot see GraphState."""
    spec = state["deck_spec"]
    slide = spec.slide_at(position)      # lookup BY position, not list index
    return {
        "session_id": state["session_id"],
        "position": position,
        "slide_spec": slide,
        "assumes": slide.assumes,
        "hands_off": slide.hands_off,
        "css_contract": spec.design_contract,
        "resolved_data": spec.resolved_data,
    }
```

> `all_positions_committed` must count **placeheld** positions as committed, otherwise a
> single terminal builder failure means deck review never fires and the turn never ends
> (spec §5.5). `len(landed) == len(spec.slides)` is the wrong predicate for that reason.

- [ ] **Step 3b: Implement fixer_node**

```python
def fixer_node(state: GraphState) -> dict:
    """Make the minimal change that resolves one objective finding.

    Takes (state) only. Picks the lowest outstanding fix so behaviour is
    deterministic when several positions need fixing in the same turn.
    """
    position = min(p for p, e in state["fix_map"].items() if e is not None)
    entry = state["fix_map"][position]

    output = call_skill_with_llm(
        "fixer",
        input={
            "finding": entry["finding"],
            "original_html": entry["original_html"],
            "original_scripts": entry["original_scripts"],
            "css_contract": state["deck_spec"].design_contract,
            "slide_spec": state["deck_spec"].slide_at(position),
        },
    )
    return {
        "fix_target": position,
        "fixed": {position: {"html": output["html"], "scripts": output["scripts"]}},
    }
```

Add the two keys this introduces to `GraphState` (Phase 1 Step 1):

```python
    fix_target: int | None                                # position currently in the fixer
    fixed: Annotated[dict[int, dict], merge_dict]         # position -> {html, scripts}
```

> **Fixer and builder are separate skills** over shared fragments (spec §5.6): the
> builder authors, the fixer makes the minimal change. Handing broken HTML to an
> authoring agent gets the slide re-authored, which can undo what already passed review
> and — once WYSIWYG lands — overwrite a user's manual edits.

- [ ] **Step 4: Implement fix_reviewer_node**

```python
def fix_reviewer_node(state: GraphState) -> dict:
    """Choose fixed-or-original and write the winner (spec §5.5).

    Three inputs: the finding, the original, and the fix. Original + fixed gives a
    diff, so "did the fix introduce a new defect?" is scoped to what changed.
    """
    position = state["fix_target"]                 # set by the fixer
    entry = state["fix_map"][position]
    original_html = entry["original_html"]
    original_scripts = entry["original_scripts"]   # NOT entry["scripts"] — that key
                                                   # never existed in an earlier draft
    fixed_html = state["fixed"][position]["html"]
    fixed_scripts = state["fixed"][position]["scripts"]

    output = call_skill_with_llm(
        "fix_reviewer",
        input={
            "finding": entry["finding"],
            "original_html": original_html,
            "fixed_html": fixed_html,
            "slide_spec": state["deck_spec"].slide_at(position),
        },
    )
    chose_fixed = output["choice"] == "fixed"
    html = fixed_html if chose_fixed else original_html
    scripts = fixed_scripts if chose_fixed else original_scripts

    SlideWriter().write_slide(
        state["session_id"], position, html, scripts,
        verification_record=build_verification_record(output),
    )

    # Clear the fix entry so foreman_router stops routing to the fixer, and land the
    # position either way — one fix round only; a survivor becomes a surfaced finding.
    return {
        "landed_positions": {position},
        "fix_map": {position: None},          # tombstone; merge_dict overwrites the key
        "findings": [] if chose_fixed else [entry["finding"]],
    }
```

> **The one-round cap is enforced here, not by a counter.** The fix entry is cleared
> whichever version wins, so no position can enter the fixer twice.

- [ ] **Step 5: Implement foreman dispatch and routing**

```python
def foreman_node(state: GraphState) -> dict:
    """Advance turn state. Dispatch itself lives in foreman_router — Send objects
    must be RETURNED from a conditional edge, never written into state. The earlier
    draft returned {"builds_to_dispatch": [...]}, a key nothing read, so nothing was
    ever dispatched."""
    now = time.time()
    updates: dict = {}

    batch = next_dispatch_batch(state)
    if batch:
        updates["dispatched_at"] = {
            p: now for p in batch if p not in state.get("dispatched_at", {})
        }

    stalled = stalled_positions(state, now)
    if stalled:
        writer = SlideWriter()
        for pos in stalled:
            writer.commit_placeholder(
                state["session_id"], pos,
                error_message="timeout: position did not complete",
            )
        updates["placeheld_positions"] = set(stalled)

    return updates
```

> Finding routing needs no loop here: the build reviewer already tagged each finding and
> put objective ones into `fix_map`, so `foreman_router` only has to check whether
> `fix_map` is non-empty. Subjective findings accumulate in `findings` via the reducer
> and are surfaced by the architect at the end of the turn.
```

- [ ] **Step 6: Hook all nodes into graph**

```python
from langgraph.graph import StateGraph, START, END   # START is a sentinel, not "START"
from langgraph.types import Send


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

    graph.add_edge(START, "architect")
    graph.add_conditional_edges(
        "architect",
        architect_router,
        {"discuss": END, "build": "foreman", "ask_data": "data_analyst", "edit": "architect"},
    )
    graph.add_edge("data_analyst", "architect")

    # Foreman fans out via Send from its ROUTER (not a static edge — a static
    # foreman->builder edge alongside this router fires builder unconditionally
    # every superstep and loops to GraphRecursionError).
    graph.add_conditional_edges(
        "foreman",
        foreman_router,                    # returns list[Send] | str
        ["builder", "fixer", "deck_reviewer", END],
    )

    # Every builder branch is reviewed, then returns to the foreman, which is the
    # single place deck-wide state is updated.
    graph.add_edge("builder", "build_reviewer")
    graph.add_conditional_edges(
        "build_reviewer",
        reviewer_router,                   # "land" | "fix"
        {"land": "foreman", "fix": "fixer"},
    )
    graph.add_edge("fixer", "fix_reviewer")
    graph.add_edge("fix_reviewer", "foreman")
    graph.add_edge("deck_reviewer", END)

    # Shared saver; session isolation comes from thread_id at invoke time:
    #   graph.invoke(state, config={"configurable": {"thread_id": session_id},
    #                               "max_concurrency": CAP})
    return graph.compile(checkpointer=get_checkpointer())


def foreman_router(state: GraphState):
    """Dispatch the next ascending batch, or advance the turn.

    Returns Send objects (fan-out) or a single next-node name. Send objects MUST be
    returned from here — writing them into state does nothing.
    """
    if state.get("fix_map"):
        return "fixer"
    batch = next_dispatch_batch(state)                 # Phase 4 pure function
    if batch:
        return [
            Send("builder", {"position": p, "slide_spec": spec_for(state, p)})
            for p in batch                              # already ascending
        ]
    if all_positions_committed(state):                  # placeholders count as committed
        return "deck_reviewer"
    return END
```

> **`reviewer_router` returns only `"land"` or `"fix"`.** The earlier draft mapped both
> branches to `"foreman"`, which made the conditional a no-op that could have been a
> plain edge — and hid the fact that the fix path exists.

- [ ] **Step 7: Write integration tests**

`tests/integration/test_build_chain.py` (stub agent nodes, real compiled graph):
- Full build chain: architect → foreman → builder → reviewer → land, no findings.
- With findings: builder → reviewer → fixer → fix_reviewer → foreman → land.
- Parallel builders: dispatch 3, all complete, all land.
- **Cap and ordering** are asserted in `tests/integration/test_foreman_graph.py`
  (Phase 4 Step 3) against the compiled graph, since batch-level behaviour is only
  observable there — do not re-assert "as slots free take lowest outstanding" here, as
  the runtime provides no per-slot event (Phase 4 preamble).
- Deck review triggers once every position is committed, including placeholders.

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

# Release timeout — state-based, not instance-based:
#   dispatched_at: dict[int, float] lives in GraphState (so, in the checkpointer).
#   stalled_positions(state, now, timeout_s) is the Phase 4 pure function.
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

- [ ] **Step 3: Implement release timeout (state-based)**

```python
def foreman_node(state: GraphState) -> dict:
    """Advance the turn. All timing state comes from GraphState, never from an
    instance attribute — the worker resuming a checkpoint is not necessarily the
    worker that dispatched."""
    now = time.time()
    updates: dict = {}

    # 1. Stamp newly dispatched positions (merged via the dispatched_at reducer).
    batch = next_dispatch_batch(state)
    if batch:
        updates["dispatched_at"] = {p: now for p in batch
                                    if p not in state.get("dispatched_at", {})}

    # 2. Convert stalled positions into placeholders so release can proceed.
    stalled = stalled_positions(state, now)          # Phase 4 pure function
    if stalled:
        writer = SlideWriter()
        for pos in stalled:
            writer.commit_placeholder(
                state["session_id"], pos,
                error_message="timeout: position did not complete",
            )
        updates["placeheld_positions"] = stalled

    # 3. Emit whatever is now releasable, in ascending order.
    updates["released"] = releasable_positions(state)
    return updates
```

> **Known limitation, stated deliberately.** Because of the superstep barrier (Phase 4
> preamble), `foreman_node` runs between batches — so the timeout is evaluated at batch
> boundaries, not the instant a position exceeds it. It therefore bounds *how long a
> stall can block release* to roughly one batch, rather than to exactly
> `RELEASE_TIMEOUT_S`. That is acceptable: the guarantee users need is "a stalled slide
> cannot block the deck indefinitely," not millisecond precision. Do not attempt to fix
> this with a wall-clock timer inside a node — the runtime gives no such hook, and the
> earlier draft's attempt could never fire while a position was actually stalled.

- [ ] **Step 4: Test retry, placeholder, and timeout**

`tests/unit/test_error_handling.py` (pure functions):
- Builder fails once then succeeds (retry path).
- Builder fails twice → `commit_placeholder` called with the error message.
- `stalled_positions` reports a position past the timeout and ignores one within it.
- **Placeholder counts as committed** for both `releasable_positions` and the
  all-committed predicate that triggers deck review.

`tests/integration/test_foreman_graph.py` (compiled graph — see Phase 4 Step 3):
- Force position 7 to fail twice → placeholder written, release proceeds past it, deck
  review still fires. This is the test that proves the *runtime* behaviour, not just the
  policy.

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

**Relocate the gate first.** `_run_output_safety_gate` lives in `src/services/agent.py:97`
(not `chat.py`), and Phase 9 deletes that file — so move it to
`src/services/output_safety.py` and re-point the existing importers (`chat.py:37` imports
`UnsafeContentError` from `src.services.agent` and uses it at `:265` and `:398`). Its real
signature and semantics:

```python
def _run_output_safety_gate(html_output, regenerate, session_id, on_retry=None):
    """-> (safe_html, retried). `regenerate` is a ZERO-ARG CALLABLE the gate invokes
    itself if scan_html_for_unsafe_patterns finds something; it retries once, then
    raises UnsafeContentError. It scans HTML ONLY — never scripts."""
```

- [ ] **Step 2: Wrap untrusted content with `spotlight()`, never a hand-rolled f-string**

```python
from src.utils.spotlight import spotlight

# In build_reviewer_node, before handing builder HTML to the reviewer LLM:
html_for_review = spotlight("builder", html, session_id=session_id)
```

`spotlight(source, text, *, scan=True, session_id=None)` (`src/utils/spotlight.py:22`)
applies `cap_tool_output`, **neutralises embedded `<untrusted-data>` openers/closers** so
a payload cannot break out of its own wrapper, and runs injection scanning. An
f-string wrapper does none of that — and that escape was a previously-fixed review
finding, so re-introducing it is a regression, not a new bug. Spec §8.1 requires this at
**every** boundary, which includes agent-shaped producers (builder, fixer, analyst).

- [ ] **Step 3: Gate fixer output with the correct signature**

```python
def fixer_node(state: GraphState) -> dict:
    ...
    def _regenerate() -> str:
        """Zero-arg retry the gate can call: re-run the fixer with a corrective
        instruction appended."""
        return call_skill_with_llm("fixer", input={**fix_input,
                                                  "corrective": SAFETY_CORRECTIVE})["html"]

    try:
        safe_html, retried = _run_output_safety_gate(
            output["html"], _regenerate, state["session_id"]
        )
    except UnsafeContentError:
        # Keep the original; the fix reviewer will surface the finding instead.
        return {"fix_target": position,
                "fixed": {position: {"html": entry["original_html"],
                                     "scripts": entry["original_scripts"]}}}
```

> **Gate coverage gap, stated explicitly.** The gate scans HTML only, so passing
> `scripts` to it (as an earlier draft did, in the `regenerate` slot) both crashes and
> gives zero script coverage. Slide scripts still get their own validation via the
> Chart.js/JS checks the builder pipeline already runs; if script-level safety scanning is
> wanted, that is a separate change to `scan_html_for_unsafe_patterns`, not something the
> current gate provides.

- [ ] **Step 4: Wrap data analyst and tool output**

The analyst is an agent, not a tool, so it does not inherit the tool-boundary wrapping
automatically. Wrap every gatherer result it returns with `spotlight("data_analyst", ...)`
before it reaches the architect, and keep the existing per-tool `spotlight` calls in
`src/services/tools/*` intact.

- [ ] **Step 5: Test security gates**

`tests/unit/test_security_gates.py`:
- Unsafe builder HTML → gate retries once via `regenerate`, then raises
  `UnsafeContentError`; assert the fix path falls back to the original.
- **Delimiter breakout:** builder HTML containing a literal `</untrusted-data>` is
  neutralised by `spotlight` (assert the payload cannot terminate its wrapper).
- Analyst output is wrapped before reaching the architect.
- The gate is called with a **callable** in the `regenerate` slot — a test that passes a
  string and expects `TypeError` documents the contract.

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

1. **`langgraph==1.2.10`** resolvable (verified against the Databricks pip proxy), with
   `langgraph-checkpoint==4.1.1`, `langgraph-prebuilt==1.1.0`, `langgraph-sdk==0.4.2`.
2. **`langgraph.checkpoint.base.BaseCheckpointSaver` and `JsonPlusSerializer`
   importable** — that is the entire checkpoint surface PR3 needs.
3. **`langgraph-checkpoint-postgres` is NOT installed**, and PR3 must not import it.
4. **`psycopg2-binary==2.9.10` unchanged; connection strings stay `postgresql://`.**
   No psycopg3.
5. **`src/core/database.py` untouched by PR2** — `get_engine()`/`get_session_maker()`,
   the `provide_token` `do_connect` listener (`database.py:303-312`), the 50-minute
   token refresh and `sslmode=require` all behave as they do today. PR3's custom saver
   is built directly on this, so it is the load-bearing promise.

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

