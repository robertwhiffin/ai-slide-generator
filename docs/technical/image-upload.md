# Image Upload & Management – Storing, serving, and embedding user images in slides

Images live entirely in PostgreSQL/Lakebase (no external storage). The agent references images via `{{image:ID}}` placeholders; post-processing substitutes them with base64 data URIs before the frontend receives HTML. A separate **image guidelines** field on slide styles controls automatic image injection without per-request tool calls.

---

## Stack & Entry Points

| Layer | Technology | Entry Point |
|-------|-----------|-------------|
| API | FastAPI | `src/api/routes/images.py` — `/api/images/*` |
| Service | Python (Pillow for thumbnails) | `src/services/image_service.py` |
| Agent tool | LangChain StructuredTool | `src/services/image_tools.py` |
| Placeholder substitution | Regex post-processor | `src/utils/image_utils.py` |
| Database model | SQLAlchemy | `src/database/models/image.py` |
| Frontend library | React + TypeScript | `frontend/src/components/ImageLibrary/` |
| Frontend types | TypeScript | `frontend/src/types/image.ts` |
| AI image generation | Responses API `image_generation` tool via the AI Gateway | `src/services/image_generation.py`, `src/api/routes/image_generation.py` |
| Architect image tool | `AgentTool` | `src/services/agent_tools/image_generation_tool.py` |

---

## Architecture Snapshot

```
User
  ├── Upload image(s) ──► POST /api/images/upload (one per file)
  │                             │
  │                        image_service.upload_image()
  │                        (validates type, size, unique name)
  │                             │
  │                        ┌────▼────┐
  │                        │Lakebase │  image_assets table
  │                        │ (bytea) │  raw bytes + 150x150 thumbnail
  │                        └────┬────┘
  │                             │
  ├── Chat message ──► ChatService
  │                         │
  │                    _replace_slide_htmls_from_cache()
  │                    (strips base64 from slide_context before LLM call)
  │                         │
  │                    LangChain Agent
  │                    ├── search_images tool (metadata only)
  │                    └── outputs {{image:ID}} placeholders
  │                         │
  │                    _substitute_images_for_response()
  │                    (regex replaces → base64 data URIs at API boundary)
  │                         │
  └── Receives HTML ◄──────┘
       with embedded images
```

---

## Key Concepts / Data Contracts

### ImageAsset model (`src/database/models/image.py`)

```python
class ImageAsset(Base):
    __tablename__ = "image_assets"

    id              = Column(Integer, primary_key=True)
    filename        = Column(String(255))     # "{uuid}.{ext}"
    original_filename = Column(String(255))   # User's original name
    mime_type       = Column(String(50))       # image/png, image/jpeg, image/gif, image/svg+xml
    size_bytes      = Column(Integer)
    image_data      = Column(LargeBinary)      # Raw bytes (max 5MB)
    thumbnail_base64 = Column(Text)            # "data:image/jpeg;base64,..." or None for SVG
    tags            = Column(...)             # JSON array; JSONB on PostgreSQL, JSON on SQLite (tests)
    description     = Column(Text)
    category        = Column(String(50))       # 'branding', 'content', 'background', 'ephemeral'
    uploaded_by     = Column(String(255))
    is_active       = Column(Boolean)          # Soft delete
```

Implementation uses `JSON().with_variant(JSONB(), "postgresql")` so tag search uses native `@>` on PostgreSQL/Lakebase. Existing databases with `tags` still typed as `json` are upgraded to `jsonb` automatically at startup (`_migrate_image_assets_tags_json_to_jsonb` in `src/core/database.py`).

**Invariants:**
- `image_data` stores raw bytes; base64 encoding happens on read
- `original_filename` must be unique among active images (case-insensitive); soft-deleted images free their name for reuse
- `thumbnail_base64` is a complete data URI ready for `<img src=...>`; `None` for SVGs (they scale natively)
- `category = "ephemeral"` means paste-to-chat images not saved to library (excluded from default library view)
- No foreign key to profiles — images are independent library items shared across all profiles

