# AI image generation in the Tellr Image Library

## Context

Add AI image generation to Tellr, built first as a prototype: one feature end to end, verified on a single-user dev app, measured, and written up in `docs/superpowers/specs/2026-11-08-ai-image-generation-findings.md`. It uses the Responses API `image_generation` tool, which generates and edits images with the gpt-image 2.5/2.6 models, called through the AI Gateway.5/2.6 models via the Responses API `image_generation` tool on `databricks-gpt-5-5`. The newer models render native transparent PNGs and (2.6) SVG vectors, which makes **slide iconography** a headline use case.

**In scope:** "Generate" and "Edit with prompt" in the Image Library, saving results as normal `image_assets` rows usable everywhere via `{{image:TOKEN}}`.
**Follow-ups (designed for, not built):** (2) on-brand assets from a design system, (3) agent-generated slide imagery.

**Constraints**
- No schema changes (keeps data and rollback clean).
- Originally everything behind `TELLR_IMAGE_GENERATION_ENABLED=1`. It ships **on by default**, with a deployment off switch (`TELLR_IMAGE_GENERATION_ENABLED=0`) and an admin off switch (corrections doc, Unit D and C15).

## Findings that shape the design

- Image model is a tool inside a Responses call on `databricks-gpt-5-5` (READY on the dev workspace; no standalone gpt-image endpoints). The `/serving-endpoints` route would also work, but Tellr routes **every** model call through the AI Gateway (`src/services/gateway_clients.py`, enforced by AST guard `tests/unit/test_gateway_clients.py`). Gateway support for the `image_generation` tool is **unverified**, hence Task 0.
- Apps reverse proxy has a **60 s timeout** (`docs/technical/real-time-streaming.md`); SVG takes ~60 s. So: **start job + poll**, reusing `export_jobs` (`session_id` is a plain string, not an FK: `src/database/models/session.py`) and the frontend `pollExportJob` (`frontend/src/services/api.ts:324`). App runs 4 uvicorn workers, so job state lives in the DB.
- `image_service.upload_image` (`src/services/image_service.py`) caps 5 MB and allows png/jpeg/gif/svg only (no WebP). SVG is sanitized; SVG thumbnails are `None`.
- Default graph engine has **no** `search_images` tool and drops slide-style `image_guidelines` (`src/services/graph/nodes.py:1176`); chat attachments are upload/paste only. In-deck use of generated images in this change is via the HTML editor's `ImagePicker` (which embeds `ImageLibrary`, so the Generate button appears there too). Gap goes into findings / follow-up 3.
- All needed deps are already pinned in `packages/databricks-tellr-app/pyproject.toml` (openai 3.19.2, databricks-openai 0.17.1, Pillow 11.3.0). Local `.venv` is stale: run `uv sync --extra dev` first.
- Frontend learns about features via per-feature `GET .../available` probes (e.g. `export.py:876` + `api.ts:1618`). Reuse that pattern.

## Design

- **New service** `src/services/image_generation.py`: a Tellr-native implementation (presets, tool builder, data-URL helper, SVG safety check, generator, save).
- **Client:** `gateway_openai_client(get_system_client())` if Task 0 shows the Gateway works, via `client.with_options(timeout=180|240, max_retries=0)` (no silent paid retries). Fallback routes per Task 0.
- **Presets** (server is source of truth, sent via `/available`):

| id | size | format | background | category | models (default*) |
|---|---|---|---|---|---|
| `background` (Slide background 16:9) | 2048x1152 | jpeg | opaque | background | 2.5-flare*, 2.5-sunburst, 2.6-flare, 2.6-sunburst |
| `illustration` | 1536x1024 | jpeg | opaque | content | same |
| `icon_png` (transparent) | 1024x1024 | png | transparent | content | same |
| `icon_svg` (vector) | auto | svg | n/a | content | 2.6-flare*, 2.6-sunburst |

  Qualities low/medium/high. Each preset carries `art_direction` text (icons: single centered, flat, consistent stroke, no text, transparent; backgrounds: calm, negative space for titles, no text/logos).
- **Fit to library:** sniff real format with Pillow; WebP to PNG/JPEG; step JPEG quality / downscale 0.8 until under 5 MB, keeping alpha.
- **Metadata:** tags `["ai_generated", model, preset]` (edits add `ai_edit`); description = prompt (500 chars) so it's searchable; filename `ai-{slug}-{UTC stamp}-{uuid8}.{ext}` (same pattern as `make_image_saver`, `src/services/agent_tools/gateway_tool.py:297`). Generated SVGs get a data-URI thumbnail (≤200 KB).
- **Edit** always creates a new row; reuse `_deny_ephemeral_cross_user` from `src/api/routes/images.py`; SVG sources rejected (400).
- **Jobs:** `export_jobs` row with `session_id="image-generation:<owner>"`, result JSON in `output_path`; `ThreadPoolExecutor(max_workers=2)`, in-flight cap 4 (429 beyond); a job still running after 300 s reads as timed out. Owner captured in the route (`images_routes._get_current_user()`, called via module so tests can patch it).

