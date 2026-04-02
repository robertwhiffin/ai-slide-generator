# Backend System Overview

This guide explains how the FastAPI/LangChain backend works, how it serves the frontend, and the concepts you need to extend or automate it. Treat it as a living reference for both engineers and AI agents.

---

## Stack & Entry Point

- **Runtime:** Python 3.11+, FastAPI (ASGI) with Uvicorn/Gunicorn, packaged under `src/`.
- **Core libs:** LangChain (tool-calling agent), Databricks `WorkspaceClient`, MLflow for tracing, BeautifulSoup for HTML parsing.
- **Entry:** `src/api/main.py` instantiates FastAPI, wires CORS, user auth middleware, request logging middleware, and registers 20+ routers under `/api`.
- **Process lifecycle:** `lifespan` context starts the chat job queue worker, the export job queue worker, and the request log cleanup task. It also recovers stuck requests on startup, initializes the database, runs profile-to-agent-config migrations, and starts the Lakebase token refresh loop when running in Databricks Apps.

---

## High-Level Architecture

```
                                      ┌────────────────────────┐
Frontend fetch -> FastAPI router ->   │ ChatService            │
                                      │  - build_agent_for_request()
                                      │  - SlideDeck cache     │
                                      └──────────┬─────────────┘
                                                 │
                                    LangChain AgentExecutor (per-request)
                                                 │
                          ┌───────────────────────┴──────────────────────┐
                          │ Databricks LLM endpoint + Genie tool APIs    │
                          │ + Vector Search + MCP + Model Endpoints      │
                          │ + Agent Bricks (multiple tools per session)  │
                          └──────────────────────────────────────────────┘
```

- **Routers** (`src/api/routes/*.py`) validate HTTP payloads and map 1:1 to frontend calls. All endpoints use `asyncio.to_thread()` for blocking operations.
- **`ChatService`** (`src/api/services/chat_service.py`) is a process-wide singleton that manages a session-scoped deck cache (thread-safe via `_cache_lock`). It no longer holds a persistent agent instance; instead it calls `build_agent_for_request()` from `src/services/agent_factory.py` to construct a fresh agent for each request using the session's `agent_config`.
- **`SessionManager`** (`src/api/services/session_manager.py`) handles database-backed sessions with locking for concurrent request handling. Stores slide deck in `deck_json`, verification results separately in `verification_map` (keyed by content hash), and the session's `agent_config` JSON column.
- **`SlideGeneratorAgent`** (`src/services/agent.py`) wraps LangChain's tool-calling agent. Built per-request by `agent_factory.py` with tools derived from the session's `agent_config`.
- **`SlideDeck` / `Slide` models** (`src/domain/slide_deck.py`, `src/domain/slide.py`) parse, manipulate, and serialize slides so both chat and CRUD endpoints share the same representation. Scripts are stored directly on each `Slide` object.

---

## API Surface (Contracts Shared with Frontend)

> **Interactive API docs:** For full endpoint details, request/response schemas, and interactive testing, see the Swagger UI at `/docs` on any running instance.

### Session Endpoints

| Method | Path | Purpose | Backend handler |
| --- | --- | --- | --- |
| `POST` | `/api/sessions` | Create new session | `routes/sessions.create_session` |
| `GET` | `/api/sessions` | List sessions (filtered by authenticated user via `created_by`) | `routes/sessions.list_sessions` |
| `GET` | `/api/sessions/shared` | List presentations shared with user via deck_contributors | `routes/sessions.list_shared_presentations` |
| `GET` | `/api/sessions/{id}` | Get session details (slides + messages if creator) | `routes/sessions.get_session` |
| `PATCH` | `/api/sessions/{id}` | Update session metadata (title, slide_count) | `routes/sessions.update_session` |
| `DELETE` | `/api/sessions/{id}` | Delete session | `routes/sessions.delete_session` |
| `GET` | `/api/sessions/{id}/slides` | Get slide deck for session | `routes/sessions.get_session_slides` |
| `POST` | `/api/sessions/{id}/contribute` | Get or create contributor session for shared deck | `routes/sessions.get_or_create_contributor_session` |
| `POST` | `/api/sessions/cleanup` | Clean up expired sessions | `routes/sessions.cleanup_expired_sessions` |
| `POST` | `/api/sessions/{id}/export` | Export full session data to JSON for debugging | `routes/sessions.export_session` |

### Session Messages Endpoints

