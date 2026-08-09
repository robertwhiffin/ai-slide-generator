# Agentification Core — Architect / Foreman / Builder Graph — Design

**Status:** Spec, ready for implementation planning
**Date:** 2026-08-06
**Parent:** `2026-07-30-tellr-agentic-rebuild-prd-design.md` (workstreams 4 + 7, merged)
**Scope:** Replace the single-agent HTML emitter with a LangGraph multi-agent system:
a conversational architect, a data analyst, a deterministic build-foreman service,
parallel per-slide builders, and a review→fix→review loop. Includes conversational
multi-target editing and the deck spec that both build and review are driven by.

**This is a clean-slate rebuild, not a refactor.** `src/services/agent.py` (1,863
lines), the intent-detection regexes in `src/api/services/chat_service.py`, and
`src/services/evaluation/llm_judge.py` are replaced. The only things that constrain
the design are the three integration seams in §3.

---

## 1. Why

The PRD (§1) describes today's agent as "an HTML emitter with a chat log bolted in
front of it." Four specific problems this workstream fixes:

1. **One agent, one giant prompt.** A single LangChain-classic `AgentExecutor` whose
   base instruction is *"You respond only valid HTML."* Conversation is a failure
   mode to retry away from.
2. **Serial full-deck generation.** One LLM call emits every slide, and
   `_parse_slide_replacements` (`agent.py:1047`) reverse-engineers which slides
   changed. A 15-slide deck takes a long time and the user sees nothing until it is
   entirely finished.
3. **Regex intent detection.** `_detect_generation_intent` (`chat_service.py:1768`), `_detect_edit_intent` (`:1826`),
   `_detect_add_intent` (`:1691`), and `_parse_slide_references` (`:1851`)
   infer what the user wants from ~40 brittle patterns.
4. **In-process session state.** `self.sessions` is a plain dict (`agent.py:812`),
   which is incorrect under multiple uvicorn worker processes (PRD §12.1).

### 1.1 Why workstreams 4 and 7 are merged

The PRD lists these separately, with 7 depending on 4. But the regex intent layer is
what *both* replace: 4 cannot route implicitly without displacing
`_detect_generation_intent`/`_detect_edit_intent`, and 7 is the multi-target case of
that same parsing. Splitting them means rewriting the intent layer twice. They are
therefore one spec, and the regexes are retired once.

---

## 2. Prerequisites (separate PRs, landing first)

Neither is optional, and both are verifiable on their own against current behaviour.

### 2.1 Row-per-slide schema

`SessionSlideDeck` (`src/database/models/session.py:234`) is one row per session
holding `deck_json` plus a `version` optimistic-lock counter. n parallel builders
writing that single row would 409 each other.

A staging table with a promotion step was considered and **rejected as technical
debt** — it is a shadow copy of deck state. Instead the deck becomes rows:

- **`session_slides`** — one row per slide, keyed `(session_id, position)`, carrying
  the fields `Slide` already has (`src/domain/slide.py:32`: `html`, `slide_id`,
  `scripts`, `created_by/at`, `modified_by/at`) plus `id`, `position`, and a
  **per-slide verification field** (see §5.2.4 — verification moves off the shared
  `verification_map` blob onto the row, for the same no-contention reason). **This is
  the deck's source of truth.** The reviewer that clears a slide writes its row (§5.5):
  no contention, no promotion step, no shadow copy.
- **`SessionSlideDeck`** — keeps deck-level state (CSS contract, scripts, title,
  `version`, `locked_by`/`locked_at`); loses `deck_json` as source of truth, and
  loses `verification_map` (now per-row).
- **`SlideDeckVersion`** (`session.py:296`) — **unchanged, stays a JSON blob.** A
  blob is the right shape for an immutable append-only snapshot; it is only wrong for
  concurrently-mutated live state. Two shapes for two jobs is correct, not
  inconsistent, and it keeps PRD §13's restore promise trivially satisfiable.
- **`html_content`** — retire, or derive from `knit()`. The model already marks it
  *"legacy, for raw HTML view."*
- **The deck-spec column (§4) lands in this same migration**, not a second one.

Measured blast radius: `deck_json` has 20 references, **18 of them in
`session_manager.py`** — already effectively encapsulated. `knit()`
(`slide_deck.py:323`) already does the stitching and does not care whether slides came
from JSON or rows. The largest number is `html_content`: **60 references across 12 `src`
Python files**, including the export chain (`html_to_pptx.py`,
`html_to_google_slides.py`).

Sequenced first because a schema migration on live production data (v0.4.1, real
decks) must be verifiable against known-good current behaviour — especially export,
which PRD §3 makes a no-regression gate. If the migration and the agent rewrite land
together and decks come back wrong, we cannot tell which half did it.

**This prerequisite is load-bearing twice over:** for the parallel per-slide writes
(one row per reviewer-cleared slide — §5.5), and for incremental slide delivery
(§6.2).

### 2.2 Dependency stack upgrade

`langgraph` is currently 1.0.3, present only transitively via `langchain 1.0.5`, and
not pinned in `requirements.txt` or `pyproject.toml`. Upgrading to 1.2.10 is not a
one-line pin bump:

```
langgraph==1.2.10  requires  langchain-core>=1.4.7
we pin            langchain-core==1.0.4
langchain 1.0.5   caps       langgraph<1.1.0
                                  → ResolutionImpossible
```

Verified-resolving set:

