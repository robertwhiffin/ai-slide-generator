# ws4-index — round 1 findings (VERBATIM, do not paraphrase)

Reviewer re-ran the runtime probes and checked anchors against code, the four sibling plans, the
superseded plan, the spec and git history.

## Blocking

**1. ws4b depends on ws4a, so the dependency graph is wrong**

The index states `ws4b … needs nothing from a/c/d/e` and "**ws4a is genuinely parallel.** It shares no
file with b–e except the e2e workflow… **nothing waits on it.**"

But the index itself assigns the CSS aggregator to ws4b, and `ws4b-contracts-and-schema.md` line 715
specifies it as: "Merges the blocks with **ws4a's at-rule-preserving `merge_css`**", with test intent
"at-rules survive". Today's `merge_css` drops every at-rule — reproduced on the shipped code:

```
merge_css(sheet, sheet) on :root/@font-face/section.slide/@media print/@keyframes/@supports
  → only ':root' and 'section.slide'
```

So B3.3's contract and one of its tests cannot be satisfied until ws4a lands. ws4a must be marked as
blocking ws4b. Related: ws4a's Task A1 attributes the dedupe requirement to "ws4c's CSS aggregation" —
the aggregator is ws4b's, per the index's own table.

**2. ws4a depends on ws4b — A2 asserts a column ws4b creates**

`ws4a-shipped-defects.md:140` test intent: "the duplicate's `spec_dirty_at` is `NULL`".
`spec_dirty_at` exists nowhere in the repo (zero hits across `src/` and `frontend/src/`); it is created
by ws4b's B2.3 migration. So ws4a as written is not executable standalone, contradicting both "ws4a —
Depends on: nothing" and the index's "nothing waits on it". Either drop that assertion from ws4a or
record the ws4b dependency.

**3. "Every item is a defect live on `main` today" is false for three of ws4a's four items**

Verified against `main`:

| Item | Status on `main` |
|---|---|
| A1 `merge_css` | genuinely live — same code, reproduced above |
| A2 `deck_spec_json` | **the column does not exist on main at all** (`git grep deck_spec_json main -- src/` → 0 hits). PR1-only |
| A3 stale docstrings | **`src/core/backfill_session_slides_startup.py` does not exist on main** (`git ls-tree main` → empty). PR1-only |
| A4 e2e matrix | nature is right, numbers are branch numbers: main has **14** matrix entries, **18** specs in `frontend/tests/e2e/`, 33 total — not 23/32/49 |

Root cause: **the index never states that PR1 (row-per-slide) and PR2 (dependency upgrade) are unmerged
prerequisites carried on `feat/langgraph-core`.** Main still pins `langgraph==1.0.10` with no
`langgraph-checkpoint`; 409 commits separate main from HEAD. The parent spec names them
(`2026-08-06-agentification-core-design.md` §2 "Prerequisites (separate PRs, landing first)"); the index
does not. Downstream consequences: the 4188-collected baseline is a branch baseline, "independent,
mergeable today" means "onto the integration branch", and anyone opening ws4a against main hits two
missing symbols. Add the prerequisite line and change "live on `main`" → "live on the integration
branch".

## Significant

**4. The ws4a summary understates the CI gap by 9 specs and mislabels which 17**

Index: "the e2e matrix collects the 17 specs it currently ignores." Measured on the branch: 23 matrix
entries; 32 specs in `frontend/tests/e2e/`, of which **9** are absent from the matrix (`admin-page`,
`design-system-brand-text-uncapped`, `genie-detail-panel`, `save-points-versioning`,
`session-config-isolation`, `slide-host-frame`, `slide-viewer`, `style-source-exclusivity`,
`template-viewer`); plus **17** strays outside `tests/e2e/` (11 in `frontend/tests/`, 6 in
`frontend/tests/user-guide/`). Uncollected total is **26**, and the 17 are the *relocation* set, a
different set from the ignored one. ws4a's A4 body gets this right; only its Goal line and the index's
summary are wrong. The decomposition commit quotes a third number (9).

**5. "~390 fenced blocks" double-counts — it is 195**

`grep -c '^```'` on the superseded plan returns 390, i.e. fence *delimiters*, two per block → **195**
blocks (193 with a language tag). This is the index's measured cause for the review loop's failure and
is quoted against ws4a's "2 code fences" (1 block), so the comparison is 2× off in one direction.
Restate as "~195 fenced blocks (390 fence lines)".

**6. §K4 / §K7 / §K8 / §K9 are unresolvable citations**

The index names the spec authoritative; the five plans cite §K4 (3×), §K7 (3×), §K8 (3×), §K9 (5×).
`grep -E '§?K[0-9]'` on `2026-08-12-pr3-open-questions-design.md` returns **nothing** — §K (line 1319,
"What this document does not decide") is three unnumbered bullet lists. The scheme is
reverse-engineerable and internally consistent (K1/K2 = the two struck-through resolved items, K3 =
§M7's probes, K4 = pre-fan-out deterministic CSS, K5 = `merge_css` at-rules, K6 = tone-vs-BRAND-MANUAL,
K7 = dirty-marker storage, K8 = sweeper identity, K9 = finding-id behaviour) — but an executor cannot
derive it. Number §K in the spec or put the mapping in the index's conventions.

**7. "Retries jump the queue by construction" is false as stated**

