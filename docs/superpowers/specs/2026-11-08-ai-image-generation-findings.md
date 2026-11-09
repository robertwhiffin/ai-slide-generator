# Findings: AI image generation in the Image Library and the chat

Status: proposed in this PR. Built as a prototype and verified on a laptop and on a single-user
dev app before review.

## What was built

- **Generate** in the Image Library: a prompt, a slide-oriented preset, a model and a quality. The
  result is saved as an ordinary library image, usable anywhere through `{{image:TOKEN}}` (HTML
  editor image picker, slide styles, decks).
- **Edit with prompt** on any raster library image. An edit always creates a new image; the source
  is never changed.
- Four presets aimed at slides: 16:9 background (2048x1152 JPEG), illustration (1536x1024 JPEG),
  transparent icon (1024x1024 PNG) and vector icon (SVG, GPT Image 2.6 models only).
- Generated images get an "AI" badge, their prompt as the description (so library search finds
  them) and tags with the model and preset.
- On by default, with two off switches: a deployment opts out with
  `TELLR_IMAGE_GENERATION_ENABLED=0`, and an admin can turn it off under Admin > Connections.
- Defaults to GPT Image 2.6 Flare at medium, with a "when to choose" explainer under the model and
  quality pickers.
- Images placed in a slide style's image guidelines are now used by deck generation on the default
  (graph) engine. Before this change they were silently dropped.

It uses the Responses API `image_generation` tool, driven through Tellr's existing AI Gateway
client.

### In the chat (second iteration, after review feedback)

Review feedback was that most people never leave the chat, so image generation has to be available
there, callable by the architect, with "make me a picture to get this message across" producing 3
options to choose from or regenerate.

- **The architect's tool.** The graph engine's architect gets a `generate_image` tool whenever image
  generation is available. All its guidance is in the tool description, not the agent prompt:
  - an open-ended ask gets 3 options in a discuss reply, with nothing placed;
  - an exact ask ("add a shield icon to slide 2") gets 1 image placed on that slide.
- **The options card.** A reply that generated images shows them as a card under it: thumbnails,
  **Use this** and **Regenerate**. Both actions send an ordinary chat message, so the architect
  does the work, and "use the second one" typed later works too.
- **Entry points.** A **Generate image** button in the chat input and **Generate image for this
  slide** on the stage open one dialog that composes the request. Both show only on agent-mode
  decks while the feature is on.
- **Limits, in code.** 2 calls, 3 images per call and 6 per turn, 240 s, and 6 concurrent
  generations per process. Images in one call run in parallel.

## Headline results

| Question | Answer |
|---|---|
| Does the AI Gateway carry the `image_generation` tool? | Yes. Tellr's existing `gateway_openai_client` works unchanged, so Tellr keeps "every model call goes through the Gateway" and its `source=tellr` request tags. |
| Can responses be read non-streamed? | Not for rasters. Both the Gateway and `/serving-endpoints` reject responses over 655,360 bytes (`MAX_READ_SIZE_EXCEEDED`), and a 1024x1024 PNG is about 780 KB. Raster calls must stream. SVG (a few KB) works non-streamed. |
| Live previews while generating? | No. The Gateway sends no partial frames, even when `partial_images` is requested (`/serving-endpoints` sent one). |
| Which orchestrator model? | `system.ai.gpt-5-5` is rate limited to 0 on the test workspace. `gpt-5-4-nano` works as well as larger models when `tool_choice` forces the tool, so it is the default (configurable). |
| How long does an image take? | 8 to 21 s end to end through the app, well under the 60 s Apps proxy limit. The app still uses start-job-and-poll, so slower images are safe. |
| Do transparent icons work? | Yes. Composited onto white they are clean flat icons; 73 to 93% of pixels are fully transparent and only 0.6 to 2% are soft edges. |

## Latency and size (measured through the running app)

