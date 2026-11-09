# AI image generation: plan corrections

These corrections **override** `2026-11-08-ai-image-generation.md` wherever they conflict.
Every implementer and reviewer reads this file first. Sources: the Task 0 probe
(a probe script under the gitignored `output/`, its JSON results,
run 2026-11-08 against a dev workspace as the developer's own identity) and code reads.

## Probe facts (verified, external state)

| Route | Orchestrator | Result |
|---|---|---|
| Gateway `/ai-gateway/mlflow/v1` (`gateway_openai_client`) | `system.ai.gpt-5-5` | 403 "rate limit set to 0" on this workspace |
| Gateway | `databricks-gpt-5-5` | 403 "no longer available, use Unity Catalog model services" |
| Gateway | `system.ai.gpt-5-6-terra`, `-sol`, `gpt-5-4`, `gpt-5-5-pro`, `gpt-5-4-mini`, `gpt-5-4-nano` | image generated |
| Any route, `stream=False`, raster | any | 400 `MAX_READ_SIZE_EXCEEDED` (response > 655,360 bytes) |
| Gateway, `stream=True`, raster | gpt-5-6-terra / gpt-5-4-nano | OK, ~10-11 s for 1024x1024 low; ~780 KB to 1.06 MB PNG |
| Gateway, transparent PNG | gpt-5-6-terra | OK, RGBA, alpha min 0 (model added a glow halo: prompt must forbid it) |
| Gateway, SVG (`gpt-image-2.6-flare`, `output_format=svg`, no size), `stream=False` | gpt-5-6-terra | OK, 16 s, ~1 KB, passes `sanitize_svg` |
| Gateway, edit (input_text + input_image data URL) | gpt-5-6-terra | OK, 11.4 s |
| Gateway, `tool_choice={"type":"image_generation"}` | terra, mini, nano | accepted |
| Gateway, `reasoning={"effort":"low"}` with 2.5-flare | terra | error "Complexity 'low' is not supported for this image model" |
| Gateway, `partial_images=2`, streamed | terra | **0 partial frames** (serving-endpoints sent 1) |
| Gateway, streamed, 2048x1152 `output_format=jpeg`, low, tool_choice | gpt-5-4-nano | OK, 9.3 s, 92 KB JPEG at exactly 2048x1152 |
| Gateway, streamed, 1536x1024 jpeg, low | gpt-5-4-nano | OK, 11.0 s, 84 KB |
| Gateway, SVG 2.6-flare `complexity=low`, non-streamed | gpt-5-4-nano | OK, 17.8 s, 3.9 KB, sanitizes |
| Gateway, edit with `size="auto"`, jpeg | gpt-5-4-nano | OK, 10.1 s, output 1254x1254 (auto picks its own size) |

## Corrections

- **C1 Route.** Use Tellr's existing Gateway client (`src/services/gateway_clients.py`). No `/serving-endpoints` fallback, no Task 2b third builder.
- **C2 Orchestrator.** `system.ai.gpt-5-5` is unusable here. `DEFAULT_ORCHESTRATOR_MODEL = "system.ai.gpt-5-4-nano"`, overridable by env `TELLR_IMAGE_GEN_ORCHESTRATOR_MODEL`. Always send `tool_choice={"type": "image_generation"}`.
- **C3 Streaming is mandatory for rasters.** Raster calls use `stream=True` and take the final image from the `response.output_item.done` event whose `item.type == "image_generation_call"` (`item.result` is base64); usage from the `response.completed` event (`event.response.usage`). SVG calls stay non-streamed (verified) and read `response.output`.
- **C4 Task 7 dropped.** No partial frames through the Gateway. Never send `partial_images`. No `preview_data_uri` anywhere.
- **C5 `with_options()` is broken** on `DatabricksOpenAI` 0.17.1 (`copy()` passes an `httpx.URL` into `_resolve_base_url` and raises `TypeError`). Instead extend `gateway_openai_client(workspace_client, **client_kwargs)` to forward kwargs (`timeout`, `max_retries`) to the `DatabricksOpenAI` constructor; construct with `max_retries=0`. Per-call timeout via the request kwarg `timeout=` on `responses.create`. Add a test in `tests/unit/test_gateway_clients.py` that kwargs are forwarded and the tag headers are still present.
- **C6 Never send `reasoning`.** Send `complexity` only for models with `supports_complexity` (2.6) and only when the preset sets one.
- **C7 Do not send unverified tool params.** Raster opaque presets: omit `background` (do not send `"opaque"`). Transparent: `background="transparent"`. SVG: `output_format="svg"`, no `size`, no `background`. No `instructions` param (unverified); put guidance in the prompt text.
- **C8 Icon art direction** must say: single centered subject, flat, consistent stroke weight, no text, **no glow, no drop shadow, no background tile or circle**, generous padding.
  - *Correction to C8 (2026-11-08, local smoke test):* the "glow halo" was an artifact of
    previewing RGBA composited onto black. Composited onto white, icons from 2.5-flare,
    2.5-sunburst and 2.6-flare are clean flat icons (only 0.6-2% soft anti-aliased pixels).
    The prohibitions stay (harmless), but "glow" is not a finding.
- **C14 Edits of transparent images.** Sent with alpha, a transparent icon is read as if on
  black: the edit comes back as a dark "neon" image whose alpha never drops below ~60 (no real
  transparency). Fix (verified live, 12.1 s, alpha 0-255, 72% clear): send the source
  flattened onto WHITE (`flatten_on_white`, JPEG data URL) while the tool still requests
  `background: transparent` + png, and append "Keep the background fully transparent." The
  Unit A edit test was updated by the controller to pin this; sabotage verified.
- **C9 Local env hazard.** `src/core/database.py` calls `load_dotenv()` at import and the developer's gitignored `.env` targets a different workspace with a PAT. Never read, edit or use that `.env` token. Local runs pre-set `DATABRICKS_HOST=<dev workspace URL>`, `DATABRICKS_TOKEN=` (blank, blocks dotenv since `override=False`), `DATABRICKS_CONFIG_PROFILE=DEFAULT`, `DATABASE_URL=postgresql://localhost:5432/ai_slide_generator`, `ENVIRONMENT=development`. Unit tests are unaffected (`tests/conftest.py`).
- **C10 Baseline.** `uv run pytest tests/unit -q -n auto`: 14802 passed, 129 skipped, **0 failed** (12m42s). Any failure after a unit is new.
- **C11 Mock transport.** `tests/fixtures/mock_chat_completions.py` serves JSON chat completions only. For streamed Responses, subclass `MockChatCompletionsWorkspace` (or a new class in the test file) whose `_handle` returns `httpx.Response(200, headers={"content-type": "text/event-stream"}, content=<SSE bytes>)` with `event:`/`data:` frames for `response.output_item.done` and `response.completed`; non-streamed SVG returns JSON. Use `install_mock_gateway_transport(monkeypatch)` so the real `DatabricksOpenAI` path, headers and base URL run. If the OpenAI SDK will not parse a hand-built SSE body, STOP and report rather than mocking higher up.
- **C12 Dispatch units.** Tasks are grouped by file to cut agent count: **Unit A** = Tasks 1+2+3 + C5 (`src/services/image_generation.py`, `src/services/gateway_clients.py`); **Unit B** = Tasks 4+5 (jobs, routes, wiring, authz inventory); **Unit C** = Task 6 (frontend). Each unit: Opus test author, then Sonnet implementer, then controller review with sabotage, then a final whole-branch Opus review. Models tags per unit: test=opus impl=sonnet.
- **C13 Never commit** `.gitignore` (BrainSync keeps rewriting it), `.env`, or anything under `output/`. Stage files by name. Never push this branch (public repo).

## Unit A interface (`src/services/image_generation.py`)

```python
ENV_FLAG = "TELLR_IMAGE_GENERATION_ENABLED"            # enabled iff os.getenv(ENV_FLAG) == "1"
ORCHESTRATOR_ENV = "TELLR_IMAGE_GEN_ORCHESTRATOR_MODEL"
DEFAULT_ORCHESTRATOR_MODEL = "system.ai.gpt-5-4-nano"
MAX_PROMPT_CHARS = 2000
QUALITIES: tuple[str, ...] = ("low", "medium", "high")
DEFAULT_PRESET = "icon_png"
SVG_THUMBNAIL_MAX_BYTES = 200 * 1024

@dataclass(frozen=True)
class ImageModelSpec:
    id: str; label: str; description: str
    supports_transparent: bool; supports_svg: bool; supports_complexity: bool

IMAGE_MODELS: dict[str, ImageModelSpec]   # gpt-image-2.5-flare, gpt-image-2.5-sunburst,
                                          # gpt-image-2.6-flare, gpt-image-2.6-sunburst

@dataclass(frozen=True)
class Preset:
    id: str; label: str; description: str
    size: str | None            # "2048x1152", "1536x1024", "1024x1024"; None for svg
    output_format: str          # "jpeg" | "png" | "svg"
    transparent: bool
    category: str               # "background" | "content"
    art_direction: str
    models: tuple[str, ...]; default_model: str; default_quality: str
    complexity: str | None      # e.g. "low" for icon_svg; only sent to 2.6 models
    timeout_s: int              # 180 raster, 240 svg

PRESETS: dict[str, Preset]      # background, illustration, icon_png, icon_svg (table in plan)

def is_enabled() -> bool
def orchestrator_model() -> str
def resolve_request(preset_id: str, model: str | None, quality: str | None) -> tuple[Preset, str, str]
    # ValueError on unknown preset, model not in preset.models, quality not in QUALITIES
def build_tool(preset: Preset, model: str, quality: str) -> dict
def build_prompt(user_prompt: str, preset: Preset) -> str
def to_data_url(data: bytes, max_side: int = 1536) -> str      # alpha -> PNG, else JPEG
def strip_code_fences(text: str) -> str
def check_static_svg(svg: str) -> None                          # ValueError on unsafe markup
def fit_to_library(raw: bytes, *, max_bytes: int = image_service.MAX_FILE_SIZE) -> tuple[bytes, str, str]
    # (data, mime, ext). Sniff the real format with Pillow; WebP -> PNG if alpha else JPEG;
    # over cap: JPEG quality 85 -> 75 -> 65 then scale 0.8 (repeat); PNG optimize then scale 0.8,
    # keeping RGBA. Result mime always in image_service.ALLOWED_TYPES.
def generated_filename(prompt: str, ext: str, *, prefix: str = "ai") -> str
    # f"{prefix}-{slug(prompt)[:40]}-{UTC %Y%m%dT%H%M%SZ}-{uuid4().hex[:8]}.{ext}"

@dataclass
class GeneratedImage:
    data: bytes; mime: str; ext: str; model: str; preset_id: str | None
    revised_prompt: str | None; latency_s: float; usage: dict | None

class ImageGenerationError(RuntimeError):
    def __init__(self, message: str, *, status_code: int | None = None) -> None

def default_client() -> Any
    # gateway_openai_client(get_system_client(), max_retries=0)

class ImageGenerator:
    def __init__(self, client_factory: Callable[[], Any] = default_client,
                 orchestrator: str | None = None) -> None
    def generate(self, prompt: str, preset_id: str, model: str | None = None,
                 quality: str | None = None) -> GeneratedImage
    def edit(self, prompt: str, source: bytes, source_mime: str, model: str | None = None,
             quality: str | None = None) -> GeneratedImage
    # edit: ValueError for image/svg+xml sources; source with alpha -> background transparent +
    # png, else jpeg; size "auto"; input = [{"role":"user","content":[input_text, input_image]}].
    # openai.APIStatusError -> ImageGenerationError(status_code=exc.status_code).
    # No image item -> ImageGenerationError. Every call: tool_choice forced, timeout=preset.timeout_s
    # (edits 180), output through fit_to_library (rasters) or svg checks.

def save_generated_image(db, img: GeneratedImage, *, owner: str, prompt: str, category: str,
                         tags: list[str], description: str | None = None) -> ImageAsset
    # image_service.upload_image(db, img.data, generated_filename(...), img.mime, owner,
    #   tags=tags, description=(description or prompt)[:500], category=category);
    # for svg (sanitized by upload_image) set thumbnail_base64 to a data URI of the stored bytes
    # when <= SVG_THUMBNAIL_MAX_BYTES, then commit.
```

## Unit B interface (jobs + routes)

Verified facts: `ExportJob.session_id` is a plain `String(128)` (no FK). `_require_export_job_access`
(`src/api/routes/_authz.py:265`) resolves the job's session and runs the deck-permission check, so an
image job polled on an export route fails closed (404). `cleanup_stale_jobs` deletes completed/error
rows after 30 min; `cleanup_export_job` only touches `output_path` if it exists as a file (JSON never
does). `tests/unit/test_route_authz_coverage.py` treats any `{job_id}` route as sensitive: it needs an
ALLOWLIST entry with a rationale. Frontend `pollExportJob` (`frontend/src/services/api.ts:324`) reads
`status`, `progress`, `total_slides`, `status_message`, `error`; finishes on `completed`, throws on
`error`.

`src/api/services/image_generation_jobs.py`:

```python
JOB_SESSION_PREFIX = "image-generation:"   # ExportJob.session_id = PREFIX + owner
JOB_STALE_SECONDS = 300
MAX_WORKERS = 2
MAX_INFLIGHT = 4                            # per process; running + queued

@dataclass(frozen=True)
class GenerationSpec:
    prompt: str; preset_id: str; model: str | None = None; quality: str | None = None

@dataclass(frozen=True)
class EditSpec:
    prompt: str; source_bytes: bytes; source_mime: str; source_name: str; source_category: str
    model: str | None = None; quality: str | None = None

def create_job(*, owner: str, title: str, session_factory=get_db_session) -> str
    # export_job_queue.generate_job_id(); row status "pending", status_message "Queued",
    # title[:512], session_id PREFIX+owner
def submit(job_id: str, *, owner: str, spec: GenerationSpec | EditSpec) -> bool
    # False (and job untouched) when in-flight >= MAX_INFLIGHT; else _submit(run_job, ...)
def _submit(fn, /, *args, **kwargs) -> Any
    # module-level seam over a lazily created ThreadPoolExecutor(MAX_WORKERS, "image-gen");
    # tests monkeypatch it to run inline
def run_job(job_id: str, *, owner: str, spec: GenerationSpec | EditSpec,
            generator: ImageGenerator | None = None, session_factory=get_db_session) -> None
    # NEVER raises. running/"Generating image..." -> running/"Saving..." ->
    # completed (output_path = json {"image_token": t}, completed_at set) | error.
    # Generation: save with tags ["ai_generated", model, preset_id], category preset.category.
    # Edit: tags ["ai_generated", "ai_edit", model], category = source_category
    # (ephemeral -> content), description f"Edit of {source_name}: {prompt}".
    # Error messages (<=300 chars, no traceback):
    #   ImageGenerationError status 403 -> "The app identity cannot use the image model (403). ..."
    #   ImageGenerationError status 429 -> "The image model is rate limited (429). Try again shortly."
    #   ImageGenerationError other / ValueError -> str(exc)
    #   any other Exception -> "Image generation failed" (logged with exc_info)
    # in-flight counter decremented in finally.
    # status_message is ALWAYS non-null ("Queued", "Generating image...", "Saving...", "Done",
    # "Failed"): the frontend pollExportJob falls back to "Processing slide 0 of 0" on null.
def get_job(job_id: str, *, owner: str, session_factory=get_db_session) -> dict | None
    # None if unknown, session_id != PREFIX+owner, or not an image job.
    # pending/running older than JOB_STALE_SECONDS -> persisted as error "Image generation timed out".
    # returns {"job_id","status","status_message","error","image_token"}
```

`src/api/routes/image_generation.py` (`APIRouter(prefix="/api/images", tags=["image-generation"])`),
included in `src/api/main.py` **before** `images.router`:

```python
def require_image_generation_enabled() -> None          # HTTPException 404 unless is_enabled()

GET  /generate/available            -> ImageGenerationOptions   (NOT flag-gated; available=False when off,
                                                                  presets/edit empty or None)
POST /generate                      -> 202 ImageGenerationJobResponse  (flag-gated)
     body GenerateImageRequest{prompt: str = Field(min_length=1, max_length=MAX_PROMPT_CHARS),
                               preset: str = DEFAULT_PRESET, model: str|None, quality: str|None}
     400 on resolve_request ValueError; 429 when submit() returns False (job row -> error)
POST /{token}/edit                  -> 202 ImageGenerationJobResponse  (flag-gated)
     body EditImageRequest{prompt (same bounds), model: str|None, quality: str|None}
     404 unknown/inactive token; images_routes._deny_ephemeral_cross_user(image) (404);
     400 for image/svg+xml source or bad model/quality. Source bytes are copied, never modified.
GET  /generate/jobs/{job_id}        -> ImageGenerationJobResponse  (flag-gated; 404 unless get_job)

class ImageGenerationJobResponse(BaseModel):
    job_id: str; status: str; progress: int = 0; total_slides: int = 0
    status_message: str | None = None; error: str | None = None
    image: ImageResponse | None = None     # via images_routes._image_to_response when completed
class ImageModelOption(BaseModel): id: str; label: str; description: str
class ImagePresetOption(BaseModel):
    id: str; label: str; description: str; output_format: str; category: str; transparent: bool
    models: list[ImageModelOption]; default_model: str; qualities: list[str]; default_quality: str
class ImageEditOptions(BaseModel):
    models: list[ImageModelOption]; default_model: str; qualities: list[str]; default_quality: str
class ImageGenerationOptions(BaseModel):
    available: bool; max_prompt_chars: int; default_preset: str | None
    presets: list[ImagePresetOption]; edit: ImageEditOptions | None
```

- Owner is captured in the route with `images_routes._get_current_user()` (call through the module so
  tests can patch `src.api.routes.images._get_current_user`), never in the worker thread.
- On import, when `is_enabled()`, log at INFO: `AI image generation is offered on this deployment (turn it off with TELLR_IMAGE_GENERATION_ENABLED=0)`
  (the deploy overlay check greps for this).
- ALLOWLIST entry in `tests/unit/test_route_authz_coverage.py` for
  `("GET", "/api/images/generate/jobs/{job_id}")` with the rationale "owner-only inline: get_job
  returns None unless the row's session_id is image-generation:<caller>, so another user's id 404s".
- `tests/unit/test_app_wiring.py`: assert the four paths are registered.

## Unit C interface (frontend)

Facts: image API calls in `frontend/src/services/api.ts` use plain `fetch` (JSON POSTs set
`Content-Type: application/json`); `pollExportJob` (module-private, `api.ts:324`) polls every 2 s and
calls `onProgress(progress, total, status_message)`. `ImagePicker` renders
`<ImageLibrary onSelect readOnly={false}>`, so a header Generate button gated on `!readOnly` also appears
in the HTML editor's picker (the in-deck path). Tests: vitest + Testing Library, `vi.mock` of the API
module (pattern: `src/components/Admin/AdminGenieOneDefault.test.tsx`).

`frontend/src/types/image.ts` adds:

```ts
export interface ImageModelOption { id: string; label: string; description: string }
export interface ImagePresetOption {
  id: string; label: string; description: string; output_format: 'jpeg' | 'png' | 'svg';
  category: string; transparent: boolean; models: ImageModelOption[];
  default_model: string; qualities: string[]; default_quality: string;
}
export interface ImageEditOptions {
  models: ImageModelOption[]; default_model: string; qualities: string[]; default_quality: string;
}
export interface ImageGenerationOptions {
  available: boolean; max_prompt_chars: number; default_preset: string | null;
  presets: ImagePresetOption[]; edit: ImageEditOptions | null;
}
export interface ImageGenerationRequest { prompt: string; preset: string; model?: string; quality?: string }
export interface ImageEditRequest { prompt: string; model?: string; quality?: string }
export interface ImageGenerationJob {
  job_id: string; status: 'pending' | 'running' | 'completed' | 'error'; progress: number;
  total_slides: number; status_message?: string | null; error?: string | null; image?: ImageAsset | null;
}
```

`api` object methods (next to the image methods):

```ts
imageGenerationOptions(): Promise<ImageGenerationOptions>
  // GET /api/images/generate/available; NEVER throws: any failure resolves to
  // { available: false, max_prompt_chars: 0, default_preset: null, presets: [], edit: null }
generateImage(req: ImageGenerationRequest, onProgress?: ProgressCallback): Promise<ImageAsset>
  // POST /api/images/generate; non-2xx -> ApiError(status, detail || 'Image generation failed');
  // then pollExportJob(`${API_BASE_URL}/api/images/generate/jobs/${job_id}`, 'IMAGEGEN', onProgress);
  // return job.image, or throw ApiError(500, 'No image returned')
editImageWithPrompt(imageId: string, req: ImageEditRequest, onProgress?: ProgressCallback): Promise<ImageAsset>
  // POST /api/images/${imageId}/edit, then same polling
```

New `frontend/src/components/ImageLibrary/GenerateImageDialog.tsx`:

```ts
interface GenerateImageDialogProps {
  isOpen: boolean; onClose: () => void; onCreated: (image: ImageAsset) => void;
  options: ImageGenerationOptions; source?: ImageAsset;   // source set => edit mode
}
```

- Modal styled like `ImagePicker` (fixed overlay, white rounded panel, close button). Title "Generate
  image" or "Edit with prompt" (+ source filename).
- Prompt `<textarea aria-label="Prompt">`, `maxLength={options.max_prompt_chars}`, live counter.
- Generate mode: one button per preset (`aria-pressed`), label + description, default
  `options.default_preset`. Edit mode: no presets; models/qualities from `options.edit`.
- `<select aria-label="Model">` from the selected preset's models (reset to its `default_model` on
  preset change); `<select aria-label="Quality">` likewise.
