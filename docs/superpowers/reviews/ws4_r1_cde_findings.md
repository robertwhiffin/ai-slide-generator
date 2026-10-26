# Round 1 findings — ws4c, ws4d, ws4e (VERBATIM, do not paraphrase)

Three separate fresh reviewers. Each verified anchors against code; two executed topology.

---
---

# ws4c — graph core (20 findings, 5 blocking)

## 1. BLOCKING — C4's `reviewer_router` decision is measurably wrong and breaks two of C5's headline invariants

C4 resolves round-3 finding 14 with *"Prefer wiring it — the fix path benefits from being explicit in the graph"*. Both variants built on installed langgraph 1.2.10 (6 builders, positions 0 and 1 needing a fix):

| Wiring | fixer invocations | foreman wakes |
|---|---|---|
| `reviewer_router` wired (`"fix"`→fixer, `"land"`→foreman) | **3** — `fixer:0`, `fixer:1`, **`fixer:NOCAND`** | **5** |
| static `add_edge("build_reviewer","foreman")`, router deleted | **2** — `fixer:0`, `fixer:1` | **4** |

Cause: reviewers split their return between `"fix"` and `"land"`, so `fixer` and `foreman` are **scheduled into the same superstep**. The foreman then independently sees `has_pending_fix` and re-routes to the fixer, producing an invocation whose candidate set is already empty. That is exactly the state C1 warns about — *"the fixer's `min()` then raises `ValueError` on an empty candidate set"* — reached by a different cause than the tombstone bug C1 guards against, and `has_pending_fix` does not guard it because the fixer is now reachable without passing through the foreman.

Consequences: C5's *"exactly one fixer invocation per position needing a fix"* and *"the orchestrator wakes once per completed batch"* both fail under the plan's own recommendation. The recommendation's stated benefit is aesthetic; the measured cost is the headline invariant.

Fix: choose deletion (the measured-clean option), or keep the router and add a required empty-candidate guard in `fixer_node` plus a restated wake assertion. Either way the plan must stop asserting both.

Two adjacent facts to record: with the clean wiring, fix rounds **serialise** one position per superstep (15 objective findings = 15 sequential rounds), and `has_pending_fix` preempts dispatch entirely, so a 31-slide deck stops dispatching new builders until every fix completes.

## 2. BLOCKING — the deck title has no source

C4 requires the pre-fan-out write to persist `title`, and ws4b B3.1 records the consequence of not writing it ("untitled deck **and** untitled session row"). But:

- `ArchitectOutput` (ws4b B1.5) declares `intent, message, deck_spec?, data_request?, target_positions, proposed_design_contract?` — no title.
- `DeckSpec`/`SlideSpec` (B1.4) declare no title.
- C1's `GraphState` table declares no `title` key, so even a derived value has no channel to the writer.
- C4 says *"Read only fields `ArchitectOutput` declares."*

This is precisely the escalation class the plan opens with, present in the plan itself. Either escalate a `title` field to ws4b or state the deterministic derivation and add the state key.

## 3. BLOCKING — `build_branch_payload` omits everything the builder needs to author a branded slide

C4 enumerates the payload exhaustively: `session_id`, `turn_id`, `position`, the `SlideSpec`, `assumes`, `hands_off`, `design_contract`, `resolved_data`. C6 says *"Builder receives: one section."* The section HTML, the section CSS and the resolved style prose are in neither list, and by the plan's own runtime fact a `Send`-reached node sees **only** its payload — so the omission fails silently.

`design_contract` does not close the gap: ws4b B1.4 makes `DesignContractRef` ids-only, *"WHICH brand, never the compiled content."*

The same gap breaks C3. `assemble_skill_prompt(skill, payload)` must inject `_SLIDE_FRAME_CONSTRAINTS` "only when the resolved style lacks it", decided "from the resolved style at request time" — but no resolved style is in scope, and resolving it per-builder from ids means N DB reads inside the fan-out. Who resolves it, and where it enters the payload, is unstated.

## 4. BLOCKING — `else: -> END` silently truncates the turn; the finding-21 reconciliation is unreachable

C4's foreman pseudocode comments `else: -> END   # a batch is in flight; the barrier re-enters us`. That comment is false. Returning `END` terminates; nothing re-enters. And by the plan's own barrier fact the foreman never wakes mid-batch, so this branch is reached **only** in the case C4 says the placeholder branch catches — "a position left uncommitted by a completed batch."

But that catch cannot fire: C2 fixes `RELEASE_TIMEOUT_S = 300`, and `stalled_positions(state, now, 300)` is evaluated moments after the batch completed. Elapsed time is seconds. So a build-reviewer exception, or a builder returning nothing usable without raising, ends the turn with slides missing, no placeholder, and no error. The plan claims to have reconciled finding 21; its stated numbers make the reconciliation unreachable.

## 5. BLOCKING — `dispatched_at` carries the identical tombstone hazard as `fix_map`, unguarded

C1 devotes a section to `has_pending_fix` because `turn_scoped_merge` cannot delete a key and `bool({0: None})` is `True`. `dispatched_at` uses the **same reducer** and the plan gives it no equivalent guard:

- The in-flight predicate is never defined anywhere in C2 or C4, despite three rules depending on it.
- C2's *"Retries need no special case beyond clearing their in-flight marker"* is impossible — the merge reducer cannot clear. A tombstone `dispatched_at[p] = None` then reads as present.
- `stalled_positions` iterating `dispatched_at` will raise `TypeError` on a `None` timestamp unless it skips them; nothing says it must.
- `retry_count` is declared in `GraphState` with a reducer and **no writer**. No node in C4's nine retries anything — `builder_node`'s exception path goes straight to a placeholder. Yet C2's test intent asserts "a retry appears ahead of higher unstarted positions" and the runtime-facts table claims "retry priority all survive". The policy is tested; the mechanism does not exist.

