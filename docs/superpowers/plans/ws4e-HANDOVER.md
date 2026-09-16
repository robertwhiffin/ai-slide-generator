# ws4e — the closing note for workstream 4

**Written 2026-09-16, on completing ws4e**, the fifth and last of the five workstreams.
`ws4-FINAL-PR-HANDOVER.md` set out to dispose of every item open across ws4a–ws4d. This note
records what ws4e did with that ledger, what it found that nobody expected, and what leaves the
programme with an owner.

There is no successor. Everything below is either **closed**, **filed with an owner**, or
**accepted in writing**.

---

## 1. Where things stand

- **ws4e is complete on `feat/ws4e-surfaces`, cut from `feat/langgraph-core` at `8e966ef3`.**
  Nine tasks, sixteen commits. **Not merged** — the operator merges locally, as with ws4a–ws4d.
- **Suite: `7 failed, 5515 passed, 27 skipped, 1 xfailed`.** The failure set is **identical** to
  the branch cut — a `diff` of the sorted `FAILED` lines is empty. Four environmental causes,
  unchanged.
- **Continuous integration has now executed this branch.** That was the item
  `ws4-FINAL-PR-HANDOVER.md` §4.1 said should be done first rather than last, and doing it first
  is what found the merge blocker in §3 below.
- **All seven release-gate checks have a disposition**, six passed on a live devloop deployment and
  the seventh skipped for want of a mechanism the plan itself says does not exist.
- **The user can now see what the graph does.** The spec view renders the architect's plan, the
  drawer shows real findings, slides appear as they are released, and a non-blocking flag says when
  the deck review is running.

**The plan was nine tasks, not seven.** Two were added on measurement, both assigned to ws4e by
name in the final handover's §3b and §4.1: **E0**, rendering the incremental slide event, and
**E7**, the continuous-integration hang.

---

## 2. Why continuous integration had never run, and what to do about it

`test.yml` triggers on `pull_request` into `main` or `release/**`. Every workstream landed through
pull requests based on `feat/langgraph-core`, which **matches no trigger**. That is the whole
mechanism. Four workstreams' Definition-of-Done items went unclaimed for want of one branch name.

**Filed:** either add `feat/**` to the trigger, or make the integration branch a `release/**` name.
Until one of those happens, the next stacked programme will repeat this exactly.

---

## 3. THE THINGS ws4e FOUND THAT WOULD HAVE SHIPPED

Each was measured, not reasoned, and each was invisible to the review that should have caught it.

| | |
|---|---|
| **`integration-graph` hung a runner for 22 minutes, and no job had a timeout.** One test drove a route that built a real workspace client to resolve a username; CI's unreachable host sent the SDK into a retry-sleep loop. Same file, real host: 11 tests in 8 seconds. Invisible because `load_dotenv()` gives every laptop a host that answers. **The first CI run found it** | E7 |
| **The review-in-progress badge's end-to-end spec failed every run, and its two sibling tests passed BECAUSE the badge never rendered.** An inert pair: three assertions, one red, two vacuous, and only the red one could tell you. The harness delivered the slide releases and the turn's completion in a single chunk, so the window the badge exists to cover never opened | final review C1 |
| **Both cross-process concurrency tests could never have passed in CI.** They handed the child a rendered database URL, and rendering masks the password — the child got three asterisks. Locally the fixture URL carries no password, so trust auth let it through. Never seen because that job had never run | final review C2 |
| **E2b's flag had neither operand.** The plan called its formula *"exact, not a heuristic"* and said *"the client already holds everything required"*. There was no `slide_ready` case in the stream handler — `api.ts` said so in its own comment — no released-position state anywhere, and no `deck_spec` on the deck type. Its headline test could never have gone green | corrections §6 → E0 |
| **The ascending-order logic had no guard at all.** Appending releases instead of inserting them reddened nothing, with 62 tests green. Ordering was asserted only by an end-to-end test that aborted before its first assertion | E0 review |

**The class all five share, and the most useful sentence in this note:** *an artefact was built and
never executed in the environment it was built for.* Three of them are the same laptop-versus-CI
asymmetry ws4d fixed once already for `TELLR_TEST_POSTGRES_URL`.

