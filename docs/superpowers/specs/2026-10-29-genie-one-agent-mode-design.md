# Genie One in agent mode — design

**Date:** 2026-10-29
**Status:** agreed in conversation with the repo owner. Calls I made without the owner are listed under "Calls made without the owner".
**Stacks on:** prompt shipping (`2026-10-29-prompt-shipping-design.md`). This PR changes agent prompts, and prompt shipping is how those changes reach existing installs.
**Background:** `~/tellr-loop/genie-one/HANDOVER.md` holds the probed facts about scopes, consent and the Genie One protocol. Probe scripts are in `~/tellr-loop/genie-one/probes/`.

## Why

Genie One (`system.ai.genie_one_mcp`, served through the AI Gateway) is Databricks' built-in data agent. Getting Tellr decks built on it is the top company-aligned priority.

Agent mode, the default engine for new decks, cannot fetch data at all today:
- The data analyst's skill lists `genie` and `vector_index` grants (`src/core/skills/data_analyst.py`).
- But the runtime binds only the output schema as a tool (`bind_structured_output_model`, `src/services/agent_runtime.py:214`). The analyst answers from nothing.
- Its output has no figures field, so `DeckSpec.resolved_data.figures` is always empty, and the builder never draws a chart from real data.

Genie One is the first tool agent mode will ever call. It should be built so other tools can join later.

## Goals

- **The flow:**
  1. A user adds Genie One to a deck with a "+ Genie One" button and asks for a deck.
  2. When the architect needs data, the data analyst asks Genie One.
  3. The analyst reads each answer, decides whether it has enough, asks again if not, and reports back.
  4. The architect builds the slides from those figures.
- **Provenance:** every slide that shows Genie One data carries a visible "Source: Genie One" note.
- **Prod gets the scopes through code:** Genie One needs `ai-gateway`, and the MCP picker needs `catalog.connections`.
- **Re-consent:** users whose consent predates the new scopes are told how to fix it, not shown an empty list or a stack trace.
- **Extensible:** the analyst's tool loop and tool registry are general, so another tool type can join later without reworking the loop. Only Genie One is wired in now.

## Non-goals

- Any other tool in agent mode: Genie Agent, Vector Index, MCP Server, Agent Bricks, Model Endpoint. They stay legacy-only and unchanged.
- Genie One in legacy mode. Legacy mode gets the scope fix and nothing else.
- Listing Unity Gateway MCP services. A user token from Apps cannot, because `unity-catalog` is not a valid Apps scope.
- Removing or changing any existing tool type.
- Asking the user to confirm the data before building, for example "here is what I found, shall I use it?". This is a possible later refinement; for now the deck is built straight away.
- Docs pages in `docs/technical/`.

## Anti-goals (failures even if it "works")

- A number on a slide that differs from Genie One's answer because a model copied it wrong between hops.
- A deck turn killed by the job timeout halfway through because Genie One was slow.
- A missing-scope failure that looks like "no data" or an empty list.
- Following instructions embedded in Genie One's output. Its text includes agent-directed HTML comments ("Your reply MUST include…").
- Breaking any existing legacy tool or any existing agent-mode turn when Genie One is not on the deck.

## Decisions made with the owner

