# Backend System Overview

This guide explains how the FastAPI/LangChain backend works, how it serves the frontend, and the concepts you need to extend or automate it. Treat it as a living reference for both engineers and AI agents.

---

## Stack & Entry Point

- **Runtime:** Python 3.11+, FastAPI (ASGI) with Uvicorn/Gunicorn, packaged under `src/`.
- **Core libs:** LangChain (tool-calling agent), Databricks `WorkspaceClient`, MLflow for tracing, BeautifulSoup for HTML parsing.
- **Entry:** `src/api/main.py` instantiates FastAPI, wires CORS, user auth middleware, request logging middleware, and registers 20+ routers under `/api`.
- **Process lifecycle:** `lifespan` context starts the chat job queue worker, the export job queue worker, the export job TTL cleanup worker, and the request log cleanup task. It also recovers stuck requests on startup, initializes the database, runs profile-to-agent-config migrations, and starts the Lakebase token refresh loop when running in Databricks Apps.

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
| `GET` | `/api/sessions` | List sessions for current user (`created_by`). Query: `limit`, `deck_only` (slide-deck sessions only) | `routes/sessions.list_sessions` |
| `GET` | `/api/sessions/shared` | List presentations shared via deck_contributors or workspace `global_permission` | `routes/sessions.list_shared_presentations` |
| `GET` | `/api/sessions/{id}` | Get session details (slides + messages if creator) | `routes/sessions.get_session` |
| `PATCH` | `/api/sessions/{id}` | Update session metadata (title, slide_count) | `routes/sessions.update_session` |
| `POST` | `/api/sessions/{id}/duplicate` | Duplicate deck into a new private session (requires CAN_VIEW). Body: optional `title`, optional `version_number` (save point) | `routes/sessions.duplicate_session` |
| `DELETE` | `/api/sessions/{id}` | Delete session | `routes/sessions.delete_session` |
| `GET` | `/api/sessions/{id}/slides` | Get slide deck for session | `routes/sessions.get_session_slides` |
| `POST` | `/api/sessions/{id}/contribute` | Get or create contributor session for shared deck | `routes/sessions.get_or_create_contributor_session` |