### Placeholder format

The agent outputs `{{image:ID}}` in two contexts:

```html
<!-- HTML img tag -->
<img src="{{image:42}}" alt="Company logo" />

<!-- CSS background -->
background-image: url('{{image:42}}');
```

Post-processing converts to:

```html
<img src="data:image/png;base64,iVBOR..." alt="Company logo" />
```

### Image guidelines (slide style field)

The `SlideStyleLibrary` model has an `image_guidelines` column (`Text, nullable`). When populated, this text is injected into the agent's system prompt as an `IMAGE GUIDELINES` section. The agent uses referenced image IDs directly without calling `search_images`. When empty, the agent only searches for images when the user explicitly asks.

---

## Component Responsibilities

| File | Responsibility | Key Details |
|------|---------------|-------------|
| `src/database/models/image.py` | ORM model | `ImageAsset` — bytea storage, JSON tags, soft delete |
| `src/services/image_service.py` | Upload, search, retrieve, delete | Validation (5MB, allowed types), Pillow thumbnails, base64 encoding |
| `src/services/image_tools.py` | Agent tool wrapper | `search_images` — returns metadata JSON, never base64 |
| `src/utils/image_utils.py` | Placeholder substitution | Regex `{{image:(\d+)}}` → `data:{mime};base64,...` |
| `src/api/routes/images.py` | REST API | CRUD + base64 data endpoint |
| `src/api/services/chat_service.py` | Integration glue | `_replace_slide_htmls_from_cache` strips base64 from inbound slide_context; `_substitute_images_for_response` adds base64 at API boundary; `_inject_image_context` for attached images |
| `src/services/agent.py` | Prompt construction | Conditional IMAGE GUIDELINES section; `search_images` tool binding |
| `src/core/settings_db.py` | Settings loader | Extracts `image_guidelines` from selected slide style |
| `src/api/routes/settings/slide_styles.py` | Slide style CRUD | `image_guidelines` field in schemas and handlers |
| `frontend/src/components/ImageLibrary/ImageLibrary.tsx` | Image gallery | Grid view, multi-file drag-drop upload, category filter, search |
| `frontend/src/components/ImageLibrary/ImagePicker.tsx` | Modal picker | Wraps ImageLibrary with select callback |
| `frontend/src/components/ChatPanel/ChatInput.tsx` | Paste-to-chat | Clipboard paste, upload, attach preview, "Save to library" toggle |
| `frontend/src/components/config/SlideStyleForm.tsx` | Style editor | Separate Image Guidelines Monaco editor + Insert Image Ref button |
| `frontend/src/types/image.ts` | TypeScript types | `ImageAsset`, `ImageListResponse`, `ImageDataResponse` |
| `frontend/src/services/api.ts` | API client | `uploadImage`, `listImages`, `updateImage`, `deleteImage` |

---

## State / Data Flow

### 1. Image upload

1. User drops/selects one or more files in ImageLibrary (multi-file drag-drop and file picker supported), or pastes into ChatInput
2. Frontend validates each file client-side (type + size), then sends one `POST /api/images/upload` per file (sequential, with progress indicator "Uploading 2 of 5...")
3. `image_service.upload_image()` validates type, size, and **unique filename** (case-insensitive check against active images; rejects duplicates with 400)
4. Pillow generates 150x150 thumbnail (PNG for RGBA, JPEG otherwise; `None` for SVG)
5. Raw bytes + thumbnail + metadata saved to `image_assets` table
6. Response returns `ImageResponse` with thumbnail for immediate display
7. Per-file errors (validation failures, duplicate names) are collected and displayed together in the UI

### 2. Paste-to-chat

