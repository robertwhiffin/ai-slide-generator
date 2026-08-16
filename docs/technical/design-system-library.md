# Design System Library

**One-Line Summary:** Org-shared brand bundles — tokens, fonts, assets and named slide templates — imported as a zip, compiled into a single prompt artifact, and resolved onto a deck through a six-tier default ladder.

---

## 1. Overview

A **design system** is an uploaded brand bundle that supplies everything a generated deck needs to be on-brand: colour and type tokens, webfonts, brand imagery, and named slide templates. It is org-shared: any user may upload one, and every user may select any of them.

Design systems sit *above* slide styles rather than beside them. A slide style supplies typography and colour only; a design system supplies the whole brand package, and when both are present the design system wins and the style is dropped.

Key design decisions:

- **User-contributed, admin-governed** — any user may import a bundle and manage the ones they uploaded; only a workspace admin may set the *org default*. Authorship does not buy the org default, because that changes what every user gets.
- **Compile-to-prompt** — a bundle is flattened once into `compiled_style_content`, a single text artifact that flows through the existing `build_generation_system_prompt` path. The generation pipeline is unchanged and remains style-agnostic.
- **Bytes live in Lakebase** — assets, fonts and template files are stored as rows, not on a filesystem, so a fork of the database carries the brand with it.
- **Retention over tidiness** — a deleted design system is *hidden*, not *gone*. Its bytes remain servable because stored decks reference them. See §7.
- **Import is adversarial-input handling** — a bundle is an untrusted zip from outside the product, so the importer refuses non-canonical entries rather than normalising them. See [Design System Bundle Format](./design-system-bundle-format.md).

---

## 2. Stack & Entry Points

| Component | Path |
|---|---|
| Router (15 routes) | `src/api/routes/settings/design_systems.py` |
| ORM models (5 tables) | `src/database/models/design_system.py` |
| Import + classification | `src/services/design_system_service.py` |
| Prompt compiler | `src/services/design_system_compiler.py` |
| Resolution for generation | `src/api/services/agent_factory.py` |
| Default ladder (client) | `frontend/src/contexts/AgentConfigContext.tsx` |
| Library UI | `frontend/src/components/DesignSystem*/`, `TemplateViewerModal.tsx` |
| Org-default admin UI | `frontend/src/components/Admin/AdminDesignSystemDefault.tsx` |

All routes are mounted under `/api/settings/design-systems`.

---

## 3. Architecture Snapshot

```
bundle.zip ──▶ import_design_system ──▶ classify each entry
                                          ├─ assets/**  ──▶ design_system_asset   (bucketed by `kind`)
                                          ├─ fonts/**   ──▶ design_system_asset
                                          ├─ tokens/**  ──▶ design_system_token   (bucketed by `group`)
                                          ├─ templates/<slug>/**
                                          │              ├─ .thumbnail ──▶ design_system_template
                                          │              └─ *.html     ──▶ design_system_file
                                          └─ everything else ──▶ skipped (allowlist)
                                                    │
                                                    ▼
                                    recompute_compiled_style_content
                                                    │
                                                    ▼
                                        compiled_style_content
                                                    │
                    ┌───────────────────────────────┴───────────────────────────────┐
                    ▼                                                               ▼
        build_generation_system_prompt                                  {{ds-asset:ID}} resolution
        (agent_factory, generation path)                                (render + export paths)
```

---

## 4. Default Resolution — the six-tier ladder

This is the contract that decides which brand a new deck uses. It is evaluated client-side in `AgentConfigContext.tsx`, and mirrored server-side for callers that have no browser (MCP).

| Tier | Source | Scope | Set by |
|---|---|---|---|
| 1 | Explicit per-deck choice in Agent Config | this deck | anyone |
| 2 | Personal default design system | this browser | anyone |
| 3 | Personal default slide style | this browser | anyone |
| 4 | Org default design system | workspace | **admin only** |
| 5 | Server default slide style | workspace | **admin only** |
| 6 | Hardcoded default style constant | — | — |

**A design system and a slide style are mutually exclusive.** When both arrive, the design system wins and the style is dropped. This is enforced in three independent places — the model serializer, the column bind, and a database `BEFORE INSERT OR UPDATE` trigger — so a caller cannot construct a deck that carries both.

**Tier 3 does not fire on a fresh surface.** The personal-slide-style branch is gated on an *incoming* non-null style, and on both the fresh-surface and new-session resolve paths the incoming style is null — so on a genuinely new deck the org design system (tier 4) wins over a personal style default. The `/admin` panel's helper text currently overstates this; see §10.

**Personal defaults are browser-local and therefore invisible to MCP.** They are a `localStorage` key with no server call and no authorization surface. An MCP-created deck resolves from tier 4 down. Clearing a personal default releases the config slot, not just the key, so tier 3 or 4 takes effect on the same surface without a reload.

For the durable, cross-browser equivalent, save a **profile** carrying the design system and set that profile as your default — a profile stores the whole agent config, design system included, and auto-applies on a fresh surface.

---

## 5. Interfaces