1. **Agent mode only.** Legacy decks ignore a Genie One entry. Legacy mode gets the scope fix and nothing else.
2. **A "+ Genie One" button,** placed first in the Tools row (`frontend/src/components/AgentConfigBar/ToolPicker.tsx:22`). One click adds it, with no picker, and a config holds at most one Genie One entry. Every other tool button is unchanged.
3. **The flow:** architect → analyst → Genie One (one or more questions, as the analyst judges) → analyst reports → architect builds. This is the existing graph shape (`architect --ask_data--> data_analyst --> architect`).
4. **A general seam, one tool.** Only Genie One is wired in, but the design must extend to other tools.
5. **Provenance:** slides using Genie One data show "Source: Genie One".
6. **The server runs Genie One's ask/poll loop.** To the analyst, each question is one tool call. The call returns the final answer, the result rows and the "Explore in Databricks" link. Tellr keeps the Genie One conversation across turns of the same deck.
7. **Scopes:**
   - Code adds `ai-gateway` and `catalog.connections`.
   - `_create_app` (`packages/databricks-tellr/databricks_tellr/deploy.py:1677`) includes them.
   - `tellr.update()` adds any missing scopes and never removes one, using the full-replace pattern in `attach_secret_resource` (`secret_key.py:314`). This means carrying `description`, `default_source_code_path`, `user_api_scopes` and `resources`, and omitting `compute_size`.
   - The app cannot do this itself. Its service principal has no `CAN_MANAGE` on its own app: the staging app's permission list shows only `admins` and the owner.
   - `mcp.external` joins only if the live check shows UC-connection MCP calls need it.
8. **An in-app consent message with reset steps.**
   - When a call fails because a token lacks a scope, the user sees one clear message. It covers both causes: the app lacks the scope (an admin runs `tellr.update()`), or the user's consent predates it. The user fixes the second by revoking consent at `DELETE {host}/api/2.0/oauth-app-integrations/{oauth2_app_client_id}/user-consent/me`, clearing site data and reloading.
   - If the live check shows the app can revoke consent for the user, the message gets a "Reset" button. If it shows the app can read its own scopes, the message names the one cause that applies.
   - The MCP picker shows this message instead of "No MCP connections available". Today both `_discover_mcp_connections` (`src/api/routes/tools.py:236`) and the frontend (`frontend/src/services/api.ts:2307`) turn the 403 into an empty list.
9. **Time budget:**
   - The analyst gets about 5 minutes and at most 3 Genie One questions per data request. Code enforces both, not only the prompt.
   - Genie One's tool description pushes for a few broad questions.
   - At the cap, the analyst reports what it has and names the gaps.
   - Agent-mode turns get a 20-minute limit instead of 10.
10. **Two stacked PRs:** prompt shipping first, then this one.
11. **Live verification overnight:** a devloop app driven through the owner's logged-in Chrome over DevTools. Clicking through the devloop app's consent prompt is part of that.

## How it works

### Adding Genie One to a deck

- A new `genie_one` member of the `ToolEntry` union (`src/api/schemas/agent_config.py:68`), with an optional `conversation_id`.
- `no_duplicate_tools` (`:103`) allows one entry. Remove-by-key (`src/api/routes/agent_config.py:280`) handles it. The conversation-id strip (`:325`) treats it like `GenieTool`.
- Frontend: the type in `frontend/src/types/agentConfig.ts`, the button first in `ToolPicker`, and a chip in `AgentConfigBar.tsx`, `ToolDetailPanel.tsx` and `toolUtils.ts`.
- Legacy `_build_tools` (`src/services/agent_resolution.py:382`) skips the entry without error.

### The analyst's tool loop

Today `AgentRuntime.run` makes one structured-output call per agent. For an agent whose skill grants a tool that the deck has configured, it instead runs a loop:

- **Binding:** the model gets the granted tools plus the output schema as its final-answer tool.
- **Each round:** run the tool calls, feed back the results, and repeat until the model calls the output schema.
- **Code-enforced budget:** wall clock and question count. When the budget runs out, the model gets a one-time budget notice telling it to report what it has; any later tool call is refused in-band with the same text. The tools stay bound (one binding).
- **Everything else stays one call:** agents with no granted, configured tool, which today means everything except an analyst on a Genie One deck, keep exactly today's single call.

Requirements on the loop:

