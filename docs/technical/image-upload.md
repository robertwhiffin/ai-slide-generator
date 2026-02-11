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

---

## Architecture Snapshot

```
User
  ├── Upload image ──► POST /api/images/upload
  │                         │
  │                    image_service.upload_image()
  │                         │
  │                    ┌────▼────┐
  │                    │Lakebase │  image_assets table
  │                    │ (bytea) │  raw bytes + 150x150 thumbnail
  │                    └────┬────┘
  │                         │
  ├── Chat message ──► ChatService
  │                         │
  │                    LangChain Agent
  │                    ├── search_images tool (metadata only)
  │                    └── outputs {{image:ID}} placeholders
  │                         │
  │                    substitute_image_placeholders()
  │                    (regex replaces → base64 data URIs)
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
    tags            = Column(JSON)             # ["branding", "logo"]
    description     = Column(Text)
    category        = Column(String(50))       # 'branding', 'content', 'background', 'ephemeral'
    uploaded_by     = Column(String(255))
    is_active       = Column(Boolean)          # Soft delete
```

**Invariants:**
- `image_data` stores raw bytes; base64 encoding happens on read
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
| `src/api/services/chat_service.py` | Integration glue | Calls `substitute_image_placeholders` after agent response; `_inject_image_context` for attached images |
| `src/services/agent.py` | Prompt construction | Conditional IMAGE GUIDELINES section; `search_images` tool binding |
| `src/core/settings_db.py` | Settings loader | Extracts `image_guidelines` from selected slide style |
| `src/api/routes/settings/slide_styles.py` | Slide style CRUD | `image_guidelines` field in schemas and handlers |
| `frontend/src/components/ImageLibrary/ImageLibrary.tsx` | Image gallery | Grid view, drag-drop upload, category filter, search |
| `frontend/src/components/ImageLibrary/ImagePicker.tsx` | Modal picker | Wraps ImageLibrary with select callback |
| `frontend/src/components/ChatPanel/ChatInput.tsx` | Paste-to-chat | Clipboard paste, upload, attach preview, "Save to library" toggle |
| `frontend/src/components/config/SlideStyleForm.tsx` | Style editor | Separate Image Guidelines Monaco editor + Insert Image Ref button |
| `frontend/src/types/image.ts` | TypeScript types | `ImageAsset`, `ImageListResponse`, `ImageDataResponse` |
| `frontend/src/services/api.ts` | API client | `uploadImage`, `listImages`, `updateImage`, `deleteImage` |

---

## State / Data Flow

### 1. Image upload

1. User drops/selects a file in ImageLibrary or pastes into ChatInput
2. Frontend sends `POST /api/images/upload` (multipart form: file + tags + description + category + save_to_library)
3. `image_service.upload_image()` validates type and size
4. Pillow generates 150x150 thumbnail (PNG for RGBA, JPEG otherwise; `None` for SVG)
5. Raw bytes + thumbnail + metadata saved to `image_assets` table
6. Response returns `ImageResponse` with thumbnail for immediate display

### 2. Paste-to-chat

1. User pastes image into ChatInput textarea (`onPaste` handler)
2. Frontend uploads via `api.uploadImage()` with `save_to_library` flag
3. If `save_to_library = false`, category is overridden to `"ephemeral"`
4. Uploaded `ImageAsset` added to `attachedImages` state
5. On send, `image_ids` array included in `ChatRequest`
6. `ChatService._inject_image_context()` appends image metadata to the user message text

### 3. Agent uses images in slides

1. Agent receives message (possibly with `[Attached images]` context)
2. Agent calls `search_images` tool if user explicitly requested images
3. Tool returns JSON metadata (id, filename, description, tags, usage example) — **never base64**
4. Agent outputs HTML with `{{image:ID}}` placeholders
5. `ChatService` calls `substitute_image_placeholders()` on the HTML output
6. Regex finds all `{{image:(\d+)}}`, loads each image's raw bytes, base64-encodes, replaces with `data:{mime};base64,...`
7. Frontend receives self-contained HTML with embedded images

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

## Operational Notes

### Validation constraints

| Constraint | Value | Enforced in |
|-----------|-------|-------------|
| Max file size | 5MB | `image_service.py` + `ChatInput.tsx` |
| Allowed MIME types | png, jpeg, gif, svg+xml | `image_service.py` + `ImageLibrary.tsx` |
| Thumbnail size | 150x150 | `image_service.py` |

### Error handling

- **Invalid type/size**: `ValueError` raised in `image_service`, returned as 400 from API
- **Image not found**: 404 from API; placeholder substitution logs warning and leaves `{{image:ID}}` intact
- **Paste upload failure**: Error shown in ChatInput UI, does not block message sending
- **Agent uses invalid ID**: Placeholder stays in HTML (graceful degradation)

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
