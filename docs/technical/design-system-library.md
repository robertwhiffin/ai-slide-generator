# Design System Library

**One-Line Summary:** Org-shared brand bundles — tokens, fonts, assets and named slide templates — imported as a zip, compiled into a single prompt artifact, and resolved onto a deck through per-path default resolution.

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
| Library UI | `frontend/src/components/config/` — `DesignSystemLibrary.tsx`, `DesignSystemDetailPanel.tsx`, `DesignSystemUploadDialog.tsx`, `DesignSystemFileBrowser.tsx`, `TemplateThumbnail.tsx`, `TemplateViewerModal.tsx`, `templatePreviewDoc.ts` |
| Org-default admin UI | `frontend/src/components/Admin/AdminDesignSystemDefault.tsx` |

All routes are mounted under `/api/settings/design-systems`.

---

## 3. Architecture Snapshot

```
bundle.zip
   │
   ├─ _ds_manifest.json  ──▶ manifest_json; declares tokens[] / templates[] / cards[]
   │                            └──▶ design_system_token      (grouped by `group`)
   ├─ CSS the manifest declares ──▶ further tokens, and retained as design_system_file
   ├─ assets/** · fonts/**   ──▶ design_system_asset          (grouped by `kind`)
   ├─ README.md · SKILL.md   ──▶ design_system_file           (the authoring layer)
   ├─ templates/<slug>/index.html ──▶ design_system_file
   ├─ templates/<slug>/.thumbnail | preview.<ext>
   │        └──▶ design_system_asset, referenced by a design_system_template row
   └─ everything else ──▶ ignored (some ignores are reported as import warnings)
                             │
                             ▼
             recompute_compiled_style_content
                             │
                             ▼
                 compiled_style_content
                             │
         ┌───────────────────┴──────────────────┐
         ▼                                      ▼
 build_generation_system_prompt      {{ds-asset:ID}} resolution
 (agent_factory, generation path)    (render + export paths)
```

**Tokens come from the manifest and the CSS it declares**, not from scanning a directory. **A template's thumbnail is an asset row that the template references** — it is not stored on the template itself.

---

## 4. Which brand a deck gets

A deck carries **one** visual-style slot. A design system and a slide style are mutually exclusive: when both are present the design system wins and the style is dropped. That exclusivity is enforced in three independent places — the model serializer, the column bind, and a database `BEFORE INSERT OR UPDATE` trigger — so a caller cannot construct a deck carrying both.

Resolution is **path-dependent**: the browser, a saved profile, a newly created session and an MCP call do not all consult the same sources. Documenting it as one ordered list overstates how uniform it is, so each path is given separately.

### Server-side resolution (`agent_factory`)

This is the only path that always applies, and it is short:

1. `design_system_id`, if set — looked up with `is_active = true`
2. otherwise `slide_style_id`, if set — also looked up with `is_active = true`
3. otherwise the default slide-style constant

**An inactive id resolves to nothing rather than to an error**, so a deck pinned to a soft-deleted design system falls through to whatever comes next.

### Browser resolution (`AgentConfigContext`)

The client seeds an unconfigured surface from its own preferences before the server sees a request. It reads two `localStorage` keys — a personal default design system and a personal default slide style — and prefers the design system when both are set.

**Which key wins on any given render depends on the path taken**, because the context also has to respect an incoming config, a mirrored pre-session config, and a default profile. In particular a personal slide-style default *is* seeded on initial render, so it is **not** correct to say a personal style default never applies on a new deck.

Clearing a personal default **releases the config slot, not just the key** — removing only the key would leave the resolved id in the mirrored config and the lower preference would never take effect.

### Saved profiles

A profile stores the whole agent config, design system included, and a default profile is applied on a fresh surface. **This is the only personal default that follows a user across browsers and machines**, because the other two live in `localStorage`.

### MCP

MCP has no browser, so it never sees a personal default. With neither `design_system_id` nor `slide_style_id` supplied, the **org default design system** is applied. An explicit `slide_style_id` suppresses that implicit seeding. See [MCP Server Reference](./mcp-server.md).

### Workspace defaults

The **org default design system** is a database flag, admin-only, and applies to any caller that has expressed no preference — including MCP. Beneath it sit the server default slide style, then a protected `is_system` style, then the hardcoded constant.

## 5. Interfaces

Authorization follows an org-shared, user-contributed model: **reads are open, mutations are creator-or-admin, and org-wide state is admin-only.** See §5.1 for the exact rules.

| Method | Path | Purpose | Backend handler |
|---|---|---|---|
| `GET` | `` | List all systems with token/asset/template counts | `list_design_systems` |
| `POST` | `/import` | Import a bundle zip | `import_design_system` |
| `POST` | `` | Create a token-only system (no binaries) | `create_design_system` |
| `GET` | `/{ds_id}` | Detail: summary plus `manifest_json`, `compiled_style_content`, **tokens and assets only** | `get_design_system` |
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

**A concurrent same-name import returns `409`, not `500`.** The fail-fast name check and the partial unique index leave a time-of-check window, so the index violation is translated to a conflict. Both paths return `409` and roll back — the losing request creates no row — but their **messages differ**: the sequential check can name the conflicting row, while the concurrent path cannot query it once its transaction has failed.

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

## 7. Soft Delete — retained bytes, resolvable references