Authorization follows an org-shared, user-contributed model: **reads are open, mutations are creator-or-admin, and org-wide state is admin-only.** See §5.1 for the exact rules.

| Method | Path | Purpose | Backend handler |
|---|---|---|---|
| `GET` | `` | List all systems with token/asset/template counts | `list_design_systems` |
| `POST` | `/import` | Import a bundle zip | `import_design_system` |
| `POST` | `` | Create a token-only system (no binaries) | `create_design_system` |
| `GET` | `/{ds_id}` | Detail: tokens, templates, assets, files | `get_design_system` |
| `PUT` | `/{ds_id}` | Update name, description, tokens | `update_design_system` |
| `DELETE` | `/{ds_id}` | Soft delete; `?hard_delete=true` for permanent | `delete_design_system` |
| `POST` | `/{ds_id}/set-default` | **Admin only.** Set the org default | `set_default_design_system` |
| `POST` | `/{ds_id}/clear-default` | **Admin only.** Clear the org default | `clear_default_design_system` |
| `GET` | `/{ds_id}/templates` | List named templates | `list_design_system_templates` |
| `GET` | `/{ds_id}/templates/{template_id}/thumbnail` | Serve a template thumbnail | `serve_design_system_template_thumbnail` |
| `GET` | `/{ds_id}/templates/{template_id}/source` | Serve template HTML | `get_design_system_template_source` |
| `GET` | `/{ds_id}/assets/{asset_id}` | Serve asset bytes | `serve_design_system_asset` |
| `GET` | `/{ds_id}/assets/{asset_id}/thumbnail` | Serve an asset thumbnail | `serve_design_system_asset_thumbnail` |
| `GET` | `/{ds_id}/files` | List bundle files | `list_design_system_files` |
| `GET` | `/{ds_id}/files/{file_path}` | Serve a bundle file | `serve_design_system_file` |

**`set-default` refuses an inactive system** with a `400` rather than silently setting a tombstone as the org brand.

**A concurrent same-name import returns `409`, not `500`.** The fail-fast name check and the partial unique index leave a time-of-check window, so the index violation is translated to a conflict. The sequential and concurrent paths return the same status, the same reason, and the same rollback — the losing request creates no row.

### 5.1 Authorization

Three tiers, and only the first is a route-level dependency:

| Surface | Rule |
|---|---|
| Reads (list, detail, templates, assets, files) | **Open.** Design systems are org-shared content; any user may read any of them. |
| `set-default`, `clear-default` | **Admin only**, as a `dependencies=[Depends(require_admin)]` on the decorator. |
| Mutations (`PUT`, `DELETE`) | **Creator or admin**, via an in-body check that falls through to `require_admin`. |

**Authorship does not buy managing org-wide state.** If the target row is the org default, the check is admin-only *even for the row's creator* — and that decision is made on the **loaded row, before** the authorship comparison, so being the creator cannot bypass the freeze.

**An author-less row is admin-only.** `created_by` is nullable and legacy rows may hold `NULL` or a blank string. Both sides of the comparison must be non-blank for the creator branch to fire, so an unattributed row never becomes "anyone may manage this", and an unresolved caller never matches a blank owner.

**Identity is server-derived, never client-asserted.** It comes from the OBO middleware's `get_permission_context().user_name`, resolved from the caller's authenticated token — never from a request body, query string or header. A caller cannot assert someone else's identity.

**Blankness normalizes; identity comparison does not.** The blankness test treats anything *visually* empty as blank, because `str.strip()` alone let a zero-width character (Unicode category `Cf` — not `isspace()`, untouched by `strip()`) present as a real name on both sides and satisfy the creator branch, and a Hangul filler did the same by normalizing to a letter. The identity **comparison** is exact on the raw values, so two principals whose names differ only by invisible characters, surrounding whitespace, or case remain different principals and still fail closed.

Both denial paths return `403`, with distinct detail strings so a not-the-author denial is debuggable rather than indistinguishable from a generic admin refusal.

---

## 6. Data Model

Five tables, all in `src/database/models/design_system.py`. Full column-level schema lives in [Database Configuration](./database-configuration.md); this is the responsibility map.

| Model | Table | Responsibility |
|---|---|---|
| `DesignSystem` | `design_system` | Parent record: name, description, author, active/default flags, and `compiled_style_content` |
| `DesignSystemAsset` | `design_system_asset` | Binary assets and fonts, bucketed by `kind` |
| `DesignSystemToken` | `design_system_token` | Colour, type and spacing tokens, bucketed by `group` |
| `DesignSystemFile` | `design_system_file` | Verbatim bundle files, addressable by path |
| `DesignSystemTemplate` | `design_system_template` | Named slide templates and their thumbnails |

**Asset and token bucketing is by field, not by folder.** Assets are grouped by their `kind` column and tokens by their `group` column, so the compiled artifact's structure is independent of how the bundle author arranged directories.

---

## 7. Soft Delete — the retention invariant

**A soft-deleted design system is hidden, not gone, and its asset bytes remain servable on purpose.** Stored decks embed handles such as `@font-face { src: url('{{ds-asset:408}}') }`. Returning `404` for a tombstoned system's bytes would silently strip fonts and images from **every historic deck** that used it.