| Method | Path | Purpose | Backend handler |
| --- | --- | --- | --- |
| `GET` | `/api/sessions/{id}/messages` | Get messages (creator only, conversations are private) | `routes/sessions.get_session_messages` |
| `POST` | `/api/sessions/{id}/messages` | Add a message (creator only) | `routes/sessions.add_message` |

### Session Editing Lock Endpoints

| Method | Path | Purpose | Backend handler |
| --- | --- | --- | --- |
| `POST` | `/api/sessions/{id}/lock` | Acquire editing lock | `routes/sessions.acquire_editing_lock` |
| `DELETE` | `/api/sessions/{id}/lock` | Release editing lock | `routes/sessions.release_editing_lock` |
| `GET` | `/api/sessions/{id}/lock` | Check lock status | `routes/sessions.get_editing_lock_status` |
| `PUT` | `/api/sessions/{id}/lock/heartbeat` | Renew lock (call every ~60s) | `routes/sessions.heartbeat_editing_lock` |

### Chat & Slide Endpoints

| Method | Path | Purpose | Backend handler |
| --- | --- | --- | --- |
| `POST` | `/api/chat` | Generate/edit slides (synchronous) | `routes/chat.send_message` |
| `POST` | `/api/chat/stream` | Generate/edit with SSE streaming | `routes/chat.send_message_streaming` |
| `POST` | `/api/chat/async` | Submit for async processing (polling) | `routes/chat.submit_chat_async` |
| `GET` | `/api/chat/poll/{request_id}` | Poll for async request status | `routes/chat.poll_chat` |
| `GET` | `/api/health` | Lightweight readiness probe | `main.health` |
| `GET` | `/api/user/current` | Get current Databricks user (username, display_name, user_id, group_count) | `main.get_current_user` |
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
| `PATCH` | `/api/slides/versions/{n}/verification` | Update verification on existing save point | `routes/slides.update_version_verification` |
| `POST` | `/api/slides/versions/sync-verification` | Backfill latest save point with current verification | `routes/slides.sync_version_verification` |

Save points are created on the backend immediately after deck persistence (in `ChatService.send_message`, `send_message_streaming`, and `update_slide`). Verification scores are backfilled via `sync-verification` after auto-verification completes. Maximum 40 per session; oldest deleted on overflow. See [Save Points / Versioning](save-points-versioning.md).

### Agent Configuration & Profile Endpoints

| Method | Path | Purpose | Backend handler |
| --- | --- | --- | --- |
| `GET` | `/api/sessions/{id}/agent-config` | Get session agent config | `routes/agent_config.get_agent_config` |
| `PUT` | `/api/sessions/{id}/agent-config` | Replace full agent config | `routes/agent_config.put_agent_config` |
| `PATCH` | `/api/sessions/{id}/agent-config/tools` | Add/remove tools | `routes/agent_config.patch_tools` |
| `GET` | `/api/profiles` | List saved profiles | `routes/profiles.list_profiles` |
| `POST` | `/api/profiles/save-from-session/{session_id}` | Snapshot session config as profile | `routes/profiles.save_from_session` |
| `POST` | `/api/sessions/{id}/load-profile/{profile_id}` | Load profile into session | `routes/profiles.load_profile` |
| `PUT` | `/api/profiles/{id}` | Update profile | `routes/profiles.update_profile` |
| `DELETE` | `/api/profiles/{id}` | Delete profile | `routes/profiles.delete_profile` |
| `GET` | `/api/tools/available` | List Genie spaces + MCP servers (deprecated) | `routes/tools.get_available_tools` |

### Tool Discovery Endpoints

| Method | Path | Purpose | Backend handler |
| --- | --- | --- | --- |
| `GET` | `/api/tools/discover/genie` | List available Genie spaces | `routes/tools.discover_genie` |
| `GET` | `/api/tools/discover/vector` | List ONLINE vector search endpoints | `routes/tools.discover_vector` |
| `GET` | `/api/tools/discover/vector/{endpoint}/indexes` | List indexes for a vector endpoint | `routes/tools.discover_vector_indexes` |
| `GET` | `/api/tools/discover/vector/{endpoint}/{index}/columns` | List columns for a vector index | `routes/tools.discover_vector_columns` |
| `GET` | `/api/tools/discover/mcp` | List UC HTTP connections (MCP servers) | `routes/tools.discover_mcp` |
| `GET` | `/api/tools/discover/model-endpoints` | List non-agent model serving endpoints | `routes/tools.discover_model_endpoints` |
| `GET` | `/api/tools/discover/agent-bricks` | List agent serving endpoints | `routes/tools.discover_agent_bricks` |

