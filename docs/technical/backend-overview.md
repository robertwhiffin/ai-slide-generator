# Backend System Overview

This guide explains how the FastAPI/LangChain backend works, how it serves the frontend, and the concepts you need to extend or automate it. Treat it as a living reference for both engineers and AI agents.

---

## Stack & Entry Point

- **Runtime:** Python 3.11+, FastAPI (ASGI) with Uvicorn/Gunicorn, packaged under `src/`.
- **Core libs:** LangChain (tool-calling agent), Databricks `WorkspaceClient`, MLflow for tracing, BeautifulSoup for HTML parsing.
- **Entry:** `src/api/main.py` instantiates FastAPI, wires CORS, and registers `chat` + `slides` routers under `/api`.
- **Process lifecycle:** `lifespan` context starts the job queue worker for async chat processing and recovers stuck requests on startup.

---

## High-Level Architecture

```
                                      ┌────────────────────────┐
Frontend fetch -> FastAPI router ->   │ ChatService (singleton)│
                                      │  - SlideGeneratorAgent │
                                      │  - SlideDeck cache     │
                                      └──────────┬─────────────┘
                                                 │
                                    LangChain AgentExecutor
                                                 │
                          ┌───────────────────────┴──────────────────────┐
                          │ Databricks LLM endpoint + Genie tool APIs    │
                          └──────────────────────────────────────────────┘
```

- **Routers** (`src/api/routes/*.py`) validate HTTP payloads and map 1:1 to frontend calls. All endpoints use `asyncio.to_thread()` for blocking operations.
- **`ChatService`** (`src/api/services/chat_service.py`) is a process-wide singleton that owns the `SlideGeneratorAgent` and a session-scoped deck cache. Thread-safe via `_cache_lock`.
- **`SessionManager`** (`src/api/services/session_manager.py`) handles database-backed sessions with locking for concurrent request handling. Stores slide deck in `deck_json` and verification results separately in `verification_map` (keyed by content hash) for persistence across deck regeneration.
- **`SlideGeneratorAgent`** (`src/services/agent.py`) wraps LangChain's tool-calling agent. Tools are created per-request with session ID bound via closure to eliminate race conditions.
- **`SlideDeck` / `Slide` models** (`src/models/...`) parse, manipulate, and serialize slides so both chat and CRUD endpoints share the same representation.

---

## API Surface (Contracts Shared with Frontend)

### Session Endpoints

| Method | Path | Purpose | Backend handler |
| --- | --- | --- | --- |
| `POST` | `/api/sessions` | Create new session | `routes/sessions.create_session` |
| `GET` | `/api/sessions` | List current user's sessions (ownership + profile filtering) | `routes/sessions.list_sessions` |
| `GET` | `/api/sessions/invocations` | List MLflow runs for current user (alternative history source) | `routes/sessions.list_invocations` |
| `GET` | `/api/sessions/{id}` | Get session details | `routes/sessions.get_session` |
| `PATCH` | `/api/sessions/{id}` | Rename session | `routes/sessions.update_session` |
| `DELETE` | `/api/sessions/{id}` | Delete session | `routes/sessions.delete_session` |
| `GET` | `/api/sessions/{id}/slides` | Get slide deck for session | `routes/sessions.get_session_slides` |

### Chat & Slide Endpoints

