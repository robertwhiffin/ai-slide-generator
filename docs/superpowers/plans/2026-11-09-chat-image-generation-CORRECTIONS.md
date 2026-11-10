# Chat image generation: plan corrections

This file **overrides** `2026-11-09-chat-image-generation.md` wherever the two conflict. Every
implementer and reviewer reads it first.

The pre-pass ran on 2026-11-09 against `feat/ai-image-generation`.

## Verified facts (code reads)

- **Polling drops unknown metadata.** `SessionManager.msg_to_stream_event`
  (`src/api/services/session_manager.py`) forwards only `details` and `sign_in_url` from a row's
  metadata. `generated_images` must be added explicitly, or polling clients never see the card.
- **The graph engine ignores `slide_context`.** `_send_message_streaming_graph(session_id,
  message, ...)` is the only graph entry, so every button message must name the slide in its text.
- **`StreamEvent` has top-level fields** `tool_name` and `tool_input`
  (`src/api/schemas/streaming.py:49-50`). The frontend's SSE `tool_call` case reads
  `event.tool_name` (`ChatPanel.tsx:395`). `nodes._emit` cannot set them today.
- **Fallback without tools.** `_GatewayPass.without_tools(exc, toolset)` (`nodes.py:3847`) is
  Gateway-only.
- **Reserved tool names.** `_RESERVED_NAMES` (`gateway_toolset.py:48`) is
  `{"genie","ArchitectOutput","AnalystOutput"}`.
- **`_say_architect_message(state, message, intent)`** (`nodes.py:2753`) emits ASSISTANT with
  `metadata={"node":"architect","intent":intent}` and then calls `_say(state, message)`.
  `_say(state, message, *, message_type="llm_response", metadata=None)` (`nodes.py:408`).
- **Conversation replay.** `_conversation` (`nodes.py:1255`) appends a `system` note after an
  assistant row whose metadata carries `REFUSAL_METADATA_KEY`. The generated-images note uses the
  same mechanism.
- **Turn-scoped state keys.** The pattern is
  `gateway_usage`/`gateway_images: Annotated[Any, turn_scoped_concat]`, with `[]` in `_EMPTY_FOR`
  (`state.py:59-76, 357-358`).
- **Turn budget.** `turn_budget(*, used_calls, used_seconds, max_calls, budget_seconds,
  turn_started_at, now, deadline_seconds=700) -> (calls_left, seconds_left)`
  (`gateway_toolset.py:290`).
- **Spotlighting.** `spotlight(source, text, *, scan=True, session_id=None)`
  (`src/utils/spotlight.py`).
- **Baseline.** The unit suite on HEAD 9d119c247 is recorded in the ledger. The prior run was
  15155 passed, 0 failed, so the cause-set is empty.

## Rulings

- **R1. Message builder naming.** The frontend message-builder that "uses" an option is named
  `pickImageMessage`, not `useImageMessage`. ESLint rules-of-hooks would treat a `use*` function
  as a hook.
- **R2. One shared sanitiser.** `src/utils/generated_images.py` holds the metadata shape. The node
  uses it to build the metadata; `session_manager` uses it to filter what it forwards.
- **R3. Tool-made refs.** The tool records refs as `{token, kind, option, prompt, for_slide}`.
  The node adds `slides`.
- **R4. Defaults.** The tool uses the presets' defaults: gpt-image-2.6-flare at medium. It does
  not choose a model or a quality.
- **R5. Never cache availability.** `_image_generation_available()` is read on every turn, in the
  node thread.

- **R6. Abandon race.** Each job claims its save under a lock: after `generate` returns, take
  the lock; if the job is abandoned, skip; otherwise mark it claimed, then save. After
  `wait(timeout=wall)`, under the same lock, mark every job that is not done and not claimed as
  abandoned. Then wait (bounded, briefly) for claimed jobs to finish saving, so the result reports
  every row that was saved. A saved row must never be reported as `FAIL_TIMEOUT`.