1. User pastes image into ChatInput textarea (`onPaste` handler)
2. Frontend uploads via `api.uploadImage()` with `save_to_library` flag
3. If `save_to_library = false`, category is overridden to `"ephemeral"`
4. Uploaded `ImageAsset` added to `attachedImages` state
5. On send, `image_ids` array included in `ChatRequest`
6. `ChatService._inject_image_context()` appends image metadata to the user message text

### 3. Agent uses images in slides

1. If the frontend sends `slide_context` (for edits), `ChatService._replace_slide_htmls_from_cache()` swaps the frontend's base64-substituted HTML with lightweight `{{image:ID}}` placeholder versions from the backend deck cache — this prevents megabytes of base64 from entering the LLM prompt
2. Agent receives message (possibly with `[Attached images]` context)
3. Agent calls `search_images` tool if user explicitly requested images
4. Tool returns JSON metadata (id, filename, description, tags, usage example) — **never base64**
5. Agent outputs HTML with `{{image:ID}}` placeholders
6. `ChatService._substitute_images_for_response()` converts placeholders to base64 data URIs at the API response boundary
7. Backend deck cache always stores the placeholder form; base64 only exists in API responses
8. Frontend receives self-contained HTML with embedded images

### 4. Image guidelines (branding flow)

1. Admin edits a slide style, adds image guidelines in the dedicated Monaco editor (e.g. `Place {{image:5}} as logo in top-right of every slide`)
2. `image_guidelines` saved to `SlideStyleLibrary.image_guidelines` column
3. On settings load, `settings_db.load_settings_from_database()` extracts `image_guidelines` into `settings.prompts["image_guidelines"]`
4. `agent._create_prompt()` checks if `image_guidelines` is non-empty
5. If set: appends `IMAGE GUIDELINES` section to system prompt with the verbatim text; agent uses pre-validated IDs directly
6. If empty: agent only uses `search_images` when user explicitly requests images
7. After generation, `substitute_image_placeholders()` resolves all `{{image:ID}}` references regardless of source

---

## Interfaces / API Table

### Image API (`/api/images`)

| Method | Path | Purpose | Request | Response |
|--------|------|---------|---------|----------|
| POST | `/upload` | Upload image | Multipart: file, tags (JSON), description, category, save_to_library | `ImageResponse` (201) |
| GET | `/` | List/search images | Query: category, query | `ImageListResponse` |
| GET | `/{id}` | Get image metadata | — | `ImageResponse` |
| GET | `/{id}/data` | Get full base64 data | — | `ImageDataResponse` |
| PUT | `/{id}` | Update metadata | JSON: tags, description, category | `ImageResponse` |
| DELETE | `/{id}` | Soft delete | — | 204 |

### Slide Style API (image_guidelines field)

The `image_guidelines` field is included in all slide style CRUD operations at `/api/settings/slide-styles`. See `src/api/routes/settings/slide_styles.py`.

### Agent tool

```python
search_images(
    query: Optional[str],      # Search by filename or description
    category: Optional[str],   # 'branding', 'content', 'background'
    tags: Optional[List[str]], # Filter by tags
) -> str                       # JSON: {message, images: [{id, filename, description, tags, category, mime_type, usage}]}
```

---

## AI image generation

Generated images are ordinary library rows (`ImageAsset`): tagged `ai_generated` plus the model
and the preset, with the prompt as the description. Anything that takes `{{image:TOKEN}}` can use
them.

### Switches

Both are read on every request and every turn, never cached on the server:

- the env flag `TELLR_IMAGE_GENERATION_ENABLED`: on unless set to `0`, `false`, `no` or `off`;
- the admin setting `image_generation_enabled` (`workspace_settings`, Admin > Connections): on
  unless a row says off.

`image_generation.generation_available(db)` is the one gate: the routes and the graph both call it.
The frontend asks `GET /api/images/generate/available` through one cached probe
(`hooks/useImageGenerationOptions.ts`, 5-minute TTL), which the admin switch invalidates.