## 6. HIGH — the runtime-facts table omits how a router out of a `Send`-reached node sees state

Measured on 1.2.10. The obvious implementation of wiring rule 1 —

```python
def build_reviewer_router(state):
    return [Send("build_reviewer", {"position": state["position"], ...})]
```

— raises `KeyError: 'position'`. The router receives **plain state, not the payload**. Further, the router is invoked **once per branch**, and each invocation sees only *that branch's* writes: with 6 builders each writing `slides[p]`, the six router calls saw `slides` keys `[0]`, `[1]`, `[2]`, `[3]`, `[4]`, `[5]` — never the merged `[0..5]`.

C4's *"carry its payload forward in `slides[position]` so the re-fan can rebuild the reviewer's input"* works, but only because of this per-branch visibility, which the plan never states. Given how much weight the plan puts on the Send-payload fact, this belongs in the table.

## 7. HIGH — C6's grain claim rests on an unstated precondition that arbitrary templates need not meet

`src/utils/html_utils.py:72` is `soup.find_all(class_="slide")` — roots are found by the **`slide` class token**, not by tag. `_detect_slide_root_tags` (`design_system_templates.py:444-450`) keys on the same token. Every in-repo template fixture supplies it (`tests/unit/conftest_design_system.py:177,181`; `tests/unit/test_design_system_templates.py:542,652`), so any probe against them returns 1 or N by construction.

A brand template whose slide roots lack `class="slide"` yields **0** roots — an empty `section_inventory`, no section ever assigned, `template_section_index` permanently `None`, the whole §M3 story silently disengaged — and `normalize_root_tag_selectors` becomes a no-op (`design_system_templates.py:543-544`). The plan's own §M7 note concedes there is no real bundle in-repo, which is exactly why the precondition needs stating rather than generalising.

## 8. HIGH — `resolve_template_bytes` cannot call `get_template_for_generation` as specified

Its actual signature is `get_template_for_generation(design_system: Any, template_id: int)` (`design_system_templates.py:849`) — a **design-system object**, not an id. Three things follow:

- `resolve_template_bytes(design_system_id, template_id)` must load the design system first (the same trap ws4b flagged for `_get_deck_owner_session` taking a `UserSession`, not a string).
- `materialize_templates` mutates `template.layout_html` (`:705`) and its docstring defers persistence to the caller (`:690-692`), so this needs a live `get_db_session`, not a detached row.
- No `is_active` filter is specified. `_design_system_is_active` (`agent_factory.py:315-350`) exists because a session keeps its pin after soft-delete; its docstring calls this "the AUTHORING question — may new content be made against this brand — and a tombstone answers no." Resolving template bytes by bare id re-opens the measured defect C8 spends a paragraph preserving.

## 9. HIGH — C7's "repoint the 13 test files" contradicts itself, the DoD, and the shipped code shape

C7 says *"Repoint the 13 test files referencing `src.services.agent`"* and the very next sentence says three gain cases **alongside** their monolith cases and the other ten **keep testing the monolith**. Nothing moves: the DoD requires `agent.py` **unmodified**. The DoD's *"all 13 `src.services.agent` test files pass at their new homes"* names homes that do not exist. (The count is right — 13 measured.)

Separately, "Both **delegate** to the shipped implementations" holds for only one half. `_run_output_safety_gate` is module-level (`agent.py:102`) and delegable. The prior-slide framing lives in `SlideAgent._format_slide_context` — a **method** (`agent.py:885`). `spotlight_prior_slides` cannot delegate to it; it must re-implement the `<slide-context>` wrapper and its notice text while calling `src/utils/spotlight.py:22`.

## 10. HIGH — the builder gets image-tool prose and no tools; brand assets are unreachable on the graph path

C9 writes the builder's prose "with `SLIDE_GUIDELINES`, `CHART_JS_RULES`, `IMAGE_SUPPORT`, `HTML_OUTPUT_FORMAT` open as source material". `prompt_modules.py:100-117` is `IMAGE_SUPPORT`, and line 102 reads *"You have access to user-uploaded images via the search_images tool"* with four HOW-TO steps. C3 requires builders and reviewers to declare **no** tool grants. A builder told to call a tool it cannot call either fabricates handles or drops images.

Two smaller inconsistencies: C3 says *"the analyst **and architect** declare tool grants"* while C9's table assigns grants only to `data_analyst`; and C8 leaves `search_brand_assets` gating in `agent_factory` (monolith-only), so the graph path has **no** brand-asset access at all — unmentioned.

## 11. MEDIUM — eight `GraphState` keys have no assigned producer, and one cannot reach output

C1 defers `token_css`, `deterministic_css`, `external_scripts`, `head_meta`, `scripts_content`, `knitted_html` and `emitted_style_blocks` to "see C4's note on who produces these". C4's note covers only `token_css` + deterministic CSS. Unassigned: `external_scripts`, `head_meta`, `scripts_content`, `knitted_html`, `emitted_style_blocks`, `error_state`, `fixed`, `reviewed_positions`.

`emitted_style_blocks` is the costly one: ws4b B3.3 says explicitly *"ws4c owns producing them; this task owns consuming them"* and asks ws4c to flag it if the premise weakens. C4 never mentions the key. Without a producer, `aggregate_deck_css` receives nothing and a graph deck knits with no layout CSS — B3.3's named §H defect.

