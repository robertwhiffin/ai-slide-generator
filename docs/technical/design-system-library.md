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
| Resolution for generation | `src/services/agent_factory.py` |
| Default resolution (client) | `frontend/src/contexts/AgentConfigContext.tsx` |
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
   ├─ globalCssPaths + root colors_and_type.css ──▶ further tokens, retained as design_system_file
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

**Tokens come from the manifest, the CSS paths named by `globalCssPaths`, and the conventional root `colors_and_type.css` when present** — not from scanning a directory. The conventional path needs no manifest declaration: `_declared_css_paths` appends `DEFAULT_CSS_TOKEN_SOURCE` to whatever `globalCssPaths` lists (`src/services/design_system_service.py`). **A template's thumbnail is an asset row that the template may reference** — it is not stored on the template itself, and the reference is optional.

---

## 4. Which brand a deck gets

A deck carries **one** visual-style slot. A design system and a slide style are mutually exclusive: when both are present the design system wins and the style is dropped. That exclusivity is enforced in three independent places — the model serializer, the column bind, and a database `BEFORE INSERT OR UPDATE` trigger — so a caller cannot construct a deck carrying both.

There is **no single ordered list of sources.** The code implements one decision tree per **entry path**, and every tree returns early. Its guards distinguish a field the caller *omitted* from a field the caller *set to `null`*, they read recorded provenance (`style_source`) instead of re-deriving it from values, and they preserve an explicit `style_source: 'user'` against every lower default. A tier table cannot express that: it has to assume one total order, and each path evaluates a different set of guards. So read the **entry path** first, then only the guards on that path.

The six entry paths, and what decides each:

| Entry path | Resolver | Workspace-default seeding eligible? |
|---|---|---|
| 4.1 Fresh pre-session browser surface | `AgentConfigContext` pre-session effect | Yes — resolves with `isNewSurface: true` |
| 4.2 Stored mirror / restored surface | same effect, mirror branch | Only for a mirror stamped `style_source: 'seeded'` whose design-system slot is empty |
| 4.3 Default profile | `profileStyleSource` | Only when the profile is server-seeded |
| 4.4 Browser-created new session | `_apply_org_default_style_source` (`src/api/routes/chat.py`) | Per field, and only for omitted fields |
| 4.5 Existing session | agent-config `GET` (`src/api/routes/agent_config.py`) | Only when the server holds no stored config for the session (`is_configured` false) |
| 4.6 MCP | `create_deck` (`src/api/mcp_server.py`) | Yes, unless an explicit source is passed |

### 4.1 Entry path: a fresh pre-session browser surface

The pre-session effect in `frontend/src/contexts/AgentConfigContext.tsx`:

1. Read the `localStorage` mirror. **Its existence, never its content, decides the branch.** A config whose only edit was "Design System: None" is byte-identical to the untouched first-paint placeholder, so no content test can separate them; a mirror that exists means path 4.2.
2. No mirror: load the selected profile (`userDefaultProfileId`, else the server `is_default` profile) and stamp its provenance — path 4.3.
3. Resolve through `withResolvedStyleSource(config, { isNewSurface: true })`. One other browser path passes the same flag — the session `GET`, when the server holds no stored config for that session (§4.5). And `isNewSurface` is not what gates seeding overall: it decides only the second guard below, so the stored-mirror branch, which passes no flag, is still eligible when its provenance is `'seeded'` (§4.2).

`withResolvedStyleSource` evaluates these guards in order and returns at the first one that matches:

| Guard | Outcome |
|---|---|
| `style_source === 'user'` | Return unchanged. The slot is the user's decision — including the decision to hold neither a design system nor a style. |
| `!isNewSurface && style_source == null` | Return unchanged. Missing provenance on an existing config is read as a choice, not as a gap. |
| `design_system_id != null` | Return unchanged. |
| Personal default design system (`localStorage`) | Set `design_system_id`, clear `slide_style_id`, stamp `style_source: 'user'`. |
| `slide_style_id != null` **and** a personal default slide style exists | Set that style, stamp `style_source: 'user'`. **This returns before the org-default design system is ever resolved.** |
| Org default design system resolves | Set `design_system_id`, clear `slide_style_id`, stamp `style_source: 'seeded'`. |
| No org default | Personal default style (`'user'`), otherwise the server's `is_default` — falling back to `is_system` — style (`'seeded'`). |

**A personal slide-style default can suppress org-default design-system seeding.** It is reached before the org-default branch and returns, so the org brand is never resolved on that surface. Any copy asserting that a personal style default cannot outrank the org design system is wrong; the behaviour is pinned by `frontend/tests/e2e/design-system-selector.spec.ts`.