| Preset | Model, quality | Time | Output |
|---|---|---|---|
| Icon (PNG) | gpt-image-2.5-flare, low | 13.0 s | 676 KB PNG, outline style |
| Icon (PNG) | gpt-image-2.5-flare, medium | 12.1 s | 674 KB PNG, filled style |
| Icon (PNG) | gpt-image-2.5-sunburst, low | 12.1 s | 658 KB PNG |
| Icon (PNG) | gpt-image-2.6-flare, low or medium | 8.1 s | 735 to 754 KB PNG, fills the frame best |
| Icon (PNG) | gpt-image-2.6-sunburst, medium | 22.2 s | slowest model |
| Background 16:9 | gpt-image-2.5-flare, low | 10.4 s | 67 KB JPEG |
| Illustration | gpt-image-2.5-flare, low or medium | 14.2 to 14.6 s | 198 to 230 KB JPEG |
| Illustration | gpt-image-2.6-flare, medium | 10.3 s | 162 KB JPEG, crisp and slide-friendly |
| Illustration | gpt-image-2.6-flare, high | 12.1 s | 281 KB JPEG, most detail |
| Illustration | gpt-image-2.5-sunburst, medium | 18.2 s | 159 KB JPEG |
| Background 16:9 | gpt-image-2.6-flare, medium or high | 8.1 s | 75 KB JPEG |
| Icon (SVG) | gpt-image-2.6-flare, low or medium | 14.1 to 20.5 s | 2 to 4 KB SVG |
| Edit (transparent icon) | gpt-image-2.5-flare, low | 14.2 to 19.5 s | 0.5 to 1.8 MB PNG |
| Edit (transparent icon) | gpt-image-2.6-flare, medium | 12.1 s | stays transparent |

Recommended default: **GPT Image 2.6 Flare at medium**. It is the fastest model with clean slide
output, and medium costs about the same time as low. High is worth it for hero images; 2.5 Sunburst
and 2.6 Sunburst are slower and best kept for detailed work or very precise edits.

Each call also spends about 2,400 to 2,900 orchestrator input tokens. Per-image cost is not
measured here; `system.ai_gateway.usage` has it per request.

## Things we learned the hard way

- **Edits of transparent images must be flattened first.** Sent with its alpha channel, a transparent
  icon is read as if it sat on black. The edit comes back as a dark "neon" image with no usable
  transparency (alpha never drops below about 60). Showing the model the icon on white, while the
  tool still asks for a transparent PNG, returns a clean transparent edit.
- **An alpha channel is not transparency.** Screenshots and design-tool exports are often RGBA with
  every pixel opaque. Treating those as transparent would ask the model to cut out a background the
  user wants kept, so transparency is judged from real alpha values.
- **`reasoning.effort` is forwarded to the image model as `complexity`**, which only the 2.6 models
  accept. It must not be sent with 2.5 models.
- **`DatabricksOpenAI.with_options()` is broken** in databricks-openai 0.17.1 (it raises a
  `TypeError`). Client options such as `max_retries=0` have to be passed at construction, so
  `gateway_openai_client` now forwards keyword arguments. SDK retries are off because a retry is a
  second paid image.

- **A model with no tool can still claim to have used it.** With the admin switch off, a session
  whose earlier replies showed generated options got "I made three picture options ... shown below
  this reply", with nothing generated: the model followed its own earlier replies. When the tool is
  not bound and the conversation shows generated images, the architect is now told image generation
  is not available, and it says so (it even corrected the earlier claim).
- **Never echo a model-written prompt as the user's words.** Regenerate first re-sent the stored
  prompt, cut to 300 characters, in the user's bubble. The architect read it as the user's text
  "cut off" and said so. Regenerate now sends a short request and relies on the conversation.

## How it is put together

- `src/services/image_generation.py`: presets, the tool builder (only parameters verified on the
  Gateway are sent), the generator, `fit_to_library` (keeps output inside the library's 5 MB cap and
  allowed types) and saving.
- `src/api/services/image_generation_jobs.py` and `src/api/routes/image_generation.py`:
  `POST /api/images/generate` and `POST /api/images/{token}/edit` start an owner-scoped job and
  return 202; the browser polls `GET /api/images/generate/jobs/{job_id}`.
  - Jobs reuse the `export_jobs` table, with `session_id = image-generation:<owner>`. Existing export
    routes cannot see them.
  - Status writes are conditional, so a slow job and the stale-job timeout cannot overwrite each other.
- Frontend: `GenerateImageDialog`, plus changes to the Image Library and an `AdminImageGeneration`
  switch.
- No schema changes.

## Risks and open questions

- **Hard-coded model list.** A config-driven list would let a workspace offer only the image models
  it has.
- **Identity and cost.** Calls run as the app service principal, so there is no per-user cost
  attribution and no per-user quota. The admin switch and an in-process cap of 4 concurrent jobs are
  the only controls today.
