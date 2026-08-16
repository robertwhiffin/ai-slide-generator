# Design System Bundle Format

**One-Line Summary:** The contract for the zip a brand team hands you — which folders import, how template thumbnails are recognised, how tokens and assets are bucketed, and which entries the importer refuses outright.

---

## 1. Overview

A design system arrives as a **zip authored outside the product**, usually by a brand or design team. The importer therefore treats it as untrusted input: it classifies every entry against an allowlist, refuses anything whose identity is ambiguous, and silently skips everything else.

Two properties follow from that, and both surprise people:

- **Most of a real bundle is not imported, and that is correct.** A bundle carries example decks, previews and source material that the product has no use for. Skipping is the default; importing is the exception.
- **A folder that looks obviously brand-related may import nothing.** Only `assets/` and `fonts/` are allowlisted. A bundle organised under `brand/` imports zero assets, with no error — the entries are simply skipped.

See [Design System Library](./design-system-library.md) for what happens to a bundle *after* import.

---

## 2. Folder Contract

```
<bundle>/
  design-system.json     # manifest: name, description, token and asset indexes
  README.md              # the brand manual — human-readable context and rules
  assets/                # ✅ imported — logos, lockups, icons, illustrations, backgrounds
  fonts/                 # ✅ imported — webfont files
  tokens/                # colour / type / spacing token definitions
  templates/
    <slug>/
      .thumbnail         # ✅ imported — the template's picker image
      *.html             # the template's layout
  uploads/  preview/  slides/  ui_kits/     # ⛔ not imported
```

**Only `assets/` and `fonts/` are allowlisted for asset import.** Everything else is skipped unless a more specific gate claims it first (see §3).

**`uploads/` being skipped costs nothing in practice.** In the reference bundle, the overwhelming majority of `uploads/` entries are byte-identical duplicates of a kept `assets/` file; the remainder are non-vector source material (`.pptx`, `.pdf`, pasted screenshots) that the product does not consume.

---

## 3. Classification — a two-gate design

Entries pass through **two gates in a fixed order**, and the order is load-bearing.

**Gate 1 — template thumbnail.** Checked **before** the skip gate, because the skip gate would otherwise discard it. A template thumbnail is matched by pattern on the path, recognising both shipped shapes — `templates/<slug>/preview…` and the dot-prefixed, extension-less `templates/<slug>/.thumbnail` — case-insensitively.

**Gate 2 — `_should_skip`,** seven rules evaluated in order (`src/services/design_system_service.py`):

| # | Rule | Skips |
|---|---|---|
| 1 | Empty path, or a path ending `/` | directory entries |
| 2 | `__macosx/` anywhere in the path | macOS zip metadata |
| 3 | Basename is `.ds_store`, **or begins with `.`** | all dotfiles |
| 4 | Path does **not** begin `assets/` or `fonts/` | everything outside the allowlist |
| 5 | Basename begins `preview` | preview renders |
| 6 | `template_shot` in the path, or `/templates/` in the path | template source and screenshots |
| 7 | — | anything surviving is imported |

**Rule 3 is why the gate order matters.** It skips *every* dotfile — `.thumbnail` included. The file only imports because Gate 1 claimed it first. **Reordering the gates, or "tidying" rule 3, silently produces bundles with no template thumbnails and a null `thumbnail_url`.** That is exactly the defect the two-gate design was introduced to fix.

**A thumbnail is validated by magic bytes, not by extension** — necessarily, since the canonical form has no extension.

**Path patterns are anchored at end-of-string, not end-of-line.** A `$` anchor matches *before* a trailing newline, so a crafted entry named `templates/x/.thumbnail\n` once satisfied the pattern and was both stored **and** linked as a template's thumbnail. The anchoring must reject that.

---

## 4. Tokens

Tokens are bucketed by their `group` — colour, type, spacing — rather than by which file they came from, so a bundle's directory layout does not constrain the compiled output.

**Token identifiers are normalised before dedup.** A leading `--` and a `brand-` namespace are stripped, so the manifest name `--brand-core-primary` and the CSS variable `primary` reduce to the same identifier and collapse into one token. A bundle that declares a token both ways gets one row, not two.