**Clearing a personal design-system default releases the slot, it does not re-seed it.** `setUserDefaultDesignSystem(null)` writes `design_system_id: null`, `template_id: null`, `slide_style_id: userPreferredStyleId()` and `style_source: 'user'`, then drops the `localStorage` key. The write happens **before** the key is removed: if the release fails the preference survives, and the Clear control — which is rendered from that key — survives with it. Workspace defaults reappear only when a later entry path performs seeding, because the surface now carries `style_source: 'user'`.

### 4.2 Entry path: a stored mirror or restored surface

Stored state is authoritative, but it is not uniformly final. The branch runs at all only when the stored config is missing a `design_system_id` or a `deck_prompt_id`, and it then resolves without `isNewSurface` — so recorded provenance decides which of **three** outcomes follows:

| Stored `style_source` | Outcome |
|---|---|
| `'user'` | Returned unchanged at the first guard. The slot is the user's decision, including the decision to hold neither a design system nor a style. |
| absent (`null`) | Returned unchanged at the second guard, which fires precisely because this path passes no `isNewSurface`. **An absent provenance marker is preserved as the user's choice rather than treated as a fresh gap.** |
| `'seeded'` | **Not an early return.** The config clears both guards, and with an empty design-system slot it reaches the org-default branch, which takes the slot, clears the seeded style and re-stamps `'seeded'`. |

The third row is the one a summary tends to lose: a stored mirror the user has never edited still tracks a later org default. It is pinned by `frontend/tests/e2e/design-system-selector.spec.ts` — "a SERVER-SEEDED style is still overridden by the org-default design system" seeds a mirror with `style_source: 'seeded'` and asserts the org-default design system ends up selected. Outside the style slot, the branch fills only a genuinely empty `deck_prompt_id`.

### 4.3 Entry path: the default profile

Provenance comes from **who wrote the profile**, not from comparing its style id to the current default. `profileStyleSource` stamps `style_source: 'user'` for a profile whose `created_by` is not `system`, and for a system profile that has since been re-pointed at a different style; it stamps `'seeded'` only for the server's own profile still holding the style the server seeds.

**A human-authored profile therefore short-circuits every lower default.** Comparing a stored config against a live `is_default` flag instead cannot distinguish a seed from a user picking that same value, and retroactively reinterprets stored configs whenever the flag is flipped.

A profile is also the **only** personal default that follows a user across browsers and machines; the personal design-system and slide-style defaults live in `localStorage`.

### 4.4 Entry path: a browser-created new session

`_apply_org_default_style_source` in `src/api/routes/chat.py` seeds **per field, and only fields the client omitted.** Presence comes from the request's `model_fields_set`, so an explicit `null` is a choice ("no style source") and is left alone, while an omitted key is a gap the org default may fill. Value inspection cannot make that distinction — both read as `None`.

- `slide_style_id` present in the payload (including as `null`) → return; no seeding at all.
- `design_system_id` already non-null → return.
- `design_system_id` omitted → seed the org default design system if one resolves, and stop.
- `design_system_id` explicitly `null` → the design-system default is off the table, but the org default *slide style* may still fill the style slot the client never mentioned.

**Session-creating requests strip `template_id`.** A pin arriving on the request that creates a session can only be another surface's carry-over, so `_without_template_pin` drops it; the design system and everything else carries over.

### 4.5 Entry path: an existing session

The persisted slot is used as stored. The agent-config `GET` sanitizes stale **pins** — a `design_system_id` or `template_id` whose row is gone is cleared and the repair is persisted — and reports a cleared design system out-of-band as `design_system_unavailable` so the emptied dropdown can be explained. It does **not** reapply current workspace defaults over stored choices: `withResolvedStyleSource` runs on this path only when the server holds no stored config for the session (`is_configured` false), which is genuine creation.

### 4.6 Entry path: MCP

MCP has no browser, so it never sees a `localStorage` preference. `create_deck` resolves in this order:

1. An explicit `design_system_id` wins, and only then is `template_name` resolved to a pin.
2. Otherwise, **an explicit `slide_style_id` suppresses implicit org-default design-system seeding** — the org default is consulted only when *neither* id was supplied.
3. Otherwise the org default design system.
4. Otherwise the tellr-configured default slide style: the `is_default` row, falling back to `is_system`, lowest id first on either.

Only when no persisted id resolves does `agent_factory` fall through to its hardcoded constant. See [MCP Server Reference](./mcp-server.md).

### 4.7 After resolution: prompt assembly

