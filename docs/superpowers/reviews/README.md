# Workstream 4 review findings — round 1, ws4a round 2, and the seam pass

Verbatim reviewer output from the `doc-review-loop` runs of 2026-09-10, kept out of `/tmp` because it
does not survive five PRs.

> **Implementing? Start at `../plans/ws4-START-HERE.md`, not here.** This directory is the review
> *record* — what was found, what was applied, what was decided and why. The only part an implementer
> needs is the residue line below, and `ws4-START-HERE.md` already points at it.

| File | Document | Findings | State |
|---|---|---|---|
| `ws4_r1_index_findings.md` | `2026-08-25-ws4-index.md` | — | **applied** (waves 1, 1b, 1c) |
| `ws4_r1_ws4a_findings.md` | `2026-08-25-ws4a-shipped-defects.md` | 14 | **applied** (wave 2) |
| `ws4_r1_ws4b_findings.md` | `2026-08-25-ws4b-contracts-and-schema.md` | — | **applied** (wave 2) |
| `ws4_r1_cde_findings.md` | ws4c / ws4d / ws4e | 20 / 21 / 29 | ws4c **all 20 applied**; ws4d 18/21; ws4e ~22/29 |
| `ws4_r2_ws4a_findings.md` | ws4a, second fresh review | 15 | **all 15 applied** |

**Remaining unapplied residue: ~3 of ws4d's and ~7 of ws4e's round-1 findings.** Those are the only
known-and-unfixed items in the set. Read them before executing ws4d or ws4e.

## Two decisions were reversed on evidence — the plans are right, older text is not

If you meet a contradiction between a plan and anything older (the superseded
`2026-08-24-pr3-langgraph-core.md`, or a spec section), the plan wins on these two:

- **The at-rule dedupe key** is `(at_keyword, serialized_prelude)`, falling back to the serialized
  **content** when the prelude is empty. Text-keying (the earlier choice) made at-rules append-only.
  Prelude-only keying silently lost `@font-face` weights, because `ensure_deck_token_css`'s guard is
  per-family, not per-block. Both measured; both recorded in ws4a Task A1 and the index's §K5 row.
- **`scripts_content` IS persisted**, derived at the post-commit write from `SlideDeck(...).scripts`.
  The earlier "deliberately unproduced" reasoning was wrong: the column is a denormalised cache of
  the per-slide aggregate, and not writing it blanks JavaScript in thumbnails, PDF and PPTX export.

## `2026-08-25-ws4c-graph-core.md.bak` — the merge is DONE; the file is now superseded

It was a divergent partial state from the wave-2 collision (a fix agent ran `git show HEAD` over
sibling plans while their agents were editing them, and lost its own uncommitted work). It carried
three fixes the committed plan had lost — the `title` producer row, the expanded
`build_branch_payload`, and the `reviewer_router` deletion decision — while lacking the
`stalled_positions` paragraph the committed plan had.

**All three have since been merged into `2026-08-25-ws4c-graph-core.md` and committed** (`ff52ad55`),
each re-verified rather than copied. The `.bak` holds nothing unique any more and is safe to delete.
It is left in place only so nobody wonders what happened to it. **Do not copy text out of it** — its
`title` row asserted a `DeckSpec.title` field that did not exist at the time; ws4b now declares one.

## The lesson that cost the most here

Never run a git command from a fix agent working in a shared tree, and give parallel fix agents
disjoint file sets. The collision above cost roughly fifteen applied findings.
