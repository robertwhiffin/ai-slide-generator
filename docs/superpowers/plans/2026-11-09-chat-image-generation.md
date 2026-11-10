# Plan: AI image generation in the chat (architect tool + options card), extending PR #376

## Context

PR #376 added AI image generation to the Image Library, plus an admin toggle and a graph-engine fix for slide-style image guidelines. Maintainer review:

- **"It needs to be available in the chat… maybe as a tool for the architect to call."**
- **"Most people don't get past the chat box."** He wants a "Generate image" button on the main page and, in keeping with the "do everything through chat" direction, it should be callable by the architect.
- **The target flow:** a user says "make me a picture to get this message across" and the AI generates it.
- **The next step:** "AI generates 3 pictures, user picks one or regenerates."

**User decisions:**
1. The button **routes through chat**: it sends a message that the architect handles.
2. **Include the 3-options flow** now.
3. **Extend PR #376** on the same branch, `feat/ai-image-generation`. Keep the Library generation, toggles and graph fix as they are.

**Intended outcome:** in an agent-mode deck, a user can ask for a picture in the chat, or press "Generate image".
- The architect generates 3 options in parallel, shows them in a chat card, and the user clicks "Use this" or "Regenerate".
- When the user says exactly what they want ("add a shield icon to slide 2"), it generates one image and places it directly.

## Design

### Where the guidance lives
The architect gets a new code-defined tool, `generate_image`. All usage guidance lives in the tool's description, so there is **no change to the architect's agent-definition prompt**. Reasons:
- Prompts are versioned in the database and only auto-ship to installs nobody has hand-edited.
- Tool descriptions are code and always ship.
- This follows the precedent set for Gateway MCP tools.
- The builder already places any `{{image:ID}}` a slide brief supplies (builder IMAGE RULES).

### The tool
- **One call** makes 1-3 images **in parallel**, because the tool loop only runs one tool call per round.
- **Images are saved** to the Image Library as the turn's user. They get the preset's category and these tags: `ai_generated`, the model, the preset, `chat`, plus `chat_option` when there are several.
- **The result text is facts only**, spotlighted: `Option N: {{image:TOKEN}} …`.
- **Caps** (enforced in code): 2 calls, 3 images per call, 6 images per turn, a 240 s budget, no call within 30 s of the 700 s turn deadline, and an explicit wall-clock wait.
- **Failure messages are fixed text**, never the exception text.

### Turn handling
- **Options card.** A discuss turn with images attaches `generated_images` metadata to the architect's reply. The frontend renders it as a card: thumbnails, "Use this" on unplaced images, and "Regenerate".
  - "Use this" sends a normal chat message ("Use option 2 on slide 3.") with `image_ids=[token]` through the existing attachment path, and the architect places it.
  - The next turn's conversation replays a system note listing the options, so typed requests like "use the second one" also work.
- **Bookkeeping** uses new turn-scoped keys, `generated_images` and `image_tool_usage`. This keeps Gateway budgets and notices separate.
- **Image-reference safety.** The architect's reference reconciliation and the builder's allow-list now run whenever this turn generated images, not only on Gateway turns.
- **Out of scope:** the monolith (legacy mode). The button is hidden for legacy decks.

## Tasks

**Process.** Every task carries a `Models:` tag, per the executing-plans-tellr skill:
- an Opus test author writes failing behavioural tests;
- the implementer makes them pass;
- the controller reviews and runs the sabotage checks;
- an Opus whole-branch review comes at the end.

The plan is copied to `docs/superpowers/plans/2026-11-09-chat-image-generation.md`, with a `-CORRECTIONS.md` file next to it.

### Task 0: Pre-flight
`Models: test=n/a impl=opus (controller)`

- Run `uv sync --extra dev`.
- Record the unit and frontend baselines by failure cause.

### Task 1: Service seams
`Models: test=opus impl=haiku`

**`src/services/image_generation.py`:**
- `generate(..., *, timeout_s=None)`. The effective timeout is `min(preset.timeout_s, max(5, timeout_s))`.
- `generation_available(db)`, which returns `is_enabled() and workspace_settings.image_generation_enabled(db)`.

**`src/api/routes/image_generation.py`:**
- `_effective_enabled` delegates to `generation_available`, so the routes and the graph never disagree.

**Tests:**
- The timeout reaches `responses.create`: values 30, None, 999, and SVG.
- `generation_available` truth table.

**Sabotage:** drop the `min`; ignore the override.