Consequences a reader must not "fix":

- `GET /{ds_id}/assets/{asset_id}` continues to serve bytes for a tombstoned system. This is the contract, not an oversight.
- `?hard_delete=true` is the permanent verb. If bytes must actually disappear, that is the route.
- The generation path *does* filter on `is_active`, so a tombstoned system is never selected for a **new** deck. The render and asset paths deliberately do not filter, so **existing** decks keep rendering.
- A tombstoned name is freed for re-import, so a delete-then-reimport cycle succeeds.

**Cross-system asset scoping fails closed, at two layers.** An asset is resolved by `(asset_id, design_system_id)`, never by global id — a handle belonging to another system does not resolve. The two layers report the miss differently: the asset route returns `404`, while the MCP resolver leaves the handle **literal** and emits zero bytes. Both are correct for their layer; a test asserting `404` at the MCP boundary is asserting the wrong contract.

---

## 8. The Compiled Artifact and Its Currency Contract

A bundle is flattened once into `compiled_style_content` by `recompute_compiled_style_content`. The artifact is stamped with `COMPILER_VERSION` (currently `20`, `src/services/design_system_compiler.py`).

**Currency is an exact version match, not a comparison.** A stored artifact is considered current only when its stamp equals the running `COMPILER_VERSION`. Two consequences that have each caused a shipped bug:

- **A compiler change that does not move the version is invisible in production.** Existing rows read as current and are never recompiled, so the change only affects systems imported afterwards. **Any change to compiler output must bump the version.**
- **"The new version is unreleased" is a perishable premise.** Reasoning that a stale row will be invalidated *later* by an as-yet-unshipped version stops being true the moment that version deploys. Re-check what is deployed before relying on it.

**The artifact embeds the design system's name**, so its character count and hash depend on what the system is called. Two systems with equal-length names produce equal character counts but **different hashes**. When comparing artifacts across builds, compare character counts and state the name they were measured under; a hash is only comparable at a byte-identical name.

**Type-scale derivation reads tokens, not template CSS.** The eyebrow band derives its size from the font-size token ramp and emits `14px`. A bundle whose templates hardcode a size but declare no matching token will compile to the ramp's floor instead — the fix is a token, not a template edit.

---

## 9. Templates

Each named template contributes layout HTML plus a thumbnail. Templates are selected per deck in Agent Config, not from the library page.

**Pinning a template raises fidelity substantially.** A pinned deck reuses the template's own classes and declaration bodies; an unpinned deck receives only a short catalog of template names and descriptions with **no CSS**, so the model picks a template sensibly and then authors its own styling. Unpinned adherence is therefore bounded by the mechanism, not by prompt wording — stronger instructions cannot copy CSS that was never supplied. Pin a template when brand fidelity matters.

**Template pinning does not survive the pre-session browser path.** A pin submitted on the request that *creates* a session is stripped, because a pin arriving at session-creation cannot be distinguished from another surface's carry-over. Pinning works on an existing session, and over MCP via `template_name`.

---

## 10. Known Limitations

| Limitation | Detail |
|---|---|
| `/admin` helper text overstates tier 3 | The panel says a personal default in *either* library takes precedence. True for a design system; **not** true for a slide style on a fresh surface — see §4. The copy, not the ladder, is wrong. |
| Personal defaults do not reach MCP | Browser-local by design. MCP resolves from the org default down. |
| No in-app bundle authoring | `POST ""` creates a **token-only** system; assets, fonts and templates require an imported bundle. |
| Agenda-badge placement in PPTX | Inline background pills are centred against their resolved ancestor, so badges on a wide list can land away from their item. Affects export only. |
| Unpinned template adherence | Bounded by the catalog mechanism, not by wording. See §9. |

---

## 11. Extension Guidance

- **Adding a bundle folder** — extend the allowlist in `design_system_service.py`; entries outside it are skipped silently by design. Document the addition in [Design System Bundle Format](./design-system-bundle-format.md).
- **Changing compiled output** — bump `COMPILER_VERSION` in the same commit, or the change will not reach existing rows. See §8.
- **Adding a table** — five tables exist; test fixtures that reset design-system schema must be extended, or a sixth table's rows will survive between tests.
- **Adding a route that resolves assets** — scope by `(asset_id, design_system_id)`. Never resolve an asset by global id; that was a shipped confused-deputy defect.
- **Tightening `is_active` filters** — filter on the generation path only. The render and asset paths must keep resolving tombstones. See §7.

---

## 12. Cross-References

- [Design System Bundle Format](./design-system-bundle-format.md) — folder contract, `.thumbnail` convention, import security refusals
- [Database Configuration](./database-configuration.md) — column-level schema for the five tables
- [Frontend Overview](./frontend-overview.md) — the default ladder in context, library and admin components
- [MCP Server Reference](./mcp-server.md) — `design_system_id` and `template_name` over MCP
- [Permissions Model](./permissions-model.md) — `require_admin` semantics for the org default
- [Backend Overview](./backend-overview.md) — router registration and prompt-assembly order