| Method | Path | Purpose | Backend handler |
| --- | --- | --- | --- |
| `POST` | `/api/chat` | Generate/edit slides (synchronous) | `routes/chat.send_message` |
| `POST` | `/api/chat/stream` | Generate/edit with SSE streaming | `routes/chat.send_message_streaming` |
| `POST` | `/api/chat/async` | Submit for async processing (polling) | `routes/chat.submit_chat_async` |
| `GET` | `/api/chat/poll/{request_id}` | Poll for async request status | `routes/chat.poll_chat` |
| `GET` | `/api/health` | Lightweight readiness probe | `routes/chat.health_check` |
| `GET` | `/api/user/current` | Get current Databricks user (username, display_name) | `main.get_current_user` |
| `GET` | `/api/slides` | Get slides (requires `session_id` query param) | `routes/slides.get_slides` |
| `PUT` | `/api/slides/reorder` | Reorder (requires `session_id` in body) | `routes/slides.reorder_slides` |
| `PATCH` | `/api/slides/{index}` | Update HTML (requires `session_id` in body) | `routes/slides.update_slide` |
| `POST` | `/api/slides/{index}/duplicate` | Clone (requires `session_id` in body) | `routes/slides.duplicate_slide` |
| `DELETE` | `/api/slides/{index}` | Delete (requires `session_id` query param) | `routes/slides.delete_slide` |
| `PATCH` | `/api/slides/{index}/verification` | Update verification result (persists with session) | `routes/slides.update_slide_verification` |

### Verification Endpoints (LLM as Judge)

| Method | Path | Purpose | Backend handler |
| --- | --- | --- | --- |
| `POST` | `/api/verification/{slide_index}` | Verify slide accuracy against Genie source data | `routes/verification.verify_slide` |
| `POST` | `/api/verification/{slide_index}/feedback` | Submit human feedback on verification (logged to MLflow) | `routes/verification.submit_feedback` |
| `GET` | `/api/verification/genie-link` | Get Genie conversation URL for source data review | `routes/verification.get_genie_link` |

### Version / Save Points Endpoints

| Method | Path | Purpose | Backend handler |
| --- | --- | --- | --- |
| `GET` | `/api/slides/versions` | List all save points for session | `routes/slides.list_versions` |
| `GET` | `/api/slides/versions/{n}` | Preview specific version (no state change) | `routes/slides.preview_version` |
| `POST` | `/api/slides/versions/create` | Create new save point | `routes/slides.create_version` |
| `POST` | `/api/slides/versions/{n}/restore` | Restore version, delete newer versions | `routes/slides.restore_version` |

Save points capture complete deck state plus verification results. Maximum 40 per session; oldest deleted on overflow. See [Save Points / Versioning](save-points-versioning.md).

### Settings & Configuration Endpoints

| Method | Path | Purpose | Backend handler |
| --- | --- | --- | --- |
| `GET` | `/api/settings/profiles` | List all profiles | `routes/settings/profiles.list_profiles` |
| `POST` | `/api/settings/profiles` | Create profile (basic, requires subsequent config) | `routes/settings/profiles.create_profile` |
| `POST` | `/api/settings/profiles/with-config` | Create profile with all config in one request (wizard) | `routes/settings/profiles.create_profile_with_config` |
| `GET` | `/api/settings/profiles/{id}` | Get profile details | `routes/settings/profiles.get_profile` |
| `PUT` | `/api/settings/profiles/{id}` | Update profile | `routes/settings/profiles.update_profile` |
| `DELETE` | `/api/settings/profiles/{id}` | Delete profile | `routes/settings/profiles.delete_profile` |
| `POST` | `/api/settings/profiles/{id}/load` | Hot-reload profile | `routes/settings/profiles.load_profile` |
| `GET` | `/api/settings/deck-prompts` | List deck prompts | `routes/settings/deck_prompts.list_deck_prompts` |
| `POST` | `/api/settings/deck-prompts` | Create deck prompt | `routes/settings/deck_prompts.create_deck_prompt` |
| `GET` | `/api/settings/deck-prompts/{id}` | Get deck prompt | `routes/settings/deck_prompts.get_deck_prompt` |
| `PUT` | `/api/settings/deck-prompts/{id}` | Update deck prompt | `routes/settings/deck_prompts.update_deck_prompt` |
| `DELETE` | `/api/settings/deck-prompts/{id}` | Delete deck prompt | `routes/settings/deck_prompts.delete_deck_prompt` |
| `GET` | `/api/settings/slide-styles` | List slide styles | `routes/settings/slide_styles.list_slide_styles` |
| `POST` | `/api/settings/slide-styles` | Create slide style | `routes/settings/slide_styles.create_slide_style` |
| `GET` | `/api/settings/slide-styles/{id}` | Get slide style | `routes/settings/slide_styles.get_slide_style` |
| `PUT` | `/api/settings/slide-styles/{id}` | Update slide style | `routes/settings/slide_styles.update_slide_style` |
| `DELETE` | `/api/settings/slide-styles/{id}` | Delete slide style | `routes/settings/slide_styles.delete_slide_style` |
| `PUT` | `/api/settings/prompts/{profile_id}` | Update prompts config (deck prompt, slide style selection) | `routes/settings/prompts.update_prompts_config` |