- **R7. Straggler slots.** A job holds its semaphore slot until it actually finishes; release it
  in the job's `finally`. An abandoned straggler therefore keeps its slot, and real concurrency
  never exceeds `MAX_CONCURRENT`.
- **R8. No owner.** When `context.owner` is falsy, `run` refuses with spotlighted text and starts
  nothing, matching `make_image_saver`, which requires a user.

- **R9. Merged toolsets keep the Gateway's own call cap.** Gateway tools don't count their own
  calls. In a merged toolset, every Gateway tool is wrapped in a shared counter that refuses
  further calls with the existing budget text once the Gateway's calls-left is used up. The
  toolset's `max_calls` is still Gateway left + image left, and the image tool keeps enforcing its
  own `calls_left`. The controller adds a test: a merged run in which the model calls a Gateway
  tool 13 times gets the budget text on the 13th, and no 13th MCP call is made.
- **R10. Notice wording by image source.** `build_branch_payload` sets a branch-only
  `turn_image_sources` (sorted list drawn from `"gateway"` and `"generated"`) next to
  `gateway_known_images`. `builder_node`, and the architect-level notice, use these texts when the
  sources are exactly `["generated"]`:
  - `_IMAGE_NOT_PLACED_GENERATED` ("A generated image couldn't be placed on slide {n}.");
  - `_IMAGE_NOT_PLACED_GENERATED_UNNUMBERED` ("A generated image couldn't be placed.");
  - every other case keeps today's Gateway wording.
  `turn_image_sources` must not be added to `_BUILDER_MODEL_PAYLOAD_KEYS`.
- **R11. Options are numbered per turn.** `ImageToolContext` gains `first_option: int = 1`, and the
  tool numbers from it. `_ImageToolPass` sets it to 1 plus the number of images already generated
  this turn, so one reply's card never shows two "Option 1"s.

- **R12. `regenerateMessage` uses the singular kind**, e.g. "Generate 3 new illustration options for
  slide 3: ...". The earlier `plural(kind)` gave "illustrations options". The controller fixed the
  pinned test strings to match.
- **R13. ChatPanel takes a `slideCount?: number` prop**, which AppLayout passes as
  `slideDeck?.slides.length ?? 0`. The SlideViewer stage button "Generate image for this slide" is
  disabled while a turn is running, the same as other stage actions that send chat messages.
- **R14. The new Playwright spec goes in the CI e2e shard matrix.** `test_e2e_matrix_covers_specs`
  requires it.

Rulings from the live check (2026-11-09):

- **R15. `regenerateMessage` never carries the stored prompt**, for example "Generate 3 new
  illustration options for slide 2." The stored prompt is the model's own, cut to 300 characters.
  In the user's bubble it read as the user's words cut off mid-word, and the architect replied "your
  description was cut off". The reply above the card already describes the images.
- **R16. No image tool, but the conversation showed generated images.** The architect's
  conversation then ends with a `system` turn, `_IMAGE_TOOL_OFF_NOTE`, saying image generation is
  not available this turn. Live, with the admin switch off, a session with earlier options got "I
  made three picture options ... shown below this reply" with nothing generated. A conversation that
  never showed generated images is unchanged.

## Shared metadata shape (backend writes it, polling forwards it, frontend reads it)

```json
"generated_images": [
  {"token": "abc_DEF-1", "kind": "illustration", "option": 1,
   "prompt": "≤300 chars", "for_slide": 3, "slides": [2]}
]
```

- `token` must match `^[A-Za-z0-9_-]+$`.
- `kind` is one of `illustration`, `background`, `icon`, `vector_icon`.
- `option` is an int of 1 or more.
- `for_slide` is an int of 1 or more, or null.
- `slides` is a list of ints of 1 or more (empty when the image is not placed).
- Unknown keys are dropped. An entry with an invalid `token`, `kind` or `option` is dropped.

## Unit G interface (Tasks 1, 2, 5): service seams, the tool, polling

