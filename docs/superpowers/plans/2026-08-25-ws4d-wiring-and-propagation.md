# ws4d — Wiring: engine selection, streaming, and spec propagation

> **For agentic workers:** REQUIRED SUB-SKILLS: `superpowers:subagent-driven-development` **plus**
> `executing-plans-tellr`. **Read `2026-08-25-ws4-index.md` first** — this plan inherits its Global
> Conventions and does not repeat them.

**Goal:** Make the graph reachable. A trigger phrase in the chat input selects it per session, slides
arrive incrementally on both transports, and a human edit schedules a debounced deck-spec review.

**Why this is its own PR:** it is the first one with user-visible behaviour, and the first that touches
`chat_service.py` and the slide routes. Everything before it was additive; this is where two engines
start living in one deployment, which is the entire point of §D.

**Depends on:** ws4b (contracts, the writer, the checkpointer) and ws4c (a graph that builds).
**Blocks:** ws4e.

**Spec:** §D, §D0–§D2, §B1–§B5, §K (dirty marker storage, sweeper identity), §3.1, §6.2, §6.3, §7.2, §7.3, §4.4, §4.6, §L4, §M1.

---

## D0 — What the switch is, and what it deliberately is not

**§D0, stated first so nobody hardens it beyond its purpose.** The switch exists so **one developer can
exercise both engines in one deployment**. It is not a product feature, not a security boundary, and
deliberately not defended against misuse. Three consequences, all intended:

- **MCP stays behind structurally, not by input absence.** MCP has no chat input, but `enqueue_create_job`
  (`src/api/mcp_server.py:170`) persists prompts and its worker runs `send_message_streaming`. Mode
  resolution must happen in the **chat route handlers** at the top of the streaming path, with mode passed
  as a parameter to `send_message_streaming` **defaulting to monolith**. MCP never calls those routes, so it
  is excluded by its traffic path, not by capability. Spec §6.4 / PRD §9.2 (the one-shot path) and §D5's
  three MCP obligations are **not delivered by this PR or any of the five** — they travel with MCP to a
  later PR. MCP behaviour is unchanged.
- **No hardening.** A loose substring match is acceptable. If the switch ever outlives testing it needs
  a strict form (exact prefix, first message only) plus an authorisation check, because a phrase matched
  anywhere in user text can be tripped by pasted content or echoed tool output — the injection surface
  §D4's spotlight guards. **Recorded, not built.**
- **Merge risk is not a consideration.** The branch is not released until the graph is ready, so both
  engines coexisting in the tree carries no release exposure.

**It restores both PRD §14 mitigations** that an earlier no-flag decision dropped: the monolith stays
live as the comparison baseline, and dogfooding happens **per message** rather than per deployment.

---

## D1 — Sticky engine-mode resolution

**Contract** — in `chat_service.py`: `AGENT_MODE_PHRASE = "USE AGENT MODE"` and
`resolve_engine_mode(session_id) -> "graph" | "monolith"`.

**Why sticky, and why derived from the transcript.** Evaluated **per message**, only the first turn
would run the graph; turn 2 has no phrase and would fall back. That breaks the thing being tested twice
over: the architect is a *conversation* whose state lives in the checkpointer under a `thread_id`, and a
deck written alternately by both engines would diverge between `session_slides` rows and `deck_json`. So
mode is a property of the **session**.

The cheapest sticky store needs no schema: resolve it from the session's **earliest `role='user'`
message**. `SessionMessage` stores `role` and `content` (`session.py:218-219`), so the answer is derived
from the database — nothing to keep in sync, and multi-worker safe by construction.

**Only the earliest user message counts.** A later message carrying the phrase must **not** switch a
monolith session, or turn *n* writes rows while turn *n-1* wrote `deck_json` — exactly the divergence
stickiness exists to prevent. Assistant messages are ignored so echoed tool output cannot flip the
engine.

**Rejected: a key on `agent_config`.** Measured — `AgentConfig` declares no `model_config`, so
Pydantic's default `extra='ignore'` applies and an undeclared key is **silently dropped** by
`sanitize_agent_config_for_persist` (`agent_config.py:319`). Making it survive means a declared field
plus its validator, both write routes and the frontend types — not worth it for a test affordance whose
answer is already in the transcript.