**Deck Prompts** are global presentation templates stored in `slide_deck_prompt_library`. Profiles reference a selected prompt via `config_prompts.selected_deck_prompt_id`. When generating slides, the agent prepends the deck prompt content (WHAT to create).

**Slide Styles** are global visual style configurations stored in `slide_style_library`. Profiles reference a selected style via `config_prompts.selected_slide_style_id`. When generating slides, the agent includes the style content (HOW slides should look).

**Prompt Assembly Order** (in `src/services/agent.py`):
1. Deck Prompt (optional) - defines presentation type/content
2. Slide Style (from library) - defines visual appearance
3. System Prompt (technical) - defines HTML/chart generation rules
4. Slide Editing Instructions - defines editing behavior

The **Advanced** tab in profile settings (system prompt, editing instructions) is hidden from regular users and only visible in debug mode (`?debug=true`).

All responses conform to the Pydantic models in `src/api/models/responses.py`. Structure mirrors what the frontend expects (`messages`, `slide_deck`, `raw_html`, `metadata`, optional `replacement_info`).

Mutation endpoints return **409 Conflict** if the session is already processing another request. See [Multi-User Concurrency](multi-user-concurrency.md).

---

## Request Lifecycle

1. **FastAPI validation**  
   - Bodies deserialize into `ChatRequest`, `SlideContext`, or CRUD request models in `src/api/models/requests.py`.  
   - `SlideContext` enforces contiguous indices and maps 1:1 with the frontend's selection ribbon.
   - All mutation endpoints require `session_id`.

2. **Session locking**  
   - Mutation endpoints call `session_manager.acquire_session_lock(session_id)` before proceeding.
   - Returns 409 if another request is already processing the session.
   - Lock released in `finally` block via `release_session_lock()`.

3. **ChatService orchestration**  
   - Singleton created lazily via `get_chat_service()`.
   - Maintains a thread-safe deck cache keyed by `session_id`.
   - Operations wrapped in `asyncio.to_thread()` to avoid blocking the event loop.

4. **Agent execution**  
   - `SlideGeneratorAgent.generate_slides()` creates tools per-request with session ID bound via closure.
   - Stitches user prompt, optional `<slide-context>...</slide-context>` block, chat history, and passes to LangChain's `AgentExecutor`.  
   - **Prompt-only mode:** When no Genie space is configured, the agent runs with an empty tools list. LangChain handles this gracefully - the LLM generates slides purely from conversation without data queries.
   - **With Genie:** Genie tool calls automatically reuse the session's `conversation_id`, so the LLM never fabricates IDs.

5. **Post-processing**  
   - **New deck:** Raw HTML is parsed into a `SlideDeck` (`SlideDeck.from_html_string`). Canvas/script integrity is checked before caching.  
   - **Edits:** Replacement info from `_parse_slide_replacements()` merges into the cached deck via `_apply_slide_replacements()`, ensuring Chart.js script blocks stay aligned with canvas IDs.

6. **Response**  
   - `ChatService` returns the message transcript, latest deck snapshot (or `None`), raw HTML for debugging, and metadata (latency, tool calls, mode).

---

## Core Modules & Responsibilities