- Submit button "Generate" (edit mode "Create edited copy"), disabled when the trimmed prompt is empty,
  over the limit, or a request is running. Payload exactly `{prompt, preset, model, quality}` (edit:
  `{prompt, model, quality}` to `editImageWithPrompt(source.id, ...)`).
- While running: inputs disabled; status text from `onProgress`'s third argument plus elapsed seconds.
- Success: call `onCreated(image)`; show the result thumbnail, a "Copy reference" button writing
  `{{image:<id>}}` via `navigator.clipboard.writeText`, and "Generate another" (reset to the form).
- Error: inline `role="alert"` message; the form stays filled for retry.

`ImageLibrary.tsx` changes:

- When `!readOnly`, fetch `api.imageGenerationOptions()` once on mount.
- Header "Generate" button only when `options.available && !readOnly`; opens the dialog.
- Hover "Edit with prompt" button on a tile only when available, `!readOnly && !onSelect`, and
  `mime_type !== 'image/svg+xml'`.
- `onCreated` -> `loadImages()`.
- Tiles whose `tags` include `ai_generated` show a small "AI" badge.
- PNG and SVG thumbnails sit on a light checkerboard so transparency is visible.

## Unit D interface (admin toggle), added 2026-11-08 at the user's request

> **C15 (2026-11-09, user ruling): the feature is ON by default.** Both gates stay, as OFF
> switches: the deployment opts out with `TELLR_IMAGE_GENERATION_ENABLED=0` (also `false`,
> `no`, `off`; unset or anything else is on), and the admin setting is on unless a row says off.
> The text below describes the original off-by-default design; where it conflicts, C15 wins.