`scripts_content` is impossible as specified: `SlideDeck.__init__` (`slide_deck.py:50-57`) has no deck-level scripts parameter, `from_dict` (`:111-139`) sets none, and `scripts` is a **read-only property** aggregating per-slide scripts (`:79-95`). So a value persisted to that column can never reach `knit()`.

## 12. MEDIUM — the finding-17 fix is type-incoherent with C1's wrapper scheme

C4 mandates `wakes + [batch]`, never `wakes.append(batch)`. But `foreman_wakes` carries `turn_scoped_concat`, and every value in that scheme is a wrapper `{"turn": …, "vals": …}`. An implementer following the letter will read via `scoped_vals`, do `wakes + [batch]`, and return a bare list — which the reducer receives as an unwrapped `b`, fails its `isinstance(…, dict)` check, and silently discards or raises. The correct write is `{"foreman_wakes": scoped(turn_id, [batch])}`, where non-destructiveness is the reducer's job and `wakes + [batch]` never appears.

## 13. MEDIUM — three C5 assertions are false or cannot fail

- *"with position 1 slow, no higher position dispatches while it is outstanding"* — positions 2..14 are dispatched in the **same batch** as position 1, so this is false for batch 1; under the barrier it is vacuous for later batches.
- *"release order is strictly ascending with a slow position"* — there is no release in ws4c. `slides_since_cursor` and `emit_slide_ready` are ws4d's (`ws4d:171,173`). At best this restates C2's pure-function test.
- *"peak concurrent builders ≤ 15 over 40 positions"* — cannot fail. The barrier plus the foreman's early returns (`has_pending_fix`, `stalled_positions`) mean the foreman never wakes with a partially-completed batch, so C2's rule 3 (in-flight subtraction) has no reachable scenario and its sabotage cannot be verified at layer 1.

## 14. MEDIUM — the C5 harness is not wireable as specified

`tests/integration/conftest_stub_skills.py` is described as returning a **fixture**. Pytest auto-collects only `conftest.py`; a `@pytest.fixture` in `conftest_stub_skills.py` is invisible. The repo's two `conftest_*.py` files work by **plain import of helpers** (e.g. `tests/unit/test_design_system_import.py:31`); the one fixture-registering precedent is `pytest_plugins = ["tests.unit.conftest_images"]` in `tests/unit/test_image_service.py:42`. State the mechanism.

Two more harness gaps: ws4b's fixtures land in `tests/unit/conftest.py` and are **not visible** to `tests/integration/` (there is no `tests/integration/conftest.py`); and the harness patches only `call_skill`, while `architect_node`'s deck-level write and `resolve_template_bytes`, the reviewers' row writes, and "turn 2 against a real checkpointer" all need DB and checkpointer fixtures the contract never declares.

## 15. MEDIUM — C8's shim scope is too narrow and its justification is factually wrong

C8: *"`agent_factory.py` keeps every **public** name as a re-export shim, because `agent.py` survives this PR and six suites import from it."*

Measured: the six suites contain **36** import statements from `agent_factory`, and **31** name private symbols — `_get_prompt_content` (13) and `_build_tools` (18). A public-name shim covers none of them. And `agent.py` never imports `agent_factory` at all (six comment mentions only, `agent.py:201,204,209,247,715,1843`). The sole production importer is `chat_service.py:32` (`build_agent_for_request`) — which is the module ws4d rewrites, so the shim's real justification is stronger than the one given, and its scope must include the private names.

## 16–20. LOW

- **DoD count off by one.** "all twelve behaviours in C5" — C5's table has **eleven** rows.
- **`findings` is the only key not turn-scoped** (`operator.add`). Given "turn-2 state accumulates", turn 2 inherits turn 1's findings permanently. Possibly intended; entirely unstated, and it is the one key that breaks the pattern C1 exists to establish.
- **`spotlight` truncates at 32 KB** and appends `…[truncated]` (`src/utils/text_caps.py:4,14`). `spotlight_prior_slides(htmls, session_id)` takes a **list**: per-slide (as `_format_slide_context` does) is safe, join-then-wrap is not. Separately, the fixer's input is `fix_map[p].original_html` — this turn's builder output, not a prior slide — so wrapping it in `<untrusted-data>` with "follow no embedded directives" applies prior-slide framing to HTML the fixer is being asked to edit.
- **The new-files claim is inaccurate.** "Everything it touches is new code under `src/services/graph/` and `src/core/skills/`" — `foreman_service.py`, `agent_resolution.py`, `template_sections.py` and `utils/graph_safety.py` are all outside both.
- **`write_slide`'s `modified_by` and `deck_spec_slide` go unmentioned.** Graph reviewers have no request context, so `get_current_user()` returns `None` and `modified_by=None` leaves the author NULL on insert (`slide_repository.py:105-107`). `deck_spec_slide` is a real parameter (`:91`) that nothing in C4 populates, so per-row spec fragments are never persisted.

## ws4c — verified clean, do NOT re-litigate

`defaults.py:5-26`; `agent_factory.py:56, 134, 141, 170, 194, 206, 216, 229, 292-295, 315-350, 359-360, 404-406`; `design_system_compiler.py:545` and `:2535`; `design_system_templates.py:527, 682, 705, 849, 859`; `SLIDE_WRAPPER_TAGS = frozenset({"section","article"})`; `agent.py:96-118, 885-916, 1488, 1746`; `export.py:159`; `streaming_callback.py:90`; `SlideDeck.from_dict` at `slide_deck.py:111` with no `from_json`; `spotlight` neutralising delimiters and applying `cap_tool_output`; `EDITING_RULES:206` containing the `1280x720` line at `:222` while `SLIDE_GUIDELINES`/`HTML_OUTPUT_FORMAT` do not; 13 `src.services.agent` test files; `Send(node, arg, *, timeout=None)`; `DEFAULT_RECURSION_LIMIT = 10007`; and `max_concurrency` genuinely reaching the **sync** path as `ThreadPoolExecutor(max_workers=…)` via `get_executor_for_config` (`langchain_core/runnables/config.py:672-674`).