| Module | Responsibility | Key Details |
| --- | --- | --- |
| `src/api/main.py` | App assembly, auth middleware | Registers routers, CORS, health root. Auth middleware extracts user identity from `x-forwarded-access-token`/`x-forwarded-user` headers (production) or sets `DEV_USER_ID` / `dev@local.dev` (local development). |
| `src/api/routes/chat.py` | `/api/chat`, `/api/chat/stream`, `/api/chat/async`, `/api/chat/poll` | Session locking, SSE streaming, polling endpoints. |
| `src/api/services/job_queue.py` | Async chat processing | In-memory job queue with background worker for polling mode. |
| `src/api/routes/sessions.py` | Session CRUD + invocations | Create, list (user-scoped via `created_by`, optional `profile_id` filter), get (with messages), rename, delete. Invocations endpoint lists MLflow runs. |
| `src/api/routes/slides.py` | Slide CRUD endpoints | Session-scoped operations with locking. |
| `src/api/services/chat_service.py` | Stateful orchestration | Deck cache, streaming generator, history hydration. |
| `src/api/services/session_manager.py` | Session persistence | Database CRUD, message storage, session locking. `list_user_generations()` provides ownership filtering (`created_by = username`) with optional `profile_id` parameter for profile-scoped history. Auto-sets `created_by` and `visibility = 'private'` on new sessions. |
| `src/services/agent.py` | LangChain agent | Per-request tools, streaming callbacks, MLflow spans. |
| `src/services/streaming_callback.py` | SSE event emission | Emits events to queue AND persists to database. |
| `src/services/tools.py` | Genie wrappers | Starts conversations, retries, converts tabular responses. |
| `src/models/slide*.py` | Deck primitives | Parsing, reordering, cloning, script bookkeeping, serialization. |
| `src/core/settings_db.py` | Settings from database | Profile-based configuration with hot-reload. |
| `src/core/databricks_client.py` | Databricks connection | Thread-safe singleton `WorkspaceClient`. |
| `src/utils/html_utils.py` | Canvas/script analysis | Extracts `canvas` ids from HTML and JS for validation. |
| `src/utils/css_utils.py` | CSS parsing & merging | Selector-level merge for edit responses using `tinycss2`. |
| `src/utils/logging_config.py` | Structured logging | JSON/text formatters, RotatingFileHandler. |

---

## Data Models & Invariants

- **ChatRequest** ensures `message` length, `max_slides` bounds (1–50), and (when present) `slide_context` contiguous indices + matching HTML count. This keeps backend/LLM alignment with the frontend selection ribbon.
- **ChatResponse** always returns every message in the current turn so the UI can stream tool and assistant chatter without reconstructing history.
- **SlideDeck** caches the canonical state:
  - `slides` store raw HTML with `<div class="slide">`.
  - `css`, `external_scripts`, `scripts` preserve deck-level styling and Chart.js snippets.
  - Canvas/script integrity is enforced two ways:
    - `_validate_canvas_scripts_in_html()` runs before caching full decks.
    - `validate_canvas_scripts()` and `SlideDeck.add_script_block()` keep replacements consistent when editing.

Breaking these invariants (e.g., submitting non-contiguous indices, missing `.slide` wrappers, or removing chart scripts) leads to immediate `ValueError` → `400/500` HTTP responses, mirroring the UI expectations.

---

## Agent Details

