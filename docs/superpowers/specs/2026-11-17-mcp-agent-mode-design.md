# Tellr MCP on Agent mode — design

Date: 2026-11-17. Status: draft for review.

Decisions are marked **(decided)** when the user made them, and **(my call)** when the
designer made them and the user has not yet confirmed them. Unmarked text describes the
code as it stands on `main` (b11fde39).

## Intent

Tellr is standardising on Agent mode, and Legacy mode will be retired. Legacy already
gets no updates. The Tellr MCP server (`src/api/mcp_server.py`) is the last surface
that still creates Legacy decks: `create_deck` makes every deck
`deck_mode="legacy"`, and `edit_deck` and `create_deck` jobs carry no `engine_mode`, so
the worker runs them on the monolith. Moving the MCP onto Agent mode removes the last
reason Legacy has to exist. **(decided)**

The MCP is built for **people**, not autonomous agents. **(decided)** The usual flow:
someone writes a prompt in Claude Code (or another agent tool), sends it to Tellr with
`create_deck`, gets a link, and then refines the deck in the Tellr app. Returned HTML is
of limited use; the link is what matters. **(decided)**

## Goals

1. **`create_deck` creates an Agent deck** and builds it from the prompt without asking
   questions. Callers keep the same contract: they send a prompt, get back
   `session_id` + `request_id`, and poll `get_deck_status`. **(decided)**
2. **Design system and template stay optional fields** on `create_deck`. If they're
   left blank, the deck gets the system default, as a new deck in the app does.
   **(decided)** Because the design is fixed at creation, the architect never has to
   stop to propose a design change on a normal one-shot build.
3. **MCP decks get the same tools and defaults as a new deck made in the app**, for
   example Genie One when the admin's "Add Genie One to new decks" switch is on.
   **(decided)**
4. **`edit_deck` runs on Agent mode**, so Agent decks made in the app become editable
   over MCP by their owner, which they aren't today. Collaborators are refused.
   **(decided)**
5. **Light conversation with the architect over MCP.** `edit_deck` accepts a change
   *or* a question. Agent mode already decides which it is: the architect classifies
   every message as `build`, `edit`, `ask_data`, `confirm_design_contract` or
   `discuss`. The status response carries the architect's reply and says whether the
   deck changed, so Claude can show the reply to the person. **(decided)** No new tool.
6. **Legacy decks are refused over MCP.** `edit_deck` on a Legacy deck returns a clear
   error with the deck's Tellr link. This includes every deck made over MCP until now.
   It is a **breaking change**, accepted as one. **(decided)** We build no
   compatibility path.

## Non-goals

- **Supporting Legacy decks over MCP** in any form. **(decided)**
- **Autonomous agent-to-architect dialogue.** That means a calling agent answering the
  architect's questions itself, with structured questions, turn limits and so on.
  **(decided:** build for human usage first)
- **A dedicated chat tool** (`send_message` or similar). `edit_deck` is the
  conversation. **(decided)**
- **A stop tool over MCP.** The person who sent the MCP turn can stop it from the Tellr
  app with the existing stop sign; the app lets only a request's sender stop it
  (`_require_chat_request_owner`). **(my call)**