- It is the one tool-capable path, so the next tool type adds a registry entry, not a new loop.
- **Registry:** agent-config tool type → agent-mode tool. Only `genie_one` is registered. The analyst's `TOOL_GRANTS` gains `genie_one`.
- **Identity:** tool calls run as the user (`get_user_client()`), since the analyst is the user-scoped boundary (`src/core/skills/__init__.py`, Ruling C-11). Model calls keep their current identity.
- **Isolation:** `run_candidate` (the admin workbench and the offline eval harness) gets no live tools: it refuses any toolset, so the eval harness cannot inject a fake tool either. Prompt work is measured on payloads that already carry figures, as the builder's source line was.
- Identity logging, persisted-configuration errors and parse-error handling stay as they are.

### The Genie One tool

- **Endpoint and client:** `{host}/ai-gateway/mcp-services/system.ai.genie_one_mcp`, through `DatabricksMCPClient` (databricks-mcp 0.9.0 is already in the app wheel, `mcp==1.27.0` is pinned). The client is built from the user's host and token, as `src/services/tools/mcp_tool.py` does, including its clean-thread handling of `asyncio.run`.
- **One call = one question:**
  - The server calls `genie_ask(question, conversation_id)`, then `genie_poll_response` every ~3 s until `status` is `completed`, `incomplete` or `failed`, or until the analyst's remaining budget runs out. If the budget runs out first, it calls `genie_cancel_response`.
  - On completion it fetches each `query_items[].item_id` with `genie_get_query_result`.
- **What it returns to the analyst:**
  - `final_answer`, the result rows (`columns`, `rows`, `truncated`), and the `deep_link`.
  - The rows are capped so a large result can't flood the context.
  - The whole result is marked as untrusted data with `spotlight()`, as `genie_tool.py` does. `narration_instruction` and Genie One's agent-directed HTML comments are dropped.
- **Conversation:** the conversation id is kept per deck *and per user*, following how `_persist_genie_conversation_ids` (`src/api/services/chat_service.py:495`) persists Genie space conversation ids. The next turn by the same user on the same deck continues that user's Genie One conversation. A contributor to a shared deck never reuses another user's conversation id: Genie conversations are likely owned by whoever started them, and sharing one could fail or leak.
- **Progress:** each question shows in the chat as a progress line ("Asking Genie One: …") while the turn is gathering data.

### Data back to the architect, and onto slides

- **Analyst output:** `AnalystOutput` gains `figures`: a list of key, value and source, reusing `ResolvedFigure`'s shape from `src/domain/deck_spec.py`. This is a new data-analyst schema contract (v3). `agent_schema_registry.py` already carries v1 and v2 digests, and #351 is the precedent for adding one. The analyst sets each Genie One figure's `source` to "Genie One".
- **Figures reach `resolved_data` verbatim.** They travel on a newly declared graph state key, and code writes them into the deck spec's `resolved_data.figures`, so the architect never retypes a number. Today the analyst's answer reaches the architect only as prose on `architect_message`, per Ruling C-7. A declared key for figures is the scope addition that ruling asked for.
- **The links:** the analyst's chat message keeps "Sources: …" and adds the "Explore in Databricks" link (`deep_link`).
- **The source note:**
  - The architect lists the figure keys each slide uses in `data_references`, as its prompt already asks.
  - The builder prompt adds a small, visible "Source: <source>" line on any slide that shows figures with a source.
  - The build reviewer's existing `source_contradiction` check now has figures to check against.

### Time

- **Job limit:** `JOB_HARD_TIMEOUT_SECONDS` (`src/api/services/job_queue.py:29`) becomes 20 minutes for graph-mode jobs. Monolith and MCP jobs keep 10 minutes.
- **Client-side limits:** the builder must check the frontend's polling and any other client-side limit against 20 minutes.
- **Analyst budget:** about 300 s and 3 questions per data request, enforced in the loop.
- **The tool description:** says a question takes 1–4 minutes, and asks for a few broad questions, not many narrow ones.

### Errors