- **Model:** `ChatDatabricks` configured via database profiles and exposed through `get_settings().llm`.
- **Prompting:** System prompt + slide-editing addendum loaded from database and injected via `ChatPromptTemplate`. Chat history pulled from `ChatMessageHistory`.
- **Tools:** Created per-request via `_create_tools_for_session(session_id)`. The Genie wrapper captures the session dict via closure, eliminating race conditions from shared state. Automatically reuses the session's `conversation_id`.
- **Sessions:** `SlideGeneratorAgent.sessions` holds `chat_history`, `genie_conversation_id`, `experiment_id`, `experiment_url`, `username`, and `metadata`. Each user operates on their own session with isolated state.
- **Concurrency:** Tools and `AgentExecutor` are created fresh for each request. No shared mutable state between concurrent requests.
- **Observability:** MLflow spans wrap each generation. Attributes include mode (`generate` vs `edit`), latency, tool call counts, Genie conversation ID, and replacement stats. Each run is also tagged with `session_id` via `mlflow.set_tag("session_id", session_id)` to link traces back to Postgres sessions.
- **Robustness:** Multiple safeguards prevent slide data loss during edits (see [Slide Editing Robustness](slide-editing-robustness-fixes.md)):
  - Response validation with automatic retry if LLM returns text instead of HTML
  - Add vs edit intent detection to preserve existing slides when adding new ones
  - Deck preservation guard to prevent deck destruction on parsing failures
  - Canvas ID deduplication to prevent chart conflicts
  - JavaScript syntax validation and auto-fix
  - **Clarification guards** (ask before proceeding on ambiguous requests):
    - "Edit slide 8" without selection → auto-creates slide context, applies to correct slide (RC13)
    - "Add after slide 3" → positions correctly based on reference
    - Ambiguous edit without slide number → asks "which slide?"
    - "Create 5 slides" with existing deck → asks "add or replace?"
    - Selection/text conflict → uses selection, shows note to user
  - **Unsupported operations** (RC14) - LLM guides users:
    - Delete/remove → "Use the trash icon in the slide panel on the right"
    - Reorder/move → "Drag and drop in the slide panel on the right"
    - Duplicate/copy → "Select the slide and ask 'create an exact copy'"

### Per-Session MLflow Experiments

Each session creates its own MLflow experiment for isolated tracing:

1. **Experiment Path** (production with service principal):
   ```
   /Workspace/Users/{DATABRICKS_CLIENT_ID}/{username}/{profile_name}/{timestamp}
   ```
   
2. **Experiment Path** (local development):
   ```
   /Workspace/Users/{username}/{profile_name}/{timestamp}
   ```

3. **Permission Granting:** When running as a Databricks App, the system client (service principal) creates the experiment in its folder and grants `CAN_MANAGE` permission to the user via `client.experiments.set_permissions()`.

4. **Frontend Link:** The `experiment_url` is returned in the `ChatResponse` and displayed as a "Run Details" link in the header, allowing users to view traces for their session.

Key helpers in `src/core/databricks_client.py`:
- `get_service_principal_client_id()` - Returns `DATABRICKS_CLIENT_ID` env var
- `get_service_principal_folder()` - Returns `/Workspace/Users/{client_id}` or `None` for local dev
- `get_current_username()` - Gets username from the user client

---

## Slide Editing Pipeline

1. Frontend sends `slide_context = { indices, slide_htmls }`.
2. Agent prepends a `<slide-context>…</slide-context>` block to the human message so the LLM edits in place.
3. `_parse_slide_replacements()` parses the LLM's HTML into discrete slide blocks and collects:
   - `replacement_slides`, `replacement_scripts`, `replacement_css`
   - `start_index`, `original_count`, `replacement_count`, `net_change`
   - Canvas IDs referenced inside HTML or `<script data-slide-scripts>` blocks
4. `_apply_slide_replacements()` removes the original segment, inserts the new slides, merges CSS rules, and rewrites script blocks so every canvas gets exactly one Chart.js initializer.
5. **CSS merging**: replacement CSS is merged selector-by-selector—matching selectors are overridden, new ones appended, and unrelated rules preserved.
6. **Canvas ID fallback chain**: if script parsing misses IDs, the system falls back to regex extraction, then to canvas elements in the slide HTML.
7. `replacement_info` is bubbled back to the frontend where `ReplacementFeedback` displays summaries like "Expanded 1 slide into 2 (+1)".

If the agent's HTML has empty slides, out-of-range indices, or references canvas IDs without scripts, the request fails fast with descriptive errors to keep state consistent.

---

## Configuration, Secrets & Clients

- **Settings loading** (`src/core/settings_db.py`):
  - Configuration stored in database (profiles with LLM, Genie, MLflow, prompts settings).
  - Environment variables for secrets (`DATABRICKS_HOST`, `DATABRICKS_TOKEN`, `DATABASE_URL`).
  - `get_settings()` caches the merged `AppSettings`. Use `reload_settings()` to refresh from database.
  - **Deck Prompts:** If a profile has `selected_deck_prompt_id` set, the prompt content is loaded and included in `settings.prompts["deck_prompt"]`.