**So the process gap is named:** **no task was ever required to run the Playwright spec it added**,
though the repo's own guard ships each new spec straight into a build gate. That produced C1, and
C2 is the same root with CI-shaped inputs. **A future brief template must demand that the author
runs the artefact where it will run.**

---

## 4. The consolidated ledger, closed

### 4.1 Closed by ws4e

- **Continuous integration has executed the branch.** Unit tests, frontend unit tests, frontend
  build and wheel build green on a runner; the first run also carried `integration-graph` and found
  it hanging.
- **`timeout-minutes` on every job.** Only `integration-general` had one; all sixteen now do, with a
  guard that reddens if a future job omits it.
- **The release gate.** Six of seven checks passed on a devloop deployment, evidenced rather than
  eyeballed — the checks were driven through the app's own API and, for the two UI-shaped ones, a
  real browser.
- **Optimistic locking, lock ordering, sweeper throughput and the release query** are now covered by
  a layer-4 suite against a real Postgres, including a cross-process read whose sabotage
  discriminates (the first process buffers instead of persisting; the child sees nothing).
- **The fifteen retired-regex rules** have their meanings derived from the code and recorded in
  `.ws4e-PLAN-CORRECTIONS.md` §9. Fourteen of the fifteen anchors the plan gave had drifted by 150
  to 600 lines while **every meaning was correct**.
- **Finding 26b struck as stale:** `test_export_parity.py` *is* named at `test.yml:553`.

### 4.2 Filed, with an owner — these leave the programme

| Item | Why it matters | Where the evidence is |
|---|---|---|
| **§4.3's selective rebuild is MEASURED AND FAILING** | A real model emitted `brief_not_delivered` on **3 slides of 3** — the sole criterion driving the decision. On that evidence a deck-level edit rebuilds every slide and **destroys manual edits**, the exact outcome §4.6 exists to prevent. **The single item to close before the graph path touches a deck anyone cares about** | this note, and the operator's decision to accept the stage-1 signal rather than pay for stage 2 |
| **A reviewer invents contradictions** | 3 of 12 findings on a real deck were `source_contradiction`, asserted against `resolved_data.figures` that is **always empty**. A product defect, not a test gap | corrections §10c |
| **The startup backfill logs one INFO line per slide row** | Implicated in **eight minutes of 502 while the app reported RUNNING**, on a production-sized dataset. `RUNNING is not serving` — which E6 check 1 treats as its first observable | the deployment's own log |
| **"Production INFO logging is dead code" is WRONG** | Those INFO lines came from a production deployment. `setup_logging()` genuinely has no caller, but something else configures logging. So the `mark_dirty` audit trail may exist after all — **verify, do not assert** | same log |
| **A devloop `update` re-forks the branch** | It discards prior session data and re-runs the multi-minute backfill on every deploy. Worth documenting in the deploy skill, along with `databricks psql` as the way to query a branch — which the skill also omits | this note |
| **Unbounded checkpoint growth** | One whole-state blob per checkpoint and an uncapped findings list, so growth is **super-linear in turns**. `delete_thread` exists and works; what is missing is a retention *policy*, which is a product decision with a data-loss failure mode | corrections §10c |
| **An architect-emitted spec is unchecked** | And **the fix the previous handover proposed is struck**: set equality would reject legitimate deck growth, so the cheap fix is a new defect. The honest shape is superset-plus-contiguity in a new helper | corrections §10c, Ruling E-8 |
| **`--db-navy7`** | One CSS token referenced and never defined. One unresolved `var()` falls back; it does not wash out a deck | E6 check 5 |
| **The huashu export preflight flake** | ~29% in isolation, no workstream-4 code in the process. Not this programme's defect, and it will confuse every future by-cause comparison until someone owns it | inherited from ws4d |
| **Three `slide-surface-fidelity` e2e failures** | Spec and matrix entry both predate workstream 4 by six weeks; causes are in-iframe filmstrip styles. **A standing red, not a regression** | re-measured twice |

### 4.3 Accepted in writing