Design invariant: "Concurrency cap 15, ascending dispatch, **retries jump the queue by construction**."
Ascending dispatch only puts a retry ahead of *higher* unstarted positions — a failure at position 30
with 15–29 unstarted jumps nothing. ws4c states it correctly ("ahead of **higher** unstarted
positions"). The index is inherited verbatim and read first, so the compressed version is what a test
will be written against.

**8. The cause-based gate has no canonical baseline artifact**

The index rules "Save the log, not the number" and "Re-derive after every schema/ORM/dependency change"
but names no location. ws4e then hardcodes `diff … /tmp/pr3_baseline.log` — an ephemeral path expected to
survive five PRs, with nothing saying who produces it or whether each PR re-derives its own. Name the
artifact here.

**9. No base-branch or stacking strategy for the serial b→c→d→e chain**

The index gives the arrows and the escalate-don't-edit rule, but never states each PR's base branch,
whether ws4c branches off ws4b's *unmerged* branch or waits for its merge into `feat/langgraph-core`, or
what happens to ws4c when a ws4b contract changes during review. For "the shared contract between five
plans", that is the missing operational half.

## Minor

**10. R1 calls all 13 repointed suites "security suites" — only 3 are.** Verified: 13 test files
reference `src.services.agent`; ws4c names exactly three as security suites
(`test_agent_safety_gate.py`, `test_safety_gate_http.py`, `test_slide_context_injection.py`) and says
"the other ten keep testing the monolith". R1 is the ruling that decides delete-vs-repoint, so
mislabelling ten monolith suites invites the wrong triage. The "six `agent_factory` suites" half is
correct.

**11. "21 findings unfixed… each is assigned below" does not hold.** The table has 21 rows, but #2 is
one of round 3's *nine blocking* findings, already fixed in `dc3aac0f`, and the index labels it "fixed".
#15 — a genuine High/Medium — is silently absent; it was fixed by `9d3d878e` ("Also fixes round 3's
finding 15"). True carry-forward: 20 items, 3 dissolved, 17 assigned. The decomposition commit says "15
to an owning PR, 6 dissolved", matching neither.

**12. #18 and #26 have two owners each but one is named.** #18's `duplicate_session`-takes-a-string half
is discharged in ws4a's A2 note, not ws4d. #26 is assigned to ws4d, but ws4b's B1.5 is where
`scripts: str` is actually picked (it cites "(Round-3 finding 26.)"); ws4d only honours it.

**13. #20 reads as a shipped defect but constrains code that doesn't exist.**
`_check_deck_permission_for_session` does default to `CAN_VIEW` (`_authz.py:190`), but `clear_context`
appears nowhere in the repo — ws4d D1 says so explicitly. Phrase as "must gate on `CAN_EDIT` when
built".

**14. R2 contradicts its own exception.** R2 forbids composing from `src/core/prompt_modules.py`, then
requires `UNTRUSTED_DATA_NOTICE` be imported — and that constant lives at `prompt_modules.py:34`. Intent
is clear from the parenthetical; as a rule someone greps against, it reads as self-contradictory. Fold
the exception into the rule.

**15. Two anchors point at the wrong span.** `get_verification_map` is cited as
`session_manager.py:1793-1811`; 1793 is the `def` and the rest of that range is docstring — the
flattening logic the invariant rests on is below it. (And ws4a anchors the at-rule loss at
`css_utils.py:28-34`, which is inside `parse_css_rules`; `merge_css` is at `:41`. Right root cause,
misleading location.)

## Verified sound — do NOT re-litigate

- **All seven "verified runtime facts" reproduce exactly on langgraph 1.2.10**, including the barrier
  (batches of 2 over 5 positions woke exactly 4 times: `[], [0,1], [0,1,2,3], [0,1,2,3,4]`); a
  `Send`-reached node saw exactly `['batch','position']`; 3 builders → **1** static-edge invocation with
  plain state; undeclared keys dropped in *both* directions; turn-2 accumulation surviving a fresh
  `checkpoint_ns`.
- `DEFAULT_RECURSION_LIMIT` = **10007** on the pyenv stack; = **25** in the gitignored in-tree `.venv`.
  `Send(timeout=)` present on 1.2.10, absent on 1.0.3; the sync-node `ValueError` string is at
  `langgraph/_internal/_timeout.py:9`; the `thread_id` `ValueError` at `langgraph/pregel/main.py:2591`.
- Baseline: **4188 collected**; `test_deploy_autoscaling.py` fails twice with exactly the two quoted
  strings at `:124` and `:152`; 3 + 4177 + 8 = 4188.
- Every other file:line anchor checked out: `chat_service.py:825`, `job_queue.py:202`, `run.py:128`,
  `session_manager.py:1859`/`:2772`/`:1014-1026`, `src/services/agent.py:1582`,
  `slide_repository.py:41-61` and `:84`, `src/core/database.py:411`/`:414`/`:584`, `_authz.py:188-191`,
  `FeedbackDrawer.tsx:13`. `slide_hash.py:44`/`:69-72`: the docstring example is indeed wrong.
- `frontend/tsconfig.json` is a solution file, `npm run typecheck` is `tsc -b`, `frontend/src/ui/`
  exists and `frontend/src/components/ui/` does not, RC1–RC15 all present in `src/`, and
  `langgraph==1.2.10` is already pinned in `packages/databricks-tellr-app/pyproject.toml` — so "none of
  these five adds a dependency" holds.

## Cross-document slips noticed while checking (same fix pass)

- ws4b's B1.5 is titled "The five remaining skill output schemas" when B1.1 covers three of seven,
  leaving **four**.
- ws4c's Definition of Done says the layer-1 suite "asserts all twelve behaviours in C5" when C5's table
  has **eleven** rows.