- **Deck Prompt Injection** (`src/services/agent.py`):
  - When creating the system prompt, if `deck_prompt` is present, it's prepended to provide presentation structure guidance.
  - This allows standardized decks (QBR, consumption review, etc.) without users retyping instructions.
- **Databricks client** (`src/core/databricks_client.py`):
  - Thread-safe singleton `WorkspaceClient` that prefers configured profile → explicit host/token → environment fallback.
  - `initialize_genie_conversation()` and `query_genie_space()` both consume this singleton to avoid reconnecting per request.

---

## Logging, Tracing & Testing

- **Logging:** `src/utils/logging_config.setup_logging()` sets JSON or text output, attaches rotating file handlers, and lowers noisy dependency log levels. Every router/service log call already uses structured `extra={...}` fields for easier filtering.
- **MLflow traces:** Each session creates its own experiment. Traces run inside `mlflow.start_span("generate_slides")`, recording latency, tool usage, session info, and (for edits) replacement counts. Users access their traces via the "Run Details" header link.
- **Tests:** `tests/unit` and `tests/integration` target agents, config loaders, HTML utilities, and API-level interactions. When adding features, mirror new code with a matching test file (e.g., `tests/unit/test_<module>.py`).

### Auto-Migration on Startup

`src/core/database.py` includes a `_run_migrations()` function that runs automatically during `init_db()`. It inspects the live database schema via `sqlalchemy.inspect()` and adds any missing columns to the `user_sessions` table using `ALTER TABLE ADD COLUMN` statements:

- `created_by` (VARCHAR) — session ownership
- `visibility` (VARCHAR, default `'private'`) — access control level
- `experiment_id` (VARCHAR) — MLflow experiment tracking

This ensures deployed apps self-heal schema differences without manual SQL, which is critical for Lakebase environments where external DDL may not propagate through the PostgreSQL protocol.

### Legacy Session Access

Sessions created before ownership tracking have `created_by = NULL`. The `PermissionService.check_permission()` method grants read access to any authenticated user for these legacy sessions, preventing "permission denied" errors on pre-existing data. New sessions always have `created_by` set to the authenticated user's identity.

---

## Extending the Backend

1. **New endpoints:** Add a router under `src/api/routes`, define Pydantic request/response models, wrap blocking calls in `asyncio.to_thread()`, and add session locking for mutations.
2. **Additional tools:** Add functions to `src/services/tools.py`, wrap them with `StructuredTool`, and include them in `_create_tools_for_session()`. Remember to update prompts so the LLM knows when to invoke them.
3. **Observability hooks:** Reuse `mlflow.start_span` or extend `logging_config` if you introduce new long-running operations (e.g., batch generation).
4. **Integration with the frontend:** Any change that affects `ChatResponse` or slide deck structure must be reflected in `frontend/src/types` and `docs/technical/frontend-overview.md`.

Keep this doc synchronized whenever you add new modules, features (e.g., streaming responses), or change API contracts so both humans and AI agents stay aligned.

---

## Cross-References

- [Frontend Overview](frontend-overview.md) – UI/state patterns and backend touchpoints
- [LLM as Judge Verification](llm-as-judge-verification.md) – Auto slide accuracy verification using MLflow and human feedback collection
- [Database Configuration](database-configuration.md) – Schema details including `verification_map` for content-hash-based verification persistence
- [Real-Time Streaming](real-time-streaming.md) – SSE events and conversation persistence
- [Multi-User Concurrency](multi-user-concurrency.md) – session locking and async handling
- [Slide Parser & Script Management](slide-parser-and-script-management.md) – HTML parsing flow
- [Slide Editing Robustness](slide-editing-robustness-fixes.md) – Deck preservation, LLM validation, canvas deduplication, JS validation
- [Save Points / Versioning](save-points-versioning.md) – Complete deck state snapshots with preview and restore

