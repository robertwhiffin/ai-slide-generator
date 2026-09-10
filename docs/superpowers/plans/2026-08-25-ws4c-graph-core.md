# ws4c — The graph core and the seven skills

> **For agentic workers:** REQUIRED SUB-SKILLS: `superpowers:subagent-driven-development` **plus**
> `executing-plans-tellr`. **Read `2026-08-25-ws4-index.md` first** — this plan inherits its Global
> Conventions (environment, the cause-based baseline gate, rulings R1/R2, the verified runtime facts,
> execution requirements) and does not repeat them.

**Goal:** A compiled LangGraph that builds a deck end to end — under stub agents in CI, and against a
real model locally — plus the seven skills, `agent_factory`'s relocation, deterministic template-section
extraction, and the two shipped security controls re-homed onto the graph path.

**Why this is its own PR:** it is the only part of workstream 4 where the *topology* is the deliverable.
Everything it touches is **new** code — under `src/services/graph/` and `src/core/skills/`, plus four new
modules that sit outside both: `src/services/foreman_service.py` (C2), `src/services/agent_resolution.py`
(C3), `src/services/template_sections.py` (C6) and `src/utils/graph_safety.py` (C7). The only existing
files it modifies are `agent_factory.py` (a move that preserves every name, **private ones included** —
C8) and the test files that pin what moved. Nothing here is reachable from chat — that is ws4d.

**Depends on:** ws4b's frozen contracts. **Blocks:** ws4d, ws4e.

**The rule inherited from ws4b, restated because breaking it caused three blocking findings:**
**if this PR wants a schema field that does not exist, that is an escalation back to ws4b — never a
local edit.** In particular, `ArchitectOutput` and `AnalystOutput` are closed: do not read a field off
them that ws4b did not declare, and never take brand bytes from model output.

**Spec:** §5.1–§5.7, §6.1–§6.3, §8, §I, §A1, §A2, §D4, §L5, §L6, §L7, §M3–§M6, §G1–§G3.

---

## The runtime facts this phase is built on

All re-executed on langgraph 1.2.10. **Do not re-derive them; do re-probe if you doubt one.**

| Fact | Measurement | Consequence |
|---|---|---|
| **Superstep barrier** | An orchestrator sending batches of 2 over 5 positions woke exactly 4 times: `[]`, `[0,1]`, `[0,1,2,3]`, `[0,1,2,3,4]` — never per worker | There is **no "a slot freed, dispatch the next" event to hook.** The cap and the ordering live in **state**, not in the dispatch call |
| **A `Send`-reached node sees ONLY its payload** | The node saw `['batch','position']`; no state key was visible | The router must **pre-copy** everything the branch needs. `deck_spec` is invisible inside a builder |
| **A static edge out of a `Send`-reached node collapses N into ONE** | 3 builders → **1** invocation, input keys were plain state with no payload | `builder → build_reviewer` **must** be a conditional edge that re-fans |
| **Re-fanning with a conditional edge** | 6 builders → **6** reviewers, each with its own payload | The fix for the above |
| **A router out of a `Send`-reached node sees PLAIN STATE, once per branch** | The re-fan router was invoked **6 times** for 6 builders; every invocation's input keys were the declared state keys with **no payload key** (`state["position"]` → `KeyError`), and each saw only its own branch's write — `slides` keys `[0]`, `[1]`, `[2]`, `[3]`, `[4]`, `[5]`, never the merged `[0..5]` | The re-fan router rebuilds each reviewer's payload from `slides[position]`, and that works **because** of the per-branch view. A router must never read a payload key off state |
| **`bool({0: None})` is `True`** | | A dict reducer cannot delete a key; a tombstone still reads as pending |
| **Turn-2 state accumulates** | turn 2 passing a fresh empty set still saw turn 1's values; a fresh `checkpoint_ns` does not reset it either | Turn-scoping is required, not a nicety |
| **Undeclared keys are silently dropped** | a node returning an undeclared key produces no error and the write is discarded; an undeclared *input* key never reaches the node | **`GraphState` is an exhaustive contract.** This caused three separate blocking findings |
| **ContextVars survive the thread boundary AND the fan-out** | A var set before `graph.invoke()` was read by **all 6** `Send`-fanned nodes, through a `threading.Thread(target=ctx.run)`; a node-local `.set()` did **not** leak back to the parent or sideways to a sibling. Cause: LangChain fans out through `ContextThreadPoolExecutor`, whose `submit` wraps every task in `copy_context().run(...)` (`langchain_core/runnables/config.py:607-628`) | This is what makes the emitter and the principal work. It is also why the caller **must** use `contextvars.copy_context()` before spawning its thread — the copy happens at spawn, so anything set after is invisible |
| **`Send(timeout=)` is unusable here** | `ValueError: Node timeouts are only supported for async nodes because sync Python execution cannot be safely cancelled in-process` | Stall detection uses state-recorded timestamps, and that is the **only** option |

**Net difference from spec §8's wording:** dispatch proceeds ascending in batches bounded by the cap,
rather than backfilling individual slots the instant one frees. Ordered release, the cap and retry
priority all survive; only per-slot backfill does not, because the runtime provides no such event.

---

## C1 — `GraphState` and the turn-scoped reducers

**Contract** — `src/services/graph/state.py`. This is one of the few places the code *is* the design, so
it is given in full.

```python
def scoped(turn_id: str, value):            # wrap a value with the turn it belongs to
    return {"turn": turn_id, "vals": value}

def scoped_vals(state: dict, key: str):
    """Read a turn-scoped key, discarding a value from a previous turn.

    The turn comparison is HERE, not only in the reducers. Reducers fire on a WRITE, but every
    foreman read happens BEFORE any write in the turn — so without this check turn 2 reads turn 1's
    landed positions, next_dispatch_batch returns [], all_positions_committed is true, and the graph
    goes straight to deck review having built NOTHING.
    """
    wrapper = (state or {}).get(key)
    empty = _EMPTY_FOR[key]                  # per-key: set(), {} or []
    if not isinstance(wrapper, dict):
        return empty
    if wrapper.get("turn") != (state or {}).get("turn_id"):
        return empty                         # stale
    return wrapper.get("vals", empty)
```

`_EMPTY_FOR` is a per-key mapping, **not** a suffix heuristic. A heuristic that returns `{}` for
anything not ending in `positions` gives a dict where `emitted_style_blocks`' list reducer needs a
list — survivable only by accident. (Round-3 finding 24.)

Three reducers, each discarding on a turn change:

```python
def turn_scoped_union(a, b):   ...   # set union within a turn
def turn_scoped_merge(a, b):   ...   # per-key dict merge; CANNOT delete a key, hence tombstones
def turn_scoped_concat(a, b):  ...   # list append within a turn
```

**`GraphState` — the exhaustive contract.** Single-writer keys carry **no** reducer (a reducer there
would silently merge where the semantics are "replace"); every key written by more than one concurrent
branch **must** carry one, or the runtime raises
`InvalidUpdateError: At key 'x': Can receive only one value per step`.

| Key | Reducer | Written by |
|---|---|---|
| `session_id`, `turn_id`, `fix_target` | none | one node each |
| `deck_spec`, `error_state` | none | `architect_node`, exception handlers |
| `architect_intent`, `architect_message`, `target_positions` | none | `architect_node` |
| `title` | none | `architect_node`, from `deck_spec.title` — ws4b B1.4 declares the field (§H1: pre-fan-out deck-level write). **Deterministic** — read off the committed spec, never derived from builder output |
| `initiated_by` | none | `invoke_graph`, from its `principal` argument or else `get_current_user()`. Carried in state **and** in `build_branch_payload`, so a fanned branch writes an author without re-reading a ContextVar (see the row-write rule under C4) |
| `token_css`, `deterministic_css` | none | `architect_node` (via `resolve_template_bytes`, C6) |
| `template_layout_html`, `resolved_style` | none | `architect_node` (C6/§L5), **once per turn**. These are the two inputs `build_branch_payload` extracts each branch's section HTML from and copies the style prose out of — without them in state there is no channel to the fan-out and each builder would re-resolve from the DB inside its own branch |
| `external_scripts`, `head_meta` | none | `architect_node`, resolved **deterministically** — the Chart.js CDN default and the deck's `<meta>` set are known before any builder runs. **NOT from `ArchitectOutput`**, which declares neither (see the closed-schema rule above) |
| `scripts_content` | none | `deck_reviewer_node`, post-commit — **derived** from `SlideDeck(...).scripts`, not read from state (see the post-commit bullet under C4) |
| `knitted_html` | none | `deck_reviewer_node` (from `SlideDeck.knit()`, post-commit) |
| `findings` | `operator.add` | every `build_reviewer_node` and `fix_reviewer_node` |
| `landed_positions`, `placeheld_positions`, `reviewed_positions` | `turn_scoped_union` | build reviewers, placeholder node, fix reviewer |
| `slides`, `dispatched_at`, `retry_count`, `fix_map`, `fixed` | `turn_scoped_merge` | builders, fixer, reviewers, foreman |
| `emitted_style_blocks` | `turn_scoped_concat` | `architect_node`, **once per turn**, from `resolve_template_bytes` (C6). **Not builders** — `BuilderOutput` forbids a builder emitting `<style>` at all, and brand bytes never pass through a model. See the shape note under C4 |
| `foreman_wakes` | `turn_scoped_concat` | `foreman_node` |

