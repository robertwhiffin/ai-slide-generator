# ws4b → ws4c handover

**Written 2026-09-13, on completing ws4b.** For the agent picking up **ws4c**
(`2026-08-25-ws4c-graph-core.md`). Read this *after* the documents in §2, not instead of them — it
carries only what ws4b changed, decided, or measured, all of which your plan predates.

---

## 1. Where things stand

- **ws4b is complete: 28 commits, all 16 tasks built, reviewed and fixed**, on
  `feat/ws4b-contracts-and-schema`. It is merged into `feat/langgraph-core` (see §7 for the merge
  commit, which carries the Definition-of-Done record).
- **This branch WAS pushed** — the first ws4 branch to be. That was needed to publish a dev wheel;
  see §6.
- Suite: **3 failed, 4570 passed, 8 skipped, 4581 collected.** The three failures are the two
  pre-existing causes recorded in `docs/superpowers/baselines/pr3_ws4_collected.log`, whose
  **Section 2b is now your baseline** — Section 2 is ws4b's, and its header says so.
- **ws4b was verified against real Lakebase**, the first in this workstream. §6.

---

## 2. Read these first, in this order

1. **`.claude/skills/executing-plans-tellr/`** *and* **`superpowers:subagent-driven-development`** —
   both, per `CLAUDE.md`. Not optional.
2. **`ws4-START-HERE.md`**, then **`2026-08-25-ws4-index.md`** — the conventions you inherit.
3. **`docs/superpowers/plans/.ws4b-PLAN-CORRECTIONS.md`** — 23 sections. **Several are contracts you
   consume**, not just ws4b's private notes: §19 (a signature that differs from the plan), §23 (three
   read paths, not two), §12 and §20 (measured database behaviour), §15 (the migration chain).
4. **Your plan**, end to end, before writing anything.
5. **Do the corrections pre-pass** into `.ws4c-PLAN-CORRECTIONS.md` before Task 1, and point every
   dispatch at it. On ws4a it produced six real corrections; on ws4b it produced **twenty-three**,
   two of which made the work smaller and several of which would otherwise have shipped a defect
   transcribed straight from the plan.

---

## 3. THE CONTRACTS YOU BIND TO — and the one that differs from your plan

Everything below is FROZEN. **If you need a field that does not exist, escalate — do not edit.**

| Contract | Where |
|---|---|
| Finding schema, criteria registry, `SlideReviewOutput`, `DeckReviewOutput` | `src/domain/finding.py` |
| Deck spec models | `src/domain/deck_spec.py` |
| Seven skill output schemas + `OUTPUT_SCHEMAS` | `src/domain/skill_io.py` |
| The TypeScript mirror | `frontend/src/types/finding.ts` |
| Shared fixtures (~25, exposed methods are the contract) | `tests/unit/conftest.py`, `tests/integration/conftest.py` |

**The seven registry keys** are `architect`, `data_analyst`, `builder`, `fixer`, `build_reviewer`,
`fix_reviewer`, `deck_reviewer`. `build_reviewer` and `fix_reviewer` deliberately share
`SlideReviewOutput`.

**`make_finding_id(criterion, subject_hash, ordinal)` — pass all three.** `ordinal` has a default, so
a two-argument call compiles and two findings of one criterion on one slide then mint the SAME id.
`ordinal` is the finding's 0-indexed position among findings of that criterion on that subject
(ruling R-D).

**`scripts` is `str` everywhere.** Picked once, in `skill_io.py`. Your `StreamEvent` must match.

**READ THIS ONE — `deck_review_store`'s signatures DIFFER from what your plan says** (corrections
§19, ruling R-O, accepted and evidenced):