| Failure | What the user sees |
|---|---|
| A token lacks a scope (`does not have required scopes` / 403 naming a scope) | A typed missing-scope error, which the chat and the MCP picker show as the consent message |
| The user lacks `EXECUTE` on `system.ai.genie_one_mcp` | A message naming the grant they need |
| Genie One returns `failed`/`incomplete`, or times out | The analyst reports a gap. The turn continues, and the deck is built without that data. |
| Genie One not on the deck | Exactly today's behaviour |

### Prompts and rollout

- **Prompts that change:** the data analyst (tool use, figures, budget), the architect (`data_references` from figures), and the builder (the source line).
- **How they're made:** measured on the offline eval harness (`evals/`) with a fake Genie One tool that replays recorded real answers, then promoted into the packaged manifest with `evals/harness/promote.py`, following the `optimise-agent-prompt` skill.
- **Recording the answers:** call Genie One directly with the scope-limited `scope-test` CLI profile (`ai-gateway` only), which is already proven to work against the gateway, using the probe scripts in `~/tellr-loop/genie-one/probes/`. Use a handful of questions on `samples.nyctaxi.trips`, including one multi-question data request and one that comes back `incomplete` or empty. This needs no app and no browser, so prompt work need not wait on the live check.
- **How they reach installs:** prompt shipping takes them to untouched installs. Admins with edited prompts see its badge. Conversations pinned to an older release keep it.

## Build order

Both PRs are built in the same overnight run. Prompt shipping comes first, on `feat/prompt-shipping`. This PR is `feat/genie-one-agent`, rebased onto prompt shipping's final head. Neither PR is merged by the build. The owner merges.

## Rollout (after merge, by the owner; not part of the build)

- Run the new `tellr.update()` on each install (prod, staging, the logfood app) so the app gains the scopes. Existing users then follow the consent message once.
- Users need `EXECUTE` on `system.ai.genie_one_mcp`. The docs say `system.ai` may carry a default grant. The live check confirms this for the owner's account only. Before announcing the feature, confirm with a non-admin user or grant it explicitly.
- Any org approval for adding `ai-gateway` and `catalog.connections` to the app's scopes is outside this build.

## Real response shapes, and what counts as proven (owner's ruling)

- **Shapes come from local auth.** Capture every Genie One response shape the code handles with the owner's local credentials: the `tellr-dev` PAT for full answers, and the `scope-test` / `scope-test-2` profiles for scope-limited behaviour, including the exact missing-scope and permission-denied errors. Bake those shapes into the code's parsing and the test fixtures. The code is built against real responses, not the docs.
- **The live check is not a gate.** If the app's forwarded token reaches Genie One and gets back an access-denied or missing-scope error, the plumbing is proven: the right API, the right URL, the user's identity. Building continues, and the error must surface through the consent or grant message. A full answer through the app is the best result, but it isn't required to finish the PR.
- **Never fall back to the app's service principal for Genie One.** That would answer every user's questions with the app's data access instead of their own.

## Live verification (overnight, on devloop)

1. Publish a `.devN` wheel from this branch and deploy it to a new devloop instance (`deploy-tellr-dev` skill, `--env devloop`). Its create-time scopes include `ai-gateway` and `catalog.connections`.
2. In the owner's Chrome, over DevTools: open the app and click through consent. Then create an agent-mode deck, add Genie One, and ask for a deck on `samples.nyctaxi.trips`. That's sample data a Genie One question already completed against, in ~23 s.
3. **Check:**
   - the progress lines appear;
   - the slides show real figures and "Source: Genie One";
   - the chat shows the "Explore in Databricks" link;
   - the turn finishes within the limits.
4. **Answer and record in the PR:**
   - Can the token Apps forwards call Genie One? This is the critical unknown.
   - Do UC-connection MCP calls (`/api/2.0/mcp/external/{conn}`) need `mcp.external`?
   - Can the app revoke a user's consent itself?
   - Can the app read its own scopes?
   - Does a plain redeploy leave scopes unchanged?