### Settings Endpoints (Deck Prompts & Slide Styles)

| Method | Path | Purpose | Backend handler |
| --- | --- | --- | --- |
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

### Settings: Contributors & Identities

| Method | Path | Purpose | Backend handler |
| --- | --- | --- | --- |
| `GET` | `/api/settings/profiles/{id}/contributors` | List profile contributors | `routes/settings/contributors.list_contributors` |
| `POST` | `/api/settings/profiles/{id}/contributors` | Add profile contributor | `routes/settings/contributors.add_contributor` |
| `PUT` | `/api/settings/profiles/{id}/contributors/{cid}` | Update contributor permission | `routes/settings/contributors.update_contributor` |
| `DELETE` | `/api/settings/profiles/{id}/contributors/{cid}` | Remove profile contributor | `routes/settings/contributors.delete_contributor` |
| `GET` | `/api/settings/identities/search` | Search Databricks users/groups (SCIM or local) | `routes/settings/identities.search_identities` |

### Deck Contributors Endpoints (Sharing Decks)

| Method | Path | Purpose | Backend handler |
| --- | --- | --- | --- |
| `GET` | `/api/sessions/{id}/contributors` | List deck contributors | `routes/deck_contributors.list_deck_contributors` |
| `POST` | `/api/sessions/{id}/contributors` | Add deck contributor | `routes/deck_contributors.add_deck_contributor` |
| `PUT` | `/api/sessions/{id}/contributors/{cid}` | Update contributor permission | `routes/deck_contributors.update_deck_contributor` |
| `DELETE` | `/api/sessions/{id}/contributors/{cid}` | Remove deck contributor | `routes/deck_contributors.delete_deck_contributor` |

### Export Endpoints (PPTX & Google Slides)

| Method | Path | Purpose | Backend handler |
| --- | --- | --- | --- |
| `POST` | `/api/export/pptx` | Export deck to PowerPoint (synchronous) | `routes/export.export_to_pptx` |
| `POST` | `/api/export/pptx/async` | Start async PPTX export (polling) | `routes/export.start_pptx_export_async` |
| `GET` | `/api/export/pptx/poll/{job_id}` | Poll PPTX export status | `routes/export.poll_pptx_export` |
| `GET` | `/api/export/pptx/download/{job_id}` | Download completed PPTX | `routes/export.download_pptx_export` |
| `GET` | `/api/export/google-slides/auth/status` | Check user authorization | `routes/google_slides.auth_status` |
| `GET` | `/api/export/google-slides/auth/url` | Get Google OAuth consent URL | `routes/google_slides.auth_url` |
| `GET` | `/api/export/google-slides/auth/callback` | OAuth callback (exchanges code for token) | `routes/google_slides.auth_callback` |
| `POST` | `/api/export/google-slides` | Start async Google Slides export | `routes/google_slides.start_google_slides_export` |
| `GET` | `/api/export/google-slides/poll/{job_id}` | Poll Google Slides export status | `routes/google_slides.poll_google_slides_export` |

See [Google Slides Integration](google-slides-integration.md) for full details on the OAuth2 flow, encryption, and converter.

### Feedback Endpoints

| Method | Path | Purpose | Backend handler |
| --- | --- | --- | --- |
| `POST` | `/api/feedback/chat` | Conversational feedback via LLM | `routes/feedback.feedback_chat` |
| `POST` | `/api/feedback/submit` | Submit structured feedback | `routes/feedback.submit_feedback` |
| `POST` | `/api/feedback/survey` | Submit satisfaction survey | `routes/feedback.submit_survey` |
| `GET` | `/api/feedback/report/stats` | Usage/feedback stats report | `routes/feedback.get_stats_report` |
| `GET` | `/api/feedback/report/summary` | Feedback summary report | `routes/feedback.get_feedback_summary` |

### Image Endpoints

| Method | Path | Purpose | Backend handler |
| --- | --- | --- | --- |
| `POST` | `/api/images/upload` | Upload image file | `routes/images.upload_image` |
| `GET` | `/api/images` | List images (optional category/query filter) | `routes/images.list_images` |
| `GET` | `/api/images/{id}` | Get image metadata | `routes/images.get_image` |
| `GET` | `/api/images/{id}/data` | Get image as base64 data URI | `routes/images.get_image_data` |
| `PUT` | `/api/images/{id}` | Update image metadata (tags, description, category) | `routes/images.update_image` |
| `DELETE` | `/api/images/{id}` | Soft-delete an image | `routes/images.delete_image` |

