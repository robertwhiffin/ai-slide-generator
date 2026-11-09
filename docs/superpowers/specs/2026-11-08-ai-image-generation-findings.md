# Findings: AI image generation in the Image Library

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
  it only uses images it is given (style guidelines, chat attachments, the HTML editor's picker).
- **The database URL is logged at WARNING on every engine creation**, first 50 characters
  (`src/core/database.py`, `get_engine`). For a `databricks://token:<PAT>@...` URL that includes
  part of the token.

## Follow-ups worth pitching

1. **On-brand assets from a design system.** Use a design system's colour and typography tokens, plus
   its logo as a labelled reference image, to generate backgrounds, illustrations and **consistent
   icon sets**: generate one icon, then use it as the style reference for the rest of the deck's
   icons.
2. **Agent-generated imagery.** A `generate_image` tool for the graph-engine slide builder (same
   pattern as brand search), so decks get bespoke icons and backgrounds when the library has nothing
   suitable. This should come with wiring library search and `image_guidelines` into the graph
   engine.

## How it was verified on a dev app

The dev app installs the released `databricks-tellr-app==0.5.6` wheel for all dependencies. The
branch's `src/` and frontend build are shipped alongside it as a source overlay of about 7 MB. No
wheel is built and nothing is published to PyPI. Rollback is one command: redeploy the app from its
original source path. That is data-safe because the change adds no schema changes.