Whatever the entry path decided is persisted as a mutually exclusive pair, and `agent_factory` reads it as a **branch, not a ladder**:

```python
if config.design_system_id is not None:   # design-system branch
    ...
elif config.slide_style_id is not None:    # legacy slide-style branch
```

**An inactive `design_system_id` resolves without an error but leaves generation on `DEFAULT_SLIDE_STYLE`.** The design-system branch is chosen on the id being *present*, so a lookup filtered by `is_active = true` that misses logs a warning and leaves the hardcoded constant in place. The `slide_style_id` branch is an `elif` and **is not evaluated at all** — there is no fallthrough from a soft-deleted design system to the deck's former style. `DEFAULT_SLIDE_STYLE` is a constant, not a database lookup.

---

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

**Rows are grouped by their stored `kind` and `group` columns, but directory layout still matters.** Paths decide whether an asset is imported at all — only `assets/**`, `fonts/**` and recognized template previews are stored — and `_infer_asset_kind` reads pathname text (`fonts/`, `logo`, `icon`, `lockup`, `background`) to choose the `kind` a row is then grouped by. Rearranging a bundle's directories can therefore change both what is imported and how it is bucketed.

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

**Cross-system scoping fails closed at two layers, and reports the miss differently.** An asset is resolved by `(asset_id, design_system_id)`, never by global id: resolving by global id would let a foreign handle return another design system's bytes. The asset route returns `404` on a scope miss; the MCP resolver instead leaves the handle **literal** and emits zero bytes. A test asserting `404` at the MCP boundary is asserting the wrong layer's contract.

---

## 8. The Compiled Artifact and Its Currency Contract

A bundle is flattened once into `compiled_style_content` by `recompute_compiled_style_content`. The artifact is stamped with `COMPILER_VERSION` (currently `20`, `src/services/design_system_compiler.py`).

**Currency is an exact version match, not a comparison.** A stored artifact is considered current only when its stamp equals the running `COMPILER_VERSION`. Two consequences follow from that exact-version check:

- **A compiler change that does not move the version is invisible in production.** Existing rows read as current and are never recompiled, so the change only affects systems imported afterwards. **Any change to compiler output must bump the version.**
- **"The new version is unreleased" is a perishable premise.** Reasoning that a stale row will be invalidated *later* by an as-yet-unshipped version stops being true the moment that version deploys. Re-check what is deployed before relying on it.

**The artifact embeds the design system's name**, so its character count and hash depend on what the system is called — but the name is only one input. Length and hash depend on the complete compiled content: description, README and SKILL text, tokens, fonts, the template section, the frame guardrails and the asset contract all vary independently of the name. Equal-length names therefore guarantee neither equal character counts nor different hashes. **Compare either measure only across byte-identical inputs**, and state what those inputs were.

**Type-scale derivation prefers tokens.** Derived sizes such as the eyebrow band read the font-size token ramp; where the ramp cannot supply a distinct rung, the compiler may fall back to inspecting authored template or CSS declarations, so the emitted size is not a fixed value. Declaring the rung as a token is the reliable route — the fix for an unexpected size is usually a token, not a template edit.

---

## 9. Templates

Each named template contributes layout HTML and may reference an optional thumbnail. `thumbnail_asset_id` is nullable and its foreign key is `ON DELETE SET NULL`, so a template exists without a preview when the bundle shipped none the importer recognized, and an existing reference becomes null when the thumbnail asset is deleted or replaced — deleting a thumbnail never deletes the template. Templates are selected per deck in Agent Config, not from the library page.

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
- **Adding a route that resolves assets** — scope by `(asset_id, design_system_id)`. Never resolve an asset by global id; always scope the lookup. `get_asset_base64` documents this as the confused-deputy guard: a `{{ds-asset:<foreign_id>}}` handle from a crafted bundle must not resolve to another system's bytes. `design_system_id=None` is fail-closed, because the column is `NOT NULL` and the `IS NULL` filter matches no row.
- **Tightening `is_active` filters** — filter on the generation path only. The render and asset paths must keep resolving tombstones. See §7.

---

## 12. Cross-References

- [Design System Bundle Format](./design-system-bundle-format.md) — folder contract, `.thumbnail` convention, import security refusals
- [Database Configuration](./database-configuration.md) — column-level schema for the five tables
- [Frontend Overview](./frontend-overview.md) — the same entry paths from the client's side, library and admin components
- [MCP Server Reference](./mcp-server.md) — `design_system_id` and `template_name` over MCP
- [Permissions Model](./permissions-model.md) — `require_admin` semantics for the org default
- [Backend Overview](./backend-overview.md) — router registration and prompt-assembly order