```
plan says:  save_deck_review(session_id, deck_id, digest, findings, author)
            get_deck_review(session_id, deck_id)
ships as:   save_deck_review(db, deck_id, digest, findings, author=None)
            get_deck_review(db, deck_id, digest)
```
A content-addressed getter must be told which digest to look up. Proven load-bearing: implementing
the plan's digest-less version reddens both edit-then-revert tests, because it silently returns the
wrong row for any deck with more than one review. **The call-site recipe**: look up the `UserSession`
from the session_id string, call `SessionManager._get_deck_owner_session(db, session)` — it takes a
**`UserSession` object and a `db`**, not a string — take the owner's `SessionSlideDeck.id`, compute
the digest with `compute_deck_digest`, then call the store.

---

## 4. What ws4b BUILT that you consume

- **`src/core/checkpointer.py`** — `SqlAlchemyCheckpointSaver` + `get_checkpointer()` (process-wide).
  Five methods: `get_tuple`, `list`, `put`, `put_writes`, `delete_thread`. **`get_next_version` is
  deliberately absent** — the base ships a working integer increment and nothing calls it.
  `get_delta_channel_history` is also left on the base, which has a **working** default; an earlier
  claim that it would raise was false and is corrected in the module.
- **`src/api/services/deck_level_writer.py`** — `write_deck_level_columns(...)` with a **SENTINEL**,
  not `None` defaults, so an omitted column is not an erasure. `read_deck_spec(session_id)`.
  It touches NO `session_slides` row, and that is the reason it exists.
- **`src/services/deck_css_aggregator.py`** — `aggregate_deck_css(existing, blocks, token_css)`.
  **You are its producer.** Its docstring carries your contract: each element must be **CSS text, not
  `<style>`-wrapped markup** — a wrapped block parses to error nodes and is dropped SILENTLY, with no
  exception and no log. The list holds exactly one element per turn, or none.
- **`src/services/deck_review_store.py`** — see §3.
- **The read path** now emits `deck_spec` and `findings` on **all three** dict-returning paths of
  `get_slide_deck` (corrections §23 — your plan, like ws4b's, describes only two). `findings` is ONE
  FLAT deck-level list, each entry carrying its own `slideIndex`.

---

## 5. TRAPS ws4b PAID FOR — do not re-learn these

- **`Send(timeout=)` is unusable.** The parameter EXISTS on `Send` in langgraph 1.2.10 — a scout
  "corrected" the plan on that basis and was wrong — but a compiled graph fanning into a **sync** node
  raises on invoke: `ValueError: Node timeouts are only supported for async nodes because sync Python
  execution cannot be safely cancelled in-process.` Stall detection must use state-recorded timestamps.
- **A test fixture for a compiled graph MUST be file-backed SQLite.** `StaticPool` with
  `sqlite:///:memory:` hands two Pregel worker threads the same connection and **segfaults the
  interpreter** — reproduced 3 of 3 runs.
- **`create_all` masks a migration.** On ws4b it did so TWICE on one task, in two different halves,
  and both masking tests were green and plausible. **For a migration that alters or drops, the only
  trustworthy test is one that first puts the database into the state the migration is meant to
  repair.**
- **A transaction boundary, not statement order, protects durability.** Moving a version check below
  the column writes does NOT make a rejected write persist — the raise propagates out of the session
  context manager, which rolls back. To prove a persistence guard you must mutate, **commit**, then
  raise.
- **`.claude/worktrees/` holds nine stale repo copies.** An unfiltered repo-wide grep returns roughly
  ten times the real hit count. Scope to `src/ tests/ frontend/src/ scripts/ .github/`, or filter.
- **Check merges by CONTENT, never by commit identity.** `git merge-base --is-ancestor` told me the
  shared-owner work was unmerged; the code was fully present, squashed in. Use `git log -S` or a grep.
  (This repo had already recorded that lesson. I repeated it anyway.)
- **`npm run typecheck` cannot see `frontend/tests/`.** Neither tsconfig includes it. The gate for a
  spec file is `npx playwright test --list`, asserting on **errors**, not on a spec count.
- **`src/core/database.py` calls `load_dotenv()`**, so a local `.env` leaks into test runs.
- **The CI seed step's line number has now been wrong three times** (`:589` in the plan, `:664`, and
  `:691` today). Re-grep it; never trust a written anchor in `.github/workflows/test.yml`.