**Persistence order is verified.** The async route (job-queue path, production) persists the user message
at `chat.py:630-637` before `enqueue_job` at `:640`, so the row exists when the job runs
`resolve_engine_mode`. The sync route persists at `chat_service.py:899` inside `if not request_id:` —
the condition is true only for non-job paths, so again the row exists before mode resolution. Both
paths read from the database, so they see the phrase there. **Critical trap:** the two paths use
**different** `message_type` values (`"user_input"` sync, `"user_query"` async and MCP), so
`resolve_engine_mode` must filter on `role` only (`role="user"`), never on `message_type`. Also:
`POST /sessions/{id}/messages` at `sessions.py:658` lets the caller append an arbitrary-`role`
message, which could become the marker on a session with no user turns yet — unusual but possible.

### The two edges that silently revert a session

Both are real, both are cheap to fix, and neither is in the spec — they are consequences of deriving
mode from the transcript.

1. **Context clearing destroys the marker.** `clear_context` **does not exist anywhere in the repo
   today** — spec §7.2 makes it this PR's work. So this PR builds both halves of a contradiction: §7.2
   drops the transcript, and §D2 reads mode off the transcript's earliest user message. **Resolution:
   clearing preserves the earliest `role='user'` row** and deletes the rest. There is precedent —
   `restore_version` already prunes messages by timestamp (`session_manager.py:2205-2212`) — and it is
   safe for mode resolution because the first user message predates every version.