### The model call (`src/services/image_generation.py`)

- **Presets.** `background` (2048x1152 JPEG), `illustration` (1536x1024 JPEG), `icon_png`
  (1024x1024 transparent PNG) and `icon_svg` (SVG, GPT Image 2.6 only). The default model is
  `gpt-image-2.6-flare` at `medium`.
- **The request.** `ImageGenerator.generate(prompt, preset_id, model=None, quality=None, *,
  timeout_s=None)` drives the Responses API `image_generation` tool through
  `gateway_openai_client`, with `tool_choice` forced.
  - The orchestrator is `system.ai.gpt-5-4-nano` (override: `TELLR_IMAGE_GEN_ORCHESTRATOR_MODEL`).
  - SDK retries are off, because a retry is a second paid image.
  - `timeout_s` can only shorten the preset's timeout.
- **Streaming.** Rasters stream, because the Gateway rejects non-streamed responses over 640 KB.
  SVG is read non-streamed and passes `sanitize_svg`.
- **Output.** `fit_to_library` keeps output under the 5 MB cap. Edits flatten a transparent source
  onto white first.

### Image Library: Generate and Edit with prompt

`POST /api/images/generate` and `POST /api/images/{token}/edit` start an owner-scoped job and
return 202; the browser polls `GET /api/images/generate/jobs/{job_id}`, because the Apps proxy cuts
requests at 60 s. Jobs reuse `export_jobs` with `session_id = image-generation:<owner>`.

### Chat: the architect's `generate_image` tool

The graph engine's architect gets the tool on every turn that is not describe-only while the gate is
open. It rides alone, or beside the turn's Gateway MCP tools on one toolset. All usage guidance is
in the tool's description, not the architect's prompt:

- an open-ended ask means 3 options, a `discuss` intent, nothing placed;
- an exact ask means 1 image, placed in the same answer by putting its reference in that slide's
  `content_brief`.

**Limits, enforced in code:**

- 2 calls, 3 images per call and 6 images per turn;
- 240 s per turn, clipped to the 700 s turn deadline;
- no call starts with under 30 s left;
- a process-wide semaphore of 6 slots, taken without blocking;
- images in one call are generated in parallel on a module-level pool, and a straggler past the
  wall clock is abandoned before it saves;