### Admin Endpoints

| Method | Path | Purpose | Backend handler |
| --- | --- | --- | --- |
| `POST` | `/api/admin/google-credentials` | Upload app-wide Google OAuth credentials.json | `routes/admin.upload_google_credentials` |
| `GET` | `/api/admin/google-credentials/status` | Check if credentials exist and are decryptable | `routes/admin.get_google_credentials_status` |
| `DELETE` | `/api/admin/google-credentials` | Remove app-wide Google OAuth credentials | `routes/admin.delete_google_credentials` |

### Version Check Endpoints

| Method | Path | Purpose | Backend handler |
| --- | --- | --- | --- |
| `GET` | `/api/version` | Check for PyPI updates (Databricks App deployments) | `routes/version.check_version` |
| `GET` | `/api/version/check` | Alias for above | `routes/version.check_version` |
| `GET` | `/api/version/local` | Check for GitHub releases (local/Homebrew installs) | `routes/local_version.check_local_version` |

### Setup Endpoints (First-Run Configuration)

| Method | Path | Purpose | Backend handler |
| --- | --- | --- | --- |
| `GET` | `/api/setup/status` | Check if workspace is configured | `routes/setup.get_setup_status` |
| `POST` | `/api/setup/configure` | Configure Databricks workspace URL | `routes/setup.configure_workspace` |
| `POST` | `/api/setup/test-connection` | Test Databricks connection (triggers OAuth if needed) | `routes/setup.test_connection` |

**Deck Prompts** are global presentation templates stored in `slide_deck_prompt_library`. Sessions reference a selected prompt via `agent_config.deck_prompt_id`. When generating slides, the agent prepends the deck prompt content (WHAT to create).

**Slide Styles** are global visual style configurations stored in `slide_style_library`. Sessions reference a selected style via `agent_config.slide_style_id`. When generating slides, the agent includes the style content (HOW slides should look).

**Prompt Assembly Order** (in `src/services/agent.py`):
1. Deck Prompt (optional) - defines presentation type/content
2. Slide Style (from library) - defines visual appearance
3. System Prompt (technical) - defines HTML/chart generation rules
4. Slide Editing Instructions - defines editing behavior

All responses conform to the Pydantic models in `src/api/schemas/responses.py`. Structure mirrors what the frontend expects (`messages`, `slide_deck`, `raw_html`, `metadata`, optional `replacement_info`).

Mutation endpoints return **409 Conflict** if the session is already processing another request. See [Multi-User Concurrency](multi-user-concurrency.md).

---

## Request Lifecycle

1. **FastAPI validation**  
   - Bodies deserialize into `ChatRequest`, `SlideContext`, or CRUD request models in `src/api/schemas/requests.py`.  
   - `SlideContext` enforces contiguous indices and maps 1:1 with the frontend's selection ribbon.
   - All mutation endpoints require `session_id`.

2. **Session locking**  
   - Mutation endpoints call `session_manager.acquire_session_lock(session_id)` before proceeding.
   - Returns 409 if another request is already processing the session.
   - Lock released in `finally` block via `release_session_lock()`.

3. **ChatService orchestration**
   - Singleton created lazily via `get_chat_service()`.
   - Maintains a thread-safe deck cache keyed by `session_id`.
   - Calls `build_agent_for_request()` to construct a fresh agent from the session's `agent_config` for each request.
   - Operations wrapped in `asyncio.to_thread()` to avoid blocking the event loop.
   - Sessions are created on the fly when no `session_id` is provided on a chat request.

4. **Agent execution**
   - `build_agent_for_request()` reads the session's `agent_config` and constructs a `SlideGeneratorAgent` with the configured tools, slide style, and deck prompt.
   - Stitches user prompt, optional `<slide-context>...</slide-context>` block, chat history, and passes to LangChain's `AgentExecutor`.
   - **Prompt-only mode:** When no Genie tools are in the agent config, the agent runs with an empty tools list. LangChain handles this gracefully - the LLM generates slides purely from conversation without data queries.
   - **With Genie:** Each Genie space gets a uniquely-named tool. Genie tool calls automatically reuse the per-space `conversation_id` stored in the agent config, so the LLM never fabricates IDs.

5. **Post-processing**  
   - **New deck:** Raw HTML is parsed into a `SlideDeck` (`SlideDeck.from_html_string`). Canvas/script integrity is checked before caching.  
   - **Edits:** Replacement info from `_parse_slide_replacements()` merges into the cached deck via `_apply_slide_replacements()`, ensuring Chart.js script blocks stay aligned with canvas IDs.