- **Changes to the `fe-tellr` plugin** in the vibe repo. Its skill already says to hand
  the link back and refine in Tellr. If its wording should change, that's a separate PR
  in that repo (EMU account, owner can't self-merge). **(my call)**
- **Deck prompts in Agent mode.** They will come back in a different shape, as separate
  work. **(decided)** This work only removes `deck_prompt_id` from the MCP.

## Anti-goals (a failure even if it technically works)

- **A second copy of the Agent-mode Enter sequence** inside `mcp_server.py`. The async
  chat route's Enter (generation snapshot, lock binding, refusals, rollback) is
  subtle and was hardened over several PRs. A diverging copy would reopen bugs that
  were already closed.
- **A poll that never ends.** Any terminal state a turn can reach, including a stop
  from the Tellr app, must map to a status that existing callers already treat as
  terminal (`ready` or `failed`).
- **Reporting an edit as applied when the deck didn't change.** Today's
  `clarification_needed` exists because this happened once (WG2-01).
- **An MCP deck that differs from an app deck.** It shouldn't have different tools,
  defaults or engine behaviour. Someone who opens an MCP deck in Tellr should find a
  normal Agent deck.

## What callers see

### `create_deck`

Same response (`session_id`, `request_id`, `status: "pending"`). The parameters are
`prompt`, `design_system_id?`, `template_name?`, `slide_style_id?` and
`correlation_id?`; `num_slides` and `deck_prompt_id` are gone (below). Behaviour changes:

- **It creates an Agent deck** (`deck_mode="agent"`, pinned to the active graph
  release, like the tour's and the app's new decks). If no graph release is active, it
  returns a clear error. **(decided)**
- **Style source:** unchanged resolution. An explicit `design_system_id` or
  `slide_style_id` wins; otherwise the org-default design system, otherwise the
  org-default slide style. `template_name` pins one of that design system's templates;
  if there's no name, or the name doesn't resolve, the design system's default template
  is used. **(decided)**
- **Tools:** the same new-deck defaults the app's `_maybe_create_session` seeds (today
  that is `_apply_genie_one_default`). No longer `{"tools": []}`. **(decided)** The
  tool description drops "v1 runs prompt-only: the agent does not invoke Genie…".
- **`num_slides` is removed from the tool.** **(decided)** It's a Legacy idea and
  doesn't fit the Agent-mode principle that everything goes through chat. A caller who
  wants a count says so in the prompt, and the architect's instructions already say
  "When the user states a slide count, plan that many slides." Nothing is lost: today
  the field is **silently dropped**, because `AgentConfig` has no `num_slides` field and
  `create_session`'s normaliser (`normalize_agent_config_dict`) discards unknown keys.
- **`deck_prompt_id` is removed from the tool.** **(my call**, following the user's
  note that deck prompts will come back in a different shape**)** Agent mode never reads
  it: only the monolith's prompt assembly (`agent_resolution._get_prompt_content`)
  does, and the graph reads only `resolve_style_source`. So the parameter does nothing
  on an Agent deck.
- **Callers that still send a removed parameter don't error.** FastMCP's argument
  model (`ArgModelBase`, pydantic, extra keys ignored) silently drops an argument the
  tool no longer declares; checked 2026-11-17 against the locked `mcp` version. The
  release note still names every removed parameter (these two, and `edit_deck`'s
  `slide_indices`), because the values now do nothing.
- **A prompt with no topic** ("make me a deck"): the architect answers `discuss` and
  asks what it's about. The turn completes with no slides. `get_deck_status` returns
  `ready` with the question as the reply and `deck_changed: false`. **(my call)**

### `edit_deck`

Same response. The parameters are `session_id`, `instruction` and `correlation_id?`;
`slide_indices` is gone (below). Behaviour changes:

- **Agent decks only.** If the deck's engine resolves to `monolith` (Legacy), it is
  refused before anything is written. The error says the deck can't be edited over MCP
  and gives its `deck_url`. **(decided)** Engine resolution uses the existing
  `resolve_engine_mode`.
- **Owner only.** A caller who isn't the deck's creator is refused with the link (see
  "Permissions and refusals"). **(decided)**
- **A change or a question.** The tool description says so, and tells the caller to
  show the architect's reply to the user. **(decided)**