---
---

# ws4d — wiring (21 findings, 4 blocking)

## 1. BLOCKING — §D0's central scoping claim is false: MCP *can* reach the graph

D0 says "MCP has no chat input, so it cannot carry the phrase and **keeps the monolith**," and the DoD asserts "MCP behaviour **unchanged**." But `enqueue_create_job` (`src/api/mcp_server.py:170`) persists the MCP prompt as `role="user", message_type="user_query"` and its own docstring says the worker "runs the agent via `ChatService.send_message_streaming`" — the exact method D2 puts the graph branch in. So `create_deck(prompt="… USE AGENT MODE …")` routes MCP through the graph, and D1's transcript-derived resolver has no way to tell an MCP session from a browser-async one (both use `message_type="user_query"`). D1's test intent ("an MCP-created session … get[s] the monolith") passes only because the fixture prompt lacks the phrase; it establishes nothing.

The fix mirrors D4's own placement rule, which the plan gets right for `mark_dirty` and wrong here: resolve mode in the **chat route handlers** and pass it into `send_message_streaming` as a parameter defaulting to monolith. MCP never calls those routes, so exclusion becomes structural rather than probabilistic.

## 2. BLOCKING — there is no mechanism for events to escape the graph; D2 and D3 are both unimplementable

ws4c's contract is `invoke_graph(session_id, initial)` (`ws4c:354`), a blocking invoke; ws4c mentions no queue, no `StreamEvent`, no emission at all, and its `GraphState` table (`:95-101`) has no queue key. Meanwhile D3's contract adds `emit_slide_ready(queue, position, html, scripts)`. Nothing states:

- how the queue reaches a node. It cannot ride `GraphState` — the index's own verified fact says undeclared keys are silently dropped, and a `queue.Queue` is not serialisable through ws4b's checkpointer. `config["configurable"]` has the same serialisation problem. A module-level registry or a ContextVar are the remaining options, and D4 rejects ContextVars on principle.
- that `invoke_graph` must run **off** the generator's thread. A straight `invoke_graph` call inside `_send_message_streaming_graph` cannot yield anything until the graph finishes, so "slides arrive incrementally" is impossible. The monolith already solves this (`run_agent` in a thread + `event_queue`, `chat_service.py:1127`), and D3's `queue` parameter implies that shape — but D2's contract never says it.

D3's test intent ("the emitter queues the object") passes with none of this wiring present.

## 3. BLOCKING — the polling transport has no delivery path, and D3 contradicts itself

Parent spec §6.2 is explicit: "**Polling:** a **slide cursor** alongside the existing `after_message_id`, reading committed rows directly" (`2026-08-06-agentification-core-design.md:759`). D3's contract table has no `poll_chat` query parameter, no new response key, and no change to `startPolling`, which tracks only `lastMessageId` (`frontend/src/services/api.ts:933-995`). `poll_chat`'s response is `{status, events, last_message_id, result}` (`src/api/routes/chat.py:724-730`) with nowhere to put slides.

Worse, two rows of the contract table cancel each other: the table requires "`msg_to_stream_event` maps `slide_ready` explicitly," and eight lines later D3 says "Persisting slide-ready as a `SessionMessage` was **rejected**." If no `slide_ready` row is ever written, the converter can never encounter one — the change is dead code and its test exercises an unreachable path. Separately, `msg_to_stream_event` returns a hardcoded 6-key dict (`session_manager.py:2792-2799`) that cannot carry `position`/`html`/`scripts` even if it did fire.

## 4. BLOCKING — contributor sessions break stickiness *and* the marker key

Decks are shared: `UserSession.parent_session_id` (`session.py:110`), and `session_slide_decks` hangs off the owner only. Two consequences:

- **D1:** mode is per-session, divergence is per-**deck**. Contributor A with the phrase runs the graph (writing `session_slides` rows) while contributor B without it runs the monolith (writing `deck_json`) on the same deck — the exact divergence D1's stickiness argument exists to prevent.
- **D4/D5:** the slides routes pass `request.session_id` straight through (`src/api/routes/slides.py:194`, `:213-219`), so `mark_dirty` can receive a contributor id whose `UserSession.slide_deck` is `None`. It must resolve through `SessionManager._get_deck_owner_session` (`session_manager.py:709`) — as ws4b's writer explicitly does — or every contributor edit either raises or writes nowhere. And since `claim_due_marker` returns the **owner's** string id, `mark_dirty`/`clear_marker` must agree on owner-keying or markers are never cleared.

## 5. SERIOUS — nothing renders `slide_ready` on the frontend

`handleStreamEvent` (`frontend/src/components/ChatPanel/ChatPanel.tsx:183`) switches only on `'tool_call'` and `'complete'`. D3 adds the type to the TS union at `api.ts:62` and stops; ws4e contains no occurrence of `slide_ready`, `slide_cursor` or `slides_since_cursor`. The DoD's "Slides arrive in ascending order on **both** transports" is true only at the API boundary — the user-visible payoff §6.2 exists for is delivered by no plan in the set.

## 6. SERIOUS — graph mode silently loses session-title generation

