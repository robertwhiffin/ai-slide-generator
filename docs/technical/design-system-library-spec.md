# Tellr — Design System Library (Design‑System‑as‑Skill) — Feature Spec

- **Status:** Draft v1 (plan gate)
- **Owner:** Tariq Yaaqba (GitHub: RicktY94)
- **Repo:** `robertwhiffin/ai-slide-generator` (Tellr)
- **Branch:** `ty/feature/design-system-library` (off `main` — **`main` is never touched**)
- **Scope:** Slides only. No external connectors (no GitHub / Figma / local‑code links).
- **Public repo:** ships the **engine only** — **zero** brand content in code or git history.

---

## 1. Summary

Replace Tellr's current manual "paste‑a‑text‑blob" **Slide Style** with a modern **Design System** experience — a *skill‑with‑files* bundle (README/manifest + templates + brand assets + color tokens + fonts + components + spacing + type) that users **create in‑app or upload**. Design systems are **org‑shared company assets** (everyone can view/use, matching how Tellr slide styles work today), stored in **Lakebase**, surfaced via a **Claude‑Design‑style pick / add / create / upload view** under "slide style," and **compiled into Tellr's existing `slide_style_id` prompt seam** so generation produces on‑brand slides using the org's real logos, colors, fonts, and templates.

