# Backend System Overview

This guide explains how the FastAPI/LangChain backend works, how it serves the frontend, and the concepts you need to extend or automate it. Treat it as a living reference for both engineers and AI agents.

---

## Stack & Entry Point

- **Runtime:** Python 3.11+, FastAPI (ASGI) with Uvicorn/Gunicorn, packaged under `src/`.
- **Core libs:** LangChain (tool-calling agent), Databricks `WorkspaceClient`, MLflow for tracing, BeautifulSoup for HTML parsing.
- **Entry:** `src/api/main.py` instantiates FastAPI, wires CORS, and registers `chat` + `slides` routers under `/api`.
- **Process lifecycle:** `lifespan` context logs startup/shutdown; there is no background scheduler yet.

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

- **Routers** (`src/api/routes/*.py`) validate HTTP payloads and map 1:1 to frontend calls.
- **`ChatService`** (`src/api/services/chat_service.py`) is a process-wide singleton that owns the `SlideGeneratorAgent`, current `SlideDeck`, and raw HTML copy. It is the sole bridge between REST handlers and LangChain.
- **`SlideGeneratorAgent`** (`src/services/agent.py`) wraps LangChain’s tool-calling agent, glues prompts, tool schemas, Databricks auth, MLflow tracing, and session memory.
- **`SlideDeck` / `Slide` models** (`src/models/...`) parse, manipulate, and serialize slides so both chat and CRUD endpoints share the same representation.

---

## API Surface (Contracts Shared with Frontend)

| Method | Path | Purpose | Backend handler |
| --- | --- | --- | --- |
| `POST` | `/api/chat` | Generate a new deck or edit contiguous slides | `routes/chat.send_message` |
| `GET` | `/api/health` | Lightweight readiness probe | `routes/chat.health_check` |
| `GET` | `/api/slides` | Return the current cached `SlideDeck` | `routes/slides.get_slides` |
| `PUT` | `/api/slides/reorder` | Persist drag/drop order | `routes/slides.reorder_slides` |
| `PATCH` | `/api/slides/{index}` | Update HTML for a single slide | `routes/slides.update_slide` |
| `POST` | `/api/slides/{index}/duplicate` | Clone a slide in-place | `routes/slides.duplicate_slide` |
| `DELETE` | `/api/slides/{index}` | Remove a slide (cannot delete last) | `routes/slides.delete_slide` |

All responses conform to the Pydantic models in `src/api/models/responses.py`. Structure mirrors what the frontend expects (`messages`, `slide_deck`, `raw_html`, `metadata`, optional `replacement_info`).

---

## Request Lifecycle

1. **FastAPI validation**  
   - Bodies deserialize into `ChatRequest`, `SlideContext`, or CRUD request models in `src/api/models/requests.py`.  
   - `SlideContext` enforces contiguous indices and maps 1:1 with the frontend’s selection ribbon.

2. **ChatService orchestration**  
   - Singleton created lazily via `get_chat_service()`.  
   - Maintains a single `session_id` today (Phase 1). Future multi-session support is planned (see `PHASE_4_MULTI_SESSION.md`).

3. **Agent execution**  
   - `SlideGeneratorAgent.generate_slides()` stitches the user prompt, optional `<slide-context>...</slide-context>` block, chat history, and passes everything to LangChain’s `AgentExecutor`.  
   - Genie tool calls automatically reuse the session’s `conversation_id`, so the LLM never fabricates IDs.

4. **Post-processing**  
   - **New deck:** Raw HTML is parsed into a `SlideDeck` (`SlideDeck.from_html_string`). Canvas/script integrity is checked before caching.  
   - **Edits:** Replacement info from `_parse_slide_replacements()` merges into the cached deck via `_apply_slide_replacements()`, ensuring Chart.js script blocks stay aligned with canvas IDs.

5. **Response**  
   - `ChatService` returns the message transcript, latest deck snapshot (or `None`), raw HTML for debugging (also used by the frontend’s Raw HTML view), and metadata (latency, tool calls, mode).

---

## Core Modules & Responsibilities

| Module | Responsibility | Key Details |
| --- | --- | --- |
| `src/api/main.py` | App assembly | Registers routers, CORS, health root. |
| `src/api/routes/chat.py` | `/api/chat`, `/api/health` handlers | Injects `ChatService`, translates exceptions into `HTTPException`. |
| `src/api/routes/slides.py` | Slide CRUD endpoints | Thin wrappers that operate on `ChatService.current_deck`. |
| `src/api/services/chat_service.py` | Stateful orchestration | Holds agent, session id, current deck + raw HTML, applies replacements, validates canvas scripts. |
| `src/services/agent.py` | LangChain agent | Configures Databricks model, Genie tool, prompts, MLflow spans, BeautifulSoup parsing, session memory. |
| `src/services/tools.py` | Genie wrappers | Starts conversations, retries query attachments, converts tabular responses to JSON. |
| `src/models/slide*.py` | Deck primitives | Provide parsing, reordering, cloning, script bookkeeping, serialization. |
| `src/config/*.py` | Settings + Databricks client | Merge YAML + env, manage singleton `WorkspaceClient`. |
| `src/utils/html_utils.py` | Canvas/script analysis | Extracts `canvas` ids from HTML and JS for validation. |
| `src/utils/logging_config.py` | Structured logging | JSON/text formatters, RotatingFileHandler, request-id filters. |

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