6. **Response**  
   - `ChatService` returns the message transcript, latest deck snapshot (or `None`), raw HTML for debugging, and metadata (latency, tool calls, mode).

---

## Core Modules & Responsibilities

| Module | Responsibility | Key Details |
| --- | --- | --- |
| `src/api/main.py` | App assembly | Registers 20+ routers, CORS, auth middleware, request logging middleware. |
| `src/core/user_context.py` | Request-scoped user identity | Provides authenticated username via `ContextVar`; middleware in `main.py` sets it per request. |
| `src/core/permission_context.py` | Request-scoped permission context | Provides user ID and group IDs via `ContextVar` for permission checks on profiles and decks. |
| `src/core/lakebase.py` | Lakebase database support | Token refresh and connection management for Databricks Lakebase (Postgres). |
| `src/core/context_utils.py` | Context utilities | Shared helpers for request-scoped context management. |
| `src/api/routes/chat.py` | `/api/chat`, `/api/chat/stream`, `/api/chat/async`, `/api/chat/poll` | Session locking, SSE streaming, polling endpoints. |
| `src/api/services/job_queue.py` | Async chat processing | In-memory job queue with background worker for polling mode. |
| `src/api/services/export_job_queue.py` | Async export processing | In-memory job queue with background worker for PPTX and Google Slides exports. |
| `src/api/services/feedback_service.py` | Feedback orchestration | LLM chat-based feedback, structured feedback submission, surveys, and reporting. |
| `src/api/services/session_naming.py` | Session naming | Auto-generates session titles from conversation content. |
| `src/api/routes/sessions.py` | Session CRUD + sharing endpoints | Create, list, get (with messages), rename, delete, shared presentations, contributor sessions, editing locks. |
| `src/api/routes/agent_config.py` | Agent config endpoints | GET/PUT/PATCH for session agent config (tools, style, prompt). |
| `src/api/routes/slides.py` | Slide CRUD endpoints | Session-scoped operations with locking. |
| `src/api/routes/export.py` | PPTX export endpoints | Sync and async PPTX generation with LLM code-gen converter. |
| `src/api/routes/feedback.py` | Feedback endpoints | Chat-based feedback, structured submission, surveys, reports. |
| `src/api/routes/images.py` | Image management | Upload, list, get, update, delete image assets stored in DB. |
| `src/api/routes/admin.py` | Admin endpoints | Upload/status/delete app-wide Google OAuth credentials. |
| `src/api/routes/version.py` | PyPI version check | Checks for newer versions on PyPI (Databricks App deployments). |
| `src/api/routes/local_version.py` | GitHub version check | Checks for newer GitHub releases (local/Homebrew installs). |
| `src/api/routes/setup.py` | First-run setup | WelcomeSetup flow: configure workspace URL, test connection. |
| `src/api/routes/deck_contributors.py` | Deck sharing | CRUD for deck-level contributors (CAN_VIEW, CAN_EDIT, CAN_MANAGE). |
| `src/api/routes/tools.py` | Tool discovery | Per-type discovery endpoints for Genie, Vector, MCP, Model Endpoint, Agent Bricks. |
| `src/services/agent_factory.py` | Per-request agent builder | Reads session `agent_config`, constructs `SlideGeneratorAgent`. |
| `src/api/services/chat_service.py` | Stateful orchestration | Deck cache, streaming generator, history hydration. |
| `src/api/services/session_manager.py` | Session persistence | Database CRUD, message storage, session locking, editing locks. |
| `src/services/agent.py` | LangChain agent | Per-request tools, streaming callbacks, MLflow spans. |
| `src/services/streaming_callback.py` | SSE event emission | Emits events to queue AND persists to database. |
| `src/services/tools/` | Tool package | Submodules: `genie_tool.py`, `mcp_tool.py`, `vector_tool.py`, `model_endpoint_tool.py`, `agent_bricks_tool.py`. |
| `src/services/config_service.py` | Config management | Reads and resolves application configuration. |
| `src/services/config_validator.py` | Config validation | Validates agent config structure and references. |
| `src/services/genie_service.py` | Genie orchestration | Higher-level Genie space interaction logic. |
| `src/services/identity_provider.py` | Identity resolution | SCIM API or local identity table for user/group lookup. |
| `src/services/image_service.py` | Image storage | Upload, search, retrieve, soft-delete image assets in DB. |
| `src/services/image_tools.py` | Image agent tools | LangChain tools for image search/insertion during generation. |
| `src/services/permission_service.py` | Permission checks | Deck and profile permission evaluation (CAN_VIEW, CAN_EDIT, CAN_MANAGE). |
| `src/services/profile_service.py` | Profile management | CRUD for saved agent config profiles. |
| `src/services/validator.py` | Input validation | Shared validation utilities for service-layer input. |
| `src/domain/slide_deck.py` | Deck primitives | Parsing, reordering, cloning, script bookkeeping, serialization. |
| `src/domain/slide.py` | Slide primitives | Single slide: HTML content, scripts, metadata (created_by, modified_by, timestamps). |
| `src/core/settings_db.py` | Settings from database | Application-level defaults (LLM, etc.). |
| `src/core/databricks_client.py` | Databricks connection | Thread-safe singleton `WorkspaceClient`. |
| `src/utils/html_utils.py` | Canvas/script analysis | Extracts `canvas` ids from HTML and JS for validation. |
| `src/utils/css_utils.py` | CSS parsing & merging | Selector-level merge for edit responses using `tinycss2`. |
| `src/utils/logging_config.py` | Structured logging | JSON/text formatters, RotatingFileHandler. |
| `src/core/encryption.py` | Fernet encryption | Encrypt/decrypt Google OAuth credentials and tokens at rest. |
| `src/services/google_slides_auth.py` | Google OAuth2 | DB-backed or file-backed credential/token management. |
| `src/services/html_to_google_slides.py` | Google Slides converter | LLM code-gen HTML to Slides API, same pattern as PPTX converter. |
| `src/services/html_to_pptx.py` | PPTX converter | LLM code-gen HTML to PowerPoint. |
| `src/api/routes/google_slides.py` | Google Slides endpoints | OAuth flow + async export to Google Slides. |
| `src/api/routes/settings/contributors.py` | Profile contributor management | CRUD for profile-level contributors. |
| `src/api/routes/settings/identities.py` | Identity search | Search Databricks users/groups via SCIM or local table. |