- **The three retired-regex CI tests are all skipped, and that is the finding.** None has a
  counterpart on the graph path: `invoke_graph` is called with `{"architect_message": …}` and
  nothing else, `GraphState` is a closed contract of thirty keys whose undeclared keys the runtime
  silently drops, and the deck cache RC6 guarded was replaced outright by row-per-slide
  persistence. **They are written and skipped rather than deleted, deliberately** — because if a
  later change lets the graph accept slide context, two of those shipped bugs become reachable
  again. **They have no tripwire; that is the gap in this ruling**, and E3 built one for the same
  problem.
- **Layer 3 ships skipped, with three mechanisms**: a marker for selection, an endpoint guard for
  safety, an unconditional placeholder skip for honesty. Enabling it is a workflow edit **plus one
  line** in `gates.py` — annotated in four places rather than glossed as "workflow-only", because
  the placeholder gate exists to make a human confront that the prompts are placeholders, and a
  value CI can flip defeats that.
- **Three of layer 3's seven behaviours are unreachable** — the analyst can call nothing, because
  no tool binding exists anywhere. One plan row therefore has **no live coverage on any path**.
- **`resolved_data` is NOT added to the re-review trigger.** The one-line change is inert while
  `figures` is always empty, and shipping an inert trigger is a manufactured tautological guard.
- **Production logging stays off in ws4e** — see 4.2, where its premise is now in doubt.

---

## 5. What must be true before PR3 merges

Everything `ws4-FINAL-PR-HANDOVER.md` §5 said still holds — the two release-note lines (durable
slide identity, the dropped `ConfigPrompts` columns), ruling R2, and the placeholder-prompt caveat.
Add three:

1. **§4.3 above.** The selective rebuild's economics are measured and they fail. This is the one
   item that can destroy a user's work.
2. **A full CI run must complete green.** At the time of writing, unit, frontend and wheel jobs are
   green on the fixed branch and the integration jobs are still running. **The `layer4-integration`
   job has never completed a run**, because it did not exist until this workstream — so its first
   real execution is still ahead.
3. **The startup window.** Eight minutes of 502 on a production-sized dataset is not a merge
   blocker for a dev fork, but it is a production question.

---

## 6. Traps ws4e paid for, on top of the inherited list

- **`--ref` on a workflow dispatch resolves against the REMOTE head.** Publish a dev wheel before
  pushing and you build the wrong commit — then the corrected run collides on the auto-incremented
  version and fails. Push first.
- **`RUNNING` is not serving.** The app reported RUNNING and SUCCEEDED while returning 502 for
  eight minutes.
- **A devloop `update` re-forks**, discarding session data. Do not build test state and then
  redeploy expecting to find it.
- **The repo's hook guard reads the whole command string.** It refused a `git commit` because
  `pytest -n auto` appeared later in the same line and it read `-n` as `--no-verify`. Split the
  commands.
- **A source-text assertion is always satisfiable by a comment containing that text.** Tightening
  the pattern narrows the loophole; it cannot close it. Two such assertions here were replaced with
  behavioural tests, and one deliberate one remains because types are erased.
- **A sabotage that does not compile is not a sabotage.** One reddened seventeen tests by failing to
  build rather than by changing behaviour — indistinguishable from a test that cannot fail.
- **The plan's E6 check-1 query is schema-blind**, and a devloop branch is forked from production,
  which carries many application schemas. It returns 14, not 0, and can never return 0. Narrow it
  to the deployment's own schema.

---

## 7. Where the decisions are recorded

**Twenty rulings**, each with what it costs if wrong, in
`.superpowers/sdd/2026-08-25-ws4e-surfaces-and-gates/progress.md`. Three are corrections to my own
earlier rulings, and two were amended by the whole-branch review — which was right both times, and
one of them (folding a scoped re-review into the final one) is what let a comment-satisfiable guard
through. Recorded as a cost actually paid.

The corrections file, `.ws4e-PLAN-CORRECTIONS.md`, **overrides the plan** and carries the fifteen
rule meanings that discharge a Definition-of-Done item in their own right.

**The workspace is deliberately NOT deleted until the operator merges**, because until then the
ledger is the only record of decisions taken on their behalf.