Reference points: **Claude Design** (Anthropic's GUI product — the UX inspiration) and **huashu‑design** (its open‑source, MIT‑licensed *agent Skill* cousin — the reusable model + render engine). Tellr already ships huashu's `html2pptx` sidecar and already keys generation off `slide_style_id`, so this is an **extension along a known seam**, not a rebuild.

## 2. Current state (from code recon)

- A "style" = one flat table `slide_style_library` (`src/database/models/slide_style_library.py:20-47`); `style_content` is a **required free‑text `Text` blob** pasted by hand, plus `name/description/category/image_guidelines/is_active/is_system/is_default/created_by`.
- **No Alembic** — schema via `Base.metadata.create_all()` + **hand‑rolled migrations** in `src/core/database.py::_run_migrations`.
- The style is **literally string‑concatenated** into the LLM system prompt: `agent_factory._get_prompt_content` fetches `style.style_content` by `slide_style_id` → `prompt_modules.build_generation_system_prompt` appends it verbatim (2nd block). **No parsing.**
- CRUD at `/api/settings/slide-styles` (`src/api/routes/settings/slide_styles.py`); UI `SlideStyleList.tsx` / `SlideStyleForm.tsx` (Monaco blob editors) + `AgentConfigBar` `<select>` picker; two‑tier default (per‑user localStorage + system‑wide `is_default`).
- A **binary asset store already exists**: `image_assets` table, referenced from styles via free‑text `{{image:ID}}` placeholders.
- Stack: React 19/TS/Vite + FastAPI/Python + **Postgres→Lakebase** (SQLAlchemy), LangChain over `databricks-claude-opus-4-6`, MLflow; wheel deploy to Databricks Apps.

## 3. Goals / Non‑Goals

**Goals**
- Design system = structured **skill‑with‑files** bundle: tokens (colors/type/spacing), fonts, brand assets (logo/lockups/product & arch icons/illustrations/backgrounds), slide templates, optional components.
- **Create** in‑app and **Upload** a ready‑made bundle; org‑shared visibility.
- Claude‑Design‑style **browse/select/detail** view under "slide style."
- Drive generation via the existing `slide_style_id` seam (structured DS → compiled prompt text + real asset injection).
- **Backward compatible**: existing styles keep working (`style_content` becomes the compiled artifact).

**Non‑Goals (v1)**
- No doc / video / website / wireframe surfaces (slides only).
- No GitHub / Figma / local‑code connectors.
- No per‑user private isolation (org‑shared is the model for now).
- No brand content shipped in the repo.

## 4. Key concepts & references

- **Claude Design** (screenshots): a design system = **README + file tree** (`Templates` [hold slide screenshots], `Brand`, `Colors` [core/accents/ink/tints], `Components`, `Slides`, `Spacing`, `Type`, `UI Kit`) + **Published/Default** flags + **"Open source file."** Export/"open source file" byte‑format is **TBD** (live‑session capture blocked; see §15).
- **huashu‑design** (MIT — reuse permitted incl. commercial): the same idea as an **agent Skill** — `SKILL.md`/README + `references/` + `assets/` + a `brand-spec.md` ("Core Asset Protocol": **Logo > product shot > UI > color > fonts**). Prose‑based (no machine schema, no upload). Liftable code ≈ `scripts/html2pptx.js` (already vendored in Tellr as `services/pptx-emit-huashu`).

## 5. The Design System bundle (the "skill with files")

```
<design-system>/
  design-system.json     # manifest: name, description, created_by, published, is_default,
                         #   version, + indexes of tokens / templates / assets / fonts
  README.md              # human-readable context + how-to (the "spec")
  tokens/
    colors.json          # groups: core / accents / ink / tints -> {name, hex}
    type.json            # font stacks + type scale
    spacing.json
  fonts/                 # font files (woff2/ttf) — subset where possible
  brand/                 # logo, lockups (+dark), product & arch icons, illustrations, backgrounds
  templates/             # named slide templates (layout HTML + example slide screenshots)
  components/            # optional snippets
```

- **Superset** of what Claude Design / huashu express, so any source can map in.
- Upload = a **zip or folder** of the above; validated against a JSON Schema on import.

## 6. Data model (Lakebase)

Extend, don't replace. Additive tables + columns, created via **hand‑rolled migration** in `src/core/database.py::_run_migrations` (no Alembic).

- **`design_system`** (the parent record; may reuse/extend `slide_style_library`):
  - `id, name (unique), description, created_by, published (bool), is_default (bool), version, created_at, updated_at`
  - `manifest_json` (the parsed `design-system.json`)
  - `compiled_style_content` (the auto‑generated prompt text — **maps to today's `style_content` for backward compatibility**)
- **`design_system_asset`** (binaries; follow the existing `image_assets` pattern — bytes in Lakebase):
  - `id, design_system_id (fk), kind (logo|icon|lockup|illustration|background|font|template_shot), filename, mime, bytes (bytea), width, height, size_bytes`
- **`design_system_token`** (optional normalized tokens for query/preview):
  - `id, design_system_id (fk), group (core|accents|ink|tints|type|spacing), name, value`
- **Visibility:** org‑shared (all rows visible/usable); `created_by` for authorship; `published` + `is_default` for the org default.
- **Guardrails:** per‑asset + per‑bundle **size limits**; bytes in a dedicated table (not inline with metadata); prefer SVG logos + compressed images + subset fonts.

## 7. Backend API

Extend `src/api/routes/settings/slide_styles.py` (or a new `design_systems.py` router under `/api/settings`).

- `GET /design-systems` — list (org‑shared), with token/template/asset summaries for the picker.
- `GET /design-systems/{id}` — detail (README, templates, tokens, assets).
- `POST /design-systems` — create (structured).
- `PUT /design-systems/{id}` — update.
- `DELETE /design-systems/{id}` — soft delete.
- `POST /design-systems/{id}/set-default` — org default.
- `POST /design-systems/import` — **upload a bundle** (zip/folder): validate manifest → store metadata + assets in Lakebase → register. Bulk‑capable.
- `GET /design-systems/{id}/export` — export the bundle (for portability).
- `GET /design-systems/{id}/assets/{asset_id}` — serve an asset (for preview + generation).

## 8. Generation integration (the seam)

1. User picks a design system in the AgentConfigBar (existing `slide_style_id` select, upgraded todesign systems).
2. Backend fetches the structured DS → **compile‑to‑prompt** serializer produces `compiled_style_content`:
   - color tokens → CSS `:root { --brand-* }` vars + style rules,
   - typography/spacing → rules,
   - template guidance → layout hints,
   - brand assets → references via the existing `{{image:ID}}` / asset‑serving mechanism (upgraded to design‑system assets).
3. This compiled text flows through the **same** `build_generation_system_prompt` path (`src/core/prompt_modules.py`), so `agent_factory` / `prompt_modules` are unchanged. `style_content` = the compiled artifact → **fully backward compatible**.

## 9. Frontend UX (Claude‑Design‑style, under "slide style")

- Left **list** of design systems + right **detail** panel: README, **Templates** (with "Use"), **Colors/tokens**, **Brand** assets preview.
- **Create design system** (structured editor: token pickers, asset uploads, template refs) — replaces the raw Monaco blob.
- **Upload** a bundle (zip/folder) → registered org‑wide.
- **Org default** badge; published flag.
- Files touched: `frontend/src/components/config/SlideStyleList.tsx`, `SlideStyleForm.tsx`, `frontend/src/components/AgentConfigBar/AgentConfigBar.tsx`, `frontend/src/contexts/AgentConfigContext.tsx`.

## 10. Reuse map

| Piece | Verdict |
|---|---|
| `html2pptx.js` / deck runtime (`services/pptx-emit-huashu`) | **Reuse** (already vendored) |
| huashu skill structure + `brand-spec.md` taxonomy | **Adapt** → `design-system.json` schema |
| CSS `:root` token convention | **Adopt** for token/asset injection |
| DB schema, CRUD, upload/import, compile‑to‑prompt, UI, bundle format | **Build new** |
| Claude Design export → Tellr / huashu `brand-spec` → Tellr | **Importers** (Phase 5; Claude Design format pending live capture) |
| huashu web/video/infographic surfaces | **Drop** (slides only) |

## 11. Constraints & locked decisions

1. **Org‑shared** visibility (everyone views/uses), `created_by` authorship. *(confirmed)*
2. **Lakebase** storage (extend `image_assets` binary pattern), **not UC Volumes** — matches existing pattern, forks with the copy‑on‑write dev‑loop, keeps wheel/PyPI untouched. *(confirmed)*
3. `style_content` = **auto‑compiled** artifact (backward compatible). *(confirmed)*
4. **Slides only**; no external connectors. *(confirmed)*
5. Bundle = **superset**; Claude Design & huashu as **importers**. *(confirmed)*
6. **Public‑repo hygiene:** engine only, zero brand content, **synthetic‑only** test fixtures. *(confirmed)*
7. **No Alembic** — hand‑rolled migrations.

## 12. Phased delivery

Each code phase is a **delegated `implement` task** (a coding sub‑agent opens its own PR — polly does not write code), followed by **opposite‑vendor review**, all on `ty/feature/design-system-library` (never `main`).

| Phase | Ships |
|---|---|
| **0** | Branch + dev‑loop familiarization |
| **1** | `design_system` schema (+ assets/tokens tables, `created_by`, `published`, `is_default`) via hand‑rolled migration; keep `style_content` as compiled artifact; synthetic fixtures |
| **2** | Compile‑to‑prompt serializer (DS → prompt text + asset refs) — the linchpin; keeps generation green |
| **3** | Backend CRUD + **upload/import** endpoint (validate bundle, store assets in Lakebase); org‑shared |
| **4** | Claude‑Design‑style pick/add/create/**upload** view under "slide style" |
| **5** | Importers (huashu `brand-spec`; Claude Design export once format known) + bundle export; **no seeded brand content** |
| **6** | Gates (`pytest -m 'not live'`, `ruff`, `mypy`, `tsc`, lint, build) + verify on a **devloop** Lakebase fork |

## 13. Dev & test loop (Lakebase branching)

Per the team's DevOps changes — isolated prod‑fork environments on demand:
```
gh workflow run publish-dev.yml                                  # publish .devN to real PyPI
./scripts/deploy_local.sh create --env devloop --instance <id> \ # own app db-tellr-dev-<id> + fresh prod-fork branch dev-<id>
    --profile tellr-dev --from-pypi <version>
./scripts/deploy_local.sh update --env devloop --instance <id> --profile tellr-dev --from-pypi <version>
./scripts/deploy_local.sh delete --env devloop --instance <id> --profile tellr-dev
```
- Each fork is a full prod mirror (copy‑on‑write Lakebase branch), full permissions to run ALTER migrations, wiped/re‑forked each deploy, fully isolated. **Ideal for verifying our hand‑rolled migration + asset storage against real prod data.**
- The in‑repo **`deploy-tellr-dev` skill** lets our implement agents drive this flow autonomously in Phase 6.
- Background: `docs/technical/dev-deploy.md`.

## 14. Public‑repo hygiene & security

- Repo contains the **engine only**: schema, CRUD, upload/import, compiler, UI. Generic, brand‑neutral code.
- **Never committed** (in code or history): real colors/fonts/logos/product shots/templates or named brand design systems. All are **runtime user data** in Lakebase.
- Tests use **synthetic fixtures only** (fake "Acme" brand, dummy hex, placeholder assets).
- MIT attribution retained if any substantial huashu code is copied.

## 15. Risks & open items

- **No Alembic** → hand‑rolled migration risk; Phase 1 needs care + tests.
- **String‑concat seam** → structured DS must always serialize to text (Phase 2 linchpin, before UI).
- **Binary size in Lakebase** → enforce size limits, dedicated assets table, subset fonts.
- **Claude Design export format** → live‑session capture BLOCKED (vibe Chrome launched with `--remote-debugging-pipe`, not a port; public share link is an empty SPA shell). Needed only for the optional Claude‑Design importer. Unblock: user clicks "Open source file"/Export and shares the format, **or** relaunch vibe Chrome with `--remote-debugging-port=9222` for a full automated capture.
- ⚠️ **Cross‑vendor review** currently blocked: `codex`/`pi` unrunnable in this deployment (`omnigent setup` re‑auth of the "Databricks AI Gateway / codex‑databricks" provider re‑mints the model‑serving token). Until fixed, PRs get **Claude‑only** review.

## 16. Appendix — evidence (key files)

- Style model: `src/database/models/slide_style_library.py:20-47`
- Migrations: `src/core/database.py::_run_migrations`
- Prompt injection: `src/services/agent_factory.py` (`_get_prompt_content`), `src/core/prompt_modules.py` (`build_generation_system_prompt`)
- CRUD: `src/api/routes/settings/slide_styles.py`; registered in `src/api/main.py`
- Binary assets: `image_assets` table; `{{image:ID}}` placeholders
- Frontend: `frontend/src/components/config/SlideStyleList.tsx`, `SlideStyleForm.tsx`, `frontend/src/components/AgentConfigBar/AgentConfigBar.tsx`, `frontend/src/contexts/AgentConfigContext.tsx`
- huashu render: `services/pptx-emit-huashu` (vendored `html2pptx`)
- Dev loop: `docs/technical/dev-deploy.md`, `.claude/skills/deploy-tellr-dev/`, `scripts/deploy_local.sh`, `.github/workflows/publish-dev.yml`

---

## 17. Confirmed bundle format & importer (reference: an exported design-system project archive)

> Abstract STRUCTURE / SCHEMA only — **no brand content**. All token names/values below are **generic placeholders**.

A reference design-system export is a **Project archive `.zip`** — which confirms the **skill-with-files** model. Abstract layout:
```
_ds_manifest.json          # manifest / index of everything (the importer reads this)
SKILL.md                   # skill frontmatter (name, description, user-invocable) -> packages the bundle as a skill
README.md                  # brand / usage guide
colors_and_type.css        # design tokens as :root CSS vars + @font-face
fonts/                     # font files (.ttf/.woff2)
assets/brand/ , assets/... # SVG/PNG brand assets
preview/                   # specimen HTML cards, one per token/component group
slides/                    # index.html + deck-runtime js + slide-*.html
templates/<name>/          # index.html + base js + deck-runtime js, per template
ui_kits/website/           # UI kit (NON-slide -> out of scope)
uploads/                   # original sources (pptx/svg/png/pdf)
_adherence.*.json          # optional lint rules enforcing token/brand adherence
```

### `_ds_manifest.json` schema (importer target — field names only)
```
namespace       : string
cards[]         : { path, group, viewport?, subtitle?, name? }   # group in Brand|Colors|Components|Slides|Spacing|Type|UI Kit
templates[]     : { name, description, folder, entryPath }
globalCssPaths  : [ css paths ]
tokens[]        : { name, value, kind, definedIn, annotation? }  # kind in color|font|spacing|shadow; value may be var(--other)
fonts[]         : { family, weight, style, cssPath, files[] }
brandFonts[]    : { family, status, tokens[], path }
components[], startingPoints[], themes[] : (reserved)
source          : string
```
Parallel representation: inline HTML annotations (e.g. `<!-- @dsCard group="..." -->`, `<!-- @template name="..." -->`) — an importer can read either the manifest or the annotations.

### Importer mapping (external `.zip` -> Tellr design system, Phase 5)
- `_ds_manifest.json` -> `design_system.manifest_json`
- `tokens[]` -> `design_system_token` rows (name/value/kind/group)
- `fonts/` + `assets/**` -> `design_system_asset` (bytes in Lakebase; kind = font/logo/icon/...)
- `templates[]` + `slides/` -> template records (layout HTML + screenshots)
- `colors_and_type.css` (:root vars) -> token source for compile-to-prompt (reuse the CSS :root var convention)
- non-slide surfaces (`ui_kits/website/`) -> ignored (slides only)

### Create flow (reference, for the later in-app create phase)
Two paths observed: "Create here" (upload slides/assets + fonts/logos, optional external links, freeform notes) and a Claude-Code / React-components path. For Tellr v1 (upload-first, NO external connectors): keep the **upload-a-bundle** path + a minimal **create form** subset (name/blurb + upload fonts/logos/assets + notes). No GitHub/Figma/Claude-Code paths.

### Org sharing model (reference)
A design system is owned by an individual; a **Published** flag makes it appear in the org picker; a **Default** flag sets the org default; access is org-scoped. Matches our org-shared + published + is_default design.