- **`export_jobs` reuse.** It is fine for a first version, but it breaks that table's "every row belongs to a
  deck" invariant. Production should have a dedicated table.
- **Payload size.** `{{image}}` placeholders are inlined as base64 when decks are served, so large
  PNG icons (0.7 to 1.8 MB) make decks heavier. JPEG is used wherever transparency is not needed.
- **Not hardened yet.** There is no wall-clock deadline on a streamed call (httpx's timeout is
  per-read) and no byte cap on the edit input.

### Measured in the chat (local app, graph engine, 4-slide deck)

| Turn | Time |
|---|---|
| "Make me a picture to get slide 2's message across" (3 illustrations, discuss) | 24 s |
| "Give me 3 icon options for slide 3" | 26 s |
| Regenerate (3 new illustrations) | 21 s |
| **Use this** on an icon (edit, slide rebuilt and reviewed) | 59 s |
| Exact ask from the Generate image dialog (1 background, placed on slide 1) | 64 s |

The 3 images of an options turn are generated in parallel in about 15 s. The deck had no image
activity on "Make slide 4 more concise", and with the admin switch off the architect said image
generation was not available.

### Does description-only guidance work? (architect evals)

The architect gets no prompt change; everything is in the tool description. The eval harness binds
the real tool over fake backends (`--case-set image_tool`, `evals/configs/architect/image-tool.yaml`),
with 8 cases, 3 repeats each, and a deterministic scorer (count, kind, intent, and where the reference
ends up):

| Run | Image-tool pass rate |
|---|---|
| First description | 22 / 24 |
| Tightened description (open-ended is the default, even for "a picture") | 24 / 24 |
| The 22 ordinary architect cases with the tool bound (no image asked for) | 22 / 22, no call made |

Both early failures were the review's own phrase, "make me a picture to get slide 2's message
across": in 2 of 3 runs the architect made one image and placed it instead of offering 3.

## Gaps found in Tellr itself (not caused by this change)

- **The default (graph) engine ignored slide-style image guidelines** (fixed in this change).
  `_resolve_brand` in `src/services/graph/nodes.py` dropped them, so an image an author put in a
  style never reached the architect or the builders. Reproduced live: a 2-slide deck on such a style
  used no image. This change passes the guidelines inside `resolved_style` with a short header that
  tells the architect to name the image in a slide's brief, and the same deck now places the icon on
  the title slide. This is a standalone fix worth upstreaming on its own.
- **The opaque image token migration missed slide styles.** It rewrote `{{image:N}}` placeholders in
  decks but not in `slide_style_library.image_guidelines`, so a style written before the migration
  still says `{{image:3}}` and never resolves. Found on a dev app (its Databricks Brand
  style) and fixed there by hand; every deployment with a pre-token style has the same breakage.
- **The graph engine still has no `search_images` tool**, so it cannot find library images by itself;
  it only uses images it is given (style guidelines, chat attachments, the HTML editor's picker, and
  now the images its own `generate_image` tool makes).
- **Slides streamed during a graph turn carry raw `{{image:…}}` placeholders.** Neither the
  `slide_ready` SSE event nor `GET /chat/poll`'s slides substitute image placeholders (they do
  substitute page numbers and design-system assets), so a slide with a newly placed image shows it
  broken until the turn ends and the deck is reloaded (about 2 s in testing). It applies to any
  image a graph turn places, not only generated ones.
- **The database URL is logged at WARNING on every engine creation**, first 50 characters
  (`src/core/database.py`, `get_engine`). For a `databricks://token:<PAT>@...` URL that includes
  part of the token.

## Follow-ups worth pitching

1. **On-brand assets from a design system.** Use a design system's colour and typography tokens, plus
   its logo as a labelled reference image, to generate backgrounds, illustrations and **consistent
   icon sets**: generate one icon, then use it as the style reference for the rest of the deck's
   icons.
2. **Agent-generated imagery: done for the architect** (the chat iteration above). Still open:
   library search for the graph engine, so it can reuse an image before generating one, and an
   owner-only or "options" filter in the Image Library, since unused options are kept there
   (tagged `chat_option`).

## How it was verified on a dev app

The dev app installs the released `databricks-tellr-app==0.5.6` wheel for all dependencies. The
branch's `src/` and frontend build are shipped alongside it as a source overlay of about 7 MB. No
wheel is built and nothing is published to PyPI. Rollback is one command: redeploy the app from its
original source path. That is data-safe because the change adds no schema changes.