2. **`duplicate_session` copies no `SessionMessage` rows** (verified: the method references them
   nowhere). A duplicate of an agent-mode session has no phrase and reverts. **Resolution: carry the
   earliest user message across**, alongside ws4a's `deck_spec_json` fix. **This has a consequence:**
   `_hydrate_chat_history` allowlist (`HUMAN_TYPES = {"user_query", "user_input", "chat"}`,
   `:1761`) replays it as turn 1 of the duplicate. And `message_count` is a live `COUNT` query, not a
   column (`:779-782`), so a duplicate carrying one message has `is_first_message == False`, suppressing
   title generation on its first *real* turn (when the architect starts working). This is acceptable —
   the early message is metadata, not user input, and the title should come from the new conversation.
   **But do not copy any other `SessionMessage` rows** — only the phrase marker. The duplicate is
   graph-mode with a deck that exists in `deck_json` (from ws4a's fix), not in prior `session_slides`
   rows, so copying rows would create a phantom-data inconsistency.

### `clear_context` — implementation and two requirements beyond the obvious

**Route and service signature:** `DELETE /sessions/{session_id}/context` calls
`ChatService.clear_context(session_id)`. Test that only a `CAN_EDIT` user can call it.

**Keep the deck spec.** §7.2's whole point: the spec is a structured compaction of the conversation, so
once it holds what was decided the transcript is just the path taken to get there. Clearing drops the
agent context and the transcript, keeps the spec, and **loses nothing that was agreed**. Every
non-architect agent starts empty on every invocation, so no hidden state can survive a clear and make
the agent "remember" something the user cleared.

**Delete the graph thread**, via `BaseCheckpointSaver.delete_thread`. It is **not** a base-class no-op:
probed on langgraph-checkpoint 4.1.1, the base method body is `raise NotImplementedError`, so an
unimplemented saver surfaces as a 500 on the clear route rather than skipping quietly. ws4b's B2.1
implements it for the Lakebase checkpointer — call that, rather than inventing a function. Otherwise
checkpointed state outlives the clear.

**Gate on `CAN_EDIT`, not the default.** `_check_deck_permission_for_session(session_id)`
(`src/api/routes/_authz.py:188-191`) defaults to `PermissionLevel.CAN_VIEW`, so taking the default
would let a **viewer** wipe another user's transcript and graph thread. The superseded plan presented
this check as closing a security finding ("any authenticated user could wipe any session") while
leaving it at view level — which closes the finding only nominally. Pass `CAN_EDIT` explicitly, and
note the helper raises `HTTPException`, not `PermissionError`. (Round-3 finding 20.)

**Test intent:** the phrase in the first message selects the graph and its absence the monolith; mode is
sticky across turns; a **later** phrase does not switch a monolith session; assistant messages are
ignored; a session with no user message and an MCP-created session both get the monolith; clearing
preserves the mode, drops the rest of the transcript, deletes the graph thread, keeps the spec, and
**refuses a viewer**; a duplicated graph-mode session stays in graph mode.

---

## D2 — Route a graph-mode turn through the graph

**Contract:** a branch at the top of the streaming path, after the user message is persisted and before
the monolith is invoked, delegating to a `_send_message_streaming_graph` generator that builds the
initial state, calls `invoke_graph`, and yields `StreamEvent`s.

**`invoke_graph` must run in a separate thread.** `_send_message_streaming_graph` is a generator that yields `StreamEvent`s as they arrive. A synchronous `invoke_graph(session_id, initial)` call blocks until the graph completes, so calling it directly inside the generator cannot yield anything until finished — incrementally delivered slides would be impossible. The monolith solves this with `run_agent` in a thread (`:1187`) plus an `event_queue` (`:1107`). Apply the same pattern: invoke the graph in a worker thread, yield events from a queue as they arrive, and signal completion with a sentinel. This is not just an implementation detail — it is the contract for "slides arrive incrementally."

**`send_message` is NOT a generator.** `chat_service.py:819` returns/raises, so adding `yield from`
there converts it into one and breaks every caller. The graph branch goes **only** in
`send_message_streaming`. If the non-streaming entry point needs graph support, that is a separate,
explicitly-designed path — not the same three lines. (Round-3 finding 19's sibling.)

**Leave the monolith path untouched.** Do not refactor a shared helper "while you are in there": the
monolith is §D's comparison baseline, and perturbing it breaks both the comparison and every existing
user.

**The initial state carries only keys `GraphState` declares, and it resolves nothing brand-related.**
Do **not** put `design_contract` in it: the key is not on `GraphState` (ws4c C1's table is the exhaustive
contract), so the runtime **silently drops** the write and no node ever sees the value. Do **not** resolve
template bytes here either — `token_css`, `deterministic_css`, `template_layout_html` and `resolved_style`
are single-writer keys ws4c assigns to `architect_node`, which resolves them once per turn through
`resolve_template_bytes` (C6); a second resolver in this generator either races that write or is overwritten
by it. **`architect_node` is the sole resolver of the design contract and the template bytes.** There is
nothing here to resolve *from* on turn 1 in any case: the contract lives at `deck_spec.design_contract`, the
architect is what commits `deck_spec`, and `build_branch_payload` copies the contract into each branch.

**Graph mode must also run `run_title_gen`.** The monolith runs it inline at `send_message_streaming:1155`
only when `is_first_message` (`:1193-1196`), emitting `SESSION_TITLE` (`:1564`). A graph branch that
bypasses the monolith entirely bypasses title generation — every graph-mode session stays untitled. The
graph branch must replicate the title-generation step: call the title model with the first message,
rename the session on success, and emit `SESSION_TITLE` to the event queue. Failing the title-gen does
not fail the message — catch and log (as the monolith does), so a naming service outage does not
stall conversations.

**Test intent:** a graph-mode turn writes rows **and** all eight deck-level columns — assert `css` is
non-empty (the §H defect), `deck_spec` present, `external_scripts` non-empty (its absence is **silent**:
no exception, just blank charts in every export), and `slide_count` equal to the row count rather than
0; **two** version bumps per turn (§L2's two deck-level writes, neither per-slide); a monolith-mode turn
still reaches the monolith; a graph-mode turn never does. **Graph-mode sessions are titled** — assert a
`SESSION_TITLE` event arrives with a non-empty string on turn 1 of a graph-mode session.

**Note on mocking the monolith:** `generate_slides_streaming` is a **method on the agent class**
(`agent.py:1582`), not a module function, so `monkeypatch.setattr("src.services.agent.generate_slides_streaming", …)`
raises `AttributeError`. Patch the class attribute. (Round-3 finding 18.)

---

## D3 — Incremental slide delivery on both transports

**§6.2, against §3.1's binding constraint.** `slides` is carried **only** on the terminal `COMPLETE`
event (`streaming_callback.py:371`; `StreamEvent.slides` is documented "for complete event"). There is
no incremental slide event today, so per-slide delivery changes **both** transports.

**The polling path is the harder one.** `poll_chat` (`chat.py:669`) does not relay live events at all —
it reads persisted `SessionMessage` rows and converts them via `msg_to_stream_event`
(`session_manager.py:2772-2799`), which returns only six hardcoded keys: `type`, `content`, `tool_name`,
`tool_input`, `tool_output`, `message_id`. It **cannot carry** `position`, `html`, `scripts` even if
the converter learned the type, because the method returns a fixed dict shape with no place for them.
So the polling path does **not** deliver incremental slides — `poll_chat` has no `slide_cursor`
parameter, no new response field for slides, and no way to return them. **This contradicts the contract
table**, which requires "`msg_to_stream_event` maps `slide_ready` explicitly" and `slides_since_cursor`
as the release query. If slide-ready rows are never persisted (finding 3's own two-line contradiction),
the converter never sees them and is dead code. **Resolution:** do not persist `slide_ready` as
`SessionMessage` rows. Instead, the polling path reads committed `session_slides` rows directly via
`slides_since_cursor(session_id, cursor)` — the same reorder-buffer query that enforces ascending
release on both transports, without needing a converter that cannot carry the data. Update the
contract table to remove the `msg_to_stream_event` row and clarify that polling reads slides via query,
not message conversion. **Note `msg_to_stream_event` is a METHOD on `SessionManager`**, not a module
function — a module-level import of it is an `ImportError`. (Round-3 finding 18.)

**The reorder buffer is a query, not a data structure:** release position *n* once all positions `< n`
are committed. Because the truth is the `session_slides` rows, it is inherently multi-worker safe; an
in-process buffer would be invisible to the worker serving the next poll.

**Contract:**

| Change | Where | Note |
|---|---|---|
| `SLIDE_READY = "slide_ready"` on the **`StreamEventType` enum** | `src/api/schemas/streaming.py` | `StreamEvent`'s field is `type`, not `event_type`, and `to_sse()` reads `self.type.value` — so a new type that is not on the enum cannot be constructed |
| `position`, `html`, `scripts`, `agent`, `slide_cursor` as optional fields | same | `StreamEvent` already has optional fields, so this extends without breaking consumers. **`scripts: str = ""`**, not `scripts: Optional[str]` — all fields follow the pattern `fieldname: Type = default_value`, and `Optional[str] = None` breaks existing code that passes no `scripts` argument. A bare `scripts: str` would break every existing `StreamEvent(...)` construction too. The correct form is `scripts: str = ""` so the field is always present, defaulting to empty. |
| `SessionManager.slides_since_cursor(session_id, cursor)` | `session_manager.py` | The release query over rows, reusing `releasable_positions`' prefix rule |
| `emit_slide_ready(queue, position, html, scripts)` | `src/services/streaming_callback.py` | That module currently contains **only** `class StreamingCallbackHandler` — no module-level functions — so this is a new function, not an edit to an existing one. (Round-3 finding 21's sibling.) |
| `slide_ready` on the `StreamEventType` union plus the new fields | `frontend/src/services/api.ts:62` | **There is no `frontend/src/types/streaming.ts`** — these types live in `api.ts` |

**The emitter must queue the OBJECT.** Every existing emitter queues the `StreamEvent`, and `chat.py`
calls `.to_sse()` on what it dequeues — so queueing a pre-serialised string double-encodes and raises
on the first slide.

**Persisting slide-ready as a `SessionMessage` was rejected:** it pollutes the chat transcript with
build mechanics, which matters more now the transcript is user-visible and clearable. The polling path
reads **committed rows** via the cursor instead.

**Agent attribution (§7.3) is attribution, not a new UI.** `Message.tsx:93` already renders tool calls
with their arguments, so this is one optional `agent` field plus a label in the existing renderer. It is
**required rather than polish**: with builders running in parallel, unattributed events make the chat an
interleaved stream of anonymous tool calls from many concurrent agents — actively worse than today's
single-agent view. **Coalesce at the fan-out** — "dispatching 10 slide builders" as one message, then
progress as slides land, not ten "builder N started" lines. Activity messages get the treatment
`_hydrate_chat_history` already gives `reasoning`/`info`/`tool_*`: excluded from replay, so they stay
out of the architect's context.

**Test intent:** streaming transport — `slide_ready` is on the enum; the event carries position/html/scripts
and survives `to_sse()` — **assert on parsed JSON, not on a formatted substring**, because `to_sse()` uses
`model_dump_json()` which emits compact JSON with no space after the colon; existing consumers are
unbroken by the new optional fields; the emitter queues the object. Polling transport — the cursor
returns only newly-released positions and nothing on a re-poll; release never emits out of order when a
later position lands first; a placeholder position is released like any other. **Frontend rendering of
`slide_ready` events is ws4e's responsibility** (`handleStreamEvent` in ChatPanel.tsx:183) — this PR
delivers infrastructure on both backend transports; ws4e realizes the user-visible feature of incremental
slides in the UI.

**Two test-hygiene notes.** Do not write `assert … in (str, "Optional[str]", type(None))` — a string
literal can never equal an annotation object and `type(None)` would pass a broken field; assert the
annotation is exactly `str`. And keep imports at module scope in these test files: a previous draft used
`SessionManager()` in one test while importing it function-locally in the preceding one.

---

## D4 — `spec_sync.mark_dirty`, from route handlers only

**§B1 is a decision about code this PR writes, not a description of code that exists** — verified,
neither `spec_sync` nor `mark_dirty` exists anywhere in the repo.

**Contract** — `src/services/spec_sync.py`: `DEBOUNCE_SECONDS = 180`,
`mark_dirty(session_id, author)`, `clear_marker(session_id)`.

**The placement rule is the whole design.** `mark_dirty` is called from the **route handlers** in
`src/api/routes/slides.py` — **never** from a service method in `chat_service.py`. The graph calls those
service methods directly, so it never fires the trigger. Placed that way, §4.5's claim becomes true **by
construction** rather than by convention: "arrived via the route" *means* "a human did this", because
the route is the only human entry point and the graph does not use it. No stored flag, no `origin=`
parameter to forget, no ContextVar to leak. **The failure mode requires actively wiring a new route
call, not merely forgetting a parameter.**

**Rejected:** an `origin='human'|'agent'` parameter (a caller that forgets it silently rebuilds a user's
manual edit — the "actively hostile" outcome §4.5 names); a ContextVar (probed to survive `Send`
fan-out, but invisible coupling and a missed reset leaks origin into the next request); a persisted
origin column.

**The route table:**

| Route | Trigger? | Why |
|---|---|---|
| `PATCH /slides/{index}` | **yes** | the human HTML edit |
| `PUT /slides/reorder` | **yes** | mutates the narrative arc with **no HTML change** — a content-hash trigger would miss it entirely |
| `POST /slides/{index}/duplicate` | **yes** | slide added |
| `DELETE /slides/{index}` | **yes** | slide removed |
| `POST /slides` (D6) | **yes** | slide inserted |
| `PATCH /slides/{index}/verification` | **out of scope** | verification verdicts do not trigger a deck-level review — they *complete* a builder task triggered by a prior change. If a human manually changes a verdict, that should re-run the review, but the specification of what "manually" means (edit route? approval endpoint? verdict-specific route?) is deferred. |
| `POST /slides/versions/create` | **out of scope** | version save/restore are part of PR ?. A version save is not a deck change (the live deck is unchanged); restoring is handled separately at D6. |
| `PATCH /slides/versions/{n}/verification` | **out of scope** | see `PATCH /slides/{index}/verification`. |
| `POST /slides/versions/sync-verification` | **out of scope** | verification sync across versions is part of PR ?; defer trigger semantics. |
| version restore | **no** | D6 *cancels* the pending review instead |
| `POST /sessions/{id}/duplicate` | **no** | a **copy, not a trigger** — the duplicated spec is already correct for the HTML it carries. Its absence from §B1's list was silence rather than a decision, which is what made ws4a's defect invisible |
| `tour.py` | **no** | see below |

**`tour.py` does not fire it.** `_phase2_add_slides` loads a **canned fixture**
(`src/api/fixtures/tour_demo_deck.json`, 4.7 KB, module-cached at `tour.py:34-39`) and saves it via
`sm.save_slide_deck` at `:82`. It is deck *creation* from fixed bytes, identical on every tour, so
firing `mark_dirty` would schedule an LLM arc re-description of the same demo deck **for every user who
takes the tour**, at §B2's per-window cost, for no value. **Ship the arc description inside the
fixture** — one `narrative_arc` field in the `DeckSpec` JSON, authored **once by hand**, never at
runtime. That field travels through `sm.save_slide_deck` → `_upsert_slide_deck` → persisted
`deck_spec_json`. Strictly better than excluding the route, because the tour then also demonstrates
§7.1's spec view, which an excluded-and-specless tour deck could not. Verify that the fixture's
`narrative_arc` text is **not** empty — a placeholder or the demo deck's actual content.

**Marker semantics:** setting is idempotent within a window — an existing unclaimed marker keeps its
**original** timestamp, so a burst of WYSIWYG edits coalesces into one review rather than pushing the
window out forever. The author is refreshed on each set (the most recent human editor is the right
attribution, and the review has not run yet).

**Contributor sessions and deck ownership:** Decks are shared across sessions via `UserSession.parent_session_id`;
a contributor session has `UserSession.slide_deck` as `None`. Routes pass `request.session_id` directly to
`mark_dirty`, which can receive a contributor id. **`mark_dirty` must resolve the actual owner deck via
`SessionManager._get_deck_owner_session(db, session)`** — an **instance method** taking a live `Session` and
a **`UserSession` object**, never a session_id string (`session_manager.py:709`; every one of its ~20 call
sites passes both, e.g. `:1096`, `:1300`). So `mark_dirty` opens a session, looks the `UserSession` up from
its string id, and passes the object — writing `_get_deck_owner_session(session_id)` raises `TypeError` on
the first human edit. The marker lives on the owner deck, not the contributor's ephemeral
session. And `claim_due_marker` returns the **owner's** string id, so if `clear_marker` uses a different key,
markers are never cleared on the owner when a contributor session clears them — both must use the owner-resolved
key.

**Test intent:** **only `src/api/routes/slides.py` may reference `mark_dirty`** (the structural
guarantee — grep the entire tree and assert no other file imports or calls it); every human mutation
route in slides.py calls it; reorder triggers despite no HTML change; the marker records its **author**;
a graph write does **not** set it; `tour.py` never calls it and its fixture ships a `deck_spec` with
a narrative arc; session-duplicate is a copy, not a trigger; the four routes not yet in the table
(`PATCH /{index}/verification`, `POST /versions/create`, `PATCH /versions/{n}/verification`,
`POST /versions/sync-verification`) either call it or are explicitly ruled out in this PR's scope.

---

## D5 — The debounce sweeper, with an atomic claim

**It cannot ride `enqueue_job`.** `src/api/services/job_queue.py` is an in-process `asyncio.Queue`
(`:21`) plus an in-memory `jobs` dict (`:20`), drained FIFO by a per-worker `worker()` loop
(`:214-239`). It has **no delay or at-time primitive**, so a 180 s coalescing window has nothing to hang
off. What *is* reusable is the **sweeper pattern**: `mark_timed_out_jobs_loop` (`:342-352`) with
`TIMEOUT_SWEEP_INTERVAL_SECONDS = 60` (`:33`) — a periodic loop that reads DB state and acts on whatever
is due.

**This is a LOOP, so it belongs in the FastAPI lifespan**, next to `mark_timed_out_jobs_loop` — **not**
in `run.py::init_database`. §L8's pre-fork rule is about migrations and backfills, which must run once;
a periodic loop is the opposite case.

**Contract:** `claim_due_marker(now) -> (session_id, author) | None`, `run_arc_review(session_id, author)`,
`spec_review_sweeper_loop()`, `SWEEP_INTERVAL_SECONDS = 60`, `CLAIM_TTL_SECONDS = 900`. The claim is
stored in `session_slide_decks.spec_dirty_claimed_at`, the third column created by **ws4b's B2.3**
migration. Cite the section, not a line: `:497-498` was B2.1's `Send(timeout=)` trap, and a line anchor
into a sibling plan moves every time that plan is edited.

**The claim is required, not defensive.** `run.py:128` defaults `UVICORN_WORKERS=4` and the sweeper runs
in every worker, so four loops racing one marker with no lease means a WYSIWYG session pays for up to
**four identical LLM arc reviews per window** — the exact cost the debounce exists to avoid. A
conditional `UPDATE … WHERE claimed_at IS NULL … RETURNING` is what makes it safe.

**`session_slide_decks.session_id` is the INTEGER PK of `user_sessions`, not the string session id**
(`session.py:252-257`). So `RETURNING session_id` yields an int, and `read_deck_spec` / `clear_marker`
filter on the **string** — no row matches, the marker is never cleared, and it is re-claimed every
`CLAIM_TTL_SECONDS` **forever**. Map the FK through `user_sessions` to the string before returning.
(Round-3 finding 3 — this one would have been invisible until a deck wedged in production.)

**A stale claim must be reclaimable** so a worker that dies mid-review does not wedge the deck
permanently — hence the TTL rather than a bare `IS NULL`.

**Identity: the marker's recorded author.** Spec §K asks "What identity a sweeper-driven arc review runs
as" — this PR answers it: use the marker's recorded author, `spec_dirty_by`. A sweeper tick has no
request, so `get_current_user()` returns `None` (`user_context.py:21-23`) and `get_user_client()`
**fails closed** in production (`databricks_client.py:492`, raised at `:536`; `:511-515` records that
SDR-4437 HIGH-6 removed the SP fallback outside non-prod). The LLM call itself is fine —
`agent_factory.py:56` uses `get_system_client()`, SP-scoped by design — but `modified_by`, the deck
permission check and PRD §8.1's cost attribution are not. Using `spec_dirty_by` gives all three a real
user, and the permission check already happened on that human's route when the marker was set. **A
marker with no author is not claimed** — with no identity there is no attribution, and inventing a
system identity was the rejected alternative. **Note:** the sweeper tick must call
`set_current_user(author)` for its duration, so `require_editing_lock` and permission checks see the
actual user, not `None`. (Finding 11 — identity must be *bound*, not just recorded.)

**`run_arc_review` never raises.** A failure clears the **claim** but keeps the **marker**, so the next
sweep retries rather than the deck wedging.

**Test intent:** a marker younger than the window is not due; an older one is claimed with its author;
**only one of four concurrent claimers wins**; a claimed marker is not re-claimed; a **stale** claim is
reclaimable; the review stamps `modified_by` from the marker; a successful review clears the marker; a
failing review clears the claim but keeps the marker; a marker with no author is not claimed.

**Sabotage:** drop the `claimed_at` predicate and confirm the four-claimer test goes red. Note the
four-thread test on sqlite is weak by construction — sqlite's single-writer lock tends to surface
`database is locked` rather than demonstrate the race — so **the load-bearing version of this test is
ws4e's layer-4 one against a real database.** Say so here rather than trusting the sqlite version.

---

## D6 — Restore cancels; insert-slide; deck-level spec edits

### Restore cancels a pending review (§B3)

On restore, **discard the marker without running the review.** Two reasons: the deck those pending edits
described no longer exists, and `SlideDeckVersion` carries its own `deck_spec_json` snapshot
(`session.py:358`) which PR1 already restores (`session_manager.py:2222,2240`) — so the restored spec is
authoritative.

This also closes §B0's remaining edge, which is a **stale-marker** edge and does not depend on who
restores: a restore replaces whole-deck HTML, so any marker left by the pre-restore deck's edits now
describes a deck that no longer exists. (An agent-driven restore fires no trigger at all, because the
graph calls `restore_version` directly and never routes.)

**Test intent:** restoring discards a pending marker; restoring does **not** run the review (monkeypatch
it to raise and assert nothing calls it); the restored spec comes from the **version's** snapshot, not
the live spec.

### Insert slide — new scope (§B4)

Tellr has **no insert-slide capability**. `SlideDeck.insert_slide(slide, position)` exists
(`slide_deck.py:251`) and is used at **six** internal call sites (all in `chat_service.py`), but there is
no service method and no route — the mutating routes are only reorder, patch, duplicate, delete,
verification and versions. A user can only obtain a new slide by asking the agent or duplicating one.

**This PR adds the backend and spec halves:** `chat_service.insert_slide(session_id, position, …)`
following `duplicate_slide`'s shape (clone/insert, `_reindex_slide_ids`, `save_slide_deck`, save point);
`POST /slides` taking a position; a deck-spec slide entry for the new position; the §4.4 trigger on the
route; and position-shift handling for every position above the insertion point.

**No UI** — the "add slide here" affordance belongs with ws8, where slide-stage affordances live. The
capability is fully usable via the API and via the architect ("add a slide after slide 3").

**`deck_spec_slide` travels with shifted positions.** `_attribute_slide_records` (`session_manager.py:194-239`)
maps `{new_position: verification_record}`, and `_upsert_slide_row` treats `deck_spec_slide=None` as
"leave unchanged" (`:337`). So a shift calls `_attribute_slide_records`, which moves verification
records correctly, but `deck_spec_slide` stays attached to the old position. D6 also introduces
persisting per-row spec fragments. **Update `_attribute_slide_records` to shift `deck_spec_slide`
values alongside verification records** — map both, so the per-slide spec snippet moves with its slide.

**Test intent:** inserting shifts every higher position; the slide lands at the requested position; the
deck spec gains an entry and higher entries shift with contiguous positions; **verification records
AND `deck_spec_slide` fragments travel with their slides across the shift** (either belongs to a slide,
not a position); the route fires the trigger; a save point is created; inserting beyond the end appends
rather than erroring.

### Deck-level spec edits and confirm-then-rebuild-all (§4.6, widened by §L4)

A deck-level change ("actually this is for a CFO, not engineers") logically invalidates every slide, so:
**re-review all, rebuild only what fails, and tell the user first.** Reviewers score every slide against
the **new** spec (cheap, parallel); only slides that actually contradict it are rebuilt, preserving
still-valid work **including manual user edits**. A blanket rebuild-all was rejected as expensive and
destructive.

**Design-contract changes are the exception — confirm first, then rebuild all.** Unlike an audience
change, a restyle genuinely affects every slide, so re-review-then-selective-rebuild would flag all of
them anyway. This is the one place a rebuild-all is correct, and gating it on confirmation keeps it from
firing by accident.

**§L4 widens the trigger three ways:** it is now **three** fields, not `slide_style_id` alone;
**pinning or unpinning a template is also a design-contract change**, because pinning is what supplies
the template's own CSS (an unpinned deck gets only a name/description catalog with no CSS); and setting
`design_system_id` additionally **clears** `slide_style_id`, so **one user action mutates two fields** —
the confirmation must **say** the slide style is being dropped, not silently drop it.

**§M1: the architect's tool manifest must carry the design-system library**, not just
`AgentConfig.tools`, or the architect cannot offer a brand it cannot see.

**Test intent:** an audience change re-reviews all and rebuilds only failures; a design-contract change
returns `confirm_design_contract` and dispatches **no** builder; the confirmation message mentions the
slide style being cleared; pinning a template is treated as a design-contract change; confirming then
rebuilds every position; the manifest includes the design-system library with each system's templates.

---

## Definition of done

- [ ] Every suite passes and **every guard has been sabotage-verified** on the executed path.
- [ ] **Streaming paths only:** `resolve_engine_mode` correct on `send_message_streaming` and its
      callers (`chat.py:588` async route, `chat.py:708` sync route). The non-streaming `send_message`
      path (§3.1 entry point 4 at `api.ts:876` / `submitChatAsync`) is explicitly out of scope — D2
      excludes it. Test is: mode is sticky on the two entry points in scope, and `send_message` never
      references the graph. Persistence order: the async route persists the user message at
      `chat.py:630-637` before `enqueue_job` at `:640` — so the row exists when `resolve_engine_mode`
      runs; the sync path persists at `chat_service.py:899` inside `if not request_id:` — both read the
      row correctly.
- [ ] A graph-mode turn writes rows **and** all eight deck-level columns, with **two** version bumps.
      **Graph-mode sessions are titled** — `SESSION_TITLE` event arrives on turn 1.
- [ ] A monolith-mode turn is unchanged: `test_agent.py`, `test_llm_edit_responses.py` and
      `test_slide_replacement_flow.py` all pass, and `git diff` shows no gratuitous change to the
      monolith path.
- [ ] Slides arrive in ascending order on **both** transports, and a placeholder releases like any
      other position.
- [ ] `clear_context` keeps the spec, deletes the graph thread, preserves the mode marker, and
      **refuses a viewer**. Route is `DELETE /sessions/{session_id}/context`.
- [ ] The sweeper's claim is exclusive; a marker with no author is not claimed; a failed review retries.
      **Sweeper tick runs with `set_current_user(author)`** so `require_editing_lock` sees the user.
- [ ] `tour.py` never calls `mark_dirty`, and its fixture ships a hand-authored `narrative_arc`.
      **The fixture's arc is not empty** — verify populated with the demo deck's actual description.
- [ ] **Only `src/api/routes/slides.py` references `mark_dirty`** — grep the tree and assert no other
      file imports or calls it.
- [ ] Full suite compared **by cause** to the index's baseline: no new cause, no change to the
      deploy-autoscaling cause, no test that stopped existing.
- [ ] MCP behaviour **unchanged** — `create_deck` / `edit_deck` contract tests pass untouched.