- failure text is fixed ("busy", "not allowed", "did not finish in time", "could not be
  generated"), never the exception's.

**Saving.** Images are saved as the turn's user, with the tags `chat`, plus `chat_option` when
there are several.

**What a turn records** (`src/services/graph/nodes.py`, `_ImageToolPass`):

- **State.** Two turn-scoped keys: `generated_images` (`{token, kind, option, prompt,
  for_slide}`) and `image_tool_usage` (`{calls, images, seconds}` per pass). Options are numbered
  across the turn.
- **Reply metadata.** The architect's reply row and its ASSISTANT event carry
  `metadata.generated_images` in the shared shape from `src/utils/generated_images.py`, with
  `slides` as the 1-based slides of the committed spec that reference each image.
  `SessionManager.msg_to_stream_event` forwards it, sanitised, to polling clients.
- **Image-reference safety.** When the turn generated images, the architect's references are
  reconciled and the builders' allow-list holds the new tokens, as on a Gateway turn. A dropped
  reference is reported as "A generated image couldn't be placed on slide N."
- **Next turn.** `_conversation` replays a `system` note after such a reply, listing each option's
  exact reference, so "use the second one" works.
- **Progress.** Each call emits a `TOOL_CALL` event with top-level `tool_name="image_generation"`
  and `tool_input={kind, count}`, and writes a `tool_call` row.

**Frontend.**

- **Options card.** `GeneratedImagesCard` renders under the reply: thumbnails, "On slide N" badges,
  "Use this" on unplaced options, and Regenerate.
- **Card actions.** Both send ordinary chat messages. Use attaches the token (`image_ids`), so
  `ChatService` names it in the message. The graph ignores `slide_context`, so every message names
  the slide in its text.
- **Entry points.** The chat input's **Generate image** button and the stage's **Generate image for
  this slide** both open `GenerateImageRequestDialog`, which composes the request. Both show only
  when the feature is available and the deck is not legacy.

**Not covered.** The legacy (monolith) engine.

---

## Operational Notes

### Validation constraints

| Constraint | Value | Enforced in |
|-----------|-------|-------------|
| Max file size | 5MB | `image_service.py` + `ChatInput.tsx` + `ImageLibrary.tsx` |
| Allowed MIME types | png, jpeg, gif, svg+xml | `image_service.py` + `ImageLibrary.tsx` |
| Unique filename | Case-insensitive among active images | `image_service.py` (server-side) |
| Thumbnail size | 150x150 | `image_service.py` |

### Error handling

- **Invalid type/size**: `ValueError` raised in `image_service`, returned as 400 from API
- **Duplicate filename**: `ValueError` raised in `image_service`, returned as 400 from API; frontend shows per-file error messages
- **Image not found**: 404 from API; placeholder substitution logs warning and leaves `{{image:ID}}` intact
- **Paste upload failure**: Error shown in ChatInput UI, does not block message sending
- **Agent uses invalid ID**: Placeholder stays in HTML (graceful degradation)
- **Multi-file upload partial failure**: Successfully uploaded files are kept; per-file errors are collected and displayed together

### Category semantics

| Category | Purpose | Visible in library? |
|----------|---------|-------------------|
| `branding` | Logos, brand assets | Yes |
| `content` | User-uploaded content images | Yes |
| `background` | Slide backgrounds | Yes |
| `ephemeral` | Paste-to-chat (not saved) | No (filtered by default) |

### Logging

- Upload success/failure logged in `image_service.py`
- Placeholder substitution warnings in `image_utils.py`
- Attached image IDs logged in `chat_service.py`

---

## Extension Guidance

- **Adding new image categories**: Add to `CATEGORIES` in `ImageLibrary.tsx`, update `search_images` tool description, and agent prompt if needed
- **Supporting new image formats**: Add MIME type to `ALLOWED_TYPES` in both `image_service.py` and `ImageLibrary.tsx`; update thumbnail generation if non-standard format
- **SVG export handling**: SVG images from the library are automatically converted to PNG during PPTX and Google Slides export via `_svg_to_png()` in both converters. The conversion uses `svgpathtools` + `Pillow` (pure Python) to parse `<path>` elements and rasterize them. This is transparent to the user — SVGs are sanitized on upload (`svg_sanitizer.sanitize_svg`: XML allowlist, no scripts/event handlers/external refs/DOCTYPE) and only converted at export time. The client-declared MIME type is not trusted: SVG content declared as another type (e.g. `image/png`) is rejected, as is an SVG-sniffed file in a design-system bundle without an `.svg` extension (F-CR-33).
- **Deferred column loading**: If `image_data` column causes performance issues with many images, add `deferred(image_data)` to the model or use explicit column selection in search queries
- **Image guidelines format**: The `image_guidelines` field is free-text — admins can use any format. The agent receives it verbatim. Consider adding structured validation if misuse becomes common
- **Adding image editing (crop/resize)**: Would go in `image_service.py`; existing `image_data` column can be updated in place

---

## Cross-References

- [Backend Overview](backend-overview.md) — agent lifecycle, ChatService, request flow
- [Frontend Overview](frontend-overview.md) — component layout, state management
- [Real-time Streaming](real-time-streaming.md) — SSE streaming through which chat responses (with images) are delivered
- [Database Configuration](database-configuration.md) — PostgreSQL/Lakebase setup, `create_all` schema management
- [Slide Parser & Script Management](slide-parser-and-script-management.md) — how HTML slides are parsed and managed after image substitution