| Package | Now | After |
|---|---|---|
| `langgraph` | 1.0.3 (transitive) | **1.2.10** (explicit pin) |
| `langchain` | 1.0.5 | **1.3.14** |
| `langchain-core` | 1.0.4 | **1.5.3** |
| `langgraph-checkpoint` | 3.0.1 | **4.1.1** |
| `langgraph-prebuilt` | 1.0.x (transitive) | **1.1.0** — *not* 1.2.x; no such version exists |
| `langgraph-sdk` | transitive | **0.4.2** (the proxy's maximum) |
| `langgraph-checkpoint-postgres` | — (absent) | **3.1.1** (the Lakebase saver) — the proxy **403s 3.1.2**, so pin 3.1.1 |
| `psycopg` (psycopg3) | — (absent) | **added** (`>=3.2.0`) |
| `psycopg-pool` | — (absent) | **added** (`>=3.2.0`) — required by the saver |
| `orjson` | — (absent) | **added** (`>=3.11.5`) — required by the saver |
| `psycopg2-binary` | 2.9.10 | **removed** |

The `langgraph-prebuilt` / `langgraph-sdk` / `psycopg-pool` / `orjson` rows and the
3.1.1 pin were established by proxy dry-runs while planning PR2; an earlier draft of
this table was incomplete. **Treat the pins as verified-against-the-proxy, and re-verify
before merging** — proxy availability moves.

**Postgres checkpointer — decided: adopt `langgraph-checkpoint-postgres` and upgrade to
psycopg3.** §5.7 requires a Lakebase-backed checkpointer, and `langgraph-checkpoint`
4.1.1 ships only `base`/`memory`/`serde` savers — the Postgres saver lives in the
separate `langgraph-checkpoint-postgres`, which requires `psycopg>=3.2.0` (psycopg3),
conflicting with the current `psycopg2-binary` pin. Rather than hand-roll a custom
`BaseCheckpointSaver` over psycopg2, we take the official saver and move the app to
psycopg3. This is a fundamental redesign; carrying the maintained checkpointer is worth
a driver upgrade.

The migration is smaller than the driver swap sounds: **no code imports `psycopg2`
directly** (verified — it is used only as SQLAlchemy's default dialect behind a bare
`postgresql://` URL at `database.py:237,255`). SQLAlchemy 2.0 speaks psycopg3 via the
`postgresql+psycopg://` scheme, so the change is chiefly the connection-string scheme
plus the requirements pin, not a rewrite. The **OBO token-injection hook**
(`database.py:306`, `provide_token`) and `sslmode=require` must be re-verified on the
psycopg3 dialect — that is the one place the driver swap could bite — and this must be
proven against the Databricks pip proxy (both new packages resolvable there).

Also in this PR:

- **Reconcile the `mlflow` pin conflict** (PRD §12.1 flags it; it is real):
  `requirements.txt` says `mlflow==3.6.0`, `pyproject.toml` says `>=3.11.0,<4`.
  `langgraph 1.2.10` resolves fine against `mlflow==3.11.0`, so the upgrades are not
  in tension.
- **Verify against the Databricks pip proxy, not just locally.** The proxy 403s some
  latest versions (`mlflow==3.15.1`, `databricks-sdk==0.125.0`) while serving
  3.14.0 / 0.120.0. PRD §12.1's dependency-resolution risk is about the Apps build,
  so resolution must be proven where the Apps build runs.
- **Keep** the `fastapi>=0.104.0,<0.137` / `starlette<1.3` bound
  (`pyproject.toml:12-17`). It guards a real APIRouter regression covered by
  `tests/unit/test_app_wiring.py`.
- **Pin `langchain-classic`** or remove it. `agent.py` imports
  `langchain_classic.agents` but it arrives only transitively via
  `langchain-community`. It disappears when `AgentExecutor` is deleted, but must not
  be left dangling meanwhile.

Blast radius is small: no code imports the top-level `langchain` meta-package. All
imports are `langchain_core.*` (18 sites), `langchain_community.chat_message_histories`
(2), and one `langchain_classic.agents`. The `chat_message_histories` count is 2 because the
surviving surface is `chat_service.py:18` after `agent.py:21` is deleted in this workstream.

---

## 3. The three seams

Everything else is ours to redraw. These are not.

### 3.1 Frontend

Generation is reached through **four** entrypoints in `frontend/src/services/api.ts`:

| Entry | Line | Shape |
|---|---|---|
| `streamChat` | :782 | SSE, live streaming |
| `submitChatAsync` + `pollChat` | :876, :910 | fire-and-poll, `after_message_id` cursor |
| `startPolling` | :933 | polling driver |
| `sendMessage` | :584 | non-streaming |

**The binding constraint:** `slides` is carried only on the terminal `COMPLETE` event
(emitted at `streaming_callback.py:371`; `StreamEvent.slides` is documented "for
complete event" at `streaming.py:34`). There is no incremental slide event today.
Per-slide delivery (§6.2) therefore changes **both** transports.

The polling path is the harder one: `poll_chat` (`chat.py:557`) does not relay live
events at all — it reads persisted `SessionMessage` rows and converts them via
`msg_to_stream_event` (`session_manager.py:2000`), which hardcodes three types and
defaults everything else to `assistant`.

### 3.2 Lakebase

`src/database/models/session.py`. Worth keeping and building on:

- `version` — optimistic lock; clients send what they read, stale writes get **409**.
- `locked_by`/`locked_at` — deck lock, explicitly for "an agent is modifying slides",
  auto-expiring.
- `verification_map` — today a content-hash-keyed blob kept out of `deck_json` so
  findings survive regeneration; `compute_slide_hash` (`src/utils/slide_hash.py:52`)
  already exists. The **content-hash keying is the right model** for per-slide findings
  (PRD §12.1 "finding persistence") and is kept; the **shared blob is not** — it moves
  onto the per-slide row (§2.1, §5.2.4) to avoid reintroducing single-row write
  contention.
- `UserSession.agent_config` (JSON) and `experiment_id` — per-session config and
  MLflow linkage already have homes.

### 3.3 Tools

`src/services/tools/{genie,mcp,vector,model_endpoint,agent_bricks}_tool.py` plus
`search_images`. Three properties survive the rebuild:

- **`<untrusted-data>` wrapping + `cap_tool_output`** at the boundary
  (`agent.py:485-486` for image search, `:566` for Genie) — the prompt-injection
  defence.
- **Session-bound closures** (`agent.py:464`) — tools capture `session_id` at
  creation to avoid cross-request races.
- **OBO token propagation** to every agent's tool calls (PRD §12.1).

---

## 4. The deck spec

PRD §12's first open question. The deck spec is the **single source of truth for both
building and reviewing**, persisted in Lakebase (column added in the §2.1 migration).

### 4.1 Structure

**Deck level** — architect-authored, stable across the deck:
- audience, purpose, the argument being made, the action the reader should take
- narrative arc: the ordered beats the deck delivers
- design contract: the CSS/style contract + image guidelines
- resolved data: the analyst's synthesis and key figures, with provenance

**Slide level** — one per slide, architect-authored, foreman-distributed:
- position, purpose / narrative role ("establishes the problem", "the ask")
- content brief: what this slide must convey
- **assumes**: what prior slides have established
- **hands off**: what it sets up for the next
- data references: which resolved figures it may cite

### 4.2 Review criteria are deliberately NOT in the spec

Criteria stay agnostic (accuracy, style, layout) and live in the **review skill**
(§5). The spec *describes* the deck — "exec comms level" — and the review skill picks
that up and interprets it.

Rationale: if the architect authored its own review criteria, the thing being
reviewed and the standard it is reviewed against would share an author, and review
independence would be nominal. This way the architect can only describe what it
built, never weaken the bar. Extensibility comes from adding criteria to the skill.

### 4.3 Spec persistence and back-fill

The spec is persisted per session. When absent, the architect **infers one from the
existing deck HTML once, then persists it**. Three cases need this:

- decks created before the cutover (PRD §13 requires adopting a deck the engine did
  not author, "inferring or back-filling structure rather than refusing");
- decks built by the one-shot MCP path, where nobody conversed;
- decks edited directly by the user, where HTML has drifted from the spec.

The spec is **advisory for content that already exists** — reviewers are what catch a
slide contradicting it (PRD §7.1 already assigns them that job), so no separate
reconciliation path is built.

### 4.4 Rebuild triggers

**Rule: any change to slide HTML kicks off a deck-spec review/update.** Deliberately
dumb — the alternative is classifying "meaningfulness," which is the brittle-heuristic
trap the regex layer already fell into.

Every mutation path that must trigger it:

| Path | Route | Note |
|---|---|---|
| Direct slide edit | `slides.py:178` `PATCH /{index}` | WYSIWYG (ws 8) |
| Reorder | `slides.py:111` `PUT /reorder` | **mutates the narrative arc with no HTML change** — a content-hash trigger would miss it entirely |
| Duplicate | `slides.py:246` | slide added |
| Delete | `slides.py:314` | slide removed |
| Version restore | `slides.py:795` | whole deck replaced |
| Tour demo slides | `tour.py:117` | slides appended |
| Agent edit | chat | already spec-driven |

Deck-level **design-contract** changes (switching `slide_style_id`, or a future
deck-CSS edit) are deliberately *not* in this table: they mutate a deck-level spec
field with no per-slide HTML change and follow the confirm-then-rebuild-all path in
§4.6, not the automatic per-slide trigger.

- The rebuild is **async and debounced/coalesced**. A WYSIWYG session emits many
  small edits; an LLM spec review per edit batch would be brutal on cost and latency,
  and must never make a direct edit feel slow (PRD §7.4). The spec may go briefly
  stale; it is advisory and reviewers are the backstop.
- **`SlideDeckVersion` must snapshot the spec** alongside `deck_json`,
  `verification_map_json` and `chat_history_json`. Otherwise restoring a save point
  leaves a spec describing a deck that no longer exists.

### 4.5 Propagation is provenance-directed (the cycle break)

"Any HTML change updates the spec" plus "a spec edit rebuilds slides" is a
self-sustaining loop that spends money per lap. It is broken by the **origin** of the
change — one hop, never two:

- **Human-originated HTML change** → the spec updates to *describe* what the user
  did. **Terminates.** The slide is never rebuilt: the user already made the slide
  they wanted, and rebuilding would overwrite their work with the agent's
  interpretation of it — actively hostile once WYSIWYG lands (ws 8).
- **Human-originated spec change** (via conversation) → rebuild affected slides. The
  resulting HTML change is **agent-originated**, so it does not re-trigger a spec
  update; the spec already says what was intended.

**No stored provenance flag is needed — origin is known from the code path.** The two
writes arrive through structurally different entry points: a human HTML edit comes via
the `PATCH /slides/{index}` route (the WYSIWYG path, §4.4), while an agent write
happens inside the graph when a reviewer commits a row (§5.5). Each caller already
knows which it is, so the "does this write trigger a spec update?" decision is made at
the call site — the HTML-change trigger fires only on the human route. Nothing has to
be persisted on the row and read back later to reconstruct origin.

(This is why `Slide.modified_by` is *not* pressed into service: it stamps the
logged-in human's username on both paths — `chat_service.py:2373` on the agent-edit
path, `:2650` on the direct path, both via `get_current_username()` — and is already
load-bearing as user-facing author attribution at `SlideTile.tsx:310` and
`SessionHistory.tsx:367`. It could not carry origin even if we wanted it to, and it
does not need to.)

### 4.6 Deck-level spec edits

Slide-level is simple: change slide 6's brief, rebuild slide 6. A deck-level change
("actually this is for a CFO, not engineers") logically invalidates every slide.

**Re-review all, rebuild only what fails, and tell the user first:**

1. Reviewers score every slide against the **new** spec (cheap calls, parallel).
2. Only slides that actually contradict it are rebuilt — this preserves still-valid
   work, including manual user edits.
3. The architect reports what it is about to rebuild before doing it.

This needs no new mechanism: scoring slides against the spec is already the
reviewers' job. A blanket rebuild-all was rejected — expensive, and it destroys
manual edits on slides that were still fine.

**Design-contract changes are the exception — they confirm first, then rebuild all.**
Changing the deck's *design contract* (switching `slide_style_id` on the agent config,
or a future deck-CSS edit) mutates a deck-level spec field with no per-slide HTML
change, so it is not one of the §4.4 slide-HTML triggers. And unlike an audience
change, a restyle genuinely affects every slide — re-review-then-selective-rebuild
would flag all of them anyway. So a design-contract change is an **explicit,
user-confirmed action**: the architect asks *"this restyles the whole deck and rebuilds
every slide — proceed?"* before kicking off the rebuild. This is the one place a
rebuild-all is correct, and gating it on confirmation keeps it from firing by accident
(and from silently discarding manual per-slide edits).

### 5.1 Definitions are in-repo skills

**Each agent role is a skill: a versioned bundle of instructions + output schema +
tool grants**, living in the repo, reviewed in PRs, tested in CI.

Not a single system prompt, for a structural reason: `AgentConfig`
(`src/api/schemas/agent_config.py:58`) is **singular** — one `system_prompt`, one
`slide_editing_instructions`, one `slide_style_id`, one tool list. With seven agent
roles it cannot express per-role behaviour.

`src/core/prompt_modules.py` is already a skill system in embryo: 11 named composable
modules (`BASE_PROMPT`, `SLIDE_GUIDELINES`, `CHART_JS_RULES`, `IMAGE_SUPPORT`, …)
assembled by two builder functions. The composition instinct is right; what is wrong
is that it composes into one prompt for one agent. **Skill composition is therefore a
first-class feature**, not an afterthought.

Two decisions in this spec *require* skills rather than prompt strings:

1. **Review independence must be structural.** Criteria live in a review skill so the
   architect cannot weaken its own bar. In one shared prompt blob that independence is
   nominal — same blob, same author, same edit.
2. **"Extensibility by adding criteria" needs a versioned artifact.** A skill carries
   the criteria list *and* its output schema together, versioned as a unit. A prompt
   fragment in a DB column cannot be validated against the schema it must produce.

There is also an MLflow consequence: PRD §7.1 wants verdicts as first-class
assessments, and the eval harness can only distinguish a quality regression from a
criteria edit if the criteria are versioned and identifiable.

**In-repo is making existing reality explicit, not adding a restriction.** Core agent
behaviour already lives in `prompt_modules.py`. While the settings UI routes
(`src/api/routes/settings/`) expose only deck prompts, slide styles, contributors and
identities, `system_prompt` and `slide_editing_instructions` are writable via
`PUT /agent-config` and `POST /profiles` (`agent_config.py:104`, `profiles.py:124`),
and are actively consumed at runtime (`agent_factory.py:155-168`).

The existing split is preserved and gains a third axis (tone, §5.2):

| Stays admin/user-editable (user-facing taste) | Becomes in-repo skills (agent innards) |
|---|---|
| Deck prompts (`SlideDeckPromptLibrary`, has UI) — *what* the deck says | architect / analyst / builder / fixer / reviewer behaviour |
| Slide styles (`slide_style_library` + `image_guidelines`, has UI) — *how* it looks | review criteria + output schemas |
| Tone / communication guidelines (§5.2) — *how* it reads | |

Consequence: `ConfigPrompts.system_prompt` and `slide_editing_instructions` (currently
populated on profiles and writable via agent-config routes) are retired. This is a
deliberate breaking change — existing custom prompts must be migrated to in-repo skills,
and the migration story should be documented in the implementation plan.

**Seven agent skills:** `architect`, `data_analyst`, `builder`, `fixer`,
`build_reviewer`, `fix_reviewer`, `deck_reviewer`.

**The foreman is not a skill — it is a deterministic orchestration service** (§5.5).
Everything it does (dispatch one builder per slide from the spec's slide list, route
builder→reviewer, route findings by the reviewer's own objective/subjective tag, count
landed slides to trigger deck review, enforce the concurrency cap / ascending dispatch
/ retry queue, release the reorder buffer) is deterministic. The one "AI decision" —
what to fix versus surface — was already made upstream by the reviewer's
self-classification (PRD §7.2). So the foreman holds no LLM reasoning, maps onto
LangGraph's topology + conditional edges + `Send` fan-out + a scheduler, and becomes
directly unit-testable rather than something tests must stub (§9).

### 5.2 Roles

Agents are drawn as `[ ]`; the foreman is a `( )` service, not an agent.

```
  USER ⇄ [ARCHITECT] ── narrative, design intent, tone, converses, surfaces findings
              │             (this IS the supervisor — no separate router tier)
              │  structured data request
              ├──▶ [DATA ANALYST] ──▶ gatherers: Genie | Genie Agent | MCP | tools
              │         └── success | missing-data | no-tool  (synthesis, not analysis)
              │
              ▼  deck spec (structured output)
        (FOREMAN)  ── deterministic orchestration service: dispatches builders,
              │        distributes narrative contracts, routes the build chain,
              │        sole CSS writer. No LLM reasoning.
      ┌───────┼────────────────┐
      ▼       ▼                ▼
 [BUILDERS] [REVIEWERS]  (reviewers write clean/chosen HTML ⇄ Lakebase rows)
 (1/slide,  → [FIXER] → [FIX REVIEWER]
  parallel)  └── 1 fix round max ──┘
                ▼
        [DECK REVIEWER] (after all slides land; non-blocking)
                ▼
        [ARCHITECT] surfaces findings to user
```

The rest of §5.2 defines each agent in detail: its purpose, what it receives, what it
returns, and its testable contract.

#### 5.2.1 Architect

The conversationalist and orchestrator. It holds the session state and is the only
agent the user talks to directly. There is no separate router tier — there is no
reason for the user to talk to a router that proxies to the persona they actually
want. On the one-shot path (§6.4) it is entered at a different edge with conversation
skipped, which is how PRD §9.2's contract is preserved without a second code path.

**Behaviour — build comprehensive, data-driven narratives.** Its headline job is to
propose and refine a narrative, not to wait for a fully-specified brief (PRD §5.1).
Some of today's generation prompt material (`prompt_modules.py` — `GENERATION_GOALS`,
`PRESENTATION_GUIDELINES`) is a starting point for this skill.