### Task 2: The tool
`Models: test=opus impl=sonnet`

New file: `src/services/agent_tools/image_generation_tool.py`.

```python
IMAGE_TOOL_NAME = "generate_image"
MAX_CALLS_PER_TURN = 2
MAX_PER_CALL = 3
MAX_IMAGES_PER_TURN = 6
BUDGET_SECONDS = 240.0
MIN_START_SECONDS = 30.0
KIND_TO_PRESET = {
    "illustration": "illustration",
    "background": "background",
    "icon": "icon_png",
    "vector_icon": "icon_svg",
}

class ImageGenerationArgs(BaseModel):
    prompt: str
    kind: Literal["illustration", "background", "icon", "vector_icon"]
    count: int = Field(1, ge=1, le=3)
    for_slide: int | None = Field(None, ge=1)

@dataclass(frozen=True)
class ImageToolContext:
    owner: str | None
    session_id: str | None
    on_call: Callable[[str, int], None]
    calls_left: int
    images_left: int
    seconds_left: float
    deadline_at: float | None
    generator_factory: Callable[[], ImageGenerator] = ImageGenerator
    save: Callable[..., str] = save_to_library

class ImageGenerationAgentTool:  # AgentTool
    name = IMAGE_TOOL_NAME
    description = IMAGE_TOOL_DESCRIPTION
    args_schema = ImageGenerationArgs

    def run(self, args, *, remaining_seconds) -> str: ...
    def saved_tokens(self) -> list[str]: ...
    generated: list[dict]  # what this tool made, for the turn's bookkeeping
```

**How `run` works:**
1. Compute `wall` = the minimum of `remaining_seconds`, `seconds_left` and the time to `deadline_at`.
2. Refuse (code-owned text, nothing started) when calls or images are used up, or `wall < 30` s.
3. Acquire slots from a per-process semaphore of 6, without blocking.
4. Call `on_call(kind, n)` for the progress line.
5. Run the generations on a module-level `ThreadPoolExecutor(max_workers=6)`.
6. Wait on all of them with `wait(timeout=wall)`. Stragglers are abandoned before they save.
7. Report failures as fixed text: busy (429), not allowed (403), did not finish in time, could not be generated.
8. Return the spotlighted facts.

**`IMAGE_TOOL_DESCRIPTION`** carries the usage rules:
- Call it only when the user explicitly asks for a picture, illustration, icon, visual or background. Never for a plain deck build.
- Open-ended asks: count=3, intent `discuss`, place nothing, ask the user to pick.
- Exact asks: count=1 and place the image in the same answer.
- Placing: put the exact `{{image:…}}` in that slide's `content_brief`, with where it goes and how big. Never write a reference in `message`.
- Prompt: match the palette and style from `resolved_style` / `deck_style`, with no text in the image.
- Explain each `kind`, and say "at most 2 calls".

**Also:** add `"generate_image"` to `_RESERVED_NAMES` in `src/services/agent_tools/gateway_toolset.py`, so a Gateway tool with the same name gets prefixed.

**Tests** (`tests/unit/test_image_generation_tool.py`), using a fake generator built from barriers and events, and real SQLite saves:
- 3 generations run in parallel; 3 rows are saved with the owner, category and tags.
- Kind-to-preset mapping.
- The `images_left` and `calls_left` caps.
- Deadline and minimum-start refusals.
- `timeout_s <= wall`.
- A straggler returns within `wall + 1` s and its image is never saved.
- A 429 gives fixed text with no exception body.
- Semaphore busy.
- `count=4` is rejected.
- No `src.core.skills` import.
- The reserved-name prefixing.

**Sabotage:** `max_workers=1`; no abandon check; no call cap; return `str(exc)`; no deadline check; reserved name removed.

### Task 3: Binding in the graph
`Models: test=opus impl=opus`

**`src/services/graph/state.py`:** add `generated_images` and `image_tool_usage` (`turn_scoped_concat`, empty `[]`).

**`src/services/graph/nodes.py`:**
- `_image_generation_available()`: opens a DB session and calls `generation_available`. It is read per turn in the node thread, and any error means False.
- `_emit(..., tool_name=None, tool_input=None)`.
- `class _ImageToolPass(state, owner)`:
  - sums prior `image_tool_usage`;
  - `tool()` returns a fresh tool per attempt, sized with `turn_budget()`;
  - also has `without_tools(exc, ts)`, `spent_seconds`, `generated()`, `saved_tokens()` and `usage()`;
  - `_on_call` emits a `TOOL_CALL` event with **top-level** `tool_name="image_generation"` and `tool_input={kind,count}`, and persists a `tool_call` row "Generating 3 illustrations".