- **Model:** `ChatDatabricks` configured via `config/config.yaml` and exposed through `get_settings().llm`.
- **Prompting:** System prompt + optional slide-editing addendum loaded from `config/prompts.yaml` and injected via `ChatPromptTemplate`. Chat history is pulled from `ChatMessageHistory`.
- **Tools:** Currently only `query_genie_space`, exposed as a LangChain `StructuredTool` with a Pydantic schema. The tool automatically looks up the session’s Genie `conversation_id`, preventing hallucinated IDs.
- **Sessions:** `SlideGeneratorAgent.sessions` holds `chat_history`, `genie_conversation_id`, `metadata`; `ChatService` uses a single session for now but APIs are ready for multiple.
- **Observability:** MLflow spans wrap each generation. Attributes include mode (`generate` vs `edit`), latency, tool call counts, Genie conversation ID, and replacement stats.

---

## Slide Editing Pipeline

1. Frontend sends `slide_context = { indices, slide_htmls }`.
2. Agent prepends a `<slide-context>…</slide-context>` block to the human message so the LLM edits in place.
3. `_parse_slide_replacements()` parses the LLM’s HTML into discrete slide blocks and collects:
   - `replacement_slides`, `replacement_scripts`
   - `start_index`, `original_count`, `replacement_count`, `net_change`
   - Canvas IDs referenced inside HTML or `<script data-slide-scripts>` blocks
4. `_apply_slide_replacements()` removes the original segment, inserts the new slides, and rewrites script blocks so every canvas gets exactly one Chart.js initializer.
5. `replacement_info` is bubbled back to the frontend where `ReplacementFeedback` displays summaries like “Expanded 1 slide into 2 (+1)”.

If the agent’s HTML lacks `.slide` wrappers, has out-of-range indices, or references canvas IDs without scripts, the request fails fast with descriptive errors to keep state consistent.

---

## Configuration, Secrets & Clients

- **Settings loading** (`src/config/settings.py`):
  - YAML files in `/config` define defaults (LLM endpoint, Genie metadata, API options, logging settings, MLflow experiments).
  - Environment variables override secrets (`DATABRICKS_HOST`, `DATABRICKS_TOKEN`, `.env` file).
  - `get_settings()` caches the merged `AppSettings`. Use `reload_settings()` during local development or tests.
- **Databricks client** (`src/config/client.py`):
  - Thread-safe singleton `WorkspaceClient` that prefers configured profile → explicit host/token → environment fallback.
  - `initialize_genie_conversation()` and `query_genie_space()` both consume this singleton to avoid reconnecting per request.

---

## Logging, Tracing & Testing

- **Logging:** `src/utils/logging_config.setup_logging()` sets JSON or text output, attaches rotating file handlers, and lowers noisy dependency log levels. Every router/service log call already uses structured `extra={...}` fields for easier filtering.
- **MLflow traces:** Each agent turn runs inside `mlflow.start_span("generate_slides")`, recording latency, tool usage, session info, and (for edits) replacement counts. Ideal for operations dashboards.
- **Tests:** `tests/unit` and `tests/integration` target agents, config loaders, HTML utilities, and API-level interactions. When adding features, mirror new code with a matching test file (e.g., `tests/unit/test_<module>.py`).

---

## Extending the Backend

1. **New endpoints:** Add a router under `src/api/routes`, define Pydantic request/response models, and call into `ChatService` or purpose-built services rather than touching the agent directly.
2. **Multiple sessions:** Thread `session_id` through every request. `ChatService` and agent classes already accept a session parameter; you mainly need a persistence strategy.
3. **Additional tools:** Add functions to `src/services/tools.py`, wrap them with `StructuredTool`, and include them in `_create_tools()`. Remember to update prompts so the LLM knows when to invoke them.
4. **Observability hooks:** Reuse `mlflow.start_span` or extend `logging_config` if you introduce new long-running operations (e.g., batch generation).
5. **Integration with the frontend:** Any change that affects `ChatResponse` or slide deck structure must be reflected in `frontend/src/types` and `docs/technical/frontend-overview.md`.

Keep this doc synchronized whenever you add new modules, features (e.g., session-aware storage, streaming responses), or change API contracts so both humans and AI agents stay aligned.