Soft delete (`is_active = false`) hides a design system and stops it being selected for new decks. What it does **not** do is guarantee that a stored deck keeps rendering, and the difference matters:

> Soft deletion retains the asset rows and keeps their scoped URLs servable. It does **not** guarantee that stored decks continue resolving their design-system handles once the session configuration has been revalidated.

Both halves are needed to resolve a handle: the **bytes** must still exist, *and* the deck's stored `design_system_id` must still be there to scope the lookup. Soft delete preserves the first and can lose the second.

**Reading a session's agent config repairs a stale pin.** The config read checks the referenced design system for `is_active` and, if it is false, **clears `design_system_id` and persists that repair**. So the pin does not merely go unused — it is removed.

What that means per surface:

| Surface | After the design system is soft-deleted |
|---|---|
| **Reopening the session in the app** | Text, layout, colours and ordinary CSS remain. Design-system **fonts fall back** and `{{ds-asset:…}}` **images do not appear**, because the pin needed to scope them has been cleared. A cached or already-resolved first paint may briefly look intact — that is a race, not a contract |
| **Exporting** | Conditional. If the stored pin is still present the retained bytes resolve; once the pin has been cleared, fonts and design-system images can be missing from the export |
| **Fetching an asset URL directly** | Still works. The route scopes by `(design_system_id, asset_id)` and does not check `is_active`; only hard deletion or asset removal stops it |

**`?hard_delete=true` is the permanent verb.** If bytes must actually disappear, that is the route.

**Do not add an `is_active` filter to the asset or render paths.** The generation path does filter it, so a tombstoned system is never chosen for a *new* deck. Filtering the asset path as well would stop retained bytes being served at all, removing the only part of the retention behaviour that currently holds.

**Cross-system scoping fails closed at two layers, and reports the miss differently.** An asset is resolved by `(asset_id, design_system_id)`, never by global id — resolving by global id was a defect the current code prevents. The asset route returns `404` on a scope miss; the MCP resolver instead leaves the handle **literal** and emits zero bytes. A test asserting `404` at the MCP boundary is asserting the wrong layer's contract.

## 8. The Compiled Artifact and Its Currency Contract

A bundle is flattened once into `compiled_style_content` by `recompute_compiled_style_content`. The artifact is stamped with `COMPILER_VERSION` (currently `20`, `src/services/design_system_compiler.py`).

**Currency is an exact version match, not a comparison.** A stored artifact is considered current only when its stamp equals the running `COMPILER_VERSION`. Two consequences that have each caused a shipped bug:

- **A compiler change that does not move the version is invisible in production.** Existing rows read as current and are never recompiled, so the change only affects systems imported afterwards. **Any change to compiler output must bump the version.**
- **"The new version is unreleased" is a perishable premise.** Reasoning that a stale row will be invalidated *later* by an as-yet-unshipped version stops being true the moment that version deploys. Re-check what is deployed before relying on it.

**The artifact embeds the design system's name**, so its character count and hash depend on what the system is called. Two systems with equal-length names produce equal character counts but **different hashes**. When comparing artifacts across builds, compare character counts and state the name they were measured under; a hash is only comparable at a byte-identical name.

**Type-scale derivation prefers tokens.** Derived sizes such as the eyebrow band read the font-size token ramp; where the ramp cannot supply a distinct rung, the compiler may fall back to inspecting authored template or CSS declarations, so the emitted size is not a fixed value. Declaring the rung as a token is the reliable route — the fix for an unexpected size is usually a token, not a template edit.

---

## 9. Templates

Each named template contributes layout HTML plus a thumbnail. Templates are selected per deck in Agent Config, not from the library page.

**Pinning supplies the template's own CSS; not pinning does not.** A pinned deck receives the template's classes and declaration bodies; an unpinned deck receives only a short catalog of template names and descriptions with **no CSS**, so the model picks a template and then authors its own styling. Unpinned adherence is therefore bounded by what the mechanism supplies rather than by prompt wording — stronger instructions cannot copy CSS that was never provided. How much this changes the generated result is a model-quality question and not established by the code; pin a template when brand fidelity matters.

**Template pinning does not survive the pre-session browser path.** A pin submitted on the request that *creates* a session is stripped, because a pin arriving at session-creation cannot be distinguished from another surface's carry-over. Pinning works on an existing session, and over MCP via `template_name`.

---

## 10. Known Limitations

| Limitation | Detail |
|---|---|
| `/admin` helper text overstates precedence | The panel states a personal default in *either* library takes precedence over the org default. That is reliable for a personal **design system**; for a personal **slide style** it depends on the resolution path — see §4. The copy asserts a uniform rule the code does not have. |
| Personal defaults do not reach MCP | They live in `localStorage`, which the server cannot read. MCP resolves from the org default down. A profile is the cross-browser alternative. |
| No in-app bundle authoring | `POST ""` creates a **token-only** system; assets, fonts and templates require an imported bundle. |
| Agenda-badge placement in PPTX | Inline background pills are centred against their resolved ancestor, so badges on a wide list can land away from their item. Affects export only. |
| Unpinned template adherence | Bounded by the catalog mechanism, not by wording. See §9. |

---

## 11. Extension Guidance

- **Adding a bundle folder** — extend the allowlist in `design_system_service.py`; entries outside it are skipped, some with an import warning and most without. Document the addition in [Design System Bundle Format](./design-system-bundle-format.md).
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