- **`slide_indices` is removed from the tool.** **(decided)** It is slide-selection
  state, the kind Agent mode retired when it deleted `SelectionContext`, and it doesn't
  fit "everything through chat". The caller names the slides in the instruction ("on
  slide 3, …"). Agent mode already finds slide references in the message text
  (`resolve_slide_references`), and it edits disjoint slides independently. With the
  parameter go the Legacy-only pieces behind it: `_check_contiguous`, the 0-based
  index lookup, and the `slide_context` the MCP built from them. The tool description
  says to name slides by number in the instruction.
- **The instruction is persisted exactly as sent.** Nothing is added to it, so the
  Tellr transcript shows what the architect read. **(my call)**
- **A design-system change asked for in an instruction** ends the turn with the
  architect's proposal (`confirm_design_contract` → END) and the deck unchanged. The
  person answers with another `edit_deck` ("yes, go ahead"). No special handling: this
  is the conversation working as designed.

### `get_deck_status`

Same statuses (`pending`, `running`, `ready`, `failed`) and same `ready` payload,
plus two fields. **(my call)**

- **`reply`**: the architect's message for this turn, as the Tellr chat shows it. This
  includes the "this is a starter, you could explore next…" suggestions on a build.
  `null` if the turn produced no architect message.
- **`deck_changed`**: whether this turn changed the deck's slides or deck-level
  fields. It is `false` for `discuss` and `confirm_design_contract` turns.

Existing fields, on an Agent turn:

- `metadata.clarification_needed` is `true` exactly when `deck_changed` is `false`,
  and `metadata.clarification` carries `reply`. That keeps today's promise ("ready
  is not always an applied change") for callers that already read it. **(my call)**
- `replacement_info` is `null`. The graph's COMPLETE event doesn't produce one, and
  we don't invent one.
- `messages` is unchanged (the turn's persisted rows).
- **A stopped turn.** The owner pressed stop in Tellr, or a timeout or orphan sweep
  rolled the turn back, leaving the chat request `cancelled`. This reports
  `status: "failed"` with an error that says the generation was stopped and the deck
  is unchanged. **(my call)** Today `cancelled` falls through to "Unknown job status".
  We use `failed`, not a new `cancelled` status, so pollers that only know
  `ready`/`failed` still stop.
- **A failed Agent turn** is rolled back (Agent turns are all-or-nothing, PR #385), so
  `failed` now also means "deck unchanged". The error text can say so.

### `get_deck`

Unchanged. It reads the persisted deck and works for both modes. **(my call)**
Read-only access to a Legacy deck stays allowed; only `edit_deck` is refused.

## How a turn enters Agent mode

The MCP today calls `enqueue_create_job`, a trimmed copy of the async route: acquire
lock, create request, persist the user message, enqueue. An Agent turn needs more than
that. `POST /api/chat/async` (`src/api/routes/chat.py`, `send_chat_async`) does all of
the following:

- binds the session lock to the request (`bind_session_lock`);
- reads the deck mode read-only, then takes the generation snapshot
  (`begin_generation`) **before** the user message;
- persists the user message with `add_user_message(..., requested_deck_mode=...)`,
  which locks the deck mode;
- resolves the engine with `resolve_engine_mode_or_unavailable` and handles the
  engine race;
- enqueues with `engine_mode` (and `stage_slide`);
- on any failure, rolls back the Enter (`_roll_back_failed_enter`), discards the
  snapshot or keeps the lock as the case requires, and maps `GenerationRefusedError`
  (restore pending, arc review running, deck locked by someone else) to answers.

The worker (`job_queue.process_chat_request`) already runs graph payloads; it only
needs `engine_mode: "graph"` in the payload.

**Approaches considered:**

- **A. (my call, recommended)** Extract the route's Enter sequence into one shared
  service function that both `send_chat_async` and the MCP call. The HTTP-specific
  parts (HTTPException mapping, `_check_chat_permission`) stay in the route. The MCP
  maps the same outcomes to `MCPToolError`s. There is one copy of the snapshot and
  rollback logic.
- **B.** Copy the Enter steps into `enqueue_create_job`. Rejected: this is the
  anti-goal.
- **C.** Have the MCP build a `ChatRequest` and call the route function directly.
  Rejected: it drags FastAPI dependencies (`get_db`, `HTTPException`) into the MCP
  path. That is why `enqueue_create_job` was written separately in the first place.

Session creation should also share the app's new-deck seeding rather than keep the
MCP's hand-rolled `agent_config`. The MCP's explicit parameters fill the fields the
caller set; app defaults fill the gaps; the same truth table applies
(`TestNewSessionSeedingTruthTable`). **(my call)** How far that shared code reaches
(one function, or the existing helpers called in order) is the builder's choice.

## Permissions and refusals

**`edit_deck` is owner-only.** **(decided)** The caller must be the creator of the
root session they pass (the same test as the first branch of the app's
`_check_chat_permission`). A collaborator with CAN_EDIT is refused with "open it in
Tellr" and the link. In the app, a collaborator chats in their own contributor session
under the editing lock and never in the owner's private conversation. The MCP doesn't
build that path. Nothing is lost: no collaborator can edit a shared Agent deck over
MCP today. `get_deck` and `get_deck_status` keep today's view permission
(`can_view_deck`).

The owner gate during a generation applies too. The app's async route refuses the
owner while someone else's live generation holds the deck
(`_check_chat_permission(..., gate_owner_on_generation=True)`), and the MCP refuses the
same case. Refusals the user can act on get plain messages:

| Situation | MCP error |
|---|---|
| Legacy deck on `edit_deck` | can't be edited over MCP; open it in Tellr: `<deck_url>` |
| Caller isn't the deck's owner | only the deck's owner can edit it over MCP; open it in Tellr: `<deck_url>` |
| Another turn running on the deck | the deck is busy; try again when it finishes |
| Deck locked by another editor | locked by `<name>` |
| A failed restore is pending, or an arc review holds the deck | the app's existing `_GENERATION_REFUSED_DETAILS` copy |
| No active graph release | Tellr can't generate right now (admin action needed) |

### Callers with no user token

`mcp_auth.extract_mcp_identity` accepts three identity sources. Priorities 1 and 2
(`x-forwarded-access-token`, `Authorization: Bearer`) carry a user token. External
clients such as Claude Code and the fe-tellr plugin use these. Priority 3
(`x-forwarded-identity`, gated on `TELLR_TRUST_FORWARDED_IDENTITY`, which the app
template sets) is the **app-to-app** path. When one Databricks App calls Tellr, the
Apps proxy strips the caller's token, so Tellr gets only a proxy-attested identity
(`docs/technical/mcp-server.md` §4.2 A). `mcp_auth_scope` deliberately leaves
`user_client` unset on that path.

On the graph, Genie One, Genie Agents and Gateway MCP tools all resolve their client
through `get_user_client()`. With no client they log a warning and run without tools
(`nodes.py`, `_genie_one_run` and the Genie Agent and Gateway MCP paths). Seeding
Genie One on a token-less MCP deck would therefore advertise a data source the turn
can't use: the architect might choose `ask_data` and get nothing back.

**(my call)** On the token-less path, `create_deck` seeds no tool that needs the
user's token. The architect then sees no data sources and builds from the prompt. Its
instructions already say to "say in `message` which data would help", so the reply
carries that. This matches what those callers get today (prompt-only). The person can
add Genie One when they open the deck in Tellr, where they have a token. Nothing else
in a build may need the user's token. Model calls already run on the app service
principal, and any other call that turns out to need the token is a defect to fix,
not a reason to refuse the turn.

### Other guards

The prompt-injection guard (`scan_for_injection`) and `MCP_PROMPT_LIMIT` stay on both
tools. Giving MCP decks tools grants nothing new. The MCP caller is the user, acting as
themselves through the existing MCP auth, with the same tools they would get in the
app. The architect's read-only tool rule applies as it does in the app.

## Hazards in the current code the builder must close

- **`cancelled` → "Unknown job status"** in `_get_deck_status_impl`. Unreachable today,
  because MCP turns never run on the graph, but reachable after this change.
- **The worker's comments and docs assume MCP means monolith.** `job_queue.py`
  ("every MCP job runs on the monolith"), `mcp_server.py` (the "MCP stays on the legacy
  monolith" block) and `docs/technical/generation-atomicity.md` (the "MCP jobs | No"
  row, and the "monolith (Legacy decks, MCP)" section) all say so. They must be updated
  so the next reader isn't misled.
- **The MCP caller's token** now drives Genie One and Gateway tool calls on the graph.
  Today an MCP turn makes no tool calls, so this path is unexercised. It must be
  verified on a devloop, not assumed. The Apps proxy has refused scope-limited CLI
  tokens before.

## Constraints

- Agent mode only; no Legacy changes. **(decided)**
- The tool names and the remaining parameters keep working. Only the decided breaking
  changes change what a caller can send: the Legacy refusal, owner-only `edit_deck`,
  and the removed `num_slides`, `deck_prompt_id` and `slide_indices`.
- MCP turns share the app's chat runner pool (`get_chat_executor`, sized by
  `chat_job_concurrency()`, default 1 per process), as they already do on the
  monolith. Agent turns take minutes, so an MCP build can now hold a runner longer and
  delay an app user's turn on the same worker. **(my call)** We accept that and add no
  separate lane. Raising concurrency waits on the 429-handling work (PR #357). Callers
  should expect `pending` for as long as the queue ahead of them.
- Per-worktree uv venv; deploy only to a `devloop` instance (repo `CLAUDE.md`).
- The release notes (release-tellr skill) must call out the breaking change for MCP
  callers. Known callers per the 2026-08-06 spec: the fe-tellr plugin, the TAP
  builder, the DAIS agenda curator and the KPMG pricing skills.

## Left to the builder

- The exact shape of the shared Enter function and how the route and the MCP map its
  outcomes.
- How `deck_changed` is computed (e.g. from the turn's intent, or from the deck or
  spec before and after), provided a `discuss` or `confirm_design_contract` turn reports
  `false` and any slide or deck-level write reports `true`.
- How `reply` is selected from the turn's persisted messages.
- Tool-description wording, within the goals above.
- Test layout (`tests/unit/test_mcp_server.py` and friends).

## How we'll know it works

- `create_deck` with a topic prompt produces an Agent deck (`deck_mode="agent"`,
  pinned release) with a built deck. `get_deck_status` reaches `ready` with slides, a
  `reply` and `deck_changed: true`. Opening `deck_url` shows a normal Agent deck with
  the default design system and template, the chat transcript and the default tools.
- `create_deck`'s tool schema no longer lists `num_slides` or `deck_prompt_id`.
- `create_deck` with a no-topic prompt reaches `ready` with the architect's question in
  `reply`, `deck_changed: false`, `clarification_needed: true`, and no slides.
- `edit_deck` on that Agent deck with a change ("make slide 2's title shorter")
  changes slide 2 only. With a question ("does the arc hold up?") it returns a reply
  with `deck_changed: false`.
- `edit_deck` with "on slides 1 and 4, …" edits those two slides only. Its tool schema
  no longer lists `slide_indices`.
- `edit_deck` on a Legacy deck, including a pre-existing MCP deck, is refused with the
  Tellr link, and nothing is written (no chat request, no message).
- `edit_deck` on an Agent deck made in the app works for its owner.
- `edit_deck` by a collaborator with CAN_EDIT on someone else's deck is refused with
  the Tellr link, and nothing is written.
- A turn stopped from the Tellr app reports `failed` with the stopped-and-unchanged
  error. A failed turn leaves the deck as it was.
- On a devloop with the admin's Genie One default on, an MCP deck shows Genie One in
  its tools. A prompt that needs data makes a Genie One call that succeeds with the
  MCP caller's token.
- A token-less (`x-forwarded-identity`) `create_deck` builds a deck with no data
  tools seeded. Its `reply` says which data would help.
- The async chat route's existing tests still pass unchanged after the Enter
  extraction.