---

## Data Models & Invariants

- **ChatRequest** ensures `message` length, `max_slides` bounds (1-50), and (when present) `slide_context` contiguous indices + matching HTML count. This keeps backend/LLM alignment with the frontend selection ribbon.
- **ChatResponse** always returns every message in the current turn so the UI can stream tool and assistant chatter without reconstructing history.
- **SlideDeck** caches the canonical state:
  - `slides` store raw HTML with `<div class="slide">`. Each `Slide` object holds its own `scripts` attribute.
  - `css`, `external_scripts` preserve deck-level styling and CDN references.
  - Canvas/script integrity is enforced via `_validate_canvas_scripts_in_html()` before caching full decks and `validate_canvas_scripts()` during replacements.

Breaking these invariants (e.g., submitting non-contiguous indices, missing `.slide` wrappers, or removing chart scripts) leads to immediate `ValueError` -> `400/500` HTTP responses, mirroring the UI expectations.

---

## Agent Details

- **Model:** `ChatDatabricks` using a fixed backend default LLM (not user-configurable).
- **Agent lifecycle:** No singleton agent. Each request calls `build_agent_for_request()` in `src/services/agent_factory.py`, which reads the session's `agent_config` JSON column and constructs a fresh `SlideGeneratorAgent` with the appropriate tools, slide style, and deck prompt.
- **Prompting:** System prompt + slide-editing addendum loaded from the session's `agent_config` (or defaults) and injected via `ChatPromptTemplate`. Chat history pulled from `ChatMessageHistory`.
- **Tools:** Derived from the session's `agent_config.tools` list. Five tool types are supported:
  - **Genie** (`src/services/tools/genie_tool.py`) - Query Databricks Genie spaces for data. Each space gets a uniquely-named tool with its own `conversation_id` tracked per-space.
  - **Vector Search** (`src/services/tools/vector_tool.py`) - Query Databricks Vector Search indexes for text-based similarity search.
  - **MCP** (`src/services/tools/mcp_tool.py`) - Call external MCP (Model Context Protocol) servers via UC HTTP connections.
  - **Model Endpoint** (`src/services/tools/model_endpoint_tool.py`) - Call non-agent model serving endpoints (foundation models, custom models).
  - **Agent Bricks** (`src/services/tools/agent_bricks_tool.py`) - Call agent serving endpoints (task starts with `agent/`).