Two session routes were removed by SDR-4437 and are intentionally absent from the
table above: `POST /api/sessions/cleanup` (F-CR-16 — unauthenticated cascading
delete of all users' expired sessions) and `POST /api/sessions/{id}/export`
(F-CR-10 — dumped full session data to disk). Neither had a caller.

### Session Messages Endpoints

| Method | Path | Purpose | Backend handler |
| --- | --- | --- | --- |
| `GET` | `/api/sessions/{id}/messages` | Get messages (creator only, conversations are private). Never returns the `engine_mode_marker` row a clear keeps | `routes/sessions.get_session_messages` |
| `POST` | `/api/sessions/{id}/messages` | Add a message (creator only) | `routes/sessions.add_message` |
| `DELETE` | `/api/sessions/{id}/context` | Clear chat. Requires CAN_EDIT on the deck and being the session's creator; 409 while a turn or slide operation holds the session lock. In one transaction, deletes the session's transcript and graph thread and writes a `context_cleared` usage event. Keeps the deck, its Spec (`deck_spec_json`), save points, the Conversation Pin, and the earliest user message (re-typed `engine_mode_marker`; `SessionManager.get_messages` and save-point capture drop it, the per-request `get_messages_for_request` does not) | `routes/sessions.clear_session_context` |
| `DELETE` | `/api/sessions/{id}/messages/{message_id}` | Delete a message and the replies to it. Requires CAN_EDIT on the deck and being the session's creator; 409 while a turn or slide operation holds the session lock; 404 ("That message is not in this conversation.") for any id that is not a visible user message of this session; 422 for a non-integer id. The unit is the **turn**: the user message and every later row of the session up to, not including, the next `role='user'` row. The session's earliest user message is hidden, not deleted: it is re-typed `engine_mode_marker` and the rest of its turn is deleted. In one transaction, deletes the turn's rows and the session's graph thread and writes a `message_deleted` usage event. Nothing is undone in the deck: slides, the Spec, save points and the Conversation Pin stay as they are | `routes/sessions.delete_session_message` |

**Deleting a message** (`ChatService.delete_message`, with the grouping in `src/domain/conversation_turns.py`):

- **The turn is addressed by its user message's id.** The turn is that row plus every later row of the same session up to the next `role='user'` row, read in `(created_at, id)` order: replies, clarifications, `info` notices (the deck reviewer's advisory, failure notices), `reasoning`, `tool_call` and `tool_result` rows. Grouping is by role and order, never by `request_id` or `message_type`, because `request_id` is `None` on the SSE path and on sweeper and ungated notices. A row of another session is never touched, and an assistant or tool row cannot start a turn.
- **Late rows join the turn they follow.** A row written after the next user message has been stored (a lock taken over after 300 s as stale, an SSE disconnect that releases the lock while the turn keeps writing, a sweeper notice from the ungated `_surface_notice`) is grouped with the turn it lands after. Deleting the earlier turn leaves that row; deleting the turn it landed in takes it.
- **The first message is hidden, not deleted.** The session's earliest user row is found through `earliest_user_message` (`session_manager.py`). Engine mode reads it. When the turn being deleted starts there, the row is re-typed `engine_mode_marker`, which every transcript read drops, and the rest of its turn is deleted. The response carries `hidden_message_id`; a second delete of that id is a 404. `message_count` still counts the row, so the next turn is not a "first message" and the deck's title is not regenerated. For a contributor session the row is the contributor's own; the deck's engine is resolved on the owner's rows, which a contributor's delete never touches.
- **The graph thread is deleted on every delete.** The checkpointer keeps every checkpoint of every turn, and each stores that turn's message and the architect's reply; leaving the thread would leave the deleted text in the checkpoint. `get_checkpointer().delete_thread(session_id, session=db)` runs in the delete's own transaction, so any delete, of any turn, drops the whole thread and the next turn starts a new one. The row delete, the re-type, the `message_deleted` event and the thread delete commit or roll back together (a failure is a 500 and changes nothing). Nothing replays the thread to an agent: the architect's `conversation` and the monolith's history are read from the rows every turn.
- **The cost of deleting the thread.** `deck_spec` lives in graph state, and the data analyst reads it for `deck_purpose`. An `ask_data` turn returns before the architect writes `deck_spec`, so **an `ask_data` turn after a delete sends the analyst `deck_purpose: None`**, and so does every later one until a build or edit turn writes `deck_spec` into the new thread. This is the same cost a clear pays, and a delete is more frequent, so it is a recorded follow-up. Build and edit turns rewrite `deck_spec` and are unaffected; so is the deck reviewer.
- **Nothing is undone in the deck.** Only `session_messages` changes, plus the thread and the attribution row. Slides, `deck_json`, the Spec, save points, `graph_release_id` and `agent_config` are untouched; the next turn starts from the current Spec and slides, which still contain what the deleted turn built. A save point already taken keeps the chat it captured; a restore re-inserts no rows, so it never brings a deleted turn back (see [Save Points](save-points-versioning.md#deleting-a-message)).
- **What every reader sees afterwards.** `GET /api/sessions/{id}` and `GET /api/sessions/{id}/messages` omit the turn; the architect's `conversation` and the monolith history omit it; `message_count` drops by the rows deleted but never reaches 0 once a user row existed; a poll for the deleted turn's `request_id` (`get_messages_for_request`, which the web poll and the MCP `get_deck_status` use) returns no rows, except that when the deleted turn was the session's first it still returns the kept row, typed `engine_mode_marker`, as after a clear.
- **Slide verification.** `verification._build_verification_corpus` builds the judge's source data from the session's `tool_result` rows. A deleted legacy (monolith) turn takes its `tool_result` rows with it, so verifying a slide built from that data afterwards has less to check against and can answer "No source data available".
- **The guided tour.** The tour's scripted stages are recorded as `tour_stage` metadata on chat rows, and `_applied_stages` (`routes/tour.py`) reads them through `get_messages`. Deleting a tour turn removes the `tour_stage` rows it holds (a delete of the first turn also hides the `prompt` row, which `get_messages` drops), so those stages no longer count as applied. A later stage whose predecessor's row went with the turn answers 409 (`StageOrderError`): for example `plan` once the `prompt` row is hidden, or `build` after the `plan` row is gone and before the deck is built. A stage whose own rows went runs again while its predecessor still counts; `build` counts while the deck has slides, a Spec and every slide verified, because it is derived from the deck, not from a row. The demo deck's slides and Spec are unaffected.
- **Genie.** A Genie space keeps its own conversation (`genie_conversation_id`). A deleted turn's data questions stay there, as they do after a clear.
- **Ids can be reused on SQLite.** `SessionMessage.id` is a plain `INTEGER PRIMARY KEY` with no `AUTOINCREMENT`, so on SQLite (the test databases, or a local `DATABASE_URL=sqlite:///…`) the next row takes the table's highest id plus one. If the deleted rows held the highest id, the next row reuses it, and a stale tab could address a newer turn. Postgres, the default local database and the deployed one, takes ids from a sequence that never reuses them.

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

### Settings: Design Systems

All routes live in `routes/settings/design_systems.py`, mounted under `/api/settings`. Reads are open (design systems are org-shared); mutations are creator-or-admin; the two default routes are admin-only. See [Design System Library §5](design-system-library.md).

| Method | Path | Purpose | Backend handler |
|--------|------|---------|-----------------|
| `GET` | `/api/settings/design-systems` | List with token/asset/template counts | `list_design_systems` |
| `POST` | `/api/settings/design-systems/import` | Import a bundle zip | `import_design_system` |
| `POST` | `/api/settings/design-systems` | Create a token-only system | `create_design_system` |
| `GET` | `/api/settings/design-systems/{id}` | Detail | `get_design_system` |
| `PUT` | `/api/settings/design-systems/{id}` | Update | `update_design_system` |
| `DELETE` | `/api/settings/design-systems/{id}` | Soft delete; `?hard_delete=true` for permanent | `delete_design_system` |
| `POST` | `/api/settings/design-systems/{id}/set-default` | **Admin only.** Set the org default | `set_default_design_system` |
| `POST` | `/api/settings/design-systems/{id}/clear-default` | **Admin only.** Clear the org default | `clear_default_design_system` |
| `GET` | `/api/settings/design-systems/{id}/templates` | List named templates, each with `is_default` | `list_design_system_templates` |
| `POST` | `/api/settings/design-systems/{id}/templates/{tid}/set-default` | **Admin only.** Set the system's default template | `set_default_template` |
| `POST` | `/api/settings/design-systems/{id}/templates/{tid}/clear-default` | **Admin only.** Clear the system's default template | `clear_default_template` |
| `GET` | `/api/settings/design-systems/{id}/templates/{tid}/thumbnail` | Serve a template thumbnail | `serve_design_system_template_thumbnail` |
| `GET` | `/api/settings/design-systems/{id}/templates/{tid}/source` | Serve template HTML | `get_design_system_template_source` |
| `GET` | `/api/settings/design-systems/{id}/assets/{aid}` | Serve asset bytes | `serve_design_system_asset` |
| `GET` | `/api/settings/design-systems/{id}/assets/{aid}/thumbnail` | Serve an asset thumbnail | `serve_design_system_asset_thumbnail` |
| `GET` | `/api/settings/design-systems/{id}/files` | List bundle files | `list_design_system_files` |
| `GET` | `/api/settings/design-systems/{id}/files/{path}` | Serve a bundle file | `serve_design_system_file` |

**Asset resolution is scoped by `(asset_id, design_system_id)`, never by global id.** Resolving by global id would permit cross-system asset disclosure: a foreign `{{ds-asset:ID}}` handle from a crafted bundle would return another design system's bytes. `get_asset_base64` documents this as the confused-deputy guard and makes the scope a mandatory keyword argument, and `design_system_id=None` is fail-closed. Any new route that resolves assets must carry the same scoping.

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
| `GET` | `/api/sessions/{id}/contributors` | List deck contributors and workspace `global_permission` | `routes/deck_contributors.list_deck_contributors` |
| `POST` | `/api/sessions/{id}/contributors` | Add deck contributor | `routes/deck_contributors.add_deck_contributor` |
| `PUT` | `/api/sessions/{id}/contributors/{cid}` | Update contributor permission | `routes/deck_contributors.update_deck_contributor` |
| `DELETE` | `/api/sessions/{id}/contributors/{cid}` | Remove deck contributor | `routes/deck_contributors.delete_deck_contributor` |
| `PATCH` | `/api/sessions/{id}/global` | Set or clear workspace-wide deck sharing (CAN_VIEW / CAN_EDIT) | `routes/sessions.set_deck_global_permission` |

### Export Endpoints (PPTX & Google Slides)

| Method | Path | Purpose | Backend handler |
| --- | --- | --- | --- |
| `POST` | `/api/export/pptx/editable/huashu/from-html` | **Primary.** Render the deck HTML to PowerPoint | `routes/export.export_pptx_huashu_from_html` |
| `POST` | `/api/export/pptx/editable/from-records` | **Fallback** — fires on 503 or an unavailable/installing pipeline message | `routes/export.export_pptx_editable_from_records` |
| `POST` | `/api/export/google-slides/from-huashu` | **Primary.** Synchronous Google Slides export via Drive conversion | `routes/google_slides` |
| `POST` | `/api/export/google-slides/from-records` | **Fallback** for the Google path | `routes/google_slides` |
| `POST` | `/api/export/pptx` | **Legacy** — LLM code-generation path; no caller exists in this repository's frontend, and the UI uses the huashu route above | `routes/export.export_to_pptx` |
| `POST` | `/api/export/pptx/async` | **Legacy** — async twin of the above; no caller in this repository's frontend | `routes/export.start_pptx_export_async` |
| `GET` | `/api/export/pptx/poll/{job_id}` | Poll PPTX export status | `routes/export.poll_pptx_export` |
| `GET` | `/api/export/pptx/download/{job_id}` | Download completed PPTX | `routes/export.download_pptx_export` |
| `GET` | `/api/export/google-slides/auth/status` | Check user authorization and whether client credentials exist | `routes/google_slides.auth_status` |
| `GET` | `/api/export/google-slides/auth/url` | Get Google OAuth consent URL | `routes/google_slides.auth_url` |
| `GET` | `/api/export/google-slides/auth/callback` | OAuth callback (exchanges code for token) | `routes/google_slides.auth_callback` |
| `DELETE` | `/api/export/google-slides/auth` | Revoke the current user's stored Google token | `routes/google_slides.revoke_auth` |
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
| `src/api/routes/deck_contributors.py` | Deck sharing | CRUD for deck-level contributors; list includes workspace `global_permission`. |
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
  - `slides` store raw HTML whose root carries the `slide` class. The root is **not** div-only — discovery keys on the class token independent of tag name, so a `<section class="slide">` root (as design-system templates use) is equally valid. Each `Slide` object holds its own `scripts` attribute.
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

## Workbench Model Selection (ws2a — Unity AI Gateway)

The Agent Definition Workbench (`/admin`) lets administrators configure which model each
of the seven graph roles uses. Since workstream 2a, model discovery and validation run
through the Unity AI Gateway rather than the Serving Endpoints API.

### Discovery (`src/services/model_endpoint_catalog.py`)

`DatabricksModelEndpointCatalog.list_system_models` calls the SDK's
`ai_gateway.list_model_services(parent="schemas/system.ai")`
(`GET /api/2.1/unity-catalog/model-services`, databricks-sdk >= 0.123.0) as the app
service principal. The SDK follows `next_page_token` lazily, so every page is read inside
the failure mapping. Scoping the list to the `system.ai` schema returns every foundation
model in one page (an unscoped list takes about ten pages and includes other catalogs'
services). Each service is named `model-services/system.ai.<model>`; the picker shows the
`system.ai.<model>` part.

A service is left out of the picker when any of these hold, so the picker never offers a
model the save then refuses:

- its name fails the save rule below;
- its `supported_api_types` lacks `mlflow/v1/chat/completions` (embedding models);
- it has a service-wide rate limit (`RATE_LIMIT_KEY_SERVICE`) of zero requests or zero
  tokens. Every call to such a model fails with 403 "rate limit set to 0". Per-user,
  per-group and per-principal limits are ignored. The Model tab says "Models with a rate
  limit of zero are not shown."

There is no custom-name free-text input field. The workbench offers only models the
Gateway list returns.

### Save-time validation

**Local name policy.** When a draft save changes the model, `_gateway_model_name_validator`
checks that the new name matches `^system\.ai\.[a-z0-9][a-z0-9._-]*[a-z0-9]$`. This
validator runs after the lock-version comparison (after the `DraftSaveConflict` early
return) and before the remote check, so a stale save reports 409 Conflict rather than 422.
A save that leaves the model unchanged is not checked by this rule, which means a role
still named `databricks-*` continues saving normally until an admin changes its model.

**Remote Gateway lookup.** `validate_custom_endpoint_remote` calls
`ai_gateway.get_model_service(name="model-services/<name>")` through a bounded catalog
client (5 s retry, 3 s HTTP). A legacy `databricks-<m>` name is looked up as
`system.ai.<m>`. The save is rejected with `endpoint_not_chat_model` if
`supported_api_types` lacks `mlflow/v1/chat/completions`, and with `endpoint_rate_limited`
if the service has a service-wide rate limit of zero.

### Legacy names on stored releases

Conversations pinned to releases created before ws2a store `databricks-*` endpoint names.
At runtime the name is passed through to the Gateway unchanged. The Gateway accepts both
`system.ai.*` and `databricks-*` forms: live-probed 2026-09-28 — `databricks-claude-haiku-4-5`
and `databricks-claude-opus-5-5` both answered on the Gateway route (ws2a spec §2
platform-facts table). Task 9's live acceptance test re-confirms this for a pinned
pre-ws2a conversation against the deployed instance. No rewriting or republishing is
required.

The v1 seed pins `system.ai.claude-opus-5-5` on four roles (architect, data_analyst,
build_reviewer, fixer) and `system.ai.claude-haiku-4-5` on the other three; it moved off
`claude-opus-5` when that model was rate-limited to zero. The seed is inserted only into
an empty database, so a database seeded earlier keeps its stored v1 release until an
admin publishes a new one.

---

## Contributor Sessions Architecture

Decks can be shared with other users or groups via **deck contributors** (stored in the `deck_contributors` table), or with all Tellr workspace users via **`user_sessions.global_permission`** on the root session (CAN_VIEW or CAN_EDIT only). Individual contributor grants use CAN_VIEW, CAN_EDIT, and CAN_MANAGE.

When a contributor opens a shared deck:
1. The frontend calls `POST /api/sessions/{id}/contribute` to get or create a **contributor session** -- a private child session linked to the parent via `parent_session_id`.
2. The contributor session shares the parent's slide deck but has its own private conversation (chat messages are never shared).
3. **Editing locks** (`POST/DELETE/GET /api/sessions/{id}/lock`) enforce exclusive editing -- only one user can edit a shared deck at a time; others see a read-only banner.
4. Lock heartbeats (`PUT /api/sessions/{id}/lock/heartbeat`) keep the lock alive while the session is open.
5. Clearing the chat (`DELETE /api/sessions/{id}/context`) affects only the caller's own session. A contributor clears their own contributor session's transcript and graph thread, never the owner's; the deck's engine is resolved on the owner's rows and does not change.
6. Deleting a message (`DELETE /api/sessions/{id}/messages/{message_id}`) is likewise confined to the caller's own session. A contributor deletes only in their own contributor session, never in the owner's, and a message id that belongs to another session is a 404 on their own.

The `PermissionService` (`src/services/permission_service.py`) evaluates permissions by checking:
- Session ownership (creator always has CAN_MANAGE on the root deck)
- Deck contributor records (direct user grants or group membership)
- Workspace-wide `global_permission` on the root session (CAN_VIEW / CAN_EDIT)

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

## Graph Path: Slide Numbers and Positions

Users say "slide 2"; the graph keys everything on `SlideSpec.position` (0-based). Issue #313 maps one to the other in code (`src/domain/slide_numbering.py`, pure, no I/O) so the architect model copies positions instead of computing them. The module docstring is the authoritative statement of the rules, and `tests/unit/test_slide_numbering.py` pins them. Glossary: **Slide Number**, **Slide Position** and **Slide Reference** in `CONTEXT.md`.

**What "slide N" means.** Slide N is the N-th slide of the current deck in ascending position order: the number the slide panel shows (list index + 1 over the rows), not `N - 1`.
- `architect_node` numbers over the committed rows' positions when there are rows, else the persisted spec's positions, else nothing (`_deck_positions` in `src/services/graph/nodes.py`). Rows win even if the spec disagrees: an edit whose spec and rows disagree is refused anyway (`_persisted_spec_describes_these_rows`).
- Positions are contiguous from 0 in practice, so Position = Number - 1. Every deck mutation re-stamps the spec and renumbers the rows from 0. Delete, duplicate and reorder re-stamp the spec through `ChatService._rewrite_deck_spec_slides` and the rows through `save_slide_deck`, which renumbers from 0 and prunes the rest. The viewer's insert does both in one transaction, `SessionManager.insert_slide` (see "Inserting a blank slide by hand" below), and the agent's insert does it in `SlideWriter.insert_pending_slides`. A gap can only come from an architect build spec that has one (for example positions 0, 2, 5 give slides 1, 2, 3, and "slide 3" is position 5).

**Payload keys.** Two literal keys on the architect payload, both always lists:
- `slide_numbering`: `[{"slide_number": 1, "position": 0}, ...]`, one entry per slide in presentation order. Empty when there is no deck.
- `slide_references`: `[{"text": "slides 2-4", "slide_numbers": [2, 3, 4], "positions": [1, 2, 3], "out_of_range": []}, ...]`, one entry per reference in the user's message, in order of appearance. `text` is the matched substring. `slide_numbers` holds every number the phrase names, sorted and deduplicated; `positions` holds the in-range ones mapped through the numbering; `out_of_range` holds numbers below 1 or above the slide count. Numbers are reported, never clamped. Empty when there is no deck.

**Reference grammar (as shipped).** Case-insensitive, at word boundaries, left to right, longest form wins. Numbers are 1-3 digits or the words one to twenty; ordinals are 1-3 digits plus `st`/`nd`/`rd`/`th` (suffix unchecked) or first to twentieth.
- Resolved: "slide 2", "slide #2", "slide number 2", "slide two", "slide 2-4", "slide 2 and 3"; "slides 2-4", "slides 2 to 4", "slides 2, 3 and 5", "slides 2-4 and 6"; an ordinal before a singular `slide` ("the second slide", "the 4th slide", "last slide: ...", "the final slide"). `last`/`final` are the slide count; "penultimate" and "second-to-last" are the count minus one. Ranges are inclusive, in either order; one spanning more than 100 numbers drops the reference.
- Abstain rule: the architect copies `target_positions` from these references, so a wrong or truncated one is worse than none. A singular `slide` whose item list is followed by a continuation the form cannot read gives NO reference for that phrase, never a shorter "slide 2": a dash and a digit with or without spaces ("slide 2 - 4", "slide 2 -4"), `to`/`through`/`thru` and a number ("slide 2 through 5", "move slide 2 to 5"), or a comma list (a comma, a number, then `,`, `and` or `&`: "Slide 2, 3 and 4"). A continuation that is not a number keeps the reference ("Change slide 2 to a chart", "Compare slide 2 to slide 5", "On slide 2, 3 cards ..."). Other references in the same text are unaffected. "slide 2 through slide 5" (also "up to", "until", "till", "through to", with "#" or "number" prefixes, or a plural head) is read as one inclusive range (2-5), never as its two ends; "from slide 2 to slide 5" stays two references.
- An ordinal before `slide` is not a reference when `slide` is a compound noun or begins a relative tail: followed by a hyphen and a word ("the second slide-deck"), by `deck`, `template`, `count` or `master` ("the last slide deck you made", "the final slide count"), by `from` plus an optional `the` and `end`, `last`, `back` or `bottom` ("the second slide from the end"), or by `but one` ("the last slide but one"). "the last slide.", "the last slide, please" and "the last slide's chart" are still references.
- Volume: at most 20 references (`MAX_REFERENCES`) are returned, and an identical reference (same `text` and `slide_numbers`) appears once, at its first position. Duplicates are removed before the cap, so they never use it up.
- Indefinite ordinals are not references: an ordinal right after `a`, `an`, `another`, `new`, `extra`, `additional`, `one` or `one more` names a slide that does not exist yet ("Add a final slide", "Add one last slide", "I need a third slide").
- Unresolved on purpose, each pinned by a test: count-relative tails ("the third to last slide", "the next to last slide", "the second from last slide"; "put it next to the last slide" is still the last slide); hyphenated number words ("twenty-one", "twenty-first"); a digit dash range the grammar cannot read ("slides 1-1000"); count-relative or plural ordinals ("the last two slides", "the second and third slides"); deictic and semantic phrases ("this slide", "the next slide", "the cover"); slide counts ("a 10-slide deck", "10 slides"); and "or" as a separator. The model looks these up in `slide_numbering`.
- Known limits, each pinned by a test: a bare-comma plural such as "On slides 2, 3 bullets each" resolves to slides 2 and 3, because a count cannot be told from a slide; and "Put 3 KPIs on slide 2 and 4 on slide 3" resolves "slide 2 and 4" (slides 2 and 4) plus "slide 3", because the singular form accepts `and` as a separator and reads the count as a slide.
- References are lexical: they say which existing slide a phrase names, not that the user wants it changed.

**Which text, and when none.** The latest user turn in `conversation` is resolved (falling back to `message`), not the analyst's synthesis that `message` holds on the pass after the analyst returns. On a describe-only turn (the sweeper's `ARC_REVIEW_MESSAGE`, which persists no user row) `slide_references` is `[]`, because the latest user turn predates the hand edit and its "slide 2" may name a different slide now; `slide_numbering` is still sent.

**Guard (log only).** `edit_ignores_references` is true when an edit's `target_positions` share no position with the resolved in-range references. `architect_node` then logs a WARNING and changes nothing: an off-by-one model also revised the wrong `SlideSpec`, and legitimate edits can be disjoint from the named slides ("slide 2 is perfect; tighten the rest"). It does not run on a describe-only turn.

**The prompt rule.** The architect's SLIDE NUMBERS rule tells the model to take `target_positions` from `slide_references`, to look any other number or ordinal up in `slide_numbering`, never to compute a position as the slide number minus one, and, when a reference has `out_of_range` numbers, not to edit but to discuss and say how many slides the deck has. It also says a reference does not by itself mean the user wants a change.

**Rollout.** The Graph V1 manifest only seeds a fresh bootstrap: `bootstrap_v1` in `src/services/graph_configuration_bootstrap.py` returns early, validating the persisted history, when any Graph Release exists, and loads the manifest only when none does. An existing install therefore keeps its persisted architect prompt. It gets the two payload keys immediately (they are built in code), but the new SLIDE NUMBERS text only when an admin publishes a release carrying it, the same as earlier prompt promotions (for example 45ce906c).

**Known limits.**
- SpecView labels slides `position + 1` (`SpecView.tsx`), so on a gapped deck its label differs from the panel's number, which is what the graph follows.
- On the SSE transport the image-attachment context is appended to the user message before it is persisted (`_inject_image_context`, `src/api/services/chat_service.py`), so an attachment filename such as "slide 3.png" can resolve as a reference. The polling transport persists the raw message, so it does not.

### Editing the deck's slides

A user on the graph path can ask for any combination of slide edits in one message ("delete slide 4, add a slide after 5 about X, expand the three bullets on 6 into three slides"). The architect answers with intent `edit` and an ordered list of **operations**, plus `deck_changes` when the user asked for a deck-level change. `architect_node` checks the whole list against the current deck, applies it as one change, and builds only the slides the list inserted, updated or replaced. The design is `docs/superpowers/specs/2026-10-28-architect-edit-operations-design.md`; it replaces the alignment approach of #314 (an edit returned the whole revised `deck_spec` and the node worked out what changed). Glossary: **Operation**, **Replace**, **Move**, **Rejected Edit**, **Slide Insertion** and **Pending Slide** in `CONTEXT.md`. Any operation that adds, removes or moves a slide changes the Position, and so the Slide Number, of other slides. The numbering is recomputed from the rows every turn, so nothing is stored. A person can also insert a **Blank Slide** by hand, with no model involved: see "Inserting a blank slide by hand" at the end of this section.

**Operations** (`src/domain/slide_operations.py`, pure, no I/O). `ArchitectOutput` (`src/domain/skill_io.py`) has two optional fields, `operations: list[SlideOperation]` and `deck_changes: DeckChanges`. `SlideOperation` is flat (`op`, `position`, `after_position`, `slides`); the per-op rules are checked in the domain module, not in pydantic, because a pydantic error fails the turn with no retry and a domain problem is retryable. Every `position` and `after_position` is a `SlideSpec.position` of the deck as it was before the message (the same numbering as `slide_numbering`); `after_position: -1` means the start.

| op | needs | meaning |
| --- | --- | --- |
| `update` | `position`, one slide | The slide gets this spec and is rebuilt in place, keeping its row. |
| `replace` | `position`, 1+ slides | "Slide N becomes these slides". The first takes over the old slide's row and is rebuilt; the rest are new slides directly after it. |
| `insert` | `after_position`, 1+ slides | New slides after `after_position`, in list order. |
| `delete` | `position` | The slide and its spec entry are removed. Nothing is rebuilt. |
| `move` | `position`, `after_position` | The row moves to directly after `after_position`. Not rebuilt; its spec entry is unchanged. |

Placement is deterministic, so nothing is guessed. A slide is the subject of at most one operation (a replace is one). Anything placed after slide *a* (inserted or moved) goes directly after *a*'s own content (*a*, or all of its replacement slides), in list order. "After *a*" follows *a* if *a* is moved, and fills *a*'s gap if *a* is deleted. A slide cannot move after itself and moves cannot loop. `slides` on a delete or move is ignored. `apply_operations(current, operations)` returns an `OperationsResult` (`slides` re-stamped `0..m-1`, `layout`, `rebuild`, `deleted`, `moved`) or `OperationProblems`, collecting every problem in one pass so one retry can fix them all. Codes (`PROBLEM_CODES`): `unknown_slide`, `slide_targeted_twice`, `missing_slides`, `update_needs_one_slide`, `missing_position`, `missing_after_position`, `move_after_itself`, `move_loop`, `deck_emptied`, `nothing_to_do`, `invalid_deck_changes`. `apply_operations(current, [])` is the identity (every slide kept, nothing rebuilt); `compose_edit_spec` reports `nothing_to_do` when the identity comes with no deck change. `problem_sentence` renders a problem in the user's 1-indexed slide numbers, and returns the problem's own `detail` for a code outside `PROBLEM_CODES` (binding and alignment problems, whose details are already sentences).

**Two paths in `architect_node`.**
- *The operations path:* an `edit` whose answer has `operations` or `deck_changes`. `_plan_answer` first runs the up-front guards as before (`edit_without_spec`, `spec_positions_stale`); only then does `_plan_operations_edit` check the rest with no side effect: `apply_operations`, the composed spec with `deck_changes` applied, the DeckSpec validators, and the template binding checks (`complete_index_only_bindings`, `invalid_slide_bindings`). `target_positions` is always the derived `rebuild` set; the model's own is ignored (WARNING `operations_targets_disagree` on a difference), and so is the rest of `deck_spec`, with one exception below. An empty `rebuild` (delete or move only) sends the foreman straight to deck review.
- *The spec path:* an `edit` without `operations` or `deck_changes` goes through the alignment described below, unchanged. This covers sessions pinned to an older release (whose prompt never mentions operations), a model that ignores the new prompt, and the describe-only sweeper. Describe-only turns ignore `operations` entirely. `operations` or `deck_changes` on any other intent (`build`, `discuss`, `ask_data`, `confirm_design_contract`) are ignored with INFO `operations_ignored`; only an `edit` takes the operations path.
- *A contract carried in `deck_spec`.* The prompt's DESIGN SYSTEMS block now says a confirmed contract is committed inside `deck_spec` on a build and in `deck_changes.design_contract` on an edit, as EDITING does (before the `edit-ops-b` follow-up it said "inside deck_spec" only). The node still tolerates an operations answer that puts the contract in `deck_spec` (C19): on the operations path, when `deck_changes` sets no contract and `deck_spec` carries one whose ids differ from the persisted spec's, that contract is adopted as the edit's `deck_changes.design_contract` (INFO `operations_contract_from_deck_spec`). The same contract adopts nothing, so an echoed spec cannot turn `nothing_to_do` into a no-op edit.
- *Numbering.* The composed spec is re-stamped `0..m-1` and so are the rows, except when `result.layout` is the identity over the persisted positions (update-only or `deck_changes`-only): then each composed slide keeps its persisted position, `target_positions` are the persisted positions of the rebuilt slides, and the row writer is not called. That keeps a gapped deck's rows and spec in step; re-stamping it would make the next turn refuse as `spec_positions_stale`. This mirrors the spec path's two numberings (equal-length edits use positions, inserts re-stamp).

**One retry.** A turn calls the architect at most twice. `_plan_answer` runs every check that can refuse an answer and says and writes nothing. A refusal whose code is in `RETRYABLE_EDIT_CODES` is retried once, with the same payload plus `rejected_edit`:

```json
"rejected_edit": {
  "your_previous_answer": { "intent": "...", "operations": [...], "deck_changes": {...}, "target_positions": [...] },
  "problems": [ { "code": "unknown_slide", "positions": [29], "detail": "..." } ]
}
```

Retryable: `edit_operations_rejected`, `invalid_slide_type_binding`, the spec path's `edit_insert_ambiguous`, `edit_spec_moves_slides` and `edit_spec_positions_changed`, and `edit_without_revised_spec` (an edit with neither `operations` nor `deck_spec`). The last four refuse an edit without operations. Their problem's `detail` says what went wrong and tells the model to return the edit as `operations` (`_AS_OPERATIONS` in `nodes.py`: a delete removes a slide, a move reorders them). It never passes on the alignment's own "removing slides is not supported" or "an edit cannot move a slide", because the prompt's `rejected_edit` rule would turn that into a `discuss` telling the user it cannot be done. The user's sentence and `error_state.message` keep their text. Not retried, because the model cannot fix them: `edit_without_spec`, `spec_positions_stale`, `insert_rows_changed` and `insert_rows_failed` (the deck's state or a failed write, found after planning). A **describe-only turn never retries**. The second answer is planned from the top and may be another intent, a `discuss` question included; if it is refused too, the turn degrades with the second answer's problems. If the retry call itself raises, the turn is refused with the FIRST answer's refusal (WARNING `architect_retry_failed`); only the persisted-runtime failure family still fails the turn, as on every model call. `rejected_edit` is a payload key of the architect's retry call (`MODEL_PAYLOAD_KEYS["architect"]`, `src/services/agent_model_payload.py`).