**Data awareness.** The architect must know what data is *available to ask for* without
holding the tools itself (the analyst holds them — §5.2.2). It is handed the **tool
manifest** — names and descriptions from `AgentConfig.tools` (Genie `space_name` +
`description`, MCP `server_name` + `description`, vector index names, etc.,
`src/api/schemas/agent_config.py:9-49`) — as context. This lets it (a) make specific
data requests to the analyst and (b) surface those asks back to the user ("I'll pull
revenue-per-customer from the Sales Genie space — is that the right source?").

**Extensible tone (new — third config axis).** Tone and communication style are
**not** centrally mandated. The architect skill reads a **tone/communication
guideline** from config and applies it. This is distinct from deck prompts (*what* the
deck says) and slide styles (*how* it looks): tone is *how it reads*. **This
workstream ships the consumption hook plus a sensible in-repo default; the
user-authoring UI and its library model are a separate, later PR** (like row-per-slide
— the graph core only assumes the hook exists). See §10.

**Two output types — this is the testable contract:**
- **Conversational output** → prose directed to the user (chat).
- **Structured output** → the deck spec (§4) handed down to sub-agents. The structured
  form is what specs and tests assert against; the prose is not.

#### 5.2.2 Data analyst

Takes a data request from the architect and produces one of **three outcomes**:

1. **Success** — got the data, returns a synthesised result.
2. **Missing data** — the tool ran but has nothing (e.g. "checked the numbers
   database; no rows for that company").
3. **No tool** — no tool is available for the request (e.g. asked to web-search with
   no web-search tool granted).

**Its real task is synthesis, not analysis.** The retrieval tools do the analysis and
the summarisation — in a Databricks deployment Genie is the primary tool and already
returns a summary. So:

- **Single source → pass through, do not re-summarise.** Summarising an
  already-summarised Genie answer degrades it.
- **Synthesis only engages with 2+ sources** — combining multiple tools/MCPs into one
  argument is the only case that needs the analyst to reason over results.

Whether an output is already summarised is a **per-tool property declared on the
tool**, not something the analyst infers. (This resolves the earlier `cap_tool_output`
truncation concern: retrieval tools return summaries sized to survive the cap, rather
than raw rows that get clipped mid-reasoning.)

**Concentrates user-scoped data access in one role** — the natural OBO boundary.

**Contract — standardise the request so the response is testable.** A poor request
("revenue per customer over time") is untestable because it under-specifies: what time
bound, which metrics, how summarised, what units. So the analyst receives a
**structured request** (metric, time bound, grouping, units, …) and returns a
**structured response** whose shape is one of the three outcomes above. Standardising
the request is what lets §9 assert that a valid request yields one of three valid
response shapes — the deterministic-ish test for a non-deterministic agent.

#### 5.2.3 Builders

Straightforward and ephemeral. **Receives** one slide's instructions plus the style
sheet (the CSS contract). **Produces and returns** that slide's body HTML. Emits body
HTML only, never `<style>` — deck-level CSS has a single writer (§5.5), and n builders
each emitting `<style>` would collide on shared deck state (`knit()` at
`slide_deck.py:323` emits one `<style>` block; `update_css()` at :97 delegates to
`merge_css()`, which merges selectors: replacement selectors override matching ones,
new selectors are appended, and existing selectors not in the replacement are preserved).

One hazard is already mitigated: `_deduplicate_canvas_ids` (`agent.py:984`) suffixes
canvas IDs with a per-call uuid, so parallel builders will not collide on Chart.js
canvas IDs provided each call dedups independently. This behaviour must be preserved.

#### 5.2.4 Build reviewer

**Receives** a builder's output. **Evaluates** it against criteria defined in the
review skill, returning the **structured output also defined in the skill** — one
reviewer with multiple criteria, not three agents per slide, so scalability comes from
adding schema fields and the cost profile stays n rather than 3n. Each finding is
self-classified **objective** (auto-fixable) or **subjective** (surface to user), per
PRD §7.2 — the reviewer is best placed to know which.

**The build reviewer writes clean slides to Lakebase.** If the review passes with no
significant (objective) fix required, the build reviewer writes the slide's
`session_slides` row — HTML and its verification record together, in the one write
(verification is a per-row field now, not a shared blob). This means **an unreviewed
slide never exists in Lakebase** (see §5.5 for why writes moved from builders to
reviewers).

**Verification is a per-slide field, not a shared blob.** `verification_map` is
currently a JSON-blob column on the single `SessionSlideDeck` row, and
`save_verification` (`session_manager.py:1136–1148`) does a read-modify-write of the
whole blob: load JSON, add the content-hash key, serialize back. With N reviewers
committing in parallel (the whole point of the architecture) that is a lost-update
race — every reviewer reads the same initial map, and all but the last write is
clobbered. It would reintroduce exactly the single-row contention the row-per-slide
prerequisite exists to remove.

So **verification moves onto the slide's own row**: the review record is written to
the reviewer's `session_slides` row alongside its HTML, in the same write. No shared
blob, no read-modify-write, no cross-reviewer contention — the same reason the deck
became rows in the first place. **This is folded into the §2.1 row-per-slide
prerequisite PR** (the `session_slides` schema carries a verification field, and
`save_verification`'s blob path is retired). Keying stays by content hash so records
still survive regeneration (PRD §12.1); it simply lives per-row rather than in one map.

#### 5.2.5 Fixer

Ephemeral. **Receives** the builder's output and the reviewer's output, and is
prompted to make **minimal edits** that resolve the objective findings. A builder's
disposition is to *author*; a fixer's is *minimal change* — hand an authoring agent
broken HTML and it re-authors the slide, potentially undoing what already passed
review or (once WYSIWYG lands) a user's manual edits. Builder and fixer are therefore
separate skills over shared fragments (§5.6).

#### 5.2.6 Fix reviewer

**Receives** three things: the builder's original output, the build reviewer's finding,
and the fixer's output. **Evaluates and decides** whether to accept the fixed version
or keep the original — it is a chooser, not just a re-checker. This is what makes a
bad fix safe (PRD §7.3): if the fix resolved the finding but introduced a new defect,
the fix reviewer keeps the original and surfaces the finding instead.

Original + new gives it a **diff**, so the "did the fix introduce a new defect?" check
is scoped to what changed. It degrades gracefully (if the fixer rewrote the whole
slide, the diff is the whole slide, so it becomes a full review), and it detects a
fixer that changed nothing (identical HTML) or overreached (diff far larger than the
finding warranted).

**The fix reviewer writes the winning version to Lakebase** — fixed or original,
whichever it chose. (§5.5.)

#### 5.2.7 Deck reviewer

Runs once all slides have landed, for genuinely global checks — narrative arc,
conclusion, cross-slide repetition. Per-slide reviewers cannot see cross-deck
consistency, so all global checks belong here; per-slide reviewers *do* receive the
CSS contract, so they catch local violations of the deck's design system. Its findings
route to the main chat (deck-level) per PRD §6.3. Non-fatal: it runs after the deck is
already usable (§8).

#### 5.2.8 Foreman (orchestration service, not an agent)

See §5.5. The foreman receives the deck spec, dispatches builders and routes the
build chain, returns status updates and surfaced findings up to the architect↔user
chat, and is the **sole writer of deck-level CSS** — design is *decided* by the
architect and *enforced* by the foreman (deciding and enforcing are different jobs).
It contains no LLM reasoning.

### 5.3 Agent lifetimes

**The only durable agent context in the system is the architect's conversation.** The
only durable *state* is the deck spec and the slide rows. Everything else is transient
by construction.

| Component | Lifetime | Holds |
|---|---|---|
| Architect | the session | the conversation |
| Data analyst | one gathering request | nothing between requests |
| Builders | **ephemeral** — one slide, one invocation | nothing |
| Fixer | ephemeral — one fix | nothing |
| Reviewers | the review→fix→review loop only | nothing (findings are *input*) |
| Deck reviewer | its own pass | nothing |
| *Foreman (service, not an agent)* | one build turn | deck-wide turn state (what has landed / is outstanding) — this is **graph/checkpointer state**, not agent memory |

**Findings are input, not memory.** Reviewers are briefed with the finding rather than
remembering it. Because the fix loop is capped at 1, re-review input is bounded to
exactly *finding + original HTML + new HTML* — never a growing history. Reviewer
*state* would grow unboundedly; input is fixed-size.

Two properties this buys:

- **Reorder has zero agent-state consequence.** No agent holds per-slide state across
  turns, so a reorder updates row positions and the spec's arc, and nothing else.
  Nothing to migrate, renumber or invalidate. Had reviewers been session-durable and
  keyed by slide index, every reorder would have had to rewrite their state, and any
  missed case would be a stale-finding bug. The lifetime rule removes the whole
  failure class.
- **Context clearing is trivial.** Clearing drops the architect's conversation and the
  transcript and keeps the deck spec. Every other agent starts empty on every
  invocation, so no hidden state can survive a clear and make the agent "remember"
  something the user cleared.

### 5.4 The build chain

```
(FOREMAN) ─dispatch─▶ [BUILDER] ─▶ [BUILD_REVIEWER] ─┬─ clean ─▶ writes row ─▶ (FOREMAN)
                                                      │
                                    (objective finding)
                                                      ▼
                                   [FIXER] ─▶ [FIX_REVIEWER] ─▶ writes winner ─▶ (FOREMAN)
                                                      │  (fixed OR original)
                    (subjective findings) ────────────────────────────▶ surfaced
                    (all slides landed?) ─────────────────────────────▶ [DECK_REVIEWER]
```

- **builder → build reviewer is a direct edge.** The reviewer starts as soon as its
  slide exists; no foreman round-trip.
- **Findings return to the foreman**, because the foreman holds the deck-wide turn
  state: it routes objective findings to the fixer and surfaces subjective ones, and
  it counts landed slides to know *when all have landed* so deck review can start. A
  builder knows only about its own slide. This routing is code, not an LLM call — the
  reviewer already tagged each finding objective/subjective (PRD §7.2), so the
  foreman only acts on that tag.
- **The fix loop is capped at 1, always.** A defect surviving its one fix becomes a
  surfaced finding, never an infinite retry. Nothing is silently dropped.
- **Re-review uses a fresh reviewer instance**, not the same conversation. An agent
  asked "was your own finding addressed?" is biased toward defending or confirming it,
  which is not an independent check. Fresh-and-briefed is structurally identical to
  the first review, so there is no separate "re-review mode" to build.

### 5.5 Reviewers write to Lakebase; the foreman is a service

**The reviewer that clears a slide writes it** — not the builder:

- If the build review passes with no objective fix, the **build reviewer** writes the
  slide's `session_slides` row — HTML and the verification record in one write (§5.2.4).
- If a fix round runs, the **fix reviewer** writes the version it chose (fixed or
  original).

The invariant this buys: **an unreviewed slide never exists in Lakebase**, with one
exception: a terminal-failure placeholder. When a builder fails after retry, a visibly-marked
placeholder is written to preserve the deck's completeness (§8); this placeholder is a terminal,
unreviewed state that must be treated as "committed/landed" for both the reorder-buffer release
query (§6.2) and the all-slides-landed deck-review trigger (§5.4, §6.1), so the deck reviewer
runs and the user can retry the position individually. Content and its verification record are
written together for all other slides, and there is no window in which a raw builder output is
visible before review. This is why the earlier "builders write their own row" invariant moved
to the reviewers — each reviewer still writes only its own slide's `(session_id, position)` row,
so row-per-slide and no-contention both hold. The exact row representation of the placeholder
(flag, sentinel, or other marker) is an implementation detail.

The **foreman is a deterministic orchestration service, not an agent** — see §5.1 for
why every one of its responsibilities is deterministic. In LangGraph terms it is the
graph topology, the conditional edges, the `Send` fan-out for parallel builders, and
the scheduler enforcing the concurrency cap / ascending dispatch / retry queue (§8).
It holds deck-wide turn state (what has landed, what is outstanding, pre-fix HTML held
until the fix reviewer runs) as **checkpointer state** — durable in Lakebase and
multi-worker safe, never in-process memory.

### 5.6 Builder and fixer are separate skills

A builder's job is to *author*. Hand an authoring agent broken HTML and it will
re-author the slide — possibly resolving the finding while changing things that
already passed review, and once WYSIWYG lands, potentially overwriting a user's manual
edits. A fixer's core instruction is *make the minimal change that resolves this
finding*, which is nearly the opposite disposition.

Both write slide HTML, so both must satisfy the CSS contract, the chart rules and
image handling — those fragments are shared. This is the same split
`prompt_modules.py` already makes between `build_generation_system_prompt` (:296) and
`build_editing_system_prompt` (:324) over shared modules.

### 5.7 State and the checkpointer

Graph state persists to **Lakebase**. This is a correctness requirement, not a
preference: production runs multiple uvicorn worker *processes*, so state shared
across requests must be visible to all workers or able to detect its own staleness
(PRD §12.1). The in-process `self.sessions` dict is the bug class being removed.

---

## 6. Data flow

### 6.1 Interactive build turn

User message → architect. If the intent is discussion, it replies and nothing touches
the deck (PRD §4.1: no brainstorm/build toggle). If it needs data, the architect sends
a structured request to the analyst, which returns success / missing-data / no-tool.
When the intent is to build, the architect writes or updates the deck spec and hands
it to the foreman service, which dispatches builders in parallel. Each builder hands
directly to a build reviewer, and the reviewer that clears a slide writes its
`session_slides` row (so an unreviewed slide never persists — §5.5). Findings return
to the foreman: objective → fixer → fix reviewer (which writes the winning version);
subjective → surfaced. When all positions are committed, the deck reviewer runs behind
a non-blocking flag. The architect surfaces findings — deck-level to the main chat,
slide-level to the per-slide drawer (PRD §6.3).

### 6.2 Incremental, sequentially-ordered slide delivery

Slides must appear one after another in index order, even though builders complete out
of order. This is the user-visible payoff of parallelism, so it is in scope here.

**The reorder buffer is not a data structure — it is a query:** release position *n*
once all positions *< n* are committed. Because the truth is the `session_slides`
rows, this is inherently multi-worker safe; an in-process buffer would be invisible to
the worker serving the next poll.

- **SSE:** a new `slide_ready` event carrying `{position, html, scripts}`.
  `StreamEvent` already has optional fields, so this extends without breaking existing
  consumers.
- **Polling:** a **slide cursor** alongside the existing `after_message_id`, reading
  committed rows directly. The alternative — persisting slide-ready as a
  `SessionMessage` — is rejected: it pollutes the chat transcript with build
  mechanics, which matters more now the transcript is user-visible and clearable.

### 6.3 Edit turn (multi-target)

Same graph. The architect resolves natural-language references ("slide 5", "the
pricing slide") against the deck spec — **no selection state, no base64
`slide_context` round-trip.** Multi-target is simply n ≠ all: "slide 5 X, slide 6 Y,
slide 10 Z" decomposes into three independent per-slide edit intents, each dispatched
and reviewed separately. This is PRD §3's headline criterion and it needs no new
machinery — it is the build path with a subset of positions.

### 6.4 One-shot turn (MCP / skills)

Enters at the architect with conversation skipped; the narrative comes from the
prompt. Runs to completion — full build, review, fix — before returning the deck plus
a review summary. Interrupts disabled. Ambiguity is resolved by choosing a sensible
default and reporting assumptions in the summary (PRD §5.1), never by blocking.
`create_deck` / `edit_deck` contracts are unchanged, so the TAP builder, DAIS agenda
curator and KPMG pricing skills need no coordinated change.

---

## 7. UI

### 7.1 Two views, one conversation

**A toggle: view slides ⇄ view spec.** One conversation throughout — not a second
chat, not a filtered view.

Rejected alternatives:
- Putting the spec in the per-slide drawer: it congests what is already power-user
  surface, and there is no natural home for the *deck-level* spec.
- A second conversation in a spec pane: two histories to persist, restore, snapshot
  and reconcile — and the architect would hold spec decisions the main chat never saw,
  which is PRD §5.1's "silently dropped" failure arriving by another door.

The spec view is **read-only plus discuss**: editing stays conversational, so the
architect remains the sole author and there is one write path. Directly editable spec
was rejected — a second author racing the async rebuild loop could silently overwrite
the user's edits.

**View is a hint, never a mode.** Intent comes from language, not view state.
`SelectionContext` was deleted in workstream 6 precisely to stop UI state gating
intent; that must not be walked back. "Tighten the arc" edits the spec; "make slide 5
bolder" edits the slide — whichever view is open.

The shipped viewer already supports this: `FeedbackDrawer.tsx:74` is an extensible
tabbed shell, and `frontend/src/types/finding.ts` already types findings as a union
(`content | design | narrative`) with Apply/Dismiss/Discuss callbacks, currently
wired to `[]` in production. **The reviewer's strict schema and that union must be
kept in step** — that is the seam where they meet.

### 7.2 What the deck spec unlocks: context clearing

`_hydrate_chat_history` (`chat_service.py:1636`) replays every user and assistant turn
into the agent's context on every request — unbounded growth, the whole conversation
every time. Clearing today would be pure loss, because the transcript *is* the agent's
only memory of what was agreed.

The deck spec changes that. It is a **structured compaction** of the conversation:
once it holds what was decided, the transcript is just the path taken to get there.
So **clearing drops both the agent context and the transcript** (normal harness
behaviour), keeps the spec, and loses nothing that was agreed. PRD §5.1's "remember
the shaping" is satisfied by the spec rather than by hoarding turns.

This also removes a real cost problem: long sessions currently pay for the entire
history on every turn.

### 7.3 Agent activity in the chat

**Attribution, not a new UI.** The chat already renders agent activity:
`StreamEventType` includes `tool_call`/`tool_result` (`api.ts:62`) and
`Message.tsx:93` already renders tool calls with their arguments. This is one optional
`agent` field on `StreamEvent` plus a label in the existing renderer.

This is required rather than polish: with builders running in parallel, unattributed
events make the chat an interleaved stream of anonymous tool calls from many
concurrent agents — actively worse than today's single-agent view. Parallelism forces
attribution. It is also the visible payoff for the PRD §7.4 latency trade (watching
progress is not watching a spinner) and for the §1.1 showcase story.

- **In scope:** `agent` attribution on events; agent lifecycle messages ("dispatching
  data analyst", "dispatching 10 slide builders", "reviewing slide 4"); tool calls
  attributed to the emitting agent.
- **Deferred to the MLflow observability workstream (PRD §7.5):** a dedicated
  agent-activity panel or graph visualisation, per-agent expandable trace trees, live
  per-agent token and cost. Those belong next to the trace data.
- **Coalesce at the fan-out.** "Dispatching 10 slide builders" as one message, then
  progress as slides land — not ten "builder N started" lines, which would drown the
  conversation. Verbose per-builder detail is what the MLflow trace is for.
- **Displayed, not conversational state.** `_hydrate_chat_history` already excludes
  `reasoning`/`info`/`tool_*` from replay as agent-internal noise; activity messages
  get the same treatment, keeping them out of the architect's context.

### 7.4 Per-slide and deck-level review progress

Because reviewers write the slide (§5.5), **a slide appears in the viewer only once it
is review-clean** — it never appears and then silently changes under the user (no
flapping). The cost is that first-paint of each slide includes one review pass; this
is a deliberate refinement of PRD §7.4's "show the deck first, reviewers run after"
(see §11). Objective fixes happen before the slide is shown; **subjective** findings
still arrive afterwards into the drawer, so the masking §7.4 relies on still holds for
those.

The whole-deck pass gets an **"Agentic deck review in progress" flag, which must be
non-blocking**: editing, export and presenting stay live while it runs (PRD §7.4). A
flag that gates export is a serial gate wearing a spinner.

### 7.5 Permissions

**Spec visibility equals deck visibility.** Whoever can see the deck can see the spec,
including contributors and read-only viewer links — the deck's data is already shared
with them.

---

## 8. Error handling

- **Builder failure:** bounded retry (once), then a visibly-marked **placeholder** the
  user can retry individually. The deck always completes. Failing the whole turn was
  rejected: discarding 14 good slides for one transient 429 is a severe regression
  versus today. This satisfies PRD §9.3 — "return the best available deck plus the
  surfaced problem; never hang."
- **Stalled-buffer guard.** Strict in-order release means a stuck position 7 would
  block visible delivery of 8–15 even though they are done. The buffer therefore has a
  **release timeout**: if position *n* has not committed within a bound after *n+1* is
  ready, later slides are released and *n* slots in late or becomes a placeholder.
  Sequential ordering is the default, not a hostage — otherwise PRD §14's
  latency-regression risk arrives by the back door.
- **Concurrency cap: 15 builders**, dispatched in **ascending position order.**
  - Ascending order is load-bearing, not tidiness. Release requires all positions
    *< n* committed, so dispatching lowest-first means releases begin almost
    immediately. Dispatching from the end would leave the buffer holding every
    finished slide while position 0 had not started, and the user would see nothing.
  - **As slots free, take the lowest outstanding position.** On a 40-slide deck,
    0–14 dispatch first; a freed slot goes to position 15, not to whatever is
    convenient. Ascending order holds for the whole queue, not just the first batch.
  - **Retries jump the queue.** A failed position 3 retrying outranks an unstarted
    position 20, otherwise the buffer stalls behind a retry waiting for a slot. The
    rule that satisfies both: always dispatch the lowest outstanding position, and a
    retry re-enters as its own position.
  - The common case is unaffected: a 15-slide deck fits entirely in the first batch —
    fully parallel, no queueing.
  - The cap is also the natural cost-control lever for PRD §14.
- **Fix loop exhaustion:** capped at 1. A surviving defect becomes a surfaced finding
  and the user is told what could not be fixed.
- **Fixer misbehaviour** is detectable from the fix reviewer's diff (identical HTML =
  did nothing; diff far larger than the finding = overreached) and is reported rather
  than silently accepted.
- **Deck reviewer failure is non-fatal.** It runs after the deck is already usable, so
  a failure clears the progress flag and surfaces a notice. It must never invalidate a
  delivered deck.
- **Observability failure is non-fatal** (PRD §9.3) — a tracing or logging failure is
  swallowed and logged, and the turn proceeds.
- **Analyst failure** degrades to building without that data rather than failing the
  deck, with the gap recorded in the spec's resolved-data section so reviewers do not
  flag missing figures as fabrication.
- **Gateway rate-limit responses** surface as a clear quota message, not a 500.

### 8.1 Security

- `<untrusted-data>` wrapping and `cap_tool_output` apply at **every** gatherer
  boundary, including agent-shaped gatherers. An agent that *reports* rather than a
  tool that *returns* must not bypass the injection defence.
- **Reviewer input and fixer output both pass the output safety gate.** Auto-remediated
  HTML reaching the user unchecked is the specific hole PRD §12.1 identifies.
- OBO tokens propagate to every agent's tool calls, and deck/profile permission checks
  still apply.

---

## 9. Testing

PRD §12.1 flags this as unresolved and distinct from the eval harness: the harness
measures **quality**, tests verify **correctness**.

The architecture is deliberately testable: because every agent except the architect is
stateless and briefed with explicit inputs, each is a function of its brief and can be
tested alone with a fabricated brief, no graph and no LLM. A builder takes
`{position, purpose, brief, css_contract, assumes, hands_off}`; a fix reviewer takes
`{finding, original_html, new_html}`.

Because the **foreman is a service, not an agent** (§5.5), its logic is tested
directly rather than stubbed — the orchestration decisions below are ordinary unit
tests with no model in the loop.

**1. Deterministic graph/orchestration tests.** The valuable target is the
orchestration, not the model's prose. With stub agents returning canned outputs, all of
§8 is deterministic and fast: the foreman dispatches ascending; the cap holds at 15;
a freed slot takes the lowest outstanding position; retries jump the queue; the buffer
releases only when all prior positions are committed; the release timeout fires; the
fix loop stops at 1.

**2. Schema-conformance tests, live.** Each skill's output must satisfy its schema.
This is the one place non-determinism is unavoidable, so assertions are on
**structure, never wording** — a reviewer must return valid multi-criteria findings
with a valid `auto_fixable` flag; whether it says "busy layout" or "cluttered" is not a
test's business. Marked `live` and excluded from CI via the existing `-m 'not live'`
convention.

The **analyst's standardised request contract** (§5.2.2) is the leverage point for
this layer: a valid structured request (metric, time bound, grouping, units) must
yield a response that is exactly one of the three valid outcome shapes — success,
missing-data, no-tool. The *content* is non-deterministic; the *shape* is asserted.
Fixtures cover single-source pass-through (no re-summarisation) and multi-source
synthesis (a combined result).

**3. Concurrency and multi-worker tests.** The bug class this rebuild exists to
remove. Parallel builders writing distinct `session_slides` rows must not collide; the
deck-level `version` counter must still reject stale writes with 409; the buffer must
behave when the worker serving a poll is not the worker that ran the build. That last
test must fail if anyone reintroduces in-process buffering.

**4. Regression checklist from the retired regexes.** PRD §12.1 is explicit that
RC10–RC15 and related rules each encode a previously-shipped bug fix and are "a test
checklist for the supervisor's intent handling, not merely dead code to delete." Each
retired regex becomes a behavioural test against the architect: add-versus-replace,
ordinal references ("the 8th slide"), ranges ("slides 2-4"), positional references
("after slide 3").

**Existing gates hold unchanged:** `create_deck` / `edit_deck` contract tests, export
parity (PPTX and Google Slides), permissions and OBO, and save-point restore — now
including **spec restore**, since a save point that restored a deck without its spec
would leave the two describing different decks.

---

## 10. What this spec does not cover

- **Inline WYSIWYG editing** (PRD workstream 8). But §4.5's rule — human-originated
  HTML edits terminate propagation and are never rebuilt — is what makes workstream 8
  safe, so it is specified here.
- **Gateway endpoint abstraction** (workstream 2) and the **MLflow rebuild**
  (workstream 3). This spec assumes the model endpoint is configurable rather than
  hardcoded at `src/core/defaults.py:31`, and that tracing is available; it does not
  build either.
- **Per-agent model routing** — deferred in PRD §8.1, though the seven-skill split
  makes it cheap later (a reviewer could run a cheaper model).
- **Tone/communication authoring UI + library model** — this workstream ships only the
  architect's **consumption hook and an in-repo default** tone guideline (§5.2.1). The
  user-facing authoring surface (a `tone_library`-style model plus admin/user UI,
  the third editable axis alongside deck prompts and slide styles) is a separate PR,
  landing alongside like row-per-slide. The graph core only assumes the hook exists.
- **Speaker notes** — deferred in workstream 6 and still absent from the domain model.
- Export, permissions, and data-tool internals (PRD §11) are reused, not rebuilt.

---

## 11. Deltas from the PRD

Recorded so the divergences are deliberate rather than drift:

| PRD says | This spec says | Why |
|---|---|---|
| §4 diagram: supervisor → builder → reviewers | A **foreman** tier sits between — as a **deterministic orchestration service, not an agent** | Parallel per-slide builds need an orchestrator that owns the CSS contract and dispatch; all of its work is deterministic (the reviewer already tagged what to fix), so it carries no LLM reasoning and becomes directly unit-testable |
| §7.4: show the deck first, reviewers run after, findings arrive later | **Reviewers write the slide**, so a slide appears only once review-clean; subjective findings still arrive later | No visible flapping (a slide never appears then silently changes under the user). Cost: first-paint includes one review pass |
| — (not mentioned) | **Tone** as a third user-editable config axis (hook here, UI later) | Communication style is neither *what* the deck says (deck prompts) nor *how* it looks (slide styles); it should not be centrally mandated |
| §7: reviewers run after a build | Reviewers are **briefed by the foreman** with the spec | Checking against the contract the builders were given beats checking against inferred intent |
| §7.1: three review agents (content / design / narrative) | **One** slide reviewer with a strict multi-criteria schema, plus a deck reviewer | Cost stays n rather than 3n; scalability comes from adding criteria fields |
| §4 diagram: data tools called by builder + reviewers | A **data analyst** agent owns gathering and synthesis | Resolves data once above the fan-out; avoids n builders each querying; converts `cap_tool_output` truncation into deliberate summarisation |
| §7.3: remediation "bounded to N iterations" | **Exactly 1** fix round | Simplest correct cycle-breaker; survivors become surfaced findings |
| §5: supervisor delegates to a builder | The supervisor **is** the architect | No reason for the user to talk to a router that proxies to the persona they want |
| Workstreams 4 and 7 are separate | **Merged** | Both replace the same intent layer; splitting means rewriting it twice |
| — (not mentioned) | Row-per-slide schema as a **prerequisite PR** | One `deck_json` row with an optimistic-lock counter cannot absorb parallel writes |