- **Sessions:** Session state (tools, conversation IDs, style, prompt) lives in the `agent_config` JSON column on `user_sessions`. Each user operates on their own session with isolated state.
- **Concurrency:** The entire agent (tools + `AgentExecutor`) is created fresh for each request. No shared mutable state between concurrent requests.
- **Observability:** MLflow spans wrap each generation. Attributes include mode (`generate` vs `edit`), latency, tool call counts, Genie conversation ID, and replacement stats.
- **Robustness:** Multiple safeguards prevent slide data loss during edits (see [Slide Editing Robustness](slide-editing-robustness-fixes.md)):
  - Response validation with automatic retry if LLM returns text instead of HTML
  - Add vs edit intent detection to preserve existing slides when adding new ones
  - Deck preservation guard to prevent deck destruction on parsing failures
  - Canvas ID deduplication to prevent chart conflicts
  - JavaScript syntax validation and auto-fix
  - **Clarification guards** (ask before proceeding on ambiguous requests):
    - "Edit slide 8" without selection -> auto-creates slide context, applies to correct slide (RC13)
    - "Add after slide 3" -> positions correctly based on reference
    - Ambiguous edit without slide number -> asks "which slide?"
    - "Create 5 slides" with existing deck -> asks "add or replace?"
    - Selection/text conflict -> uses selection, shows note to user
  - **Unsupported operations** (RC14) - LLM guides users:
    - Delete/remove -> "Use the trash icon in the slide panel on the right"
    - Reorder/move -> "Drag and drop in the slide panel on the right"
    - Duplicate/copy -> "Select the slide and ask 'create an exact copy'"

### Per-Session MLflow Experiments

Each session creates its own MLflow experiment for isolated tracing:

1. **Experiment Path** (production with service principal):
   ```
   /Workspace/Users/{DATABRICKS_CLIENT_ID}/{username}/{session_id}/{timestamp}
   ```

2. **Experiment Path** (local development):
   ```
   /Workspace/Users/{username}/{session_id}/{timestamp}
   ```

3. **Permission Granting:** When running as a Databricks App, the system client (service principal) creates the experiment in its folder and grants `CAN_MANAGE` permission to the user via `client.experiments.set_permissions()`.

4. **Frontend Link:** The `experiment_url` is returned in the `ChatResponse` and displayed as a "Run Details" link in the header, allowing users to view traces for their session.

Key helpers in `src/core/databricks_client.py`:
- `get_service_principal_client_id()` - Returns `DATABRICKS_CLIENT_ID` env var
- `get_service_principal_folder()` - Returns `/Workspace/Users/{client_id}` or `None` for local dev
- `get_current_username()` - Gets username from the user client

---

## Contributor Sessions Architecture

Decks can be shared with other users or groups via **deck contributors** (stored in the `deck_contributors` table). Permission levels are CAN_VIEW, CAN_EDIT, and CAN_MANAGE.

When a contributor opens a shared deck:
1. The frontend calls `POST /api/sessions/{id}/contribute` to get or create a **contributor session** -- a private child session linked to the parent via `parent_session_id`.
2. The contributor session shares the parent's slide deck but has its own private conversation (chat messages are never shared).
3. **Editing locks** (`POST/DELETE/GET /api/sessions/{id}/lock`) enforce exclusive editing -- only one user can edit a shared deck at a time; others see a read-only banner.
4. Lock heartbeats (`PUT /api/sessions/{id}/lock/heartbeat`) keep the lock alive while the session is open.

The `PermissionService` (`src/services/permission_service.py`) evaluates permissions by checking:
- Session ownership (creator always has CAN_MANAGE)
- Deck contributor records (direct user grants or group membership)

---

## Slide Editing Pipeline

1. Frontend sends `slide_context = { indices, slide_htmls }`.
2. Agent prepends a `<slide-context>...</slide-context>` block to the human message so the LLM edits in place.
3. `_parse_slide_replacements()` parses the LLM's HTML into discrete slide blocks and collects:
   - `replacement_slides`, `replacement_scripts`, `replacement_css`
   - `start_index`, `original_count`, `replacement_count`, `net_change`
   - Canvas IDs referenced inside HTML or `<script data-slide-scripts>` blocks
4. `_apply_slide_replacements()` removes the original segment, inserts the new slides, merges CSS rules, and rewrites script blocks so every canvas gets exactly one Chart.js initializer.
5. **CSS merging**: replacement CSS is merged selector-by-selector -- matching selectors are overridden, new ones appended, and unrelated rules preserved.
6. **Canvas ID fallback chain**: if script parsing misses IDs, the system falls back to regex extraction, then to canvas elements in the slide HTML.
7. `replacement_info` is bubbled back to the frontend where `ReplacementFeedback` displays summaries like "Expanded 1 slide into 2 (+1)".

