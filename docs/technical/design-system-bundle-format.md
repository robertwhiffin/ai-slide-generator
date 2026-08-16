# Design System Bundle Format

**One-Line Summary:** The contract for the zip a brand team hands you — the manifest, which paths import as what, how template previews are recognised, and which entries the importer refuses.

---

## 1. Overview

A design system arrives as a **zip authored outside the product**, usually by a brand or design team. The importer treats it as untrusted input: it classifies every entry, refuses entries whose identity is unsafe, and ignores the rest.

Two properties surprise people:

- **Most of a real bundle is not imported, and that is expected.** Bundles carry example decks, previews and source material the product does not consume.
- **An obviously brand-related folder may import nothing.** Asset import is restricted by path. A bundle organised under `brand/` contributes no assets.

**Ignoring is not always silent.** The import response carries a warnings list — each entry a `{path, reason}` pair — populated for cases the importer judged worth reporting, such as a non-allowlisted dotfile, a thumbnail candidate that failed validation, or declared CSS it could not read. Ordinary out-of-scope entries are dropped without a warning.

See [Design System Library](./design-system-library.md) for what happens to a bundle after import.

---

## 2. What the bundle contains

### The manifest

**`_ds_manifest.json`** at the bundle root (or in a single top-level folder) is required — the importer locates the bundle root by finding it. It declares `tokens[]`, `templates[]` and `cards[]`.

**Tokens come from the manifest and from CSS sources the manifest declares** — not from scanning a `tokens/` directory. A stray CSS file the manifest does not reference contributes nothing.

### What each path becomes

| Path | Imported as |
|---|---|
| `assets/**` | `design_system_asset` rows — brand imagery |
| `fonts/**` | `design_system_asset` rows — webfonts |
| `_ds_manifest.json` | parsed into `manifest_json`; drives tokens, templates and cards |
| CSS files the manifest declares | token sources, plus retained as `design_system_file` |
| `README.md`, `SKILL.md` | retained as `design_system_file` — the authoring/brand-manual layer |
| `templates/<slug>/index.html` | retained as `design_system_file` — the template's layout source |
| `templates/<slug>/.thumbnail` or `preview*` | a `design_system_asset`, referenced by the template row |
| anything else | ignored |

**The README is not decoration.** Its first `# Heading` is read as a fallback for the design system's name, and its content reaches the model as brand context.

---

## 3. Classification

Entries are classified by path. The rule that matters is not evaluation order — it is that **template preview paths are an explicit exception to the generic skip policy.**

### The skip policy

`_should_skip` drops an entry when any of the following holds: the path is empty or a directory; it is macOS zip metadata; its basename is `.ds_store` or begins with `.`; it does **not** begin `assets/` or `fonts/`; its basename begins `preview`; or the path contains `template_shot` or `/templates/`.

Read literally, that policy discards every dotfile and everything under `templates/` — including template previews.

### The exception, and the real invariant

The asset collector applies `not _should_skip(rel) or _is_template_preview(rel)`, so a recognised template preview is retained **despite** the skip policy.

> **The load-bearing property is exception preservation across every classification layer, not the order in which two checks run.** Every layer that classifies an entry must let a `_is_template_preview(path)` candidate reach storage even when `_should_skip(path)` is true; an extensionless candidate must then pass raster magic-byte validation before being retained.

Five things must stay aligned, and breaking any one of them silently produces templates with no preview image:

1. Safe-entry classification must not discard a recognised preview path.
2. The collector must retain the `or _is_template_preview(rel)` exception.
3. The preview path patterns must stay tightly anchored — anchoring at end-of-*string* rather than end-of-*line*, so a crafted name with a trailing newline does not satisfy them.
4. Extensionless candidates must be magic-byte sniffed.
5. An invalid candidate must warn and store nothing, rather than store an unusable asset.

### Template preview forms

Both shapes are accepted, and they are validated differently:

| Form | Validation |
|---|---|
| `templates/<slug>/.thumbnail` (dot optional, **no extension**) | **magic bytes** — the format is sniffed from content |
| `templates/<slug>/preview.png` (and `.jpg`, `.gif`, `.webp`) | **pathname** — MIME derived from the extension |