5. Check that prompt shipping behaves on the fork: the shipped release goes live, or the badge shows if prod's live graph was edited.

**Pitfalls:**
- Never test app endpoints with a CLI bearer token. The app forwards that token with all its scopes, so the result proves nothing. Use the browser, or the scope-limited `scope-test` / `scope-test-2` profiles against the workspace APIs directly.
- `databricks apps logs` keeps only about 600 lines. Pull them right after each check.

## Constraints

- Work in a worktree, using the per-worktree `uv` venv.
- The Apps build resolves dependencies from `packages/databricks-tellr-app/pyproject.toml`. No new dependency is expected.
- Deploy dev builds only to `devloop`, never `devtest`.
- Output schemas are frozen by digest and published releases pin them. A new schema contract is a new version, never an edit to an existing one.
- Graph state keys need declaring, because the runtime silently drops undeclared keys.
- DeckSpec fields are mirrored in two TypeScript places. This design adds no DeckSpec or SlideSpec field. `ResolvedFigure` already exists.
- The legacy agent's 600 s limit (`src/core/defaults.py:35`) is unchanged.

## Calls made without the owner

1. **The slide note is plain text.** The "Explore in Databricks" link appears in the analyst's chat message, not on the slide.
2. **Scopes and consent ship in this PR,** because Genie One cannot work without `ai-gateway`.
3. **Provenance uses the existing fields:** `ResolvedFigure.source` and `data_references`, plus a builder prompt line. No new SlideSpec field.
4. **Figures travel to `resolved_data` through a declared state key and code,** so no model retypes a number between the analyst and the slide.
5. **Code enforces the budget** (clock and question count), with a one-time budget notice telling the analyst to report what it has.
6. **The longer limit applies to graph-mode jobs only.**
7. **Genie One's output is marked as untrusted data,** and its instructions to agents are dropped.
8. **Workbench and eval runs never call live Genie One.** Evals use recorded answers.
9. **In a legacy deck, the Genie One chip says it works in agent mode only.**
10. **Genie One conversations are per user,** never shared across the contributors of a deck.
11. **The basic consent message is enough to ship:** both fixes listed, no Reset button. Reset and the single named cause are improvements the live check may unlock, not requirements.
12. **Eval recordings come from direct calls with the `scope-test` CLI profile,** not through the app.

## Left to the builder

- How the tool loop fits inside `AgentRuntime` (a new method or a branch inside `_run_resolved`), and the tool registry's shape.
- The new state key's name, and where code merges figures into `resolved_data` (`data_analyst_node`, or the architect node when it commits the spec).
- The row cap, the poll interval within 2–5 s, and the exact budget numbers within the decisions above.
- The consent message's wording and layout, and the chip's look.
- How recorded Genie One answers are captured for the eval fake.
- Test layout. Every test is sabotage-verified, per `executing-plans-tellr`.

## Rulings made during planning (2026-10-29, night build)

These override earlier sections of this document where they conflict. Each is recorded with its reason and what it costs if wrong. The owner reviews them in the morning.

1. **`AnalystOutput` is not changed; there is no schema v3.** Code builds figures from Genie One's result rows (`figures_from_answer`) and carries them on a turn-scoped state key, and the architect node writes them into `resolved_data.figures`.
   - *Why:* adding a field re-pins the data analyst's v1 and v2 digests in place, the #351 precedent across 15 files, or else needs a new contract tier. Building figures in code also means no model retypes a number at all, which is stronger than the anti-goal asked for.
   - *Cost if wrong:* figure keys are mechanical (`trip_count (pickup_zip=10001)`) rather than curated by the analyst.
2. **The data analyst prompt doesn't change.** The bound tool is named `genie`, which the existing prompt already lists ("genie — SQL and Databricks SQL warehouse queries"). Its guidance travels in the tool's description.
   - *Why:* the data analyst prompt is promote-locked (`LegacyV1PromptTransition`, `prompt_assembler.py:231`).
   - *Cost if wrong:* the analyst's procedure text still mentions `vector_index`, which isn't bound.
