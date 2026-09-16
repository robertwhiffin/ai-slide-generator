# Workstream 4 — start here

The entry point for implementing the five ws4 plans in this directory. Read this, then §3's reading
list, then your plan.

## 1. What you are building

Tellr generates slide decks. Today one monolithic agent (`src/services/agent.py`) does the whole job in
one pass. Workstream 4 replaces that with a **LangGraph multi-agent graph**:

> the **architect** converses with the user and commits a deck spec → the **data analyst** resolves
> figures → the **foreman** (a deterministic service, not an agent) dispatches **builders in parallel**,
> one per slide → **one reviewer per slide** → a **fixer** and **fix reviewer** for objective defects →
> a **deck reviewer** assesses the whole arc.

Three properties drive most of the design, so keep them in mind when a plan seems fussy:

- **Reviewers write the slides**, not builders. An unreviewed slide therefore never persists, and a slide
  never appears and then silently changes under the user.
- **Exactly one fix round** per slide position. Unbounded fixing was the rejected alternative.
- **Brand bytes never pass through a model.** Template HTML and CSS are extracted by deterministic code.
  A model that retypes brand markup has no safety net, and dropping it has already shipped a defect.

The graph runs alongside the monolith, selected per session — **it is not a cutover.** The monolith is
deleted in a later PR, not this workstream.

**The specs the plans argue from**, both in `docs/superpowers/specs/`:

| Spec | Role |
|---|---|
| `2026-08-06-agentification-core-design.md` | the parent design |
| `2026-08-12-pr3-open-questions-design.md` | the addendum — **wins wherever the two disagree** |

Each plan's `**Spec:**` header names the sections it implements. Read those sections; the plans do not
restate them.

## 2. Five PRs, in this order

**ws4a → ws4b → ws4c → ws4d → ws4e.** The order is a dependency chain, not a preference.

| Plan | Delivers | Why here |
|---|---|---|
| `2026-08-25-ws4a-shipped-defects.md` | Three already-shipped defects, plus CI collection hygiene | **Blocks ws4b:** its at-rule-preserving `merge_css` is what ws4b's CSS aggregator needs, and it exists on no other branch. It also creates and commits the test baseline every later PR compares against |
| `2026-08-25-ws4b-contracts-and-schema.md` | The seven skill output schemas, the finding schema, deck-spec models, four migrations, the checkpointer, the deck-level writer/reader | **Freezes every contract the rest consume.** This is what makes "ws4c cannot invent a schema field" true rather than aspirational |
| `2026-08-25-ws4c-graph-core.md` | `GraphState`, the foreman, nodes and routers, `call_skill`, the seven skills, template-section extraction, two security controls re-homed | The only PR where the **topology** is the deliverable. Nothing here is reachable from chat yet |
| `2026-08-25-ws4d-wiring-and-propagation.md` | Engine selection, streaming and polling transports, deck-spec propagation, the dirty-marker sweeper | Makes the graph reachable |
| `2026-08-25-ws4e-surfaces-and-gates.md` | The spec view, the findings drawer, test layers 3 and 4, the RC matrix, the release gate | Surfaces and the gate |

Each plan's own **Definition of done** is the completion bar. Don't infer one.

## 3. Read these before Task 1, in this order

1. **`.claude/skills/executing-plans-tellr/`** *and* **`superpowers:subagent-driven-development`** — both,
   per the repo's `CLAUDE.md`. Not optional; the first carries the practices that caught the real defects
   on the last build.
2. **`2026-08-25-ws4-index.md`** — the conventions all five plans inherit and deliberately do not repeat:
   the environment, the baseline gate, the two standing rulings, the verified LangGraph runtime facts, and
   the spec-section mapping. Skipping it is how a plan gets misread.
3. **Your plan**, end to end, before writing anything.
4. **If you are on ws4d or ws4e:** `../reviews/ws4_r1_cde_findings.md`. Roughly **3 of ws4d's** and
   **7 of ws4e's** review findings were never applied — the only known-unfixed items in the set. Everything
   else has been applied.

**The plans are authoritative.** They have been through review and several recorded decisions were
reversed on measurement. If an older document disagrees — the superseded
`2026-08-24-pr3-langgraph-core.md`, an earlier plan, or a spec section — **the plan wins**, and the plan
says so where it matters.

**The one ruling you are most likely to violate:** the graph is a **new** code path that *copies* what it
needs. `src/services/agent.py`, `src/core/prompt_modules.py` and `src/services/design_system_compiler.py`
are never modified. Reading or importing from them is fine; editing them is not. (Reading a private name
is fine too — several plans do it deliberately.) ws4a's `merge_css` fix is the one recorded exception.

## 4. Do a corrections pre-pass before Task 1

Verify the plan against the code, and write what you find to
`docs/superpowers/plans/.ws4<x>-PLAN-CORRECTIONS.md`. Then point every task dispatch at that file
alongside the plan.

This is not ceremony. On the last build roughly **half the tasks would have shipped a defect straight from
the plan's own text** without it. Re-grep every `file:line` anchor your tasks depend on — the index lists
the anchors that recent edits shift, and a stale anchor is a silent misfile, not an error.

## 5. Environment — two hard rules

- Use **`~/.pyenv/versions/3.11.0/bin/python`**. The in-tree `.venv` carries the pre-upgrade stack; do not
  delete or modify it, just never reach for it.
- **Never `pip install` from an agent.** It is a shared pyenv site-packages, so an install corrupts other
  agents' test runs.

## 6. Two verification rules that are not optional

**Sabotage-verify every test before you believe it.** Break the production line the test guards, confirm
it goes red *for the right reason*, and confirm your sabotage landed on the executed path. A sabotage that
misses its target is indistinguishable from a test that cannot fail — and several tests in these plans
exist because exactly that happened.

**Compare failure CAUSES to the baseline, never counts.** A 13→13 count collision once hid a new breakage
for seven consecutive tasks. The bar is: no new cause, no change to the known environmental cause, and no
test that stopped existing.

## 7. If you dispatch subagents

- **No git commands in a fix or implementation agent** — not even read-only ones. `git show HEAD` in a
  shared tree once destroyed a sibling agent's uncommitted work and cost ~15 applied findings.
- **Give parallel agents disjoint file sets**, stated explicitly, or separate worktrees.
- **For evidence that work landed, ask for a quote of the new text plus its heading**, then grep for it
  yourself. Never ask for line numbers — an agent once reported 24 fabricated ranges having written
  nothing at all.