`run_title_gen` is inline in `send_message_streaming` (`chat_service.py:1155`), started only when `is_first_message` (`:1191-1195`), and `SESSION_TITLE` is emitted at `:1564`. A branch placed "after the user message is persisted and before the monolith is invoked" skips both, so every graph-mode session stays untitled. (`SESSION_CREATED` is fine — the route emits it at `chat.py:462-465`.) The DoD checks monolith parity in both directions but never checks graph-mode parity on the surrounding behaviour.

## 7. SERIOUS — `clear_context` has no entry point

D1 states four requirements and a test intent for it but no signature, no route, no HTTP verb, no file, and no UI affordance. ws4e's surfaces plan never mentions it. As written the DoD item is satisfiable by an unreachable service method, so spec §7.2's feature ships in no PR. (The claim that it doesn't exist today is correct — verified, zero occurrences repo-wide.)

## 8. SERIOUS — ws4a and ws4d collide inside `duplicate_session`

The index says "ws4a is genuinely parallel. It shares no file with b–e except the e2e workflow." ws4a edits `duplicate_session` to carry `deck_spec_json` (`ws4a:43`); ws4d's D1 edge 2 edits the same method to carry the earliest user message and says so ("alongside ws4a's `deck_spec_json` fix"), while ws4d's **Depends on** line names only ws4b and ws4c. Same function, two PRs, no declared ordering.

## 9. SERIOUS — carrying the earliest user message into a duplicate is not inert

`_hydrate_chat_history`'s allowlist is `HUMAN_TYPES = {"user_query", "user_input", "chat"}` (`chat_service.py:1765`), so the copied marker replays into the architect's context as turn 1 of the duplicate's conversation. And `message_count` is a live `COUNT` query (`session_manager.py:607`, `:779-782`), not a column — so a duplicate carrying one message has `is_first_message == False`, suppressing title generation on its first real turn. Separately, `duplicate_session` writes no `session_slides` rows, so a duplicate is graph-mode with a deck that exists only in `deck_json`.

## 10. SERIOUS — `deck_spec_slide` does not travel with its slide, and D6 introduces the write

`_attribute_slide_records` (`session_manager.py:194-239`) maps **only** `{new_position: verification_record}`; `_upsert_slide_row` treats `deck_spec_slide=None` as "leave unchanged" (`:337`). So D6's insert shifts verification records correctly (already solved by existing code — the test is a regression guard, not new work) while leaving per-row spec fragments attached to positions. That is the identical mis-attribution class D6 names for verification, in the column D6 itself adds. `deck_spec_slide` has no producer today (`slide_repository.py:171` only), so this is latent — until D6 ships it.

## 11. SERIOUS — the sweeper needs identity *bound*, not just stamped

D5 rules the identity question and specifies `modified_by = spec_dirty_by`, but not `set_current_user(author)` for the tick's duration. `require_editing_lock` (`session_manager.py:2353`, `:2367`) reads `get_current_user()`; with `None`, any deck a human currently holds the editing lock on raises `PermissionError` — so the arc review can never run for an actively-edited deck, exactly the deck it exists for. It degrades safely (marker kept, retried) but silently, forever. The cost-attribution half also needs checking: if attribution comes from request-log middleware it won't fire on a sweeper tick regardless of `modified_by`.

## 12. SERIOUS — D4's structural test is scoped too narrowly to be a structural guarantee

"**no `chat_service` method mentions `mark_dirty`** (assert it against the module source)" leaves a graph node in `src/services/`, `deck_level_writer.py`, `slide_repository.py` or `session_manager.py` free to call it. Invert it: only `src/api/routes/slides.py` may reference `mark_dirty`, asserted across the tree.

## 13. SERIOUS — the route table repeats the silence it correctly diagnoses

D4 notes that session-duplicate's absence from §B1's list "was silence rather than a decision, which is what made ws4a's defect invisible" — then omits four mutating slide routes from its own table: `PATCH /{index}/verification` (`slides.py:388`), `POST /versions/create` (`:507`), `PATCH /versions/{n}/verification` (`:552`), `POST /versions/sync-verification` (`:607`). D4's test intent says "every human mutation route calls it," which those four would fail. Rule them in or out explicitly.

## 14. SERIOUS — round-3 finding 26 is not actually closed; D3 restates it

The contract table says add "`position`, `html`, `scripts`, `agent`, `slide_cursor` as **optional fields**" and then "**`scripts` is `str`** … not `Optional[str]`," and the test-hygiene note says "assert the annotation is exactly `str`." All three cannot hold: no existing emitter passes `scripts`, so a bare `scripts: str` breaks every current `StreamEvent(...)` construction (twelve fields, all `Optional[...] = None`, `src/api/schemas/streaming.py:41-55`). The only shape satisfying the whole set is `scripts: str = ""`. State that literally.

## 15. Column-name drift with ws4b

ws4b's migration creates `spec_dirty_at`, `spec_dirty_by`, `spec_dirty_claimed_at` (`ws4b:497-498`). D5's SQL sketch and its sabotage step both write `claimed_at`. Agents copy identifiers literally.

## 16. §K7 and §K8 are not addressable

Spec §K ("What this document does not decide", `2026-08-12-pr3-open-questions-design.md:1319`) is an unnumbered bullet list. The two items D5 cites are "The dirty marker's storage (§B2)" and "What identity a sweeper-driven arc review runs as (§B2)" — the 5th and 6th "Still open" bullets, not §K7/§K8. Same for the **Spec:** header line. Quote the bullets.

## 17. `delete_thread` "already exists" is misleading

`BaseCheckpointSaver.delete_thread` raises `NotImplementedError`. The working implementation is ws4b's Lakebase saver (`ws4b:411`). "Use it rather than inventing a function" is right; "already exists" invites a call that raises if ws4b's implementation slips.

## 18. The tour fixture's arc has no write path

`_phase2_add_slides` (`src/api/routes/tour.py:82`) calls `sm.save_slide_deck(deck_dict=…)`, which does not persist a deck spec. "Ship the arc description inside the fixture — one JSON field" plus the DoD item leave the fixture→`deck_spec_json` wiring unstated, so §7.1's spec view on the tour deck stays empty.

## 19. "All four §3.1 entry points" is incoherent with D2 and unusable as a checklist

§3.1's four are **frontend** `api.ts` functions — `sendMessage` (:584), `streamChat` (:782), `submitChatAsync`+`pollChat` (:876/:910), `startPolling` (:933), all verified. D2 explicitly excludes the non-streaming path, so the DoD demands mode correctness on a path D2 refuses to support. Enumerate the backend call sites you actually mean. Note `api.sendMessage` has **no caller** in `frontend/src` (only `api.sendChatMessage` at `ChatPanel.tsx:313`).

## 20. D1's persistence-order investigation — answered; replace the instruction with the result

The async route persists the user message at `src/api/routes/chat.py:630-637`, **before** `enqueue_job` at `:640`, so the row exists when the job runs. The sync path persists at `chat_service.py:899` inside `if not request_id:` (`:898`) — both anchors correct. One trap to carry instead: the two paths use **different** `message_type` values (`"user_input"` sync, `"user_query"` async and MCP), so `resolve_engine_mode` must filter on `role` only, never `message_type`. Also: `POST /sessions/{session_id}/messages` (`src/api/routes/sessions.py:658`) lets the creator append an arbitrary-`role` message, which can become the marker on a session with no user turns yet.

## 21. Two off-by-one anchors

`get_system_client()` is called at `agent_factory.py:57`, not `:56`; `send_message`'s `return response` is at `chat_service.py:819` with the `except/raise` at `:821-823`.

## ws4d — verified correct, do NOT re-derive

`session.py:218-219`, `:252-257`, `:358`; `agent_config.py:319` and `AgentConfig` at `:75` declaring no `model_config`; `chat_service.py:825`, `:899`/`:898`, `agent.py:1582` (method), `_hydrate_chat_history` excluding `reasoning`/`info`/`tool_*` via allowlist; `streaming_callback.py:371` and that module containing only `StreamingCallbackHandler`; `StreamEvent.type` + `to_sse()` via `model_dump_json()`; `chat.py:669`, `:505`; `session_manager.py:2772`, `:2205-2211`, `:2222`/`:2240`, `:1859`; `duplicate_session` copying no `SessionMessage` rows and taking a string; `_authz.py:188-191` defaulting to `CAN_VIEW` and raising `HTTPException`; `api.ts:62` and the absence of `frontend/src/types/streaming.ts`; `Message.tsx:93`; `slide_deck.py:251` with exactly six call sites; `duplicate_slide` at `chat_service.py:2850`; no `POST /slides` insert route; `job_queue.py:20,21,33,202,214-239,342-352`; `main.py:128-129`; `run.py:128`; `user_context.py:21-23`; `tour.py:34-39`, `:82`, fixture 4,663 bytes; `spec_sync`/`mark_dirty`/`clear_context` absent repo-wide.

---
---

# ws4e — surfaces and gates (29 findings, 8 blocking)

Anchors that hold: `AppLayout.tsx:762`/`:988-990`, `test.yml:100-105`, `test_dependencies_resolve.py:19-25`, the RC marker counts (61 in `chat_service.py`, 14 in `agent.py`, 1 in `mcp_server.py`, RC1..RC15), all 11 RC anchors in the ground-truth table, `run.py`'s five `SystemExit(1)` steps, `UVICORN_WORKERS=4`, `VERSION_LIMIT=40`, `slide_count` as a column, `ensure_deck_token_css`'s 57-token docstring, the Google Slides hermeticity note, `_SLIDE_FRAME_CONSTRAINTS`, §M7 probe 3.

## Blocking

**1. E2 has no read path. Findings cannot reach the frontend.** E1 gets its data because ws4b B3.2 explicitly adds a parsed `deck_spec` key to both read paths. Nothing equivalent exists for findings. ws4b defines `findings_from_record(record, content_hash) -> list[Finding]` (`ws4b:61`) and it is called by **nobody** in ws4c, ws4d or ws4e. `get_slide_deck` merges `verification_map` into `Slide.verification` as a `VerificationResult` (`frontend/src/types/slide.ts:9`) — the LLM-as-Judge shape, not findings. So E2's headline assertion has nothing to render from. E2 is a wiring task with one end unattached.

**2. The component tests have no CI job, and no guard notices.** `frontend-build` runs `npx tsc -b` + `npx vite build` and nothing else (`test.yml:399-425`). There is no `vitest` / `test:unit` invocation anywhere in the workflow. ws4b adds the runner and a `test:unit` script but no job; ws4e adds component tests for E1 and E2 but no job. ws4a's guard covers `*.spec.ts` under `frontend/tests/e2e/` only, so it will not fire. The DoD's "ws4a's guard test enforces this" is true for Playwright and silently false for every component test in this PR.

**3. Layer 4 is marked "In CI ✅" and has no CI home or DB harness.** CI runs `tests/unit` plus seven *named* integration files. Ten integration files already on disk run in no job. E4 also needs a database shared across processes: the existing row-per-slide integration tests use `sqlite:///:memory:` (`tests/integration/test_slide_row_identity_and_verdicts.py:45-47`), which two processes cannot share at all. Both cross-process assertions need a postgres (or file-sqlite) fixture that no conftest provides — `tests/integration/` has no conftest.py.

**4. E4's sabotage step is unsound and will push the executor to break a correct test.** The plan: *"Add an in-process cache in front of the release query and confirm the second-process test goes red. If it stays green the test is not actually crossing a process boundary — fix the test."* The test's own description is "compute releasable positions in a second [process] **with a cold cache**." A cold cache in a fresh process misses and reads the DB, so the sabotage stays **green** — which the plan then reads as proof the test is fake. The instruction it issues ("fix the test") points at converting a genuine cross-process test into an in-process one so the sabotage fires. A sabotage that actually discriminates: have the *first* process buffer instead of persist, and confirm the second sees nothing; or assert the child PID differs.

**5. E3's own DoD command fails on the machine the plan describes.** DoD: `pytest tests/agentic -q` → "all SKIPPED, none failed." But the two skip conditions are different things: **no reachable endpoint** and **placeholder prompts**. The plan specifies only the first. `.env` contains `DATABRICKS_HOST` — the index itself cites a local test failing *because* of local `.env` state. So locally the guard passes, the tests run against ws4c's placeholder prompts, and they fail. E3 states the right rule and then specifies only two mechanisms where three are needed: an unconditional `pytest.mark.skip(reason="real prompts pending")` distinct from the endpoint `skipif`.

**6. §7.4's UI surface is delivered by no plan, and ws4e is the last of five.** The index assigns ws4e "the UI surfaces §7.1/**§7.4** promise" (`ws4-index.md:68`). ws4e's Spec line lists §7.1, §7.2, §7.5 — not §7.4. Across all five plans the only §7.4 hit is a ws4c line about ascending release. §7.4's actual requirement — the non-blocking "Agentic deck review in progress" flag, with the spec's warning that "a flag that gates export is a serial gate wearing a spinner" — appears nowhere, and the index's exclusions list does not name it. It is dropped, not deferred.

**7. Deck-level findings never reach chat — the positive half of §F4 is unowned.** E2 correctly states the negative and claims §F1–§F4 in scope. But PRD §3's grain routing needs deck-level findings to *arrive in chat*, and §F4 closes with "the verdict is stored here and still surfaces in chat." ws4b defines `save_deck_review(session_id, digest, findings, author)`; across all five plans it is called by nobody. ws4c's `deck_reviewer_node` says "then review" with no persistence and no chat emission.

**8. The deleted-test gate command misses 82% of the suite.** `git diff main...HEAD -- tests/ | grep -c '^-def test_'` matches only top-level defs. Measured: **569** top-level `def test_` vs **2593** class-method `    def test_`. Under ruling R1 the deletions this series authorises are the thing the gate exists to count, and the DoD's headline requirement will report `0` while hundreds of class-method tests are removed.

## Medium

**9. `/tmp/pr3_baseline.log` does not exist and no plan creates it.** Referenced only in ws4e (`:269`). The `diff` is unrunnable as written, and `/tmp` will not survive five PRs. Say who captures the baseline, when, and where it lives durably.

**10. "All six RC10–RC15 mappings in the superseded plan were wrong" is a misattribution.** ws4e's superseded plan is `2026-08-24-pr3-langgraph-core.md`. Its RC table at `:10083-10093` is the *same, correct* table ws4e reproduces verbatim. The ordinal/range/relative mappings were in an earlier draft; `2026-08-09-pr3-langgraph-core.md:2728-2730` says so. Teaching an executor to distrust the correct table it was handed matters.

**11. E5 discards derivations the repo already holds.** RC1, RC4, RC8, RC9 are one grep from the meanings the plan says "must be derived": `agent.py:960` (validate response is real slide HTML, retry once), `:1005` (unique canvas IDs to prevent collisions), `chat_service.py:1268` (synthesise `slide_context` from a parsed reference), `:1325` (add *with* a slide reference). `2026-08-09-pr3-langgraph-core.md:2739-2748` already recorded verified semantics for all four.

**12. "One behavioural test per rule, against the COMPILED graph" is wrong for at least six of fifteen — and R1 forbids the escape hatch E5 needs.** RC7 is logging only (the 2026-08-09 plan ruled "RC7 needs no test (logging only)"). RC1/RC4/RC5/RC15 are builder script-integrity, not "the architect's language handling." RC6 is subsumed by row-per-slide persistence. And **RC11's precondition is retired**: `SelectionContext` is gone from `frontend/src`, and the only surviving `slide_context` producer is Optimize-layout (`SlideViewer.tsx:353`, `SlidePanel.tsx:218`), whose fixed message carries no textual slide reference — so RC11's conflict branch is unreachable through the product. R1 says "removed → delete it"; E5 says "Do not skip them and do not write 'pending'." One of the two has to give.

**13. E6 check 1 is a tautology.** `create_all` at `database.py:411`, `_run_migrations` at `:414`. Three of the four new migrations are no-ops in production because `create_all` already made the tables. So RUNNING proves the ORM converged, not that the migrations ran. The one migration that does real work is §E2's `ConfigPrompts` column DROP, and E6 offers no observable for it. (Relatedly `_reassign_new_objects_to_shared_owner` at `:584` — index finding #12 — is not checkable from RUNNING either.)

**14. "Past 50 minutes" will miss the refresh roughly half the time.** `TOKEN_REFRESH_INTERVAL_SECONDS = 50 * 60` (`database.py:40`) with `jitter = random.uniform(-5*60, 5*60)` (`:136`) — refresh lands anywhere in **45–55 min**. It is an asyncio task per worker, each with its own `_postgres_token` global and its own jitter draw. One request at 51 minutes can land on a worker that has not refreshed. Needs "past ~60 minutes, several requests".

**15. E6 check 7 has no mechanism.** "Force a builder failure" on a live Databricks Apps deployment — no fault-injection flag, env var or failing-prompt recipe exists in any plan. As written this step gets skipped or claimed without evidence.

**16. E6 deploys to devtest; the DoD requires devloop.** The command block is `--env devtest`; the DoD says "on a **devloop** deployment." Per `.claude/skills/deploy-tellr-dev/SKILL.md` these are materially different (devtest reuses `db-tellr` with schema `devtest_app_data`; devloop forks a copy-on-write branch per instance and re-forks on every deploy). Which one changes what checks 1 and 6 mean.

**17. E1's permission claim is wrong at the layer it names.** `get_slide_deck` (`session_manager.py:1455`) performs no permission check — it resolves the deck owner and reads. Enforcement is `_require_slide_permission(session_id, db, PermissionLevel.CAN_VIEW)` in the route (`src/api/routes/slides.py:87`). Aiming the assertion at `get_slide_deck` yields a test that proves nothing.

**18. E1 needs a TypeScript mirror of `DeckSpec` that no plan creates, with no conformance test.** ws4b B1.2 mirrors only `Finding` into TS — *with* a parsing conformance test, because "there is no runtime bridge between the two, which is exactly why they had already drifted." E1 renders `narrative_arc`, `slides[].assumes`/`hands_off` and `design_contract` ids, all of which need TS types plus a `deck_spec` field on `SlideDeck` (`frontend/src/types/slide.ts:16-28` has none) — and gets no conformance guard. (E1's "never compiled style content" assertion is also unfalsifiable at the UI layer: `DesignContractRef` holds three integers.)

**19. E1's toggle placement is under-specified, and the naive reading breaks §7.1's one requirement.** `ViewMode` (`AppLayout.tsx:39`) is route-level navigation, driven by `navigate()` (`:747-756`). The chat + viewer two-pane layout lives *inside* `viewMode === 'main'` (`:871-1006`). "A toggle in `AppLayout.tsx` beside the existing view controls" reads as "add `'spec'` to `ViewMode`", which unmounts the ChatPanel and destroys "one conversation throughout". There is a shipped comment at `:944-946` warning about exactly this — *"React must reconcile this as the SAME element across collapse toggles, or ChatPanel remounts and the conversation state (and any in-flight stream) is lost."* E1's test intent has no assertion that the conversation and an in-flight stream survive the toggle.

**20. E1 ⇄ E2 interaction, unnoticed.** `dismissed` is transient (`useState<Set<string>>(new Set())`, `SlideViewer.tsx:96`) and reset on `deckKey` change (`:153-154`). If the toggle conditionally renders `SpecView` in place of `SlideViewer`, a round trip to the spec unmounts the viewer and resurrects every dismissed finding.

**21. E2's deck-level assertion cannot fail, and misses the hazard ws4b flagged.** `visible.filter(f => f.slideIndex === currentIndex)` (`SlideViewer.tsx:197`) already excludes `slideIndex: -1`, and that line predates this PR. The real grain-routing risk is a deck-level *criterion* on a real slide index — exactly what `frontend/tests/fixtures/findings.ts` ships today (`f3`, `category: 'narrative'`, `slideIndex: 3`) and which does render. ws4b calls this out and says "do not let it become the basis of a deck-level assertion".

**22. §G1's discoverable target is dropped.** The spec requires "a dedicated directory **plus a `make test-agentic` (or equivalent script)**… Discoverable and one command, rather than a marker nobody remembers." E3 and the DoD specify the directory, the marker, the guard and the disabled job — no command.

**23. E4 restates ws4b's tests without saying what it adds.** ws4b B3.1 already covers "version bumps exactly once per call and the optimistic lock rejects a stale write" and "omitted columns are left alone rather than nulled **across two calls**". E4's rows 2 and 3 are the same assertions; the added value must be *concurrency against a real DB*. Row 2 also asserts a **409**, which is route-level (`slides.py:142`, `:162`) in a suite described as needing "a database, no model" — it needs the app too. The genuinely untested case is human-vs-graph: the graph bumps `version` twice per turn while the frontend holds `slideDeck.version`, so a user editing mid-turn gets 409s. E4 tests machine-vs-machine only.

**24. §7.2 is claimed but not delivered or tested here.** ws4e's Spec line includes §7.2; the work is ws4d's. The ws4e-owned assertion this creates is missing: after `clear_context`, the spec view still has data while the transcript is empty.

## Low

**25.** "The table anchors everything in `chat_service.py`" — RC5's anchor in that same table is `src/utils/js_validator.py:3`.

**26.** "This manual check is the only coverage [Google Slides export] has" — `tests/unit/test_google_slides_converter.py` has 20 tests over the converter's helpers. It is the only *end-to-end* coverage. (Separately `tests/integration/test_export_parity.py`, the existing PRD §3 export-parity suite, is not in the CI matrix either.)

**27.** Terminology drift: E2 says the id rule is `(criterion, slide_content_hash)`; ws4b's contract is `make_finding_id(criterion, subject_hash)`, where `subject_hash` is the slide hash for a slide finding and the **deck digest** for a deck one.

**28.** RC10 is specified twice — once as an E3 layer-3 behavioural assertion and once as one of E5's fifteen. Say it is the same test.

**29.** §M7 is cited in the Spec line as though ws4e owns it; only probe 3 is in scope (probe 1 is ws4c `:445`, probe 2 dropped).