Both gates, with distinct jobs: the env var `TELLR_IMAGE_GENERATION_ENABLED=1` says whether a
DEPLOYMENT offers the capability at all (keeps the unapproved feature invisible everywhere else;
the workspace must have a usable orchestrator model); the admin setting says whether it is ON for
the workspace right now (no redeploy; off by default because every image is a paid call made as
the app service principal). **Effective = env AND admin.** The admin control only renders when the
env capability is present.

Backend:

```python
# src/services/workspace_settings.py  (same shape as GENIE_ONE_DEFAULT_KEY)
IMAGE_GENERATION_KEY: Final = "image_generation_enabled"
def image_generation_enabled(db: Session) -> bool          # False unless a row says True
def set_image_generation_enabled(db: Session, *, enabled: bool, user: str) -> bool

# src/api/routes/admin.py  (router already depends on require_admin)
GET  /api/admin/image-generation  -> {"available": is_enabled(), "enabled": image_generation_enabled(db)}
PUT  /api/admin/image-generation  body {"enabled": bool}
     -> 409 {"detail": "Image generation is not available on this deployment ..."} and NOTHING
        stored when not is_enabled(); else store (updated_by = admin) and return
        {"available": True, "enabled": <stored>}

# src/api/routes/image_generation.py
require_image_generation_enabled(db = Depends(get_db))   # 404 unless env AND admin setting
GET /generate/available                                    # available = env AND admin setting
```

Frontend:

```ts
// frontend/src/api/admin.ts
getImageGeneration(): Promise<{ available: boolean; enabled: boolean }>
setImageGeneration(enabled: boolean): Promise<{ available: boolean; enabled: boolean }>
// frontend/src/components/Admin/AdminImageGeneration.tsx (pattern: AdminGenieOneDefault.tsx)
//   renders NOTHING when available === false; otherwise a checkbox
//   aria-label "Let users generate images with AI", help text explaining it adds Generate /
//   Edit with prompt to the Image Library, that each image is a paid model call made as the
//   app's service principal, and that it is on by default (C15). Save on click; on failure toast
//   "Failed to save: ..." and keep the previous state. Load error shows "Failed to load: ...".
// Mounted in AdminPage's Connections tab, above <AdminGenieOneDefault />.
```

Existing Unit B route tests that turn the feature on via env only must ALSO enable the admin
setting (fixture change ruled by the controller); new cases cover env on + admin off and
env off + admin on (both: 404 on generate/edit/poll, `available: false`).