If the agent's HTML has empty slides, out-of-range indices, or references canvas IDs without scripts, the request fails fast with descriptive errors to keep state consistent.

---

## Configuration, Secrets & Clients

- **Agent configuration** (session-bound):
  - Each session stores an `agent_config` JSON column on `user_sessions` containing tools, slide style ID, deck prompt ID, and optional prompt overrides.
  - `build_agent_for_request()` reads this config to construct the agent per-request.
  - The LLM is a fixed backend default (not user-configurable).
  - Environment variables for secrets (`DATABRICKS_HOST`, `DATABRICKS_TOKEN`, `DATABASE_URL`).
- **Deck Prompt Injection** (`src/services/agent.py`):
  - When creating the system prompt, if `deck_prompt_id` is set in the agent config, the prompt content is loaded and prepended to provide presentation structure guidance.
  - This allows standardized decks (QBR, consumption review, etc.) without users retyping instructions.
- **Databricks client** (`src/core/databricks_client.py`):
  - Thread-safe singleton `WorkspaceClient` that prefers explicit host/token -> environment fallback.
  - `initialize_genie_conversation()` and `query_genie_space()` both consume this singleton to avoid reconnecting per request.
- **First-run setup** (`src/api/routes/setup.py`):
  - For local/Homebrew installations, the WelcomeSetup flow allows users to configure their Databricks workspace URL via the UI.
  - `GET /api/setup/status` checks for `~/.tellr/config.yaml` or `DATABRICKS_HOST` env var.
  - `POST /api/setup/configure` saves the workspace URL and enables OAuth browser authentication.

---

## Logging, Tracing & Testing

- **Logging:** `src/utils/logging_config.setup_logging()` sets JSON or text output, attaches rotating file handlers, and lowers noisy dependency log levels. Every router/service log call already uses structured `extra={...}` fields for easier filtering.
- **MLflow traces:** Each session creates its own experiment. Traces run inside `mlflow.start_span("generate_slides")`, recording latency, tool usage, session info, and (for edits) replacement counts. Users access their traces via the "Run Details" header link.
- **Tests:** `tests/unit` and `tests/integration` target agents, config loaders, HTML utilities, and API-level interactions. When adding features, mirror new code with a matching test file (e.g., `tests/unit/test_<module>.py`).

---

## Extending the Backend

1. **New endpoints:** Add a router under `src/api/routes`, register it in `src/api/main.py`, define Pydantic request/response models in `src/api/schemas/`, wrap blocking calls in `asyncio.to_thread()`, and add session locking for mutations.
2. **Additional tools:** Add a new module under `src/services/tools/`, implement a `build_*_tool()` function that returns a LangChain `StructuredTool`, re-export it from `src/services/tools/__init__.py`, and wire it into `agent_factory.py`. Remember to add a corresponding discovery endpoint in `routes/tools.py` and update prompts so the LLM knows when to invoke the tool.
3. **Observability hooks:** Reuse `mlflow.start_span` or extend `logging_config` if you introduce new long-running operations (e.g., batch generation).
4. **Integration with the frontend:** Any change that affects `ChatResponse` or slide deck structure must be reflected in `frontend/src/types` and `docs/technical/frontend-overview.md`.

Keep this doc synchronized whenever you add new modules, features (e.g., streaming responses), or change API contracts so both humans and AI agents stay aligned.

---

## Cross-References

- [Frontend Overview](frontend-overview.md) -- UI/state patterns and backend touchpoints
- [LLM as Judge Verification](llm-as-judge-verification.md) -- Auto slide accuracy verification using MLflow and human feedback collection
- [Database Configuration](database-configuration.md) -- Schema details including `verification_map` for content-hash-based verification persistence
- [Real-Time Streaming](real-time-streaming.md) -- SSE events and conversation persistence
- [Multi-User Concurrency](multi-user-concurrency.md) -- session locking and async handling
- [Slide Parser & Script Management](slide-parser-and-script-management.md) -- HTML parsing flow
- [Slide Editing Robustness](slide-editing-robustness-fixes.md) -- Deck preservation, LLM validation, canvas deduplication, JS validation
- [Save Points / Versioning](save-points-versioning.md) -- Complete deck state snapshots with preview and restore
- [Google Slides Integration](google-slides-integration.md) -- OAuth2 flow, encrypted credential storage, LLM converter