- `_architect_toolset(gateway, images)` merges the Gateway tools and the image tool into one `AgentToolset`. The call cap is the Gateway cap plus the image calls left.
- `_GatewayPass.spent(..., exclude_seconds=0.0)`, so image time isn't charged to the Gateway budget.

**`architect_node`:**
- Bind images when `not describe_only and _image_generation_available()`.
- Compute `known_images` when the Gateway or images are present.
- Fall back without tools with `gw.without_tools(...) | images.without_tools(...)`. The non-short-circuiting `|` matters.
- Write the two state keys on every return path.

**Test fixture:**
- An autouse fixture in `tests/conftest.py` sets `nodes._image_generation_available → False` unless a test is marked `@pytest.mark.image_tool`.
- Register the marker in `pyproject.toml`.
- This keeps the roughly 22 existing architect test files, which assert `toolset is None`, unchanged.

**Tests** (`tests/unit/test_graph_image_tool.py`), using shared fake-runtime helpers moved to `tests/fixtures/graph_tool_runtime.py`:
- With the feature on and no Gateway, the toolset is exactly `["generate_image"]`, with a 2-call budget.
- Env or admin off → no toolset and no state keys.
- `describe_only` → no toolset.
- Gateway plus images → merged, with a 14-call budget.
- A second pass after 2 calls → no tool.
- Past the deadline → no tool.
- A raising call that carried only the image tool is retried without tools and the turn commits.
- One `tool_call` row and one top-level SSE event.

**Sabotage:** drop the `describe_only` check; drop `images.without_tools`; use a short-circuiting `or`; remove the conftest fixture (existing tests go red).

### Task 4: What the turn records and reports
`Models: test=opus impl=sonnet`

All in `nodes.py`:
- `_turn_tool_images(state)` covers Gateway plus generated images. It replaces `_turn_gateway_images` in `known_images` and in `build_branch_payload`.
- **Builder allow-list gate:** `gateway_usage or generated tokens`.
- **Architect reconciliation** runs when there is a Gateway pass, or this turn generated images. A turn with the tool bound but unused behaves exactly as today.
- **The "not placed" notice** for generated images reads "A generated image couldn't be placed on slide N." The Gateway wording stays as it is.
- **`_say_architect_message(..., metadata=None)`** puts metadata on both the row and the event.
- **`_with_option_labels(message, refs)`** rewrites any generated `{{image:…}}` in the reply text to "option N".
- **`_generated_images_metadata(refs, spec)`** builds `[{token, kind, option, prompt≤300, for_slide, slides:[…]}]`.
  - `slides` is computed from the committed canonical spec, after the insert re-stamp and the composed operations.
  - It is the 1-based index of each slide whose `refs_in(slide)` contains the token.
  - It is `[]` for discuss, ask_data and confirm.
- **`_degrade_edit(..., extra_metadata=None)`** carries the images on a refused turn too.
- **`_conversation`** replays a system note after any assistant row with valid `generated_images`: "Images generated with the reply above…: option 1 {{image:A}} (illustration, on slide 2); option 2 … To use one, put its exact reference in that slide's content_brief." It tolerates malformed rows.

**Tests:**
- Discuss with 3 options: the metadata has 3 entries with `slides == []`, and the reply text has no tokens.
- An edit placing option 1 on slide 2: `slides == [2]`, the builder allow-list contains the token, and an invented reference is stripped with the notice.
- An insert gives canonical numbering.
- A mistyped token tail is corrected.
- Unused tool → today's behaviour.
- The replay note appears; junk metadata is safe.
- A refused edit keeps its images.
- Update the pinned `_EMPTY_FOR` set and `_EXPECTED_NODE_WRITES`.

**Sabotage:** compute `slides` before the re-stamp; leave the builder gate unchanged; drop the note; skip the reply clean-up; reconcile on every turn.

### Task 5: Polling allowlist
`Models: test=opus impl=haiku`

**`src/api/services/session_manager.py`:** today `msg_to_stream_event` forwards only `details` and `sign_in_url`. Extend it to also forward a validated `generated_images` list:
- each token must match `^[A-Za-z0-9_-]+$`;
- only these keys are kept: `token, kind, option, prompt, for_slide, slides`;
- malformed entries are dropped.