**What the user is told, and when.**
- *The architect's message waits.* A `build` or `edit` message is said (emitted and saved) only after the plan has passed every check and the rows are laid out (`_say_architect_message`), just before the deck-level re-review notice. `discuss`, `ask_data` and `confirm_design_contract` still say theirs straight away. On any refusal only the refusal is said and the model's own message is never shown.
- *The refusal sentence* for operations problems is "I couldn't apply that edit, so nothing in the deck has changed: …", with one clause per problem in the user's slide numbers (`_operations_rejected`); `error_state.message` carries the model-facing details in positions.
- *The refusal note.* The refusal row is saved as an `llm_response` with `metadata={"architect_refusal": {"code", "problems"}}` (`_degrade_edit`). `_conversation` replays that row as the assistant turn followed by a `system` turn ("The edit above was NOT applied; nothing in the deck changed. It was rejected because: …"), so next turn the architect reads the reason, not its own apology, and does not resend the same plan. Problems in message metadata are returned by the poll API; they carry codes, positions and details only.
- *Blank slides.* A blank entry the edit did not produce (not in `rebuild`) is never built or re-judged (N1, below). The "Slide N is still blank, so I left it as it is" notice fires for each blank the user's message named whose persisted position is neither the `position` of any operation nor the `after_position` of an insert or move: an anchor is a place, not a fill request. It is said after the deferred message.