## Tasks

Pre-flight: on `main` (0.5.6) create branch `feat/ai-image-generation`; `uv sync --extra dev`; record unit-test baseline by failure cause (`uv run pytest tests/unit -q -n auto`). Copy this plan to `docs/superpowers/plans/2026-11-08-ai-image-generation.md` on the branch (tasks carry `Models:` tags per executing-plans-tellr).

**Task 0: Probe (throwaway).** Models: test=n/a impl=opus (controller-run; external-state facts).
a probe script under `output/` (gitignored, outside the AST guard). Local OAuth via `~/.tellr/config.yaml` (`save_tellr_config(host, "external-browser")`, no PAT) or `WorkspaceClient(profile="DEFAULT")`. Try routes (a1) `gateway_openai_client` with `system.ai.gpt-5-5`, (a2) Gateway native `/ai-gateway/openai/v1`, (b) `/serving-endpoints` with `databricks-gpt-5-5`; cases: raster low 1024², raster streamed (partials), transparent PNG (check RGBA alpha), SVG on 2.6-flare (passes `check_static_svg` + `sanitize_svg`), edit with a data-URL input; variants `tool_choice` and `reasoning.effort=low`. Print route/case/status/latency/bytes/format/usage. `--matrix` mode feeds Task 8. **Branch:** a1 works → no gateway changes; only a2 → Task 2b; only b → isolated non-Gateway client with comment (flag as upstreaming blocker); none → stop and write findings.

**Task 1: Presets, tool builder, post-processing (pure).** Models: test=opus impl=sonnet.
`src/services/image_generation.py`: `IMAGE_MODELS`, `PRESETS` (frozen dataclass), `is_enabled()`, `resolve_request()`, `build_tool()`, `build_prompt()`, `to_data_url()`, `check_static_svg()`, `fit_to_library()`, `generated_filename()`. Tests `tests/unit/test_image_generation_core.py`: preset sizes pass the flexible-size rule; transparent presets never jpeg; SVG presets only list SVG-capable models; `fit_to_library` keeps alpha and lands under 5 MB.

**Task 2: Generator.** Models: test=opus impl=sonnet.
`ImageGenerator.generate()/edit()/_run()` returning `GeneratedImage`; parse `image_generation_call` items, base64 decode, SVG fence-strip + check. Tests `tests/unit/test_image_generation_client.py` with `install_mock_gateway_transport` (`tests/fixtures/mock_chat_completions.py`): path and tellr headers, tool payload, no-image → error, a 500 produces exactly one request (proves `max_retries=0`); gateway guard stays green.

**Task 2b (only if probe picks a2): third Gateway builder.** Models: test=opus impl=haiku. Add `gateway_openai_responses_client()` to `gateway_clients.py` + mirrored test.

**Task 3: Save to library.** Models: test=opus impl=sonnet.
`save_generated_image()` over `image_service.upload_image`, plus SVG thumbnail. Tests `tests/unit/test_image_generation_save.py`: metadata stored, RGBA thumbnail, SVG sanitized, no filename collisions, findable via `search_images`, retrievable via `get_image_base64`.

**Task 4: Job store + runner.** Models: test=opus impl=sonnet.
`src/api/services/image_generation_jobs.py`: `create_job`, `submit` (cap), `run_job` (never raises; 403 mapped to a clear SP-permission message), `get_job` (owner-only, ignores real export jobs, stale → error). Tests `tests/unit/test_image_generation_jobs.py`.

**Task 5: Routes + flag + authz inventory.** Models: test=opus impl=sonnet.
`src/api/routes/image_generation.py` (prefix `/api/images`): `GET /generate/available`, `POST /generate` (202), `POST /{token}/edit` (202), `GET /generate/jobs/{job_id}`; flag dependency → 404. Register in `src/api/main.py` after `images.router`. Add ALLOWLIST entry in `tests/unit/test_route_authz_coverage.py` for the job poll (owner-gated inline); update `tests/unit/test_app_wiring.py`. Tests `tests/unit/test_image_generation_routes.py` (flag off, happy path, validation 400/422/429, edit authz, cross-owner poll 404). Log one startup line `AI image generation is offered on this deployment` (used to verify the deploy overlay).

**Task 6: Frontend.** Models: test=opus impl=sonnet.
Types in `frontend/src/types/image.ts`; `imageGenerationOptions()`, `generateImage()`, `editImageWithPrompt()` in `api.ts` (reuse `pollExportJob`); new `frontend/src/components/ImageLibrary/GenerateImageDialog.tsx` (prompt, preset cards, model/quality, elapsed time, result + copy `{{image:TOKEN}}`); `ImageLibrary.tsx` gets a Generate button (hidden unless available) and an "Edit with prompt" tile action on raster images. Vitest: `GenerateImageDialog.test.tsx`, `ImageLibrary.generate.test.tsx`.

**Task 7 (optional): partial previews** via polling `preview_data_uri`, only if Task 0 shows streaming works on the chosen route. Models: test=opus impl=sonnet.