**Tests** (`tests/unit/test_poll_generated_images.py`):
- Valid metadata is forwarded exactly; junk is dropped.
- A `tool_call` row's `tool_input` doesn't leak.
- `details` and `sign_in_url` are unchanged.

**Sabotage:** forward the whole metadata; skip validation.

### Task 6: Frontend plumbing
`Models: test=opus impl=sonnet`

- **Types:** `GeneratedImageRef` and `Message.generated_images` in `types/message.ts`, plus `utils/generatedImages.ts` with `readGeneratedImages(unknown)`.
- **`ChatPanel.tsx`:** map the field on reload (`loadSessionMessages`) and in the SSE/poll `assistant` event.
- **`api.getImage(token)`:** `GET /api/images/{token}`, an existing route that returns `thumbnail_base64`.
- **`hooks/useImageGenerationOptions.ts`:**
  - a module-level cached probe with a 5-minute TTL;
  - `invalidateImageGenerationOptions()`;
  - used by `ImageLibrary`; `AdminImageGeneration` invalidates it after a save.
- **`ToolActivityBar` / `toolCallLabel`:** special-case `image_generation`, showing "Image generation · 3 illustrations" and the live label "Generating 3 images…".

**Tests:**
- Card from reloaded rows; card from an SSE event; no card for malformed metadata.
- The activity label.
- The hook dedupes fetches and invalidation refetches.
- Update the `ImageLibrary` test to reset the cache.

### Task 7: Options card and actions
`Models: test=opus impl=sonnet`

**New `components/ChatPanel/GeneratedImagesCard.tsx`:**
- Thumbnails come from `getImage`, with a placeholder on error.
- Each image has an "Option N" label and an "On slide N" badge.
- "Use this" appears only on unplaced images; "Regenerate" is always there.
- Caption: "Saved to your Image Library".

**Wiring:** rendered by `Message.tsx` under the assistant bubble. `MessageList` and `ChatPanel` pass the actions, which are disabled while loading and hidden in save-point preview.

**`utils/imageChatMessages.ts`:**
- `useImageMessage(img)` → "Use option 2 on slide 3.", sent with `imageIds=[token]` through the existing `ChatPanel.handleSendMessage(content, imageIds)`. The graph ignores `slide_context`, so the slide number is always in the text.
- `regenerateMessage(images)` and `generateImageMessage({prompt, kind, options, forSlide})`.

**Tests:**
- The card's rendering rules.
- Clicking Use sends the exact text plus `["tok2"]`; Regenerate sends no ids; no buttons in preview.
- Pure tests for the message builders.

**Sabotage:** omit `imageIds`; show Use on placed images.

### Task 8: Entry points (main-page button)
`Models: test=opus impl=sonnet`

**New `components/ChatPanel/GenerateImageRequestDialog.tsx`:**
- A prompt field.
- Kind chips: Illustration, Icon, Background, Vector icon.
- A "Show me 3 options" toggle, on by default.
- An optional "For slide" select.

**`ChatInput.tsx`:**
- A labelled **Generate image** button (`WandSparkles`) in the hint row. It opens the dialog and calls `onSend(generateImageMessage(...))`.
- It is shown only when the feature is available and the deck mode is `agent`, never `legacy`.

**`SlideViewer.tsx`** (stage toolbar, next to Optimize layout): a **Generate image for this slide** action that opens the same dialog with `forSlide = currentIndex + 1`.

**Optional:** a `ChatWelcome` tip.

**Tests:**
- The button is hidden when unavailable or in legacy mode.
- The dialog sends the exact text.
- The stage action names the slide.
- New Playwright spec `frontend/tests/e2e/chat-image-generation.spec.ts`, mocking `/generate/available`, `/api/chat/stream` with `generated_images` and `/api/images/tok*`:
  - the dialog sends the right request body;
  - 3 thumbnails render;
  - Use sends `image_ids: ["tok2"]`.

**Sabotage:** show the button regardless of availability; leave out the slide number.

### Task 9: Eval parity
`Models: test=opus impl=sonnet (controller-run, spend cap)`

- **`evals/harness/runner.py`:** bind the real tool, with its real description, for the architect, using a fake generator and saver. Opt-in via config.
- **6-8 architect cases:**
  - an open-ended ask → count 3 and discuss;
  - "add a shield icon to slide 2" → count 1, an edit, and the token in slide 2's brief;
  - "build me a deck on X" → no call;
  - "make slide 4 more concise" → no call;
  - an empty deck with "make me a picture" → discuss.
- A scorer in `scorers.py`.
- This measures whether the description-only guidance is enough.