```python
# src/services/image_generation.py
class ImageGenerator:
    def generate(self, prompt, preset_id, model=None, quality=None, *, timeout_s: float | None = None) -> GeneratedImage
    # effective per-call timeout = preset.timeout_s if timeout_s is None
    #                              else min(preset.timeout_s, max(5.0, timeout_s))
def generation_available(db) -> bool
    # is_enabled() and workspace_settings.image_generation_enabled(db);
    # does NOT read the DB when the env gate is off

# src/api/routes/image_generation.py
_effective_enabled(db) delegates to generation_available(db)

# src/utils/generated_images.py
GENERATED_IMAGE_KINDS = ("illustration", "background", "icon", "vector_icon")
GENERATED_IMAGE_KEYS = ("token", "kind", "option", "prompt", "for_slide", "slides")
def sanitize_generated_images(value: object) -> list[dict]   # never raises; [] for junk

# src/services/agent_tools/image_generation_tool.py
IMAGE_TOOL_NAME = "generate_image"
MAX_CALLS_PER_TURN = 2; MAX_PER_CALL = 3; MAX_IMAGES_PER_TURN = 6
BUDGET_SECONDS = 240.0; MIN_START_SECONDS = 30.0; MAX_CONCURRENT = 6
KIND_TO_PRESET = {"illustration": "illustration", "background": "background",
                  "icon": "icon_png", "vector_icon": "icon_svg"}
FAIL_BUSY = "the image model is busy"
FAIL_FORBIDDEN = "the app is not allowed to use the image model"
FAIL_TIMEOUT = "did not finish in time"
FAIL_OTHER = "could not be generated"

class ImageGenerationArgs(BaseModel):
    prompt: str = Field(min_length=1, max_length=MAX_PROMPT_CHARS)
    kind: Literal["illustration", "background", "icon", "vector_icon"]
    count: int = Field(1, ge=1, le=MAX_PER_CALL)
    for_slide: int | None = Field(None, ge=1)

def save_to_library(img: GeneratedImage, *, owner: str, prompt: str, category: str, tags: list[str]) -> str
    # get_db_session() + image_generation.save_generated_image(...) -> asset.token

@dataclass(frozen=True)
class ImageToolContext:
    owner: str | None
    session_id: str | None
    on_call: Callable[[str, int], None]        # (kind, n), called before generating; errors swallowed
    calls_left: int
    images_left: int
    seconds_left: float
    deadline_at: float | None                  # epoch seconds; None = no deadline
    generator_factory: Callable[[], Any] = ImageGenerator
    save: Callable[..., str] = save_to_library
    clock: Callable[[], float] = time.time

class ImageGenerationAgentTool:                # satisfies AgentTool
    name = IMAGE_TOOL_NAME
    description = IMAGE_TOOL_DESCRIPTION
    args_schema = ImageGenerationArgs
    def __init__(self, context: ImageToolContext) -> None
    def run(self, args: ImageGenerationArgs, *, remaining_seconds: float) -> str
    generated: list[dict]       # successes, in option order: {token, kind, option, prompt, for_slide}
    calls: int; images: int; seconds: float
    def saved_tokens(self) -> list[str]
```

**`run` behaviour:**
- `wall = min(remaining_seconds, context.seconds_left, deadline_at - clock())`.
- **Refusals.** It returns spotlighted refusal text, starting no generation, when any of these hold:
  - this tool instance has used up `calls_left`;
  - `images_left - images <= 0`;
  - `wall < MIN_START_SECONDS`;
  - no slot is free in the process semaphore (`MAX_CONCURRENT`, acquired without blocking).
- **How many.** `n = min(count, MAX_PER_CALL, images_left - images, free slots)`.
- **Generating.**
  - Call `on_call(kind, n)` first.
  - Run `n` jobs on a module-level `ThreadPoolExecutor(max_workers=MAX_CONCURRENT,
    thread_name_prefix="chat-image-gen")`.
  - Each job calls `generator.generate(prompt, preset, timeout_s=wall)`, then
    `save(img, owner=owner, prompt=prompt, category=PRESETS[preset].category, tags=[...])`.
  - Tags are `["ai_generated", img.model, preset, "chat"]`, plus `"chat_option"` when `n > 1`.