---

## 6. Lakebase, and the dev-deploy loop — it all works

`db-tellr` is a Lakebase **PROJECT** (autoscaling), not a provisioned instance. `databricks database
get-database-instance db-tellr` returns "Resource not found" and that is **not** an absence — use
`databricks postgres list-projects` / `list-branches` / `list-endpoints`. The project is
`projects/db-tellr`, one protected `production` branch.

The `.claude/skills/deploy-tellr-dev/` loop was exercised end to end and works:
`gh workflow run publish-dev.yml --ref <branch>` → `deploy_local.sh create --env devloop --instance
<id> --profile tellr-dev --from-pypi <version>` → confirm RUNNING → `delete` to tear down.

Three things that cost time:
- **`gh` must be the personal account, not the EMU one.** `gh auth switch --user robertwhiffin`; the
  EMU token gets HTTP 403 "Must have admin rights" on workflow dispatch.
- **PyPI is blocked from the laptop**, so a local `curl` to pypi.org returns 503. That is not a
  publish failure. Publishing must go through CI, which is why the branch has to be pushed.
- **The publish can partially fail.** One package published while the other's job was never acquired
  by a runner. `gh run rerun --failed` fixed it. Check BOTH packages.

RUNNING is the plan's proof that migrations applied, since each step exits on failure — but ws4b did
not trust the inference: the fork's schema was queried directly through the real OAuth token path.
Do the same.

---

## 7. What ws4b leaves open

- **CI has still never run ws4a or ws4b to completion.** The branch was pushed only to publish a
  wheel. A known fragility waits there: `test_dependencies_resolve_on_proxy` is marked `live` and does
  a **real `pip` resolve** against the Databricks proxy, while the `unit-tests` job applies **no `-m`
  filter** — contrary to what the marker's own documentation promises. It flaked once locally.
- **Four pre-existing findings, reported and deliberately not fixed** (rulings R-K, R-P, R-S, R-U):
  15 lockfile entries resolving from `registry.npmmirror.com`; a circular import that makes
  `import src.database.models` fail as the first import in a fresh interpreter; two config predicates
  that disagree about `design_system_id`; and the `live`-marker gap above.
- **The monolith path has a latent CSS defect** the aggregator fixes only for the graph path: the
  token backstop prepends in front of a hoisted `@import`, which a browser then ignores. Fixing it
  would mean editing a module ws4b may not touch. Recorded in
  `src/services/deck_css_aggregator.py`'s docstring.
- **17 deferred minors** are listed in ws4b's ledger, triaged by the whole-branch review. None blocks
  merge.
- **Ruling R2 still binds**: `src/services/agent.py`, `src/core/prompt_modules.py` and
  `src/services/design_system_compiler.py` are never modified. Your one recorded exception is
  importing `UNTRUSTED_DATA_NOTICE`. Do not widen it.
- **`agent.py`'s legacy prompt-concatenation branch is now dead in production** but still reachable in
  the tree via `create_agent()`, which three test files call. It was deliberately left in place; it
  goes as a unit when the monolith goes.

---

## 8. One process note worth more than any of the above

Across ws4b, **every single task needed at least one guard broken by someone other than its author**,
and on six of them that outside sabotage was the only thing that found the defect. Three fabricated
claims were caught — two by re-probing an agent's volunteered fact, one of which the controller had
already propagated into code without checking. Six times a confident wrong answer came from searching
an incomplete set.

The single most common defect in this PR was **not** broken code. It was a test, name or docstring
that asserted more than it could observe: a guard test that re-implemented the guard, a coverage test
that passed against an empty directory, an order assertion satisfied by silent stubs, two tests whose
kwarg was discarded by `extra='ignore'` before it reached anything, and a fixture docstring
instructing a future author how to reconstruct the behaviour the PR had just removed.

**Assign every reviewer a sabotage target its implementer has not used, and require it to say plainly
when nothing goes red.** That instruction, more than any other, is what found the defects here.