**`findings` is deliberately NOT turn-scoped, and that carries one rule.** It is the single key on
`operator.add` — the one that breaks the pattern C1 exists to establish — because a finding is stamped
with an id and persisted at the moment its row is written, so the channel is an append-only log rather
than turn state. But turn 2 inherits turn 1's entries permanently (the accumulation fact above), so
**no node may read `state["findings"]` as *this turn's* findings**: `build_reviewer_node` persists the
findings it returned, `deck_reviewer_node` persists what the deck review returned, and ws4d emits from
the node's own return value. A consumer needing a per-turn view adds a turn-scoped key rather than
re-purposing this one. **Test it:** turn 2 sees turn 1's findings in state and still emits and persists
only its own.

**`has_pending_fix(state)` — never `if state.get("fix_map")`.** `turn_scoped_merge` cannot delete keys,
so a completed fix is tombstoned as `{position: None}` — and `bool({0: None})` is `True`. Testing
truthiness routes to the fixer **forever**; the fixer's `min()` then raises `ValueError` on an empty
candidate set and the graph loops to `GraphRecursionError`.

**`stalled_positions(state, now, timeout_s)` — guard against `dispatched_at` tombstones.** `dispatched_at`
uses the same `turn_scoped_merge` reducer as `fix_map`, carrying the identical tombstone hazard. The in-flight
predicate — *"a position was dispatched but has not yet committed or placeheld"* — is never defined despite
three rules depending on it (C4's stall check, C2's "retries need no special case", and C2's rule 2 "in-flight
excluded from batch"). `stalled_positions` must skip `None` timestamps. `retry_count` is declared with a
reducer but **never written** — no node retries anything (builder exceptions go straight to placeholder). Yet
C2 tests state "retry priority" and "retries appear ahead of higher unstarted positions". Either delete the
`retry_count` key or define and implement its writer.

**Test intent:**

| Assertion | Why |
|---|---|
| union/merge/concat each merge within a turn and **discard** on a turn change | The core mechanic |
| `scoped_vals` returns empty for a **stale** wrapper even though the reducers have not fired | The read-side half — this is the one an earlier draft missed, so turn 2 built nothing while the test passed |
| `scoped_vals` returns the **right empty type** per key (`set`, `dict`, `list`) | Finding 24 |
| `has_pending_fix` is False for an all-tombstoned map and True when any entry survives | |
| every fan-in key declares a reducer; every single-writer key does not | Undeclared/mis-declared keys fail silently |
| **a compiled graph actually merges 6 concurrent `Send` branches** | The test that catches a missing reducer. A dict-merge unit test alone does **not** — `InvalidUpdateError` is raised by the runtime |
| **turn 2 against a real checkpointer builds** | The behavioural version. State it as "turn 2 dispatched N builders", never as "turn 2's landed set equals X" — the latter passes *because* the bug is present |

**Sabotage:** swap `turn_scoped_union` for `turn_scoped_merge` on `landed_positions` and confirm the
turn-2 test goes red **for the right reason** (an earlier attempt went red on a `TypeError` in turn 1,
which gave false confidence); make `has_pending_fix` truthiness-based and confirm the tombstone test
goes red.

---

## C2 — The foreman: pure functions over state

**Contract** — `src/services/foreman_service.py`. `CAP = 15`, `RELEASE_TIMEOUT_S = 300`, and:

```python
def outstanding_positions(state) -> list[int]      # not landed, not placeheld, ascending — INCLUDES in-flight
def next_dispatch_batch(state, cap=CAP) -> list[int]
def releasable_positions(state) -> list[int]       # the committed PREFIX
def stalled_positions(state, now: float, timeout_s=RELEASE_TIMEOUT_S) -> list[int]   # two limbs, C4
def all_positions_committed(state) -> bool
```

**No class and no instance state.** Every function is a pure function of `GraphState`, so the
checkpointer is the only home for turn state. A bare state class that is never instantiated is
`self.sessions = {}` under a new name — PRD §12.1's named bug class.

**Three rules inside `next_dispatch_batch`, and each has a failure behind it:**

1. **Ascending is load-bearing, not tidiness.** Release requires all positions `< n` committed, so
   lowest-first means releases begin almost immediately. Dispatching from the end would leave the buffer
   holding every finished slide while position 0 had not started, and the user would see nothing.
2. **In-flight positions are never re-dispatched.** The foreman re-runs on a partially completed batch,
   so a batch computed from `outstanding_positions` alone re-dispatches the siblings still running —
   duplicating LLM spend and racing two writers onto the same slide row.
3. **Subtracting in-flight from the cap is what makes the cap real.** The cap bounds *concurrent*
   builders, so dispatching `cap` fresh positions while N run allows up to `cap + N`.

**Retries need no special case** beyond clearing their in-flight marker: a failed position is still
outstanding, so ascending order re-enters it ahead of higher unstarted positions by construction.

**A placeholder counts as committed** for both `releasable_positions` and `all_positions_committed`
(§5.5, §I). `len(landed) == len(spec.slides)` is the wrong predicate: one terminal failure would mean
deck review never fires and the turn never ends.

**An edit turn covers `target_positions` only** (§6.3's multi-target case is simply n ≠ all), a build
turn every spec slide.

**Test intent:** first batch is `[0..14]` of 31; a 15-slide deck dispatches entirely (the common case —
fully parallel, no queueing); the next batch continues ascending; in-flight excluded; the cap counts
in-flight; a retry appears ahead of higher unstarted positions; release emits only a committed prefix
and extends when the gap lands; a placeholder releases and satisfies the deck-review trigger; stalls
computed from state timestamps, never a wall clock on an instance; **a dispatched, uncommitted position
outside the most recent wake's batch is stalled at zero elapsed time** (C4's limb 1) while one inside that
batch is not; a `dispatched_at` entry with no wake record needs the full timeout (limb 2, the resumed
checkpoint); a landed position is never stalled;
an empty spec dispatches nothing and is trivially committed; a partial multi-target turn dispatches only
its targets.

**Sabotage:** remove the in-flight subtraction and confirm both the duplicate-dispatch and real-cap
tests go red.

> These tests pin the **policy**, and they pass whether or not the wiring is right. That is exactly why
> C5 exists — the superseded plan had only these and would have shipped green with the runtime silently
> degraded to "dispatch 15, wait for all 15, dispatch the next 15."

---

## C3 — Skill invocation: `call_skill`, prompt assembly, model binding

**This lands before the nodes, because every node calls it.** An earlier draft put it in the skills
phase, so Phase 4 imported a module Phase 5 created.

**Contract** — `src/core/skills/__init__.py` and `src/services/agent_resolution.py`:

```python
@dataclass(frozen=True)
class Skill:
    name: str; version: int; instructions: str
    output_schema: type[BaseModel]; tool_grants: list[str]

def load_skill(name) -> Skill
def list_skills() -> list[str]
def call_skill(name: str, payload: dict) -> BaseModel      # every node's single entry point

# src/services/agent_resolution.py
def assemble_skill_prompt(skill: Skill, payload: dict) -> str
def get_structured_model(schema: type[BaseModel])
def resolve_slide_style(config: AgentConfig) -> str        # the producer of `resolved_style`
```

**One `Skill` definition, in one place.** An earlier draft defined this module twice in two tasks — a
`BaseModel` with `prompt_body` in one and a frozen dataclass with `instructions`/`version`/`tool_grants`
in the other, with different register functions. The dataclass wins: spec §5.1 requires the version and
the tool grants.

**`assemble_skill_prompt` must pass the payload.** The obvious implementation returns the instructions
plus two conditional blocks and stops — which means the builder never receives its slide brief, the
reviewer never receives the HTML it is reviewing, and the fixer never receives the finding. Every skill
would be invoked with instructions and nothing else. **Serialise the payload into the prompt.**

**`resolve_slide_style` is the producer of `resolved_style`, and it DELEGATES.** One line:
`_get_prompt_content(config)["slide_style"]`, importing from `src.services.agent_factory`. Do **not**
reimplement the resolution branch. What delegation buys, all of it already measured and defended in C8:
resolution is a **branch, not a ladder** (an inactive `design_system_id` lands on `DEFAULT_SLIDE_STYLE`
and the `elif` is never evaluated); `_design_system_is_active` fails **closed** on a tombstone; a
`compiled_style_content` that predates `COMPILER_VERSION` is lazily recompiled; the pinned-template block
is appended and the type-scale re-assertion sentinels survive. A second copy of that branch is free to
regress independently of the monolith's, silently, with no test comparing the two — and the tombstone case
is a defect that has already shipped once.

Three facts that make the delegation safe, each checkable:
- **`mode` is irrelevant.** Style is resolved before `_get_prompt_content`'s mode split, so `generate`
  and `edit` return the same `slide_style`. Call it with the default.
- **The assembled system prompt in the returned dict is discarded.** That is wasted string assembly once
  per turn, and it is the whole cost of delegating. Accept it.
- **The config comes from the session, not from state.** `architect_node` calls
  `resolve_agent_config(session["agent_config"])` (`src/api/schemas/agent_config.py:238`) — the same
  helper `chat_service.py:204` uses. An `AgentConfig` does **not** go into `GraphState`: the architect is
  the sole resolver of everything brand-related (see ws4d D2), it needs the config exactly once, and a
  pydantic config object in checkpointed state is bloat that the next turn would inherit.

When `agent.py` is deleted in a later PR the implementation moves into this function and its signature
does not change — the same arrangement C7 uses for the two security controls.

**Two conditionals, both decided from the *resolved style* at request time, not from the skill:**

- **`_SLIDE_FRAME_CONSTRAINTS` is injected only when the resolved style lacks it** (§L5's third case).
  Import it from `src.services.design_system_compiler` **under its private name** — reading a private
  constant is legal and changes no existing file, and §L5's actual requirement is only that both sites
  read the **same bytes at request time**. Retyping the numbers would create exactly the divergence the
  `COMPILER_VERSION` currency contract exists to prevent.
- **`DESIGN_SYSTEM_PRECEDENCE` only when a design system is active.**

**Why three style cases, not two (§L5):**

| Resolved style | Carries the safe-area numbers? |
|---|---|
| design system (`compiled_style_content`) | **yes** — the compiler emits them |
| no style at all → `DEFAULT_SLIDE_STYLE` | **no safe area at all.** `defaults.py:5-26` has only body-level `1280x720px` / `margin:0; padding:0; overflow:hidden` — no 88px, no 72px, no 56px, no clearance rule |
| a selected library slide style | **unknown, usually no** — `agent_factory.py:216` does `slide_style = style.style_content`, which **replaces** `DEFAULT_SLIDE_STYLE` wholesale |

This is not cosmetic: §L7 puts `overflow` on the build reviewer's objective criteria and tells it to
judge against these exact numbers, so a legacy-style deck would be judged against numbers its builder
never received. **The builder and the reviewer must be handed the same numbers or the criterion is
unfair by construction.**

**All three rows are reachable in a test only because `resolve_slide_style` exists** — construct an
`AgentConfig` per row and assert which case you land in. Add one more assertion that no other test can
replace: **the graph and the monolith resolve the same bytes from the same config**, asserted by calling
`resolve_slide_style(config)` and `_get_prompt_content(config)["slide_style"]` and comparing. That is the
guard against someone later "optimising away" the delegation, which is the only way these two can drift.

**`get_structured_model` follows the repo's existing client path** — `agent_factory.py:56` uses
`get_system_client()`. Do not invent a new client.

**Test intent:** all seven skills load and bind to their `OUTPUT_SCHEMAS` entry; each declares a
version and a non-empty instruction body (a placeholder is fine, empty is not — an empty prompt
produces garbage that still parses); **the payload appears in the assembled prompt**; frame constraints
injected in cases 2 and 3 and **not duplicated** in case 1; `DESIGN_SYSTEM_PRECEDENCE` present only with
an active design system; no skill body contains `88px`/`72px`/`56px`/`1280x720`; the analyst and
architect declare tool grants and builders/reviewers declare none (§5.2.2 concentrates user-scoped data
access in the analyst — the natural OBO boundary); an unknown skill name raises.

---

## C4 — Nodes, routers and graph assembly

**Contract** — `src/services/graph/nodes.py`, `routers.py`, `builder.py`. Nine nodes:
`architect`, `data_analyst`, `foreman`, `builder`, `build_reviewer`, `fixer`, `fix_reviewer`,
`placeholder`, `deck_reviewer`.

### The four wiring rules

1. **`builder → build_reviewer` is a CONDITIONAL edge that re-fans**, never static. A static edge
   collapses N branches into one invocation receiving plain state with no payload — so
   `payload["position"]` raises `KeyError`, there is one review per *batch* rather than per slide
   (breaking both the one-reviewer-writes-one-row invariant and the n-not-3n cost model), and the
   per-slide fix path never fires.
2. **`Send` objects are returned from a router**, never written into state. Signature
   `Send(node, arg, *, timeout=None)`.
3. **A router takes `(state)` or `(state, config)` only** — extra positional params raise `TypeError`,
   and the config parameter must be **named `config`**.
4. **One conditional-edge set per node.** A static `add_edge` alongside conditional edges from the same
   node gives duplicate conflicting edges and a `GraphRecursionError`.

### `foreman_node` — and the two things it owns because routers cannot write state

```
if has_pending_fix(state):        -> "fixer"
if stalled_positions(...):        -> "placeholder"
batch = next_dispatch_batch(...)  -> [Send("builder", build_branch_payload(state, p)) for p in batch]
if all_positions_committed(...):  -> "deck_reviewer"
else:                             -> END        # nothing outstanding, nothing to reconcile
```

`foreman_node` itself writes two things before the router runs:

- **`dispatched_at`**, written as `scoped(turn_id, {p: now})` for every position about to be dispatched
  — the wrapper, never `state["dispatched_at"][p] = now`. This must be a **dispatch**
  timestamp. Writing it on builder *return* makes it a **completion** timestamp, so a branch that hangs
  or dies never gets an entry and `stalled_positions` can never observe the case it exists for. The
  foreman runs before the batch, so it is the only node that can stamp it. Stamp **only the positions it
  actually dispatches**: a wake whose decision is `"fixer"` or `"placeholder"` stamps nothing, or the next
  wake reads positions that never started as dispatched-and-never-completed.
- **`foreman_wakes`**, written as `{"foreman_wakes": scoped(turn_id, [batch])}` — this turn's batch in a
  wrapper, and **`wakes + [batch]` must not appear anywhere.** Non-destructiveness is
  `turn_scoped_concat`'s job, not the node's: a value read through `scoped_vals`, concatenated and
  returned bare arrives at the reducer as an unwrapped list, fails its `isinstance(b, dict)` check, and
  the write is discarded or raises. Record a wake on **every** foreman entry, including one that
  dispatches nothing (`[]`) — C5 counts wakes through this channel, and the reconciliation rule below
  reads the most recent entry. `wakes.append(batch)` is worse still — in-place mutation of
  checkpointed state is the failure the adjacent comment warns about, and an earlier draft did exactly
  that for `dispatched_at` while forbidding it for `wakes`.

**`build_branch_payload(state, position)` pre-copies everything the branch needs**, because a
`Send`-reached node cannot see `GraphState`: `session_id`, `turn_id`, `initiated_by`, `position`, the
`SlideSpec` looked up **by position**, `assumes`, `hands_off`, `design_contract`, `resolved_data`, **plus
the extracted section HTML, the section CSS, and the resolved style prose**. The builder authors on this
foundation — section HTML provides the markup, section CSS + resolved style are the constraints §M5/§M6
require. This is also the resolved style C3's `assemble_skill_prompt` needs to inject
`_SLIDE_FRAME_CONSTRAINTS` conditionally (§L5's cases: the builder and reviewer must receive the same
safe-area numbers or the criterion is unfair by construction).

`design_contract` does **not** close this gap — ws4b makes `DesignContractRef` ids-only, *"WHICH brand,
never the compiled content"* — and nothing resolves brand bytes inside a branch. The payload builder
resolves nothing either: `architect_node` already put `template_layout_html`, `deterministic_css` and
`resolved_style` in state once per turn, so `build_branch_payload` **extracts** the section with
`extract_section(template_layout_html, spec.template_section_index)`, carries `deterministic_css` whole as
the section CSS (§M5 — never pruned), and copies `resolved_style` across. No DB read happens inside the
fan-out.

**Reconcile stall detection with the barrier explicitly — and do NOT gate the reconciliation on the
timeout.** The barrier means a timeout evaluated in `foreman_node` cannot fire *while* a position is
stalled: the node only runs once the batch completes, which is the one moment the timeout is not needed.
So what the `"placeholder"` branch actually catches is a position **left uncommitted by a completed
batch** — a builder that returned nothing usable, a build reviewer that raised, or a resumed checkpoint
whose branch died. `stalled_positions` therefore has **two limbs**, and the first is the one that fires
in practice:

1. **Has a `dispatched_at` entry, is NOT in the most recent `foreman_wakes` batch, and is neither landed
   nor placeheld** — read from state, not inferred. Terminal *by construction*: the barrier guarantees
   every earlier batch completed before this wake, so nothing outside the current batch can still be
   running. Placehold it **immediately** — elapsed time is irrelevant here and must not gate it. Excluding
   the current batch is what keeps the limb safe if the runtime ever does wake the foreman mid-batch.
2. **A `dispatched_at` entry with NO wake record in this turn, elapsed > `RELEASE_TIMEOUT_S`** — the
   resumed-checkpoint case, where the timestamp predates this process and no barrier covers it. Elapsed
   time *does* gate this limb, because a second worker on the same `thread_id` may still be building that
   position and placeholding it would race a live writer.

Gating limb 1 on the 300 s timeout makes the whole branch unreachable: it is evaluated seconds after the
batch completed, so `now - dispatched_at` is always small, and the turn falls through to `END` instead —
with slides missing, no placeholder, no error, and nothing in chat. So **`END` is reachable only with
nothing outstanding and nothing to reconcile**; reaching it with an uncommitted position is a bug, and
that branch must record `error_state` and surface a notice rather than returning quietly. Say all of this
in the docstring rather than claiming a live-stall guard the runtime cannot provide. (Round-3 finding 21.)

### `reviewer_router` — delete it; the static edge is measured clean

An earlier draft specified it, tested it, and left `builder.py` using a static
`add_edge("build_reviewer", "foreman")`, so its return values matched no node name. Both variants were
built and run on langgraph 1.2.10 with 6 builders (positions 0 and 1 needing a fix):

| Approach | fixer invocations | foreman wakes |
|---|---|---|
| Wiring `reviewer_router` (`"fix"`→`fixer`, `"land"`→`foreman`) | **3** — positions 0, 1, and one with empty candidates | **5** |
| Static `add_edge("build_reviewer", "foreman")` | **2** — positions 0, 1 | **4** |

The measured cause: reviewers split their return between `"fix"` and `"land"`, so `fixer` and `foreman`
land in the **same superstep**. The foreman then independently routes to the fixer on `has_pending_fix`,
creating an invocation whose candidate set is already empty. That is the exact state C1 guards against —
*"the fixer's `min()` then raises `ValueError` on an empty candidate set"* — reached by a different cause,
bypassing the `has_pending_fix` check because the fixer is now reachable without passing through the
foreman.

**Consequence:** C5's two headline assertions both fail under the wiring — *"exactly one fixer invocation
per position needing a fix"* (3, not 2) and *"the orchestrator wakes once per completed batch"* (5, not 4).

**Re-measured while porting this decision, on the same runtime:** the wiring does not merely over-invoke.
Because `fix_target` is declared single-writer with **no** reducer (C1's table), the wired variant puts
`fixer` and `fix_reviewer` in one superstep and the runtime raises
`InvalidUpdateError: At key 'fix_target': Can receive only one value per step` — the turn dies rather than
degrading. The static variant reproduced 2 fixer invocations and 4 foreman wakes exactly, and reached deck
review once.

**Decision: delete the router and keep the static edge.** A tested-but-unreachable router misleads about
the topology. Record the two adjacent facts it revealed: with the clean wiring, fix rounds **serialise**
one position per superstep (15 objective findings = 15 sequential rounds), and `has_pending_fix` preempts
dispatch entirely, so a 31-slide deck stops dispatching new builders until every fix completes.

### Node behaviour, and the invariants each one carries

| Node | Reached by | Must |
|---|---|---|
| `architect_node` | edge | Read the previous arc verdict via `get_deck_review(session_id, deck_id)` (ws4b B2.2) — **this is that function's only production caller**, and without it turn *n+1* re-proposes an arc the deck reviewer already rejected, forever. Set `architect_intent`/`architect_message`; on build/edit commit `deck_spec` and perform the **pre-fan-out deck-level write** (§H1's trigger *is* "the architect committed the spec"). **Sole resolver of everything brand-related** (§L5, ws4d D2): `resolve_slide_style` into `resolved_style`, plus `resolve_template_bytes` into `template_layout_html`/`deterministic_css`/`token_css` — **once per turn**, so no builder re-resolves inside its branch. **Read only fields `ArchitectOutput` declares** |
| `data_analyst_node` | edge | Return exactly one of three outcome shapes; **read only `AnalystOutput`'s fields** |
| `builder_node` | `Send` payload | Emit body HTML only (no `<style>`); gate the HTML through the safety control (C7); carry its payload forward in `slides[position]` so the re-fan can rebuild the reviewer's input; on exception, commit a **placeholder** and return `placeheld_positions`, never `landed_positions` |
| `build_reviewer_node` | re-fan `Send` | Stamp finding ids with `make_finding_id(criterion, content_hash, ordinal)` — **all three arguments**; `ordinal` is the finding's 0-indexed position among findings of that criterion on this slide, and omitting it (it defaults) makes two `overflow` findings share one id. If no objective finding, **write the row** with an explicit `verification_record`; else populate `fix_map` with `original_html` **and `original_scripts`** |
| `fixer_node` | state | Pick the lowest entry that is neither tombstoned nor `in_flight`; mark it `in_flight` on dispatch |
| `fix_reviewer_node` | state | Choose fixed-or-original, **write the winner**, mark auto-fixed objective findings `status="fixed"`, tombstone the `fix_map` entry |
| `placeholder_node` | `foreman_router` | Commit via `SlideWriter.commit_placeholder`; detect failures via `is_placeholder_record`, **never an HTML class** |
| `deck_reviewer_node` | edge | Perform the **post-commit deck-level write** (§H1b); invoke the deck reviewer to assess the arc, and **persist findings via `save_deck_review`** (ws4b B2.2). Surface the verdict to the human by persisting a chat message — `add_message(session_id, role="assistant", content=<verdict prose>, message_type="info")`. **No new `StreamEventType`, no route and no frontend change:** `info` is the shipped vehicle for machine-generated advisories the user must see (`chat_service.py:758` RC11 conflict note, `:793` safety notice), the frontend keys rendering on `role` and never inspects `message_type` (`ChatPanel.tsx:101`), and `_hydrate_chat_history` skips `info` explicitly, so the architect does not also receive it as prose. **Non-fatal** — a failure clears the flag and surfaces a notice, never invalidating a delivered deck |

**Fix-round bookkeeping — this table is what makes "exactly one fix round" true rather than
aspirational:**

| Stage | `fix_map[pos]` becomes | Effect |
|---|---|---|
| build reviewer finds an objective defect | `{original_html, original_scripts, finding, payload}` | `has_pending_fix` → True, router sends to the fixer |
| fixer dispatches it | `{…, "in_flight": True}` | excluded from candidates, so it cannot be picked twice |
| fix reviewer decides | `None` (tombstone) | `has_pending_fix` → False once every entry is tombstoned |

Without `in_flight`, `fix_reviewer_node` clears only `fix_target`, so **every position above the minimum
is re-fixed on the next foreman pass** — measured as each position entering the fixer twice and deck
review firing twice.

**Every graph row write passes `modified_by` and `deck_spec_slide` explicitly.** There is no request
context inside the graph, so `get_current_user()` is `None` and `SlideWriter.write_slide`'s
partial-update semantics then *preserve* the existing author — which on an INSERT leaves the author
**NULL** (`slide_repository.py:91`, `:104-107`). Pass `modified_by=initiated_by`, resolved once in
`invoke_graph` and carried in state and in `build_branch_payload` so the re-fanned reviewer has it, on
every reviewer, fixer and placeholder write. `deck_spec_slide` is a real parameter of the same writer that
nothing in C4 currently populates, so per-row spec fragments would never be persisted: write the
position's `SlideSpec` with the row, from the payload the branch already carries. **Test both** — a
reviewer-written row has a non-NULL author and a parsed `deck_spec_slide`.

### Where the deck-level write's values actually come from

**This is the trap that produced four separate findings, so it is stated as a rule.** `token_css`,
`deterministic_css` and the template's style block are **brand bytes**. They come from
`resolve_template_bytes` (C6) — **deterministic code** — and **never from model output**. An earlier
draft read them off `ArchitectOutput`, which both violated the invariant and invented five fields the
schema does not declare.

- **Pre-fan-out** (in `architect_node`, after the spec is committed) — **five of ws4b B3.1's eight
  columns**: `title`, `external_scripts`, `head_meta`, `deck_spec`, and §K4's deterministic CSS, which is
  the pinned template's `token_css` plus its `<style>` block, resolved **here**, from the deck spec's
  `design_contract`.

  `external_scripts` and `head_meta` are resolved **deterministically**, not read off model output —
  the Chart.js CDN default and the deck's `<meta>` set are both known before any builder runs, and
  `ArchitectOutput` declares neither field.

- **Post-commit** (in `deck_reviewer_node`) — the other **three** columns plus the aggregated `css`:
  `slide_count`, `html_content` and `scripts_content`. The last two are **derived, not read from state**:
  build the domain object from the deck dict (`SlideDeck.from_dict`, `slide_deck.py:111` — there is no
  `from_json`), then call `knit()` for `html_content` and read the aggregating `scripts` property for
  `scripts_content`.

  **`scripts_content` is a denormalised cache of the per-slide aggregate, and the read-only property is
  its SOURCE, not an obstacle.** `SlideDeck.scripts` (`slide_deck.py:79-96`) IIFE-wraps and joins the
  slides' own scripts, and all six monolith save sites persist exactly that value —
  `scripts_content=current_deck.scripts` (`chat_service.py:690, 1489, 2746, 2826, 2892, 2956`). So nothing
  needs injecting into `SlideDeck`: re-deriving from the committed slides reproduces the column, exactly
  as `knit()` reproduces `html_content`. It **cannot** go in the pre-fan-out write — no slides exist yet.

  **Leaving it NULL regresses graph decks silently.** The row-read dict emits
  `"scripts": deck.scripts_content or ""` (`session_manager.py:1549`) and three surfaces consume that key
  — `ThumbnailRibbon.tsx:163`, `pdf_client.ts:98` and `pptx_client.ts:96` (`export.py:563` logs it) — so
  thumbnails, PDF export and PPTX export would render with **no JavaScript and blank charts**, with no
  exception raised. Same failure class as `external_scripts_json` losing Chart.js.

**⚠️ `emitted_style_blocks`' shape, and what it settled in ws4b.** The template's `<style>` block is
resolved **once per turn** by `architect_node`, from `resolve_template_bytes` — not by builders, which
`BuilderOutput` forbids from emitting `<style>` at all. So on a pinned deck the `turn_scoped_concat` list
holds **exactly one element**, and on an unpinned deck it holds none.

That is harmless in itself, but it undercut what ws4b's B3.3 originally said it was for: *"N identical
copies collapse to one"* and *"§M5 hands every builder the template's full `<style>` block, so a 15-slide
pinned deck yields up to 15 identical copies and the aggregator's job is to collapse them."* **With one
producer there are never 15 copies**, so that dedupe test described a path nothing reaches — the "test that
cannot fail" class. ws4b's own B3.3 anticipated this and asked to be told: *"If ws4c concludes one pinned template needs
no per-slide accumulation at all, this function's dedupe premise weakens and its test must change with it."*
**It does, and B3.3 has been re-scoped accordingly** — the N-identical-copies assertion is gone and its
"one emitted block" premise is stated there. The aggregator still earns its place: it merges the one
template block into existing deck CSS and runs the token backstop. Nothing further is owed to ws4b here;
if a later change ever gives `emitted_style_blocks` a second producer, B3.3 is the document to reopen.

**Guard the template resolution on `design_system_id and template_id`, not on `design_contract`'s
truthiness.** `design_contract` has a `default_factory`, and an all-`None` pydantic model is **truthy**,
so a bare truth test calls `resolve_template_bytes(None, None)` on every unpinned deck and a `try/except`
hides it. (Round-3 finding 28.)

**`invoke_graph(session_id, initial, *, emitter=None, principal=None)`** mints a fresh `turn_id` per turn (the discriminator that resets
turn-scoped state), passes `thread_id`, sets `max_concurrency=CAP` as the belt to the queue's braces,
and sets **no `recursion_limit`** — the default is 10007 and the superseded plan's ~50 would have made
the graph fail *earlier* than shipping no config.

### Event emission via ContextVar (the emitter lifecycle)

**Context:** nodes cannot queue events into `GraphState` because the runtime **silently drops undeclared
keys**, and a `queue.Queue` is not serialisable through the checkpointer anyway. D3 specifies the
emission contract; this section specifies the **graph-side setup**.

**The emitter lives in a `ContextVar`**, and **ws4c owns its lifecycle.** The queue is created by the
caller and handed in as `invoke_graph`'s `emitter=` argument; `invoke_graph` sets the ContextVar. The
dependency is therefore visible in a signature rather than ambient — a caller in another module setting
a variable this module's nodes read is not a contract, and nothing would test it.

Measured (see the runtime-facts table): a var set before `graph.invoke()` reaches every `Send`-fanned
node, and a node-local write cannot leak to a sibling. So no parameter threading through the payload and
no state pollution.

**Contract** — `src/services/graph/event_emitter.py`:

```python
event_emitter_var: ContextVar[StreamEventQueue]     # a queue.Queue or similar
def set_event_emitter(queue: StreamEventQueue) -> None
def get_event_emitter() -> StreamEventQueue | None
```

- **Set in `invoke_graph`** before `graph.invoke()` runs, so the ContextVar is live for the entire turn.
  When `emitter` is `None` — the sweeper path, and every layer-1 test that asserts state rather than
  events — nodes see `None` from `get_event_emitter()` and **skip emission**; they must not raise.
  Emission is an optional side channel, never a precondition for building a deck.
- **Every node that emits calls `get_event_emitter().put(event)`** — e.g., `deck_reviewer_node` queues
  finding events and `builder_node`'s exception handler can queue error placeholders.
- **The ContextVar must NOT enter `GraphState`.** Declare it only once, set it once per turn, never
  read it into state. An undeclared key read back from state is silently dropped by the runtime, so
  its presence in `GraphState` is undetectable until the next turn inherits it from the checkpointer —
  a silent corruption risk.
- **Reset or validate it when resuming a turn in a new process.** A second invoke on a different worker
  must set a fresh emitter, or events queue into the first process's queue forever.

**The principal travels the same way, and needs no payload field.** `invoke_graph` resolves
`principal or get_current_user()` **once**, into `initiated_by`. `get_current_user()` genuinely works
inside the graph — including inside a fanned branch — **provided the caller copied its context before
spawning the thread**, which is ws4d's obligation and is stated there. The explicit `principal=` argument
exists for callers with no request context: ws4d's D5 sweeper passes the marker's `spec_dirty_by`.
Resolve it once and read it from state thereafter; a node that calls `get_current_user()` itself will
work today and break the first time someone invokes the graph from a bare thread.

**Test intent:** `invoke_graph` sets the emitter before the graph runs, and with `emitter=None` the graph
still builds a deck and emits nothing; a second `invoke_graph` in the same turn-id gets a fresh emitter;
the emitter survives `Send` fan-out and **every fanned node queues independently**; `initiated_by` equals
an explicitly passed `principal` even when `get_current_user()` is `None`; and — the regression this
closes — a graph invoked from a thread whose context was copied writes a **non-NULL** `modified_by` on
every reviewer-written row.

---

## C5 — Layer-1 orchestration tests against the COMPILED graph

**These are the ones that matter.** Spec §8 is explicit that a scheduler test in isolation passes
regardless while the shipped behaviour silently degrades.

**Harness** — `tests/integration/conftest_stub_skills.py`: a `SkillRecorder` the fixture returns and
each test mutates, carrying `slide_count`, `fail_positions`, `slow_positions`,
`objective_findings_at`, plus `calls`, `positions(skill)`, `counts(skill)` and `peak_concurrent`.
`call_skill` is monkeypatched to return canned schema-valid outputs.

**Register the fixture; auto-collection will not find it.** Pytest auto-collects only `conftest.py`, so a
`@pytest.fixture` living in `conftest_stub_skills.py` is invisible and every test requesting it errors on
an unknown fixture. The repo has exactly one fixture-registering precedent —
`pytest_plugins = ["tests.unit.conftest_images"]` (`tests/unit/test_image_service.py:42`) — while its other
`conftest_*.py` modules are consumed by **plain import of helpers**
(`tests/unit/test_design_system_import.py:31`). Pick one and state it in the module docstring: either
`pytest_plugins = ["tests.integration.conftest_stub_skills"]` in the suite, or make the module
helpers-only and construct the recorder in each test.

**Declare the fixtures this suite needs beyond `call_skill`.** Patching `call_skill` covers the models and
nothing else: `architect_node`'s deck-level write and `resolve_template_bytes` need a live DB session, the
reviewers' and placeholder's row writes need `stub_writer` (or the real `SlideWriter` against that engine),
and *"turn 2 against a real checkpointer"* needs the checkpointer. ws4b's B1.7 fixtures are unit-scoped and
`tests/integration/` cannot see them; the file-backed engine fixture in `tests/integration/conftest.py`
that ws4b creates for ws4e's layer-4 tests is the one to reuse. Anything still missing is **added to
`tests/integration/conftest.py`**, never imported across the boundary.

**The stub's parametrisation lives on the recorder, never in graph state.** An earlier draft passed
`_stub_slide_count` through `invoke()`, which the runtime **silently drops** because it is not a declared
key — so every test built 3 slides regardless: six failed, and two (`cap holds at 15`,
`release order ascending`) **passed vacuously** on 3 slides. Then the "fix" declared it *in*
`GraphState`, putting test scaffolding into the production contract. Neither. Put it on the recorder,
alongside `fail_positions`.

**Test intent** — each against the real compiled graph with stub agents:

| Assertion | Guards |
|---|---|
| a 3-slide deck builds every position | baseline |
| **one reviewer invocation per slide, not per batch** (6 → 6) | the re-fan; a static edge collapses to 1 |
| peak concurrent builders ≤ 15 over 40 positions | the cap — falsifiable by removing it (peak becomes 40). It does **not** cover C2's rule 3: the barrier plus the foreman's early returns mean the foreman never wakes with a partially-completed batch, so in-flight subtraction has no reachable layer-1 scenario. Sabotage rule 3 at C2, and say so in this test's docstring so nobody mistakes it for that coverage |
| the first batch of 31 is `[0..14]`, ascending | ordering |
| with position 1 slow, **no position outside the in-flight batch** dispatches until the batch completes — positions 15+ of 31 stay unstarted | ordering under skew. Positions 2..14 *are* dispatched alongside position 1 — same batch — so "no higher position dispatches" would be false for batch 1 and vacuous for every later one |
| the **committed prefix** from `releasable_positions` never regresses across foreman wakes with a slow position | §7.4's no-flapping guarantee, asserted at the layer that owns the prefix. The *emission* of releases is ws4d's (`slides_since_cursor`, `emit_slide_ready`) — do not assert it here |
| the orchestrator wakes once per **completed batch** | acknowledges the barrier, so a future change assuming per-completion wakeups fails loudly. Read `foreman_wakes` through `scoped_vals`, and assert something falsifiable about each wake — not `len(wake) % 1 == 0`, which is true for every int |
| **exactly one fixer invocation per position needing a fix**, and deck review fires **once** | the headline invariant |
| a surviving defect becomes a surfaced finding, not a retry | |
| a terminal failure becomes a **placeholder**, release proceeds past it, and deck review still fires | §I |
| **turn 2 builds** rather than going straight to deck review | no test in the superseded plan covered a second turn, and that is the failure it hid |

**Sabotage two, at minimum:** replace the re-fan with a static edge and confirm the per-slide reviewer
test goes red; drop `in_flight` from the fixer's `fix_map` write and confirm the one-fix-round test goes
red.

---

## C6 — Template-section extraction and the architect's inventory

**Contract** — `src/services/template_sections.py`:

```python
def section_inventory(layout_html: str) -> list[dict]     # index, tag, classes, text_snippet, affordances
def extract_section(layout_html: str, index: int) -> str  # VERBATIM markup
def resolve_template_bytes(design_system_id, template_id) -> tuple[str, str, str]
                                                          # (normalized layout_html, <style> block, token_css)
```

**The division of labour, and the line that must not be crossed (§M3):** the **architect assigns** a
section per slide (intent — model-appropriate); **deterministic code extracts** its HTML and CSS
byte-for-byte. **The architect never rewrites layout HTML or CSS.** That is not stylistic: it is the
failure `ensure_deck_token_css` was built to catch — a model dropped 57 `var(--…)` definitions and
washed out preview and both PPTX export paths. A model retyping brand markup has no backstop.

**Grain is measured, not assumed.** `find_slide_roots(BeautifulSoup(layout_html))` returns **1** root
for a per-slide template and **N** for a deck skeleton — probed on both shapes — so **no grain detection
appears in the graph at all**:

| Sections in layout | Architect assigns | Builder receives |
|---|---|---|
| N | section *i* per slide | one section |
| 1 | that section for every slide | the same section |
| fewer than the slide count | reuses sections, varying which | its assigned section |

The last row is already the shipped instruction — *"vary which slide sections you reuse rather than
repeating one"* — written for a monolith emitting a whole deck, and here it becomes a per-slide
assignment.

**The precondition that measurement rests on: roots are found by the `slide` CLASS TOKEN, not by tag.**
`find_slide_roots` is `soup.find_all(class_="slide")` (`html_utils.py:72`) and `_detect_slide_root_tags`
(`design_system_templates.py:444-450`) keys on the same token, and every in-repo template fixture supplies
it (`tests/unit/conftest_design_system.py:177,181`; `test_design_system_templates.py:542,652`) — so a probe
against those fixtures returns 1 or N **by construction**. A brand template whose slide roots carry no
`slide` class yields **0** roots: an empty `section_inventory`, no section ever assigned,
`template_section_index` permanently `None`, §M3's whole story silently disengaged, and
`normalize_root_tag_selectors` reduced to a no-op (`design_system_templates.py:543-544` returns its input
unchanged when the root-tag set is empty). §M7 already concedes there is no real bundle in-repo, so **do
not generalise the measurement**: `section_inventory` must treat zero roots as a **named, logged outcome**
that falls back to the no-template path, never as an empty success.

**`resolve_template_bytes` MUST route through `get_template_for_generation`** (`design_system_templates.py:849`,
which calls `materialize_templates` at `:859`) and only then read `template.layout_html`.

**Its signature takes a design-system OBJECT, not an id** — `get_template_for_generation(design_system:
Any, template_id: int)` — so `resolve_template_bytes(design_system_id, template_id)` must do three things
before it can call it, and each has a defect behind it. **(a) Load the design system first** — the same
trap ws4b flagged for `_get_deck_owner_session` taking a `UserSession` rather than a string. **(b) Do it
inside a live `get_db_session`**, because `materialize_templates` self-heals by assigning
`template.layout_html` (`:705`) and its docstring leaves persistence to the calling session (`:690-692`),
so a detached row silently loses the normalisation this function exists to guarantee. **(c) Filter on
`_design_system_is_active(design_system_id)`** (`agent_factory.py:315-350`, fails closed): a session keeps
its pin after a soft delete, so resolving bytes by bare id re-opens the tombstone defect C8 spends a
paragraph preserving. An inactive or unknown design system resolves to the no-template path, exactly as an
invalid `template_id` does. There is no
normalizing accessor to read through: `normalize_root_tag_selectors` (`:527`) is a plain function whose
callers **persist** its output — `materialize_templates` self-heals existing rows by assigning
`template.layout_html` (`:705`). Extracting from a row that has not been through that pass yields a
section whose CSS selectors match nothing in the built slide: a **silent, whole-section styling loss**.
The pass is idempotent, so routing through it costs nothing on an already-healed row.

**The promotion gotcha.** `SLIDE_WRAPPER_TAGS` is `{"section", "article"}` only — a `<div>` is
deliberately excluded and so is `<main>`. A template wrapping its slides in a non-promoting tag keeps
that wrapper's styles **outside** the extracted section. **Probe this before implementing:** render an
extracted section against its template's full CSS and compare computed styles with the same section
in situ. If they diverge (expect `padding` via a custom property defined on the wrapper, plus
`font-family`, `background-color`, `color`), `extract_section` must **re-parent** — return the section
wrapped in its non-promoted ancestor chain with the ancestors' other children stripped. **Never resolve
a divergence by pruning or rewriting the template's CSS**; §M5 is explicit that CSS travels whole, and
an undefined `var(--…)` is the measured washout defect.

Two notes on running that probe: the spec file must live **inside** `frontend/tests/` (Playwright's
`testDir` is `./tests`, so a `/tmp` file is never collected), and `page.evaluate` takes
`(pageFunction, arg)` — passing a third argument, or a function as the second, throws instead of
measuring.

**The inventory is deterministic and small (§M4)** — a few hundred bytes per section: index, tag,
class list, a short text snippet, and structural affordances (canvas / image / table / list). It is
**not** the raw layout: a real template measures **24–47 KB**, and the architect holds the only durable
conversation in the system (§5.3), so injecting the full layout every turn would be both expensive and
contrary to §7.2's compaction story. Per-turn context, never accumulated into the transcript.

**CSS travels whole with every section, never pruned (§M5).** Pruning was rejected: CSS is small next
to markup, and under-including is the known washout defect — and `ensure_deck_token_css` backstops only
custom properties and `@font-face` families, so a pruner's mistakes land outside the safety net.

> **§M6's rejected alternative, recorded so it is not revisited:** handing every builder the full
> template layout and grouping builders by template for prompt-cache reuse. ~130k duplicated tokens per
> build turn against PRD §14's cost risk, and it leaned on prompt caching that workstream 2 has not
> delivered.

> **§M7 probe 2 is dropped:** there is no real design-system bundle in the repo and the DS fixtures
> carry an explicit "no real brand content ever" hygiene rule, so §M5/§M6's "CSS is small next to
> markup" cost claim stands **unmeasured**. It does not reopen §M5 — under-including is the washout
> defect either way.

**Test intent:** a deck skeleton inventories every section and a single-slide template exactly one;
affordances detected; the inventory carries **no markup** and is smaller than the layout; extraction is
byte-for-byte verbatim; an out-of-range index raises rather than silently returning nothing; the
`<main>`-wrapper case behaves per the probe's finding; **a layout whose roots carry no `slide` class
inventories zero sections and is reported as the no-template fallback, not as an empty success**; and
`resolve_template_bytes` returns the no-template result for an **inactive** design system id.

---

## C7 — The two shipped security controls, re-homed

**§D4.** `src/services/agent.py` is the only home of two controls that landed as security work and have
no equivalent on the graph path (verified: no other module implements either).

| Control | Where | Pinned by |
|---|---|---|
| **Output safety gate** — `_run_output_safety_gate` + `SAFETY_RETRY_NOTICE` (`agent.py:96-118`, call sites `:1488`, `:1746`): scans model HTML for disallowed external network/resource access, regenerates once with a corrective instruction, raises if still unsafe (AISEC-248) | generation *and* streaming paths | `test_agent_safety_gate.py`, `test_safety_gate_http.py` |
| **Slide-context spotlight** — `spotlight("slide_context", html, session_id=…)` (`agent.py:885-916`): prior slide HTML is untrusted input, framed as `<untrusted-data>`, delimiters neutralised, injection patterns scanned at the prompt boundary (SDR-4437 F-TM-12) | edit/add operations injecting prior slides | `test_slide_context_injection.py` |

**Neither is a monolith artifact.** The graph's builder and fixer emit HTML from a model, and its
fixer and reviewers receive prior slide HTML as input, so both threats survive the rewrite unchanged.
`export.py:159` runs the same scanner at *export* time and `streaming_callback.py:90` suppresses unsafe
streamed text, but **neither replaces the generate-time gate-and-retry.**

**Contract** — `src/utils/graph_safety.py`: `gate_emitted_html(html, regenerate, session_id, on_retry=None) -> (html, retried)`
and `spotlight_prior_slides(htmls, session_id) -> str`.

**Only one of the two can delegate, and that asymmetry is the work.** `gate_emitted_html` delegates:
`_run_output_safety_gate` is **module-level** (`agent.py:102`), so there stays one scanner and one policy.
`spotlight_prior_slides` **cannot** — the prior-slide framing lives in `SlideAgent._format_slide_context`,
a **method** (`agent.py:885`), unreachable without constructing an agent. So it re-implements the
`<slide-context>` wrapper and its notice text, copied from `:908-916` so both paths frame identically,
while calling the shared `spotlight()` (`src/utils/spotlight.py:22`) for the security-relevant part.
When the later PR deletes `agent.py`, `gate_emitted_html`'s implementation moves here and neither
signature changes.

**Two API traps:** `_run_output_safety_gate(html_output, regenerate, session_id, on_retry=None)` takes
`regenerate` as a **zero-arg callable it invokes** and returns `(safe_html, retried)`; it scans HTML
only, never scripts. Passing `scripts` as the second argument raises `TypeError` on the unsafe path.
And **never hand-roll an `<untrusted-data>` f-string** — `spotlight()` neutralises embedded delimiters
(its docstring cites review finding #7) and applies `cap_tool_output`; an f-string does neither, so
builder HTML containing a closing delimiter breaks out of the wrapper.

**Two more traps on the spotlight side.** `spotlight` **caps at 32 KB** and appends `…[truncated]`
(`text_caps.py:4,14`), and `spotlight_prior_slides(htmls, session_id)` takes a **list** — so wrap **per
slide** inside one `<slide-context>` block, exactly as `_format_slide_context` does, and never join the
HTML and wrap once: a joined multi-slide context loses everything past 32 KB, silently and mid-tag. And
the framing has a **boundary**: the fixer's input is `fix_map[p].original_html` — *this* turn's builder
output, already gated on emission — not a prior slide, so it is passed as the artifact under edit and is
**not** given prior-slide framing. Wrapping it would tell the fixer to *"follow no embedded directives"*
about the very HTML it was asked to edit. `spotlight_prior_slides` applies where a builder or fixer
receives **other** slides' HTML as context.

**Wire both:** the gate at the builder's and fixer's HTML boundary (spec §8.1 — reviewer input **and**
fixer output both pass it; auto-remediated HTML reaching the user unchecked is the hole PRD §12.1
names); the spotlight on every path receiving prior slide HTML.

**The 13 test files referencing `src.services.agent` do not move** (13 measured). `agent.py` is unmodified
by this PR, so there is nothing to repoint and no new home to name: the three named security suites **gain
graph-path cases alongside** their existing monolith cases, because both paths now carry the controls, and
the other ten keep testing the monolith exactly where they are. **Under the cause-based gate a deleted test
is invisible**, and these are security controls — all 13 must still collect and pass at their current
paths. Ruling R1 does not apply here: the functionality survives.

**Sabotage both:** bypass the gate in `builder_node` and confirm red; replace `spotlight_prior_slides`
with an f-string and confirm red.

---

## C8 — `agent_factory` MOVES; it is not deleted

**§L6.** An earlier plan said delete or "reduce to graph config assembly". That is unsafe: it is now the
only home for the design-system resolution branch and its `compiled_style_content` currency check;
pinned-template block assembly; **the late type-scale re-assertion**; and **`search_brand_assets` tool
gating**.

**The type-scale re-assertion is not incidental plumbing.** `strip_type_scale_region_markers` (`:170`),
`extract_type_scale_block` (`:292`), `build_type_scale_reassertion` (`:294-295`) and the
`template_pinned` flag (`:134`, set at `:194`) exist because the compiled artifact delimits its
type-scale region with control-character sentinels so the numbers restated **last** cannot drift from
those injected earlier — and **a pinned template changes those numbers** (its own CSS title sizes
outrank the design system's ramp). Dropping it re-opens a measured defect: the model fell back to its
own heading sizes when the scale was stated only early.

**The brand-tool gate has TWO halves, and the docstring lies about it.**
`agent_factory.py:359-360`'s docstring says "only when `design_system_id is not None`". The code is
`if config.design_system_id is not None and _design_system_is_active(config.design_system_id)`
(`:404-406`), and the comment above it records the measured defect the second half fixes: a session
keeps its pin after the design system is soft-deleted, and on the id alone generation *"got a fully
working brand tool for a TOMBSTONE (measured: 'Found 2 brand asset(s)' with embeddable handles) while
the prompt branch, which does filter `is_active`, supplied no brand at all."* `_design_system_is_active`
(`:315-350`) fails **closed**. **Preserve both halves.**

**Resolution is a BRANCH, not a ladder.** An **inactive** `design_system_id` does **not** fall through
to the slide style — it lands on the `DEFAULT_SLIDE_STYLE` constant and the `elif` is never evaluated.

**Sequencing:** `src/services/agent_resolution.py` is **created** here (C3 adds to it), so it belongs in
this plan's new-files list — not described as a file to "modify". (Round-3 finding 10.)

**`agent_factory.py` keeps every name as a re-export shim — the PRIVATE ones especially.** Measured across
the six suites: **38** import statements reach `agent_factory` and **31** of them name a private symbol
(`_build_tools` 19, `_get_prompt_content` 12), so a public-name shim would cover almost none of them. The
justification an earlier draft gave is also wrong: `agent.py` never imports `agent_factory` at all — six
comment mentions only (`:201`, `:204`, `:209`, `:247`, `:715`, `:1843`). The sole production importer is
`chat_service.py:32` (`build_agent_for_request`), the module **ws4d rewrites**, so the shim exists for the
six suites and for ws4d's cutover window — a stronger reason than the one it replaces, not a weaker one.
**Repoint and run all six:** `test_ds_generation_state_matrix.py`,
`test_design_system_compiler.py`, `test_prompt_precedence_fixes.py`, `test_factory_tool_spotlighting.py`,
`test_agent_factory.py`, `test_design_systems_routes.py`. If a test is genuinely obsolete, say so in the
commit rather than letting it vanish.

**`chat_service` likewise keeps its design-system responsibilities** through ws4d's rewrite:
`resolve_active_design_system_id`, `{{ds-asset:ID}}` substitution inside
`_substitute_images_for_response(..., session_id=)` (note the keyword-only argument),
`_resolve_pinned_template_token_css` and `_ensure_pinned_template_token_css`.

**Test intent:** every moved symbol exists in the new module and is still reachable from the old one —
**assert the private names explicitly**, since they are the majority of what the suites import;
the brand gate's source retains both halves; `_design_system_is_active` fails closed on `None` and an
unknown id; the type-scale re-assertion is still wired; resolution is a branch — asserted
**behaviourally** (construct a config with an inactive `design_system_id` **and** a real
`slide_style_id`, resolve, assert the slide style was **not** used), never with a source-string grep.
Note `agent_factory` imports `get_db_session` **inside** each function (`:141`, `:206`, `:229`, `:335`),
so a module-level patch does not intercept it — patch where it is imported from. (Round-3 finding 14's
sibling.)

---

## C9 — The seven skills, with placeholder prompts

**§A1 governs this task.** A skill's prose is metadata; its output schema is a contract (frozen in
ws4b). The build proceeds on **generated placeholder prompts**, and real authoring is a separate track
in the dependency order `architect → builder → fixer → build_reviewer → fix_reviewer → deck_reviewer →
data_analyst` (the architect first because its deck-spec output is every downstream skill's input;
reviewers after builders because a reviewer's rubric is the builder's brief).

**Ruling R2 applies: the skills COPY their prose; `prompt_modules.py` is neither modified nor composed
from.** The graph is a new code path, so it owns its own prose and the monolith keeps its blocks exactly
as they are.

| Skill | Prose |
|---|---|
| `build_reviewer` | Its criteria block is **generated from `CRITERIA`**, not written — that keeps the prompt and the schema in step by construction |
| `builder` | Own slide-authoring / Chart.js / image / HTML-output rules, written with `SLIDE_GUIDELINES`, `CHART_JS_RULES`, `IMAGE_SUPPORT`, `HTML_OUTPUT_FORMAT` open as source material — **but the image prose is rewritten, not transcribed.** `IMAGE_SUPPORT` (`prompt_modules.py:100-117`) opens *"You have access to user-uploaded images via the search_images tool"* and gives four HOW-TO steps, while the builder declares **no** tool grants (C3): a builder told to call a tool it cannot call either fabricates handles or drops images. Keep the embedding syntax (`{{image:ID}}`, never a guessed id, no base64) and **delete every instruction to call a tool**. Nothing in PR3 carries image ids into a branch, so the prose offers an id only if the brief already contains one and otherwise says to build without images |
| `fixer` | Own editing rules, written from `EDITING_RULES` **minus that block's `"1280x720"` line**, plus a minimal-change instruction. The one file whose copy must differ from its source, and §L5 is why |
| `data_analyst` | Own synthesis guidance (single source → pass through; synthesis only at 2+ sources), plus tool grants |
| `architect`, `fix_reviewer`, `deck_reviewer` | Net-new writing |

**Two consequences of "builders and reviewers hold no tools" that are settled here, not discovered later:**

- **The grant list has two holders, not one.** C3's test intent asserts that *the analyst and the
  architect* declare grants, while this table names grants only on `data_analyst`. Give the architect its
  own grants row (its inventory/section work is tool-free, so the honest answer may be none) or change
  C3's assertion — one of the two is wrong and whichever ships gets pinned by a test.
- **Brand assets are unreachable on the graph path, and that is a recorded PR-3 gap.** `search_brand_assets`
  gating stays in `agent_factory` (C8, monolith-only) and no graph skill holds the tool, so a graph deck can
  embed no brand asset at all — and user-uploaded images are in the same position, since no `GraphState` key
  and no payload field carries an id list. Record both as known gaps rather than discovering them in review,
  and keep the builder's prose unable to reach an id it was not given, so the gap degrades to "no image"
  instead of a fabricated handle. Closing it needs a **declared channel** — a field on `SlideSpec` (an
  escalation to ws4b) or a new `GraphState` key `build_branch_payload` copies — which is a scope addition,
  not a local edit.

**`UNTRUSTED_DATA_NOTICE` is IMPORTED, not copied** — it is a security control's prose (§D4), two
copies can drift where it matters, and reading a constant is not modifying the monolith.

**Do not add a test pinning skill prose to `prompt_modules` bytes.** That would re-couple exactly what
R2 separates, and the two paths are deliberately diverging — the monolith is deleted in a later PR.

**Builder and fixer are separate skills over shared fragments (§5.6):** a builder's disposition is to
*author*, a fixer's is *minimal change*. Hand an authoring agent broken HTML and it re-authors the
slide, undoing what already passed review and — once WYSIWYG lands — a user's manual edits.

---

## Definition of done

- [ ] Every suite passes and **every guard has been sabotage-verified**, with the sabotage confirmed on
      the executed path.
- [ ] The layer-1 suite runs against the **compiled** graph with stub agents and asserts all **eleven**
      behaviours in C5's table, none of them vacuously.
- [ ] A real-model local run builds a multi-slide deck end to end: ascending release, one reviewer per
      slide, at most one fix round per position, deck review once.
- [ ] All six `agent_factory` suites pass against the moved module (private names included), and all 13
      `src.services.agent` test files still collect and pass **where they already live** — nothing moves
      them, because `agent.py` is unmodified. **None deleted** — the functionality survives, so R1's
      deletion rule does not apply.
- [ ] `prompt_modules.py`, `design_system_compiler.py` and `agent.py` are **unmodified**. Confirm with
      `git diff --stat` against the merge base.
- [ ] No skill body contains `88px`, `72px`, `56px` or `1280x720`.
- [ ] Full suite compared **by cause** to the index's baseline: no new cause, no change to the
      deploy-autoscaling cause, no test that stopped existing.
- [ ] `GraphState` is exhaustive: no node returns or reads a key it does not declare. A grep of node
      returns against the TypedDict is a cheap standing check.