- **Stragglers.** `concurrent.futures.wait(..., timeout=wall)`. A job that has not finished is
  abandoned: it checks a flag after `generate` returns and never saves.
- **Failure text.**
  - `ImageGenerationError` with status 429 → `FAIL_BUSY`.
  - 403 → `FAIL_FORBIDDEN`.
  - Not done in time → `FAIL_TIMEOUT`.
  - Anything else → `FAIL_OTHER`.
  - Never include `str(exc)`.
- **Return value.** `spotlight("image_generation", text, session_id=context.session_id)`. The text
  is facts only:
  ```
  Generated 2 of 3 illustration images, saved to the user's Image Library:
  Option 1: {{image:A}} (image/jpeg, 1536x1024)
  Option 2: {{image:B}} (image/jpeg, 1536x1024)
  Option 3: not generated (did not finish in time).
  Nothing is on a slide yet. The user sees these images under your reply.
  ```
- **`IMAGE_TOOL_DESCRIPTION`** carries the usage rules from plan Task 2 (call only on an explicit
  ask; options → count 3 plus discuss; exact ask → count 1 and place it; how to place it in
  `content_brief`; prompt guidance; the kinds; at most 2 calls). Each argument has a one-line
  `Field(description=...)`.
- **Reserved name.** `gateway_toolset._RESERVED_NAMES` gains `"generate_image"`.
- **Polling.** `session_manager.msg_to_stream_event` forwards
  `metadata["generated_images"] = sanitize_generated_images(...)` only when the result is
  non-empty. Nothing else changes.

## Unit H interface (Tasks 3, 4): graph binding and turn records

```python
# src/services/graph/state.py
generated_images: Annotated[Any, turn_scoped_concat]    # list of tool refs (R3 shape)
image_tool_usage: Annotated[Any, turn_scoped_concat]    # list of {"calls","images","seconds"} per pass
# _EMPTY_FOR: both []

# src/services/graph/nodes.py
GENERATED_IMAGES_METADATA_KEY = "generated_images"
_IMAGE_NOT_PLACED_GENERATED = "A generated image couldn't be placed on slide {n}."
def _image_generation_available() -> bool          # get_db_session + generation_available; False on any error
def _emit(..., tool_name: str | None = None, tool_input: dict | None = None)   # additive
class _ImageToolPass:
    def __init__(self, state: dict, owner: str | None) -> None   # sums this turn's image_tool_usage
    def tool(self) -> ImageGenerationAgentTool | None            # fresh per attempt; None when spent or past the deadline
    def without_tools(self, exc: Exception, toolset) -> bool
    def generated(self) -> list[dict]; def saved_tokens(self) -> list[str]; def usage(self) -> dict
def _architect_toolset(gateway, images) -> AgentToolset | None
def _turn_tool_images(state) -> set[str]          # gateway images ∪ generated tokens this turn
def _turn_generated_tokens(state) -> set[str]
def _say_architect_message(state, message, intent, *, metadata: dict | None = None) -> None
def _with_option_labels(message: str, refs: list[dict]) -> str
def _generated_images_metadata(refs: list[dict], spec) -> list[dict]   # adds "slides" (1-based, canonical order)
def _generated_images_note(refs: list[dict]) -> str                    # system replay note
```

- **Progress event.** `_ImageToolPass._on_call(kind, n)`:
  - emits `TOOL_CALL` with top-level `tool_name="image_generation"`,
    `tool_input={"kind": kind, "count": n}` and `metadata={"node": "architect"}`;
  - persists `_say(..., message_type="tool_call", metadata={"tool_name": "image_generation",
    "tool_input": {...}})`, with content such as "Generating 3 illustrations".
- **Owner.** `state["initiated_by"]`, falling back to `image_service.resolve_requesting_user()`
  (same as `_gateway_user`).
- **Test seam.**
  - An autouse fixture in `tests/conftest.py` patches
    `src.services.graph.nodes._image_generation_available` to return False, unless the test is
    marked `@pytest.mark.image_tool`.
  - Register the marker in `pyproject.toml` `[tool.pytest.ini_options] markers`.