**Task 8: Findings write-up.** Models: test=n/a impl=opus (controller re-probes any number).
`docs/superpowers/specs/2026-11-08-ai-image-generation-findings.md` (screenshots kept out of the repo; no hostnames/tokens; no em dashes). Gateway route result, latency/size per model × preset × quality, alpha/SVG reliability, cost (`response.usage` + `system.ai_gateway.usage`), SP permission result, PPTX/Google Slides export behaviour for PNG/SVG icons, the graph-engine library gap, risks, and follow-up designs.

**Task 9: Verify on a single-user dev app (source overlay, no wheel, no PyPI).** Models: test=n/a impl=opus (controller-run).
Idea: keep the app's `requirements.txt` = `databricks-tellr-app==<release>` (all deps, huashu sidecar, release frontend) and ship the branch's `src/` + built frontend alongside. Apps run the command from the source dir, so `./src` shadows the wheel's `src` package (on `sys.path` first for `python -c` and `python -m`; uvicorn spawn workers inherit `sys.path`). Bundle is ~7 MB, under the ~10 MB cap.
1. Stage in a fresh dir outside the repo: `git archive <branch> src | tar -x -C <bundle>` (committed code only, no `__pycache__`); `cd frontend && npm ci && npm run build`, copy `dist` to `<bundle>/frontend-dist`; copy `requirements.txt` and `app.yaml` from the app's release source path (keyless, generated by `update()`).
2. Edit the bundle `app.yaml`: add env `TELLR_IMAGE_GENERATION_ENABLED: "1"`; before `python -m databricks_tellr_app.run` insert a step that replaces the installed package's `_assets/frontend` with `frontend-dist` (path resolved like the existing huashu `setup.sh` lookup).
3. `databricks workspace import-dir <bundle> /Workspace/Users/<you>/.apps/<app>-imagegen --overwrite`.
4. Ensure compute ACTIVE and no deployment in flight (`apps start` auto-redeploys the old source), then `databricks apps deploy <app> --source-code-path /Workspace/Users/<you>/.apps/<app>-imagegen`.
5. Verify: RUNNING; the startup log line appears once per worker; Image Library shows Generate (after the admin switch); one icon and one SVG succeed. On 403: grant the app SP access to the orchestrator model service.
6. **Rollback** (data-safe, no schema change): redeploy from the release source path. The app venv persists across deployments, so also force-reinstall the wheel or the overlay frontend keeps being served.

## Verification

- Backend: `uv run pytest tests/unit/test_image_generation_*.py tests/unit/test_gateway_clients.py tests/unit/test_route_authz_coverage.py tests/unit/test_app_wiring.py tests/unit/test_image_service.py tests/unit/test_authz_images.py -q`, then full `uv run pytest tests/unit -q -n auto` vs baseline causes; `uv run ruff check src tests`.
- Frontend: `cd frontend && npm run test:unit && npm run typecheck && npm run lint`.
- Sabotage checks (each must turn a test red): drop flag dependency; remove `max_retries=0`; skip owner check in `get_job`; flatten alpha in `fit_to_library`; drop SVG thumbnail; remove `_deny_ephemeral_cross_user` from edit; remove the ALLOWLIST entry.
- Local run: `.env` with `TELLR_IMAGE_GENERATION_ENABLED=1` (or OAuth `~/.tellr/config.yaml` mode), `./start_app.sh`, open `http://localhost:3000/images`.
- Demo checklist (local, then deployed): flag off hides button and POST 404s; 16:9 background lands under Background; transparent icon shows checkerboard; SVG thumbnail renders; edit creates a new tile and leaves the source unchanged; generate + insert an icon from the HTML editor's ImagePicker into a slide; export that slide to PPTX and Google Slides (PNG + SVG icon); refused prompt shows an error; record timings and screenshots.

## Risks

- Gateway may not pass the `image_generation` tool through; a `/serving-endpoints` fallback would be Tellr's only non-Gateway model call (loses `source=tellr` attribution). Key finding either way.
- `export_jobs` reuse breaks the "every ExportJob is session-bound" invariant (fails closed); production needs a dedicated table.
- Orchestrator may answer in text instead of calling the tool (`tool_choice` if supported); gpt-5-5 reasoning adds latency (`reasoning.effort` lever).
- Large backgrounds inflate deck payloads (base64 inlining at the API boundary); keep JPEG.
- Calls run as the app SP, so no per-user cost attribution or quotas yet.

## Follow-ups (not built)

- **(2) On-brand design-system assets:** read `design_system_token` colours/typography and the logo `design_system_asset`; build the prompt from role-tagged references (background, product, logo, style); pass the logo as a labelled `input_image`. Includes **consistent icon sets**: generate N icons using the first as a style reference so a deck's iconography matches.
- **(3) Agent `generate_image` tool** on the graph builder (pattern: `BrandSearchAgentTool`, `max_calls=2`, timeout from `remaining_seconds`), plus wiring library search and `image_guidelines` into the graph engine, which today has neither.