### Task 10: Live check, docs and PR
`Models: impl=opus (controller)`

- Run the live script below, then the whole-branch Opus review.
- Docs:
  - a "Chat image generation" section in `docs/technical/image-upload.md`;
  - update the findings doc (follow-up 3 is now done, and builder → architect);
  - the `src/core/skills/architect.py` docstring only, not `INSTRUCTIONS`.
- Update the PR #376 description.
- Push the branch and update the PR.
- Commit and PR trailers as before.

## Interactions with existing guards
- **Gateway client AST guard:** stays green. The tool only uses `ImageGenerator()` and its `default_client`.
- **Routes and authz inventories:** no new routes. The UI uses `GET /api/images/{token}` and `/generate/available`.
- **Payload-key fixtures:** no new architect payload keys; only the conversation content grows. `gateway_known_images` stays branch-only.
- **Prompt and manifest hash pins:** untouched, because `INSTRUCTIONS` doesn't change.
- **Pinned state tables:** `_EMPTY_FOR` and `_EXPECTED_NODE_WRITES` get updated.
- **Gateway-gated code:** `_GatewayNotices` and the Gateway budget sums are unchanged. Only the builder allow-list gate is widened, and `spent` excludes image seconds.

## Verification

**Automated:**
- `uv run pytest tests/unit -q -n auto`, compared against the baseline causes.
- The integration suites: `test_graph_orchestration.py`, `test_api_routes.py`, `test_image_api.py` and the slide-deck suites.
- `cd frontend && npx tsc -b && npx vite build && npm run test:unit`.
- The new Playwright spec, plus `06-uploading-images` and `admin-page`.
- Sabotage checks per task.

**Live, on the local app** (as before: backend `:8010`, OAuth `DEFAULT` profile, `run_local.sh`):
1. Build a 4-slide agent deck.
2. "Make me a picture to get slide 2's message across."
   - Expect the "Image generation · 3 illustrations" row, a discuss reply, and a card with 3 options.
   - The logs show 3 parallel `image generation:` lines.
   - The slides are unchanged (`content_hash`).
   - Note whether the model chose 3 or 1.
3. "Give me 3 icon options for slide 3." Expect 3 icons.
4. **Use this** on option 2.
   - The user bubble reads "Use option 2 on slide 3.", followed by an edit turn.
   - The deck spec's slide 3 `content_brief` has `{{image:TOKEN2}}`.
   - The stored `session_slides.html` at position 2 contains the token.
   - Look at the rendered slide.
5. **Regenerate** gives 3 new tokens. Then "use the second one on slide 1" works (the replay note).
6. "Add a calm blue background image to slide 1": count 1, an edit, and the card badge "On slide 1".
7. Negative checks:
   - "Make slide 4 more concise" → no image activity;
   - admin toggle off → no generation;
   - Legacy deck → no button.
8. Polling transport (`VITE_USE_POLLING=true`): the card arrives live and survives a reload.
9. Main-page **Generate image** button and the stage **Generate image for this slide** action send the expected messages.
10. Image Library rows have the tags `ai_generated`, `chat` and `chat_option`, with the right owner.
11. Record turn times (discuss turns expected around 20-45 s).

Optionally redeploy to a single-user dev app with the source overlay, for a multi-worker polling check.

## Risks
- **Model compliance with description-only guidance.**
  - Mitigations: code-enforced caps, option labels rewritten in the reply, a card that renders whatever the reply says, the Task 9 evals, and the live steps.
  - Escalation path: tighten the description; then bind only on an image-intent keyword match; a conditional manifest addendum via `evals.harness.promote` comes last.
- **Cost.** Up to 6 images per turn, paid by the app's service principal.
  - Controls: the caps, the env and admin switches, a semaphore of 6 per process, and tags plus `session_id` for attribution.
  - Lever if needed: options at `low` quality.
- **Every web-deck architect call now runs through the tool loop.** It's the same single call when the tool isn't used, plus about 300 tokens of tool definition. The fallback without tools covers provider errors, and the switches unbind it completely.
- **Leftover options in the shared Library.** They're tagged `chat_option`; stragglers are never saved. Follow-up: an owner-only filter, or promote-on-place.
- **Latency.** About 20-40 s for a discuss turn with options, well within the 700 s and 1,200 s limits.
- **Known existing gap** (not fixed here; noted in the PR): Gateway progress lines don't render live over SSE, because the frontend reads top-level `tool_name`. The image tool's event sets it.