## Unit I interface (Tasks 6, 7, 8): frontend

```ts
// types/message.ts
export interface GeneratedImageRef {
  token: string; kind: 'illustration' | 'background' | 'icon' | 'vector_icon';
  option: number; prompt?: string; for_slide?: number | null; slides: number[];
}
// Message gains: generated_images?: GeneratedImageRef[]
// utils/generatedImages.ts
export function readGeneratedImages(value: unknown): GeneratedImageRef[]   // never throws; drops junk (same rules as the backend)
// services/api.ts
getImage(token: string): Promise<ImageAsset>          // GET /api/images/{token}
// hooks/useImageGenerationOptions.ts
export function getImageGenerationOptions(): Promise<ImageGenerationOptions>   // module-cached, 5-min TTL, failure resolves "unavailable"
export function useImageGenerationOptions(): ImageGenerationOptions | null
export function invalidateImageGenerationOptions(): void
export function __resetImageGenerationOptionsCacheForTests(): void
// utils/imageChatMessages.ts (exact strings)
pickImageMessage(img)
    // for_slide set → `Use option ${img.option} on slide ${img.for_slide}.`
    // otherwise     → `Use option ${img.option} where it fits best.`
regenerateMessage(images)
    // `Generate 3 new ${singular(kind)} options${for_slide ? ` for slide ${n}` : ''}.`  (R12: singular; R15: no prompt)
generateImageMessage({prompt, kind, options, forSlide})
    // options: `Generate 3 ${singular(kind)} options${forSlide ? ` for slide ${n}` : ''}: ${prompt}`
    // single:  `Generate ${a(kind)} and add it to slide ${n}: ${prompt}` when forSlide is set,
    //          else `Generate ${a(kind)}: ${prompt}`
    // An empty prompt drops the ": ..." part and ends with ".".
// kind labels: illustration/illustrations, icon/icons, background/backgrounds, vector icon/vector icons;
// a(kind) = "an illustration" | "an icon" | "a background" | "a vector icon"
```

**`GeneratedImagesCard`** (`components/ChatPanel/GeneratedImagesCard.tsx`):
- Props `{images, onUse(img), onRegenerate(images), actionsDisabled, hideActions}`.
- For each image: a thumbnail from `api.getImage` (a placeholder on error or null) and an
  "Option N" label.
- "On slide N" badge(s) when `slides` is non-empty.
- A "Use this" button only when `slides` is empty.
- One "Regenerate" button, and the caption "Saved to your Image Library".

**Wiring:**
- `Message.tsx` renders the card under the assistant bubble.
- `ChatPanel` calls `handleSendMessage(pickImageMessage(img), [img.token])` for Use, and
  `handleSendMessage(regenerateMessage(images))` for Regenerate.
- The actions are hidden in save-point preview and disabled while loading.

**`GenerateImageRequestDialog`** (`components/ChatPanel/GenerateImageRequestDialog.tsx`):
- Prompt textarea (`aria-label="Describe the image"`).
- Kind chips (`aria-pressed`): Illustration, Icon, Background, Vector icon.
- Checkbox "Show me 3 options", checked by default.
- Optional "For slide" select (None, 1..slideCount).
- Submit button "Send to chat", disabled when the prompt is empty and no slide is chosen.

**Entry points:**
- `ChatInput` gets the prop `imageRequest?: { slideCount: number }`. When set, it renders a
  labelled button "Generate image" in the hint row, which opens the dialog and calls
  `onSend(generateImageMessage(...))`.
- `ChatPanel` passes the prop only when the options say available and the deck mode is not
  `legacy`.
- `SlideViewer` gets a stage-toolbar button "Generate image for this slide", shown when the prop
  `imageGenerationAvailable` is set. It opens the same dialog with `forSlide = currentIndex + 1`
  and sends through the existing `onSendMessage` path.

**Activity labels.** `ToolActivityBar` / `toolCallLabel` show `image_generation` with
`tool_input {kind, count}` as "Image generation · 3 illustrations". The live label is
"Generating 3 images…".