**Type-scale rungs must exist as tokens.** Derived sizes read the font-size token ramp, not template CSS. A bundle whose templates hardcode a size with no matching token compiles to the ramp's floor instead — see [Design System Library §8](./design-system-library.md).

---

## 5. Assets

Assets are bucketed by `kind` — logo, icon, lockup, illustration, background, font — again independent of folder layout.

Prefer SVG for logos and marks, compressed raster for photography, and subset webfonts. Bytes are stored as rows in Lakebase, so bundle size is database size.

---

## 6. Worked Example

One real 872-entry bundle, to make the allowlist legible. **These are the numbers for one bundle, not a contract** — but the *shape* is representative.

| Outcome | Entries | Composition |
|---|---|---|
| **Imported** | **420** | 396 from `assets/` · 12 from `fonts/` · 4 template `.thumbnail` |
| **Skipped** | **452** | `uploads/`, `preview/`, `slides/`, `templates/` source, `ui_kits/`, root files |
| **Warned** | **0** | — |
| **Refused** | **0** | — |

Every entry lands in exactly one bucket, and every skip names the rule that skipped it. **If those four numbers do not sum to the zip's entry count, an entry has been dropped without being classified** — that is a defect, not a rounding difference.

---

## 7. Import Refusals — the security contract

A bundle is untrusted input from outside the product. The importer therefore **refuses an entry whose identity is ambiguous rather than normalising it**, because normalising is what lets one archive present two different identities to two different unzip implementations.

Refusals are grouped by what makes the name unsafe:

| Class | Refused because |
|---|---|
| **Empty or unreadable name** | The entry has no name, or the recorded central-directory name is empty while a name is declared elsewhere |
| **Non-text characters** | Control characters, bidirectional-override characters, or unpaired surrogates — none of which are legitimate in a path |
| **Path escape** | Absolute paths, drive letters, `..` traversal, empty segments, dot segments |
| **Separator confusion** | Backslash separators, which some extractors treat as directory separators and others as literal characters |
| **Identity disagreement** | The name in the local file header disagrees with the central directory, or an extra-field record rewrites the name |
| **Malformed metadata** | A corrupt or truncated extra-field record, or an out-of-range ZIP64 offset |

Two properties worth stating explicitly:

**Identity is checked before scope.** The refusal applies to entries *outside* the import root as well as inside it. An archive cannot smuggle an ambiguous identity past the check by placing it somewhere the importer would otherwise ignore.

**Dotfiles are skipped, not refused.** This is deliberate and load-bearing: refusing them would break `.thumbnail`, and hard-failing an entire multi-hundred-megabyte bundle because it contains a `.DS_Store` would be hostile. `assets/.env` is skipped; `templates/<slug>/.thumbnail` is imported via Gate 1.

**A malformed archive fails with a client error, not a server error.** A crafted offset that cannot be seeked produces a `400`, not a `500` — the request is rejected, not crashed.

---

## 8. Name Conflicts

Design system names are unique among active systems.

- A sequential duplicate import returns **`409`**.
- A **concurrent** duplicate import also returns `409` — the same status, reason and rollback as the sequential path. The losing request creates no row.
- A **soft-deleted name is freed**, so delete-then-reimport under the same name succeeds.

---

## 9. Authoring Guidance

- Put every asset you want imported under **`assets/`** or **`fonts/`**. If your source tree uses another name, rename on export.
- Give each template folder a **`.thumbnail`** — dot-prefixed, no extension, a raster image. Without it the template appears in the picker with no preview.
- Declare every type-scale rung as a **token**, not only as template CSS.
- Keep the **`README.md`** substantive. It is the brand manual and it reaches the model as context, so rules expressed there influence generated decks.
- Do not rely on `uploads/`, `preview/` or `slides/` being read. They are skipped.

---

## 10. Cross-References

- [Design System Library](./design-system-library.md) — what happens after import: compilation, defaults, retention
- [Database Configuration](./database-configuration.md) — where imported rows land
- [Backend Overview](./backend-overview.md) — router registration and the import route