**The row writer** (`SlideWriter.apply_slide_layout`, `src/api/services/slide_repository.py`) generalises the old pending-slide shift. `layout[i]` is the index into the current rows (position order) that lands at new index `i`, or `None` for a Pending Slide; a row index that is absent is deleted. The node maps the plan's persisted positions to row indices (the rows are in position order and, past the persisted-spec guard, at the persisted spec's positions). It runs in `architect_node` after every degrade decision and before `classify_spec_change`, on every edit turn with a changed layout that is not describe-only; builders land by position, so laying out later would interleave with them. One `get_db_session()` transaction:
1. Re-read the rows. `[(slide_id, content_hash)]` in position order must equal `expected_rows`, the list the node read at the top. Rows that exist while `expected_rows` is empty (the top read swallows errors and returns `[]`), a missing deck row, or any other mismatch raises `SlideRowsChangedError`. A deck with no rows (described, not yet built) takes only the spec and version, and its layout must be all `None`.
2. Snapshot each old row (raw column values) and its `SlideAttribution` before any write. The upsert rewrites those ORM objects in place.
3. Lay the rows out through `_lay_out_slide_rows` (a module function in `session_manager.py`), THE shift primitive: the exact old-row-to-new-index map (never the attribution heuristic), `now_dt=None` and `author_fallback=None`, so a kept row keeps its `slide_id`, authorship, `modified_at`, verification record and spec fragment, and a NULL stays NULL. A `None` slot gets `placeholder_slide(PENDING_SLIDE_MESSAGE, text=PENDING_SLIDE_TEXT)` ("New slide — not built yet.") with a fresh `slide_id` and explicit authorship. Rows beyond the new count are pruned, which is how a deleted row goes. `_splice_slide_rows` is the in-order special case, so the manual `SessionManager.insert_slide` shares the one primitive.
4. Set `deck_spec_json` to the canonical spec (its slide count must equal `len(layout)`), bump `version` (every worker's deck cache is invalidated, and a stale client save gets a 409 and refetches) and touch `last_activity`. `slide_count` and `html_content` are not written here.
5. Record one shared-deck mutation, named by `layout_mutation_operation(layout, old_count)`: `insert_slide` when every old index is present in order and some slot is `None`; `delete_slide` when there is no `None`, the kept indices ascend and some are missing; `reorder_slides` when there is no `None`, every old index is present and out of order; `save_deck_slides` for any mix. The identity layout has nothing to write and raises `ValueError`.

A Pending Slide, rather than a gap, keeps rows and spec aligned on every path: a gap would break `_persisted_spec_describes_these_rows` and the polling prefix. An updated or replaced row keeps its identity until its builder overwrites the HTML. A moved or deleted slide is a database change: no HTML is regenerated and no per-slide build or review runs for it. Deck review still runs over the whole deck after an edit that changed it. Write refusals on the operations path use edit-neutral sentences ("The deck changed while I was planning, so I have not made that edit. Nothing has been changed; please ask again." for `insert_rows_changed`; "I could not make that edit, so nothing has been changed. Please try asking again." for `insert_rows_failed`); the spec path keeps its original "added the slide" wording, which `tests/unit/test_architect_insert_slide.py` pins.

**Deck-level changes** (title, audience, purpose, argument, call to action, narrative arc, design contract, resolved data) come in `deck_changes`; an unset field is unchanged. They re-review every slide as on the spec path: `classify_spec_change` returns `design_contract` (every position is rebuilt), `deck_level` (serial re-review of every committed slide, rebuilding the failing ones plus `rebuild`) or `none`. A design-system or slide-style change still goes through `confirm_design_contract` first.

#### The spec path: alignment (edits without operations)

Still used for the cases above. **Alignment** (`src/domain/slide_alignment.py`, pure, no I/O; `tests/unit/test_slide_alignment.py` pins it). `align_slides(old, new)` reads both lists in position order and pairs every persisted slide with one returned slide, keeping the order. The remaining `len(new) - len(old)` returned slides are the inserted ones. It minimises, in order, two costs per pair: 1 if `(purpose, content_brief)` differ, then 1 if any field but `position` differs (`slide_key`). An untouched slide pairs at (0, 0), a neighbour whose only change is `assumes` or `hands_off` at (0, 1), and a rewritten slide at (1, 1). It never guesses. `AlignmentRefused.code` is one of:
- `ambiguous`: more than one pairing is optimal. The usual case is an add plus a rewrite of the slide next to it, which is why this approach could not express "replace slide N with M slides".
- `moves_slides`: the edit moves a slide's spec. Two forms are caught: a revised pair whose returned slide equals a different persisted slide, and an inserted slide equal to a persisted slide whose own pair is revised. A duplicate append (`[A, B, C]` to `[A, B, C, B]`) is not refused.
- `removes_slides`: fewer slides than the deck has.

The result is reported in both numberings. `inserted` and `revised` are the returned spec's own `SlideSpec.position` values. `inserted_indices` and `revised_indices` are indices in position order, which is the canonical numbering once the node re-stamps. `old_to_new_index` maps each persisted position to its index. The equal-length path uses `revised` (positions), which equals the old positional `changed` on any deck, gapped included. The insertion path re-stamps the spec to `0..m-1` and uses the indices. A returned list that is out of position order is read in position order, with an INFO log. Equal-length edits are aligned too: one that turns a slide into an exact copy of another is refused as `moves_slides`.

A refused spec-path turn degrades to `discuss` with the code in `error_state` (after the one retry above). Nothing is written but the chat lines: rows, spec and version are unchanged.

| Code | Cause |
| --- | --- |
| `edit_insert_ambiguous` | Alignment `ambiguous`. The message asks for the add first, then the other change. |
| `edit_spec_moves_slides` | Alignment `moves_slides`. |
| `edit_spec_positions_changed` | A shorter spec, or an equal-length one with other positions (`removes_slides` falls back to it). |
| `insert_rows_changed` | `SlideRowsChangedError` from the shift: the rows are not the ones the architect planned against (for example a UI edit during planning). |
| `insert_rows_failed` | Any other failure of the shift. A persisted runtime failure is re-raised instead. |

A spec with duplicate positions never reaches the node: the runtime's parser rejects it and the turn ends with an error, not a refusal. The binding check (`invalid_slide_type_binding`) runs before the alignment, as on any edit.

**Targets on the spec path.** On an insertion turn, `target_positions` is exactly the inserted and revised slides, in the canonical numbering. The model's own targets are mapped through the re-stamp and compared; a difference logs WARNING `insert_targets_disagree` and is not honoured. The #313 `edit_ignores_references` guard is skipped on an insertion turn, because a named slide is the anchor, not a target. Equal-length edits keep the model's targets plus the revised positions. The shift runs through `SlideWriter.insert_pending_slides`, the pending-slide special case of `apply_slide_layout`, with the same transaction and `insert_slide` mutation.

**Failure guarantee** (both paths).
- *A refusal, or a failed or stale layout:* nothing is written. Nothing is applied unless the whole list checks out.
- *After the layout:* rows `0..m-1` equal the spec positions, and each new position holds a Pending Slide.
- *A new slide's build fails or is rejected:* `_placehold_failed_position` replaces the Pending Slide with the failed placeholder and posts a chat notice. Every other slide is untouched.
- *The turn dies after the layout* (for example a re-raised non-transient `PersistedRuntimeError`): the Pending Slide stays and its copy is still true. The next turn sees rows matching the spec, so an edit that targets the new slide builds it from its brief. `slide_count` and `html_content` stay stale until the next post-commit deck-level write, which is the deck reviewer's; and the client keeps its mid-turn view until reload.
- *The pre-fan-out deck-level write fails:* rows and spec are already aligned, because the spec was written in the layout's transaction. The turn records `deck_level_write_failed` as today.
- *Version:* a turn that changes the layout bumps `deck.version` twice, once in the layout and once in the pre-fan-out write.
- *Save points:* one per message (graph turns get exactly one from `chat_service`), so the whole list is one undo. Restoring an earlier one restores rows and `deck_spec_json` together.
- *Still true of every edit turn:* a UI mutation made after the layout, while builders run, can misplace a landed slide.

No in-process state is added (multi-worker coherence): the writer re-reads the rows inside its own transaction, and the version bump invalidates every other worker's cache.

**Findings and verification follow their slide.**
- On the row path, `get_slide_deck` gives each finding (except a deck-level `-1`) the list index of the row it was read from, not the index stamped when it was minted (`_deck_findings(..., slide_indices=...)`, applied before `_finding_to_camel`). The stored record is not rewritten, and the blob and no-rows paths still project verbatim. This also fixes UI insert, reorder, delete and duplicate.
- `write_slide_verification` treats `position` as a hint, because a layout may have landed since the judge started. The verdict goes to the row at `position` if its HTML hashes to the record's key; else to the one other row whose HTML does; else to `position`, as before. A record with more than one key, or two rows sharing the hash, falls through to `position`.

**A placeholder is judged by its current verdict.** `is_placeholder_verdict(verdict)` (`slide_repository.py`) is stricter than `is_placeholder_record`: the verdict has `error: true` and its keys are a subset of `error` and `message`. The LLM judge's error verdict also sets `error` but carries `score`, `rating`, `explanation` and more, so a judged slide whose judge call failed is not a placeholder. `nodes._holds_placeholder(row)` applies it to the verdict under the row's CURRENT `content_hash`, never the whole record, because a record keeps the history of every hash and a slide rebuilt after being a placeholder would still match. `_write_draft_row` uses it (a Pending or failed position takes the builder's draft, a real slide is never overwritten), and so does `rereview_committed_slides` (a placeholder fails by definition).

**Transports.** No frontend change was needed to deliver an edit. Both transports end in `ChatPanel`'s `complete` case (the polling client emits the same event), which refetches the deck with `api.getSlides` and passes it to `onSlidesGenerated`; `event.slides` (the poll route's `result.slides` on polling) is the same final deck and the fallback. After the edit the refetched rows and spec are contiguous, so the panel (`index + 1`) and SpecView (`position + 1`) agree. `frontend/tests/e2e/agent-insert-slide.spec.ts` pins the SSE end state for an insert. The viewer's New-slide indicator (`slide-viewer.md`) marks and selects an inserted slide. Known limits, each pinned by a test:
- *Mid-turn on SSE:* the new slide's `slide_ready` replaces the old slide at that index until `complete`.
- *Mid-turn on polling:* when the first poll lands before the layout, later polls get the old last slide again at `n` (`slides_since_cursor`) and only the Pending Slide as a revision (`slide_revisions_since`; moved rows keep their `modified_at` because it is attribution). The client shows `[A, B, P, D, D]` until `complete`, whose `result.slides` is the shifted deck. `tests/unit/test_poll_route_across_an_insert.py` pins this at the route.
- *Error path:* an errored turn refetches the deck (`ChatPanel`'s `refetchDeckAfterError`, on an SSE `error` event and on the polling transport's `onError`), so a turn that dies after the layout does not leave the mid-turn view in place. It hands the deck up through `onDeckRefetched`, not `onSlidesGenerated`, so none of the success-path side effects run (see `slide-viewer.md`).

**Two UI limits** (accepted; the change is backend-only; spec §11):
- *No "New" chips on a turn that also deletes.* `frontend/src/components/SlideViewer/newSlides.ts` `diffNewSlides` flags new slides only on pure growth. A baseline id that disappears reads as a replace, so nothing is flagged.
- *A delete- or move-only turn shows the old order until it completes.* No slide is built, so no `slide_ready` event arrives mid-turn. #314 accepted the same limit for inserts.

**Where the new slide goes.** The resolver is unchanged: "after slide 3" still resolves "slide 3" only, an indefinite ordinal ("a final slide") is still unresolved, and "Insert a new slide 3" still resolves the EXISTING slide 3. The prompt carries the placement. The architect reads slide numbers against `slide_numbering` (the deck before the message), and a slide the user names to say where the new one goes is the anchor (`after_position`), not a target. Product rule when the user states no place: the new slide goes where it fits the argument, before a closing or call-to-action slide unless it is itself a closing slide, and the message says where it went. When the user asks for the end, it goes after the last slide. "Expand", "split" and "replace slide N with…" map to `replace`; "rebuild slide N" with no content change is an `update` with the slide's current content. The message names new slides by their number in the revised deck and deleted slides by the number they had.

**A build that is really an add.** A model that answers an add with `build` rebuilds every position in place, and identity and records stay by position, so every slide after the new one is mis-attributed (existing build semantics). `architect_node` logs the WARNING `build_looks_like_insert` when a build's spec aligns as a pure insertion of the persisted spec over committed rows. It is a diagnostic: it changes nothing, and a build the alignment refuses logs nothing and never fails. The eval scores `build` on an add as a failure.

**Evals.** The architect pack scores an operations answer with production's `apply_operations` on the payload's `current_deck_spec`, and composes it into a spec before the judge sees it (`evals/README.md`). Existing `add_slide_*` and `edit_*` references stay `deck_spec`-shaped. The layer-3 tests (`test_rc2_*`, `test_rc9_*`) are live and not run in CI.

**Rollout.** The Graph V1 manifest only seeds a fresh bootstrap (see "Rollout" above). An existing install gets the node behaviour at once, on every release: the deferred message, the retry, the refusal note, and the operations path whenever a model emits `operations`. It keeps its persisted architect prompt, which never asks for operations, until an admin publishes a release carrying the new one, and only new conversations pick that up. Older releases receive the optional output fields in the schema but never use them; everything is additive.

**Limits of this path.**
- An edit without `operations` still cannot delete or reorder slides: the spec path refuses it (`edit_spec_positions_changed`, `edit_spec_moves_slides`), and the one retry tells the model to send it as operations.
- On the spec path, an agent "duplicate slide N", or adjacent identical blank entries, align as `ambiguous`, and the refusal text ("add the slide on its own first") misleads.

#### Inserting a blank slide by hand

A person adds a slide from the viewer (the stage's **New slide** button or a ribbon "+"; see `slide-viewer.md`) with `POST /api/slides`. No model runs and no turn starts. With no `html` the slide is a Blank Slide (`CONTEXT.md`); with `html` it is stored verbatim, after the slide-wrapper check only (the same trust as `update_slide`; only the server-built shell is scanned). A Pending Slide is the agent's placeholder and is built; a Blank Slide is the person's and is left alone. The response is the reloaded deck plus `inserted_slide_id` and `inserted_position` (where it landed), which the viewer uses to select it.

**The blank shell** (`blank_slide_shell(slide_htmls, position)`, `src/domain/deck_spec_slides.py`, pure; `ChatService.insert_slide` calls it with the deck's slides and the clamped landing position). A bare `<div class="slide"></div>` paints only where the deck's ground sits on `.slide`. A pinned design system paints it on a `<section>` wrapper and an unpinned graph deck carries it as an inline `style`, where a bare div is a white box, so the blank copies the deck's own frame:
- *Candidates.* Each slide with a `.slide` element yields one: the chain from the fragment's top-level root down to its first element carrying the `slide` class token, rebuilt with only `class`, `data-label` and `style` (in that order, values verbatim), no other child and no text.
- *Source.* The most common candidate wins, compared as the full serialised shell, style included: on an inline-styled deck every slide has the same tags and classes, so the style is what tells the content ground from a cover. A tie goes to the nearest slide holding a tied candidate, scanning the slides before the landing position (nearest first), then the ones after it, and never slide 0 (the cover) while another slide holds a tied candidate.
- *Safety.* The winner must be a blank row (`is_blank_slide_html`: a `<div>` slide wrapper and nothing else) and pass `scan_html_for_unsafe_patterns`, otherwise the result is the bare `BLANK_SLIDE_HTML`. The winner is judged, not skipped past: an unsafe majority gives the bare div, not the runner-up. `style` is kept verbatim, `url()` included (a brand ground may be an image); the slide CSP enforces at render. An empty deck, or one with no `.slide`, gets the bare div. So does a deck whose slides are `<section class="slide">` roots (Meridian): the shell must be a `<div>` slide, and that design system's CSS paints `.slide` itself.
- *Residuals.* An untouched blank keeps the old design system's classes after a design-system switch: nothing re-derives it (the architect leaves an untouched blank alone, below). A deck whose slides all have distinct frames copies its nearest non-cover slide's frame.

**The writer** (`SessionManager.insert_slide`, `src/api/services/session_manager.py`, the one writer behind the route). One `get_db_session()` transaction, in this order, and nothing is written on any raise (a failed evidence write rolls the whole insert back):
1. *Lock order.* The session and the deck OWNER are resolved, then `_refuse_during_an_arc_review(db, deck_owner)` reads the owner's deck row `FOR UPDATE` first (a no-op on SQLite) and refuses (`ArcReviewInFlightError`) while the arc-review sweeper holds a live claim.
2. *Other-session busy refusal.* A session of this deck other than the requester (the owner's, or any contributor's: `parent_session_id` is the owner) with `is_processing` and a `processing_started_at` younger than `SESSION_LOCK_TIMEOUT_SECONDS` (300 s, naive UTC) raises `DeckBusyError`. The requester's own lock (the route's) does not count. The session rows are read without `FOR UPDATE`: the deck row is already locked, and other writers flush `user_sessions` before it, so locking them here would invert the order. The processing lock has no heartbeat, so a turn running longer than 300 s stops blocking inserts (`acquire_session_lock` uses the same constant as its default, so the two cannot drift).
3. *Validate.* The deck exists, `expected_version` (when sent) is current, the position is not negative, and the mutation context is `insert_slide` on `deck`.
4. *Rows re-read and compared.* `[(slide_id, content_hash)]` in position order must equal `expected_rows`, the rows `ChatService.insert_slide` planned against (read off the cached deck before it builds the new deck on a `copy.deepcopy`), else `SlideRowsChangedError`. A deck with NO rows is first materialised in this transaction by the startup backfill's non-committing core, `_backfill_deck(..., dry_run=False, existing_positions=set())` plus a flush (`backfill_session` commits, so it cannot be used): raw emails and NULL timestamps kept, verdicts migrated from `verification_map`, css, external scripts and head meta lifted into their columns. A refusal after that rolls the materialisation back too. Row-less decks occur at runtime, not only before the startup backfill: `duplicate_session` copies `deck_json` and no rows, so a duplicated deck is row-less until its first write. On this path only the content hashes, in position order, must equal `expected_rows`' hashes. The rows were made from this very blob a moment earlier in the same transaction, so order and hash are exact, but the ids are not: a blob slide with no `slide_id` key gets `slide_{idx}` from `SlideDeck.from_dict` (the cache the caller planned on), while the backfill writes NULL. Comparing ids there would refuse that deck's every insert. After the first insert the deck has rows; their NULL ids reload as NULL, so later inserts take the full comparison and match.
5. *Rows.* `_splice_slide_rows` lays the new slide among the old rows with the exact old-row map and `now_dt=None` / `author_fallback=None`, so every existing slide keeps its `slide_id`, authorship, `modified_at`, verdict and spec fragment. It is the in-order wrapper of `_lay_out_slide_rows`, the shift primitive `SlideWriter.apply_slide_layout` (and so `insert_pending_slides`) uses too, so there is one shift and one row writer. The new slide has a fresh `slide_id`, the current user as author and one explicit `created_at` / `modified_at`.
6. *Spec.* `deck_spec_json` gains a blank entry at the landed index (`spec_json_with_blank_entry`, through `renumber_spec_slides`, the pure core `_rewrite_deck_spec_slides` also uses), re-stamped contiguously from 0. A NULL or unparseable spec, a non-dict, `{}` and a dict with no `slides` list are left alone, so legacy decks still insert; `{"slides": []}` gains the entry; entries of an invalid shape are kept, not destroyed.
7. *Deck columns and evidence.* `title`, `html_content`, `scripts_content`, `slide_count`, `deck_json`, ONE `version` bump, `modified_by` (the new slide's author, when it has one) and `last_activity`; on the rows path css, external scripts and head meta are not touched. One `slide_inserted` usage event (when the route passes `get_current_user()`; see `usage-analytics.md`) and one `insert_slide` shared-deck mutation event whose `object_id` is the new slide's id.

After the commit, `ChatService.insert_slide` invalidates the deck cache (on every exit, so a refused write leaves no ghost slide and a stale-rows 409 heals on the next try), reloads the deck from the database, and writes ONE save point, "Inserted slide N" (the oldest version is evicted at the limit, so a save point per shifted position would delete real history).

**Why not `save_slide_deck`.** It recovers the old-row-to-new-position map with the attribution heuristic, which pairs id-less rows that share HTML in order (a blank inserted before an id-less twin takes the twin's record and fragment). Its round trip through `get_slide_deck` writes SCIM display names back into `created_by` / `modified_by`, and it turns NULL timestamps into "now". The writer above moves rows with the exact map and writes raw column values.

**Refusals.** Nothing is written on any of them.

| Status | Detail | Cause |
| --- | --- | --- |
| 409 | `CONVERSATION_BUSY_DETAIL`: "Something is still running on this deck. Wait for it to finish, then try again." | The route cannot take this session's processing lock (the lock belongs to whoever holds it and is not released), an arc review holds a claim on the deck (`ArcReviewInFlightError`), or another session of the deck is running a turn (`DeckBusyError`). |
| 409 | `DECK_CHANGED_DETAIL`: "The deck changed while the slide was being added. Refresh and try again." | `SlideRowsChangedError`: the rows moved between the viewer's deck and the write (another editor, or a stale worker cache). |
| 409 | `Version conflict: expected N, current is M` | `VersionConflictError`, only when the client sends `expected_version` (the viewer does not). |
| 423 | The editing-lock text | Another user holds the editing lock. |
| 403 | The permission text | The caller lacks CAN_EDIT on the session. |
| 400 | The validation text | No deck, a negative position, or `html` with no slide wrapper. |

**The spec-dirty marker.** The route calls `spec_sync.mark_dirty` only for an insert that carries `html`. A blank insert splices an entry that is already the exact description of the blank, in the same transaction as the rows, so there is nothing for the arc-review sweeper to describe, and no claim opens that would refuse the next insert. `tests/unit/test_spec_sync_placement.py` pins the route table.

**What the architect does with a blank.** A blank entry is one with an empty `purpose` and an empty `content_brief` (`is_blank_slide_spec`; HTML ASCII whitespace counts as empty). The frontend decides the same thing in `frontend/src/services/blankSlide.ts`, and both languages are tested against `tests/fixtures/blank_slide_cases.json`.
- *Filling one.* "Put our pricing on slide 4" resolves to position 3 and is an equal-length edit that revises entry 3, so it is built in place and the reviewed write keeps the `slide_id`. No prompt change: the payload shows the blank entry and `slide_numbering` counts its row.
- *N1: an untouched blank is never built or re-judged on an edit turn.* `_untouched_blank_positions(spec, alignment, inserting)` is the final spec's blank entries that the edit neither added nor revised (`inserted_indices | revised_indices` on an insertion turn, `alignment.revised` otherwise; empty when there is no alignment, so a build turn and the sweeper are outside it). `_drop_untouched_blanks` removes them from the three lists an edit builds from: its targets, the design-contract rebuild-all and the deck-level `rebuild` set. It is entry-based and does not read the row, so a blank someone has since typed into is not rebuilt from an empty brief either. If the user's message named a dropped blank ("fill slide 4" answered with an entry left blank), the turn says so once, with the user's own Slide Number: WARNING `blank_named_but_not_described` and a chat notice, "Slide N is still blank, so I left it as it is. Tell me what to put on it." An insertion turn passes no references, because there a named slide is the anchor.
- *The re-review skip.* `rereview_committed_slides` makes no model call for a blank entry: it is counted in `committed` and in the new `blank` set, never in `reviewed` or `failing`, and `judged_nothing` ignores it. The check runs after the placeholder check, so a Pending Slide at a blank entry (an agent insert) is still placeheld and failing. It also spares a blank on a deck-level change, a deck-level build turn included.
- *N2: what the arc-review sweeper keeps.* Its architect sees the persisted spec and no slide HTML. When the persisted spec still describes the rows, `_description_keeps_what_it_cannot_see` (a) discards a re-description whose position set differs and keeps the persisted spec whole as a deep copy, on every deck (WARNING `describe_spec_positions_changed`), and (b) keeps the persisted entry where the committed row is still a blank row and the persisted entry is still blank (INFO `describe_kept_blank_slides`), because a purpose or brief written for a blank is invention that would later fail a re-review and rebuild it. A blank someone has typed into is no longer a blank row, so describing it is reading and the model's entry stands. The sweeper never rebuilds and writes no findings.
- *The deck reviewer* is not blank-aware. It reads the deck as a whole, so it may mention a blank in its deck-level notes; those are advice in the chat and rebuild nothing.
- *Monolith sessions* have no spec, so the spec splice leaves them alone and N1 and N2 do not run. A blank is a slide the monolith may regenerate; to fill it, select it and ask.
- *A `build` answer* replaces the whole deck by request, blanks included (as in "A build that is really an add" above).

**Known gaps** (recorded, not fixed):
- Update, duplicate, delete and reorder still go through `save_slide_deck`: its heuristic attribution, display names written back, NULL timestamps fabricated, the spec renumbered in a second best-effort transaction (`_rewrite_deck_spec_slides`), no arc-review check, no check for another session's turn, and the cached deck mutated before the write. Moving them onto the pattern above is the follow-up.
- On PostgreSQL an insert that races another writer within milliseconds can deadlock. The insert takes the deck row first, and a writer that flushes slide rows before the deck row takes them in the opposite order; PostgreSQL aborts one and the route answers 500. It is the same pattern as clear and message delete, and a rollback, never corruption.
- A model that fills a blank during an unrelated edit builds it, because the entry is then revised and so touched.

---

## Deck style (graph)

The graph's architect can author a **deck style** that gives the deck a look of its own on top of the brand. Glossary: **Deck style** and **Look** in `CONTEXT.md`. Design in `docs/superpowers/specs/2026-10-29-architect-deck-style-design.md`, which ends with what changed during the build. The sanitiser is `src/domain/deck_style.py` (pure, no I/O).

**What the architect writes.** `DeckSpec.deck_style` is `css` on `dk-` classes plus a `components` catalogue (name, `class_names`, when to use it, example markup). Each slide may carry a `look`, a free-text recipe naming the pieces it uses. The style is part of the persisted spec. Limits: `DECK_STYLE_TARGET_CHARS` 4000, `DECK_STYLE_MAX_CHARS` 10000 (more is dropped), `DECK_STYLE_MAX_COMPONENTS` 12.

**Sanitiser.** `sanitise_deck_style(style, *, design_system_active)` returns `(style or None, notes)`. The style is model-authored CSS inlined in a `<style>` element, so it may only add its own `dk-` pieces.
- Every at-rule is dropped. `:root` is dropped under a design system, and otherwise keeps only `--dk-` properties. The reason is `merge_css`, which keys at-rules by (keyword, prelude) and `:root` by selector, so a deck-style one would replace the template's.
- A selector survives only with a top-level `.dk-` class and descendant or `>` combinators after it.
- Declarations with a remote address (`http:`, `https:`, `//`; scanned after removing tab, LF and CR and reading a backslash as `/`; `data:` URLs exempt) or `expression()` are dropped, as are image functions and nested rules.
- Repeated selectors are coalesced at the last occurrence. Empty rules go, `<style` text never survives, a rebuilt sheet must re-sanitise with no notes, and notes are capped at 200 characters.
- Unchanged input comes back as the same object. Blank, or over the cap, gives `None`.
- `architect_node` sanitises every answer before planning (`_sanitise_answer_deck_style`) with the flag of the contract it will commit, so build, edit, retry and full-spec paths share one gate. On a build, a style that comes back `None` is logged and the deck builds without one. On an edit, a dropped `deck_changes.deck_style` refuses the edit (`invalid_deck_changes`, naming the notes) and the one retry is told why.

**CSS order and where it is written.** Tokens, then the template block, then the deck style. It is written twice, in that order: the pre-fan-out write (`deterministic_css` plus the deck style's CSS into `deck.css`, with `emitted_style_blocks` carrying the template block then the deck style as CSS text, not `<style>` markup), and the post-commit aggregate (`aggregate_deck_css`), which re-merges the blocks. Builders' slides render with the style from the first `slide_ready`, and a restyle rewrites `deck.css` from the current style, so a removed piece does not linger.

**Payload keys.** `deck_style` (the style's dump, when present) goes on the builder, build_reviewer, fixer and fix_reviewer payloads and on the re-review of committed slides. `deck_style_context` goes on the architect: the design tokens and template classes it must not restate. The `deck_style` key is optional in the model-payload fixtures, so a deck without a style sends the payload it always did.

**Edits.**
- A slide edit builds the new slide with the current style.
- A deck-style-only edit (`deck_changes.deck_style`) rebuilds no slide and rewrites `deck.css`. It is not a narrative change, but the deck (arc) review still runs, one call per restyle.
- Drop check: if a restyle removes a class that a kept slide still uses, the edit is refused (`deck_style_drops_used_class`) with a sentence naming the slides and the class, unless those slides are updated in the same edit. It runs only when there is a prior and a new style and the contract is unchanged. Template-owned classes and `slide` are excluded; every other class counts.
- A full-spec edit, and a describe-only answer with intent `build`, carry the persisted style forward when the contract is unchanged. A null `deck_changes.deck_style` means unchanged, so an edit cannot remove a style.
- A style carried into a changed contract (an operations edit with no new style) is re-sanitised under the committed contract's flag, and committed as absent if nothing survives.
- A design-contract change rebuilds every slide, so the architect writes a fresh style with it.

**Old decks.** A deck with no style builds, edits and renders as before: no payload key, no extra CSS. The architect may add one when the user asks for a style change or a rebuild. Slides built earlier do not use its classes.

**Prompts and model.** The architect, builder, fixer and fix_reviewer prompts changed. The build reviewer prompt did not: it is a transition source in the promote step, so editing it would break the v1 to v2 upgrade on released installs. It receives `deck_style` but has no rule for it, which is a follow-up. The builder now runs on `system.ai.claude-sonnet-5-5`: better on the deck-style cases, but about 1.6 to 1.8 times slower and 2.8 times the cost per slide (numbers in `evals/README.md`). The production workspace must offer that endpoint with non-zero rate limits.

**Rollout.** Node code ships with the app: the sanitiser, payload keys, CSS writes and edit checks apply on every install at once. The new prompts and the builder model are in the Graph V1 manifest, which only seeds a fresh bootstrap, so an existing install keeps its persisted prompts and models until an admin publishes a graph release carrying them (as in "Graph Path: Slide Numbers and Positions"). Until then its architect writes no style and its decks stay as they were.

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
- [LLM as Judge Verification](llm-as-judge-verification.md) -- Slide verification (MLflow default; optional Direct) and **agent** MLflow span policy when Direct (`mlflow_agent_spans.py`)
- [Database Configuration](database-configuration.md) -- Schema details including `verification_map` for content-hash-based verification persistence
- [Real-Time Streaming](real-time-streaming.md) -- SSE events and conversation persistence
- [Multi-User Concurrency](multi-user-concurrency.md) -- session locking and async handling
- [Slide Parser & Script Management](slide-parser-and-script-management.md) -- HTML parsing flow
- [Slide Editing Robustness](slide-editing-robustness-fixes.md) -- Deck preservation, LLM validation, canvas deduplication, JS validation
- [Save Points / Versioning](save-points-versioning.md) -- Complete deck state snapshots with preview and restore
- [Google Slides Integration](google-slides-integration.md) -- OAuth2 flow, encrypted credential storage, LLM converter