3. **The builder is the only prompt change.** It gets a `SOURCE LINE` block, measured on the eval harness and promoted. The architect already lists metric keys in `data_references`, and the analyst's message names the figure keys.
4. **Tools come from the actor's own agent config,** which is how legacy mode already works. Contributors' rows start with no config, so a contributor's turn runs without Genie One until they add it. The Genie One conversation id is stored on the actor row's `genie_one` entry, which makes it per user per deck automatically.
5. **The consent message has no Reset button.** It gives both causes and a CLI command that revokes consent, using the app's OAuth client id when the user's token reveals it. Whether the app can revoke consent itself is still recorded by the live check.
6. **At most 2 analyst rounds per turn.** A third `ask_data` in the same turn gets a code-owned "plan with what you have" message. *Why:* LangGraph's recursion limit (10007) is the only bound today, and each round can take minutes.
7. **Genie figures stay code-owned across turns.** On a turn without new analyst figures, the prior spec's `Genie One` figures are re-applied verbatim, so an architect full-spec edit can't retype them.
8. **Missing-scope detection matches both real texts:** `…does not have required scopes…`, seen in staging logs, and `…Invalid scope, required scopes…`, recorded from the SDK as a `PermissionDenied` parse error. The fixtures are in `tests/fixtures/genie_one/`.

## Calls made during the build (2026-10-30, final review)

These override earlier sections where they conflict. The owner reviews them.

1. **A gateway 401, and a 403 for a token known to lack `ai-gateway`, are a missing scope (the consent message), not a missing grant.** This reverses Task 4's "a gateway 403 is `access_denied`" for the case where the token's scopes are known. The node also runs a pre-flight: it reads the user token's `scope` (else `scp`) claim, unverified, and when that claim is present and holds neither `ai-gateway` nor `all-apis`, it says the consent message once and runs the analyst without tools. A token whose scopes can't be read (not a JWT, or no claim) is never refused up front, and a 403 for it stays `access_denied` unless the error body names a scope.
   - *Why:* the whole-branch review drove the real `databricks_mcp` / `httpx` stack against a local server. A 403 whose body said "Invalid scope, required scopes: ai-gateway" came back as `access_denied` (`raise_for_status` drops the body), and a 401 came back as a generic error. A missing `ai-gateway` is the most likely day-one failure, since existing users keep their old consent until they re-approve.
   - *Evidence:* real tokens carry a space-separated `scope` claim (`ai-gateway offline_access` for `scope-test`; `all-apis offline_access` for a full CLI token, which is why `all-apis` counts). A bogus token sent to the real gateway gets HTTP 401.
   - *Cost if wrong:* a real `EXECUTE` refusal for a token that lacks `ai-gateway` is labelled a consent problem (both need fixing then anyway). An expired or invalid token's 401 also shows the consent message.
2. **Genie One is called with a fixed bearer, not `databricks_mcp`'s OAuth provider.** The client is still `DatabricksMCPClient`, whose `call_tool` (`asyncio.run`, error handling) is kept. Only its session's auth is swapped: the user's token from the `WorkspaceClient`, plus reading a 4xx/5xx body before `raise_for_status` sees it.
   - *Why:* the provider answers a 401 by starting an OAuth discovery flow from an empty server URL. That flow fails with an unrelated `httpx.UnsupportedProtocol`, so a 401 could never be classified.
   - *Evidence:* the fixed-bearer path was checked live, side-effect free, with the `scope-test` token: a poll for a bogus conversation got HTTP 200 and an in-band "Conversation not found".
   - *Cost if wrong:* the override replaces the base class's private `_call_tools_async` (a dozen lines, on the non-deprecated `streamable_http_client`). A `databricks-mcp` upgrade that renames it would silently bring the provider back. The local-server 401 test would then fail.