**A template with no stored preview is not necessarily blank in the UI** — the frontend can render a live preview from the template's own HTML instead. A missing thumbnail costs the stored image, not the feature.

---

## 4. Tokens

Tokens are grouped by their `group` value. `group` is **free text**, not a fixed enumeration — colour, type, spacing and shadow are the values in common use, but others are accepted.

**Token identifiers are normalised before comparison.** A leading `--` and a `brand-` namespace are stripped, so `--brand-core-primary` and `primary` reduce to the same identifier.

**Deduplication requires a matching name *and* value.** Two sources declaring the same normalised identifier with the same value collapse to one row; the same identifier with *different* values remains two rows.

**Type-scale rungs should exist as tokens.** Derived sizes prefer the font-size token ramp; where the ramp cannot supply a distinct rung, the compiler may fall back to inspecting authored template or CSS declarations. Declaring the rung as a token is the reliable route.

---

## 5. Assets

After import, assets are grouped by `kind` — logo, icon, lockup, illustration, background, font, template shot.

**`kind` is inferred partly from the pathname**, and asset eligibility is restricted by path in the first place. So layout is *not* irrelevant: moving a file can change how it is classified, or remove it from the import entirely.

Prefer SVG for logos and marks, compressed raster for photography, and subset webfonts. Bytes are stored as rows, so bundle size is database size.

---

## 6. Import Refusals

A bundle is untrusted input. The importer **refuses an entry whose identity is unsafe or ambiguous rather than normalising it**, because normalising is what allows one archive to present different identities to different extractors.

| Class | Refused because |
|---|---|
| **Symlink or zip-slip path** | **Rejects the whole bundle up-front, before any bytes are read** — not a per-entry skip |
| **Duplicate canonical path** | Two entries normalise to the same destination, so which one wins would depend on archive order |
| **Empty or unreadable name** | No name, or a recorded central-directory name that is empty while a name is declared elsewhere |
| **Non-text characters** | Control characters, bidirectional overrides, unpaired surrogates |
| **Path escape** | Absolute paths, drive letters, `..` traversal, empty segments, dot segments |
| **Separator confusion** | Backslash separators, which some extractors treat as directory separators and others as literal characters |
| **Identity disagreement** | The local file header's name disagrees with the central directory, or an extra-field record rewrites the name |
| **Malformed metadata** | A corrupt or truncated extra-field record, an unreadable local header, or an out-of-range ZIP64 offset |

Two properties worth stating explicitly:

**Identity is checked before scope**, so the refusal applies to entries outside the import root as well as inside it. An archive cannot smuggle an ambiguous identity past the check by placing it somewhere otherwise ignored.

**Dotfiles are skipped rather than refused.** Refusing them would break template previews, and failing an entire multi-hundred-megabyte bundle over a `.DS_Store` would be hostile. A non-allowlisted dotfile is skipped with a warning.

**A malformed archive produces a client error, not a server error** — a crafted offset that cannot be seeked yields a `400`, not a `500`.

---

## 7. Name Conflicts

Design system names are unique among active systems.

- A duplicate import returns **`409`**, sequentially or concurrently, and rolls back — the losing request creates no row.
- The two paths return **different messages**: the sequential check can name the conflicting row, while the concurrent path cannot query it after its transaction has failed.
- A **soft-deleted name is freed**, so delete-then-reimport under the same name succeeds.

---

## 8. Authoring Guidance

- Include **`_ds_manifest.json`** at the bundle root. Without it the importer cannot locate the bundle root.
- Declare tokens **in the manifest**, or in a CSS file the manifest references. Unreferenced CSS contributes nothing.
- Put brand imagery under **`assets/`** and webfonts under **`fonts/`**. Other folder names contribute no assets.
- Give each template folder a preview — either `.thumbnail` (no extension) or `preview.<ext>`.
- Keep **`README.md`** substantive: its first heading can name the design system, and its content reaches the model as brand context.
- **Read the import response's warnings.** They name entries the importer ignored and why, which is the fastest way to find a mis-shaped bundle.

---

## 9. Cross-References

- [Design System Library](./design-system-library.md) — what happens after import: compilation, defaults, retention
- [Database Configuration](./database-configuration.md) — where imported rows land
- [Backend Overview](./backend-overview.md) — router registration and the import route
