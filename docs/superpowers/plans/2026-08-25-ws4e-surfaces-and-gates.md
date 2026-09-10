# ws4e — Surfaces, test layers and the release gate

> **For agentic workers:** REQUIRED SUB-SKILLS: `superpowers:subagent-driven-development` **plus**
> `executing-plans-tellr`. **Read `2026-08-25-ws4-index.md` first** — this plan inherits its Global
> Conventions and does not repeat them.

**Goal:** Ship the two UI surfaces §7.1 promises, stand up the two test layers that cannot live in CI
as-is, re-derive the retired-regex checklist from the code, and close PRD §3's no-regression gate on a
real deployment.

**Why this is its own PR:** everything here needs the graph to be *producing* something. The spec view
needs a persisted spec, the drawer needs real findings, layer 3 needs a real model, layer 4 needs
parallel writers, and the release gate needs a deployment. None of it is testable before ws4d.

**Depends on:** ws4b, ws4c, ws4d. **Blocks:** nothing — this is the last of the five.

**One interlock worth knowing:** ws4a added a guard test asserting every `*.spec.ts` under
`frontend/tests/e2e/` is either in the CI matrix or in `DELIBERATE_EXCLUSIONS` with a reason. So **every
new Playwright spec this PR writes must be added to the matrix in the same commit**, or that guard fails.
That is the interlock working as intended.

**Spec:** §7.1, §7.4, §7.5, §F1–§F4, §G1–§G3, §9, §M7 (probe 3 only), PRD §3, PRD §12.1. (§7.2 is ws4d's work, not this PR's; §M7 probes 1–2 are ws4c's.)

---

## E1 — The spec view toggle

**Contract:** a `SpecView` component reading `slideDeck.deck_spec` — ws4b's new read-path key, so **no
new endpoint** — and a toggle in `AppLayout.tsx` beside the existing view controls. **Critical:** implement
as a **local `showSpec` state inside the main view**, not an entry in `ViewMode`. `ViewMode` drives route-level
navigation via `navigate()`, and adding `'spec'` would unmount the ChatPanel, destroying the conversation state
and any in-flight stream. The chat and viewer must coexist unconditionally; the toggle switches which panel
renders inside them (`AppLayout.tsx:944-946` carries a shipped comment warning about remount hazards).

**TypeScript surface:** E1 renders `narrative_arc`, `slides[].assumes`/`hands_off` and `design_contract` ids
from a `DeckSpec` object. Create TypeScript types mirroring `DeckSpec` (currently ws4b mirrors only `Finding`);
add a `deck_spec` field to `SlideDeck` (`frontend/src/types/slide.ts:16-28` has none); and add a conformance
test to `frontend/src/services/__tests__/` asserting the shape matches the server schema. ws4b's `Finding` type
came with such a test precisely because "there is no runtime bridge, which is exactly why they had already
drifted."

**§7.1's shape, and the two alternatives it rejects.** A toggle: **view slides ⇄ view spec**, with **one
conversation throughout** — not a second chat, not a filtered view. Rejected: putting the spec in the
per-slide drawer (it congests what is already power-user surface, and there is no natural home for the
*deck-level* spec); and a second conversation in a spec pane (two histories to persist, restore, snapshot
and reconcile — and the architect would hold spec decisions the main chat never saw, which is PRD §5.1's
"silently dropped" failure arriving by another door).

**Read-only plus discuss.** Editing stays conversational, so the architect remains the sole author and
there is one write path. A directly editable spec was rejected: a second author racing the async rebuild
loop could silently overwrite the user's edits.

**View is a hint, never a mode.** Intent comes from language, not view state. `SelectionContext` was
deleted in ws6 precisely to stop UI state gating intent, and that must not be walked back — "tighten the
arc" edits the spec, "make slide 5 bolder" edits the slide, **whichever view is open**. So the toggle
switches which panel renders and **nothing about it reaches intent parsing**. Assert that: the toggle's
state must not appear in any request body.

**Permissions are free here.** §7.5 makes spec visibility equal deck visibility — contributors and
read-only viewer links included — and the spec rides `get_slide_deck`'s dict. Enforcement lives in the route
(`src/api/routes/slides.py:87`, `_require_slide_permission`), not in `get_slide_deck` itself. Nothing to add;
assert that the route gate is still there, not that `get_slide_deck` checks permissions (it does not).

**Test intent** — a component test plus one e2e spec:

| Assertion | Why |
|---|---|
| deck-level fields render: audience, purpose, argument, call to action | |
| the narrative arc renders **in order** | An unordered arc is a different deck |
| each slide brief renders with its `assumes` / `hands off` contract | Those are the fields that make the arc legible |
| **no `input`, `textarea` or `contenteditable` anywhere** | Read-only is a structural property, not a styling one |
| Discuss is offered and is the only write path | |
| a specless deck renders an empty state rather than crashing | Pre-cutover and MCP-built decks have no spec |
| the design contract shows **which** brand (ids), never compiled style content | §L3 — the spec stores a reference |
| a contributor sees the spec | §7.5 |
| **the conversation (and any in-flight message stream) survives the toggle** | Structural property — no remount |
| **dismissed findings are still dismissed after toggling to spec and back** | `dismissed` is `useState` reset on `deckKey` change; state must survive |

**CI note:** E1's component test is collected by **ws4b's `frontend-unit-tests` job** — ws4b owns that job
outright and lands first, so **this PR adds no vitest job**. ws4a's guard test covers only `*.spec.ts`
under `frontend/tests/e2e/`, so it does not fire on component tests under `frontend/src/`. **Verify the
collection rather than assuming it:** run `cd frontend && npm run test:unit` and confirm this PR's
component test files are in the collected set. If the job is missing, escalate to ws4b — a component test
that runs nowhere is the silent disappearance this note exists to prevent.

---

## E2 — Wire the drawer to real findings

**Today the drawer is fixture-wired.** Its callbacks point at `console.info` against test-injected
findings — `testFindings` is an `AppLayout` state variable filled from `window.__TELLR_TEST_FINDINGS__`,
and **production renders an empty list** (`AppLayout.tsx:762`, `:988-990`).

**Slide-level findings come from `session_slides.verification_record` (§F3)**, which is hash-keyed,
**merged never overwritten**, travels with its slide on reorder, and is re-materialised by
`restore_version` — all built and tested in PR1. A parallel store would re-solve reorder-safety,
edit-then-revert recall and save-point restore, each of which PR1 already got right once, and one of
which shipped as a defect during 0a before being caught.

**Deck-level findings do NOT come from here.** They route to **chat** (PRD §3's grain routing) and live
in `deck_reviews` keyed `(deck_id, deck_digest)` (§F4). The drawer must never render one.

**Where the positive half of §F4 is delivered, so this negative assertion is not the whole story:**
`deck_reviewer_node` (ws4c C4) persists the verdict as a `role="assistant", message_type="info"` chat
message, which renders through the existing transcript with no change in this PR, and `architect_node`
reads the structured row back via `get_deck_review`. **This PR adds no deck-findings surface** — if you
find yourself building one, stop: that is the drawer rule being violated from the other direction.

**Test intent:**

| Assertion | Why |
|---|---|
| findings render from the slide's verification records, not from a test global | The wiring itself |
| findings are scoped to the current slide by `slideIndex` | |
| a finding **travels with its slide across a reorder** | §F3's non-obvious property, and the 0a defect |
| a finding with a deck-level criterion AND a real slide index does NOT appear | Grain routing. Build it in the **component** test on its own injected finding — never on `mockFindings.f3` (see the note below) |
| Apply / Dismiss / Discuss call real handlers, not `console.info` | |
| Dismiss persists to seen-state keyed `(deckKey, finding.id)` | `seenState.ts`'s store shape |
| **a re-review of an UNCHANGED slide does not re-highlight a dismissed finding** | §K9, half one |
| **a finding re-raised after an EDIT reads as unseen** | §K9, half two |

**Those last two are the pair that justify ws4b's id rule**, and they are the reason it had to be settled
before any code bound to it. A `(criterion, subject_hash)` composite is what makes both true at once (ws4b
names this `make_finding_id(criterion, subject_hash, ordinal)` — **three** arguments, where `subject_hash`
is the slide hash for slide findings and the deck digest for deck findings, and `ordinal` separates two
findings of one criterion on one subject); either component alone is satisfiable by a simpler scheme that
breaks the other. **Note:** `slideIndex: -1` assertions are tautologies (filtering already excludes them),
so the real test must be a *deck-level criterion on a real slide index* — and it gets **its own fixture
data, injected by the component test**. Do not reach for `mockFindings.f3`: ws4b pins it at
`slideIndex: 3`, unreachable in the 3-slide e2e deck (`slide-viewer.spec.ts:63-64`), and that is exactly
what keeps `drawer-empty` visible on slide 2 at `:319`. Ten e2e assertions at `:314-359` are bound to
that fixture, so moving f3 onto a reachable index to give this assertion something to filter turns
`:319` red — and ws4b forbids the move for that reason. `mockFindings` is left alone.

**Note ws4b already delivered the `status` branch** (fixed findings render read-only) and the `hasUnseen`
rule (a fixed finding does not count as unseen). This task wires real data into that behaviour; it does
not re-implement it.

**CI note:** E2's component test is collected by the same **ws4b `frontend-unit-tests` job**. Confirm it
appears in `npm run test:unit`'s collected set, exactly as E1 requires.

---

## E2b — §7.4: The "Agentic deck review in progress" flag

**§7.4 names a non-blocking UI flag: "Agentic deck review in progress"**, with the spec's warning that
*"a flag that gates export is a serial gate wearing a spinner"*. This means the flag suppresses nothing
— export, presenting, and editing all stay live. It is purely informational: a user seeing it knows a
review is pending.

**Contract** — trigger on the marker being set (ws4d D4's `spec_sync.mark_dirty`), clear when the
review completes or the marker clears. The flag lives in UI state (`AppLayout`), not server state.

**Where it appears:** §7.1's spec view, as a subtle spinner or "Review pending" badge. The spec does
not name a location; choose one that is discoverable but non-intrusive — e.g., near the view toggle or
in the spec pane header.

**Test intent** — a component test plus one e2e spec:

| Assertion | Why |
|---|---|
| the flag appears once a marker exists on a deck | editing triggers it |
| the flag disappears when the marker clears | successful review or restore |
| **editing, export and presenting all stay live while the flag is set** | "non-blocking", stated as a structural property — buttons work, routes respond |
| a failed review clears the claim but keeps the marker, so the flag stays on | retried reviews must not flicker the UI |

**Sabotage:** make export gate on the flag and confirm the test goes red — confirming that the sabotage
landed and that the gate is not in the code.

---

## E3 — `tests/agentic/`: layer 3, honest and skipped

**§G's four layers, organised by what each needs in order to run** — not by marker. The spec conflated
"excluded from CI" with "rarely run"; the real constraint is environmental.

| Layer | Needs | In CI | Owned by |
|---|---|---|---|
| 1. Orchestration | nothing — stub agents, real compiled graph | ✅ via ws4c's **`integration-graph`** job | ws4c |
| 2. Schema / contract | nothing — canned payloads | ✅ | ws4b |
| 3. **Agentic behaviour** | a real model via local Databricks | ❌ today | **here** |
| 4. Concurrency / multi-worker | a database, no model | ✅ | **here** |

**`tests/agentic/` is a SIBLING of `tests/unit/`, not a subdirectory — and that placement is what makes
the marker sufficient.** The `unit-tests` job runs `pytest tests/unit -v --tb=short -n auto` with **no
marker filter and no `DATABRICKS_HOST`/`DATABRICKS_TOKEN` at all** (`test.yml:100-105`), so **under
`tests/unit/` the `live` marker is not a CI gate.** The repo already documents the consequence in
`tests/unit/test_dependencies_resolve.py:19-25`: those tests *are* collected in CI and are "saved only
incidentally because the Databricks proxy host is unreachable". A layer-3 suite parked under
`tests/unit/` would be collected on day one.

**Built CI-ready now, enabled later — and "enabled" means three mechanisms, not one.**

- **The workflow gate** is a **new job** running `pytest tests/agentic -m live` with real credentials,
  added **disabled** (`if: false`). When the repo moves to a company org, turning this on must be a
  workflow change and **nothing else** — no test rewrites.
- **A `skipif` guard on endpoint reachability**, so a test collected without `DATABRICKS_HOST` reachable
  skips rather than fails.
- **An unconditional `pytest.mark.skip(reason="real prompts pending")`**, distinct from the endpoint guard.
  Local `.env` contains `DATABRICKS_HOST`, so the endpoint guard passes locally; the real barrier is that ws4c
  ships placeholders, not the real prompts. Every layer-3 test carries both guards — **marker for selection,
  endpoint guard for safety, placeholder skip for honesty**.

**The trap to refuse, stated as a rule.** Layer-3 tests are written against **real prompts** and ws4c
ships **placeholders**, so they will not pass. **Mark them skipped and enable them with the real
prompts.** The failure mode to refuse is **weakening a layer-3 assertion until a placeholder satisfies
it** — that manufactures exactly the "test that cannot fail" class this project has already paid for
twice. **A skipped honest test beats a passing dishonest one.**

**§G2: assert structure AND behavioural outcomes, never wording.** §9's "structure, never wording" is
necessary but insufficient — it can confirm a reviewer returns valid JSON, not that it reviews well. So:

| Behaviour | Assertion shape |
|---|---|
| the architect **asks** rather than picking when a reference is ambiguous | intent is `discuss`, and the message contains a question — this is RC10 from E5's table |
| a deliberately-broken slide **is** flagged by the build reviewer | a finding with `criterion == "overflow"` exists — judged against `_SLIDE_FRAME_CONSTRAINTS`' numbers, the same ones the builder received |
| the fixer's diff is **small** relative to the finding | a diff ratio below a threshold — not a re-author |
| the fix reviewer **keeps the original** when handed a worse "fix" | verdict is `surfaced` |
| the analyst returns exactly one of its three outcome shapes | one call per outcome, asserting `outcome` |
| a **single source passes through** without re-summarising | the canned tool output appears verbatim in the synthesis |
| **§M7 probe 3:** the section inventory supports good assignment | a title slide gets the title section, not the data section. If names and snippets prove insufficient the inventory grows — thumbnails already exist per template, though not per section |

**Phrasing is never asserted.** Add a guard on ourselves: a test that reads this module's own source and
fails if it contains a wording comparison. Layer 3 is exactly where that temptation lives.

**Test intent for the placement itself** — a cheap unit test, because the placement is the mechanism:
`tests/agentic/` exists and `tests/unit/agentic/` does not; every file under it carries **both**
`pytest.mark.live` and a `skipif` guard.

---

## E4 — Layer 4: concurrency and multi-worker

**The bug class this rebuild exists to remove** (PRD §12.1). Needs a database, no model, runs in CI.

| Assertion | Why it earns its place |
|---|---|
| 15 parallel row writes do not collide | The precondition for the fan-out. Row-per-slide exists for this |
| the deck-level `version` counter still rejects a stale write with **409** | The optimistic lock survives the new writer |
| **two** deck-level writes in one turn do not conflict | §L2's two writes, neither per-slide |
| **the release query is correct from a DIFFERENT PROCESS than the builder** | **This test must fail if anyone reintroduces in-process buffering.** Run the build in one process, then compute releasable positions in a second with a cold cache |
| the checkpointer **resumes a turn in a second process** | Graph state must be visible to every worker, or the architect's conversation is lost the moment a poll lands elsewhere |
| **four concurrent sweepers run at most one arc review** | ws4d defers this here deliberately: its sqlite version is weak by construction, because sqlite's single-writer lock surfaces `database is locked` rather than demonstrating the race. **This is the load-bearing version** |

**Sabotage the cross-process one.** A cold cache in a fresh process misses and reads the DB, so an in-process
cache sabotage stays **green** and masks the defect. Instead: have the **first process buffer instead of
persist** to the database and confirm the second process sees nothing (finds no releasable positions), or assert
the child process ID (`os.getpid()`) differs from the parent. Either discriminates in-process buffering from
a genuine cross-process read.

**CI: the layer-4 integration job** — `.github/workflows/test.yml` adds a new **`layer4-integration`**
job running `pytest tests/integration -k layer4 -v --tb=short` (or a marker-based filter of your choice).
The job must use the shared database fixture from `tests/integration/conftest.py` (ws4b's infrastructure
task). The job is **enabled by default** (not disabled like the layer-3 job) because it needs only a
database, not a live model endpoint.

---

## E5 — The retired-regex regression checklist

**PRD §12.1 is explicit** that the retired regex rules "each encode a previously-shipped bug fix" and are
"a test checklist for the supervisor's intent handling, not merely dead code to delete."

**There are RC1–RC15, not six** — verified by grepping the in-code markers. The RC table in the immediate
superseded plan (`2026-08-24-pr3-langgraph-core.md`) is correct and appears again below. An earlier draft
(`2026-08-09-pr3-langgraph-core.md:2728-2730`) had wrong ordinal/range/relative mappings. **Wrong-but-plausible
mappings are the worst class of defect here, because a test written against the wrong semantics ships the
regression green.** Do not teach this plan to distrust the correct table it reproduces.

**Derive every rule from the code before writing a single test:**

```bash
grep -rn 'RC[0-9]' src/ | sort -t: -k1,1 -k2,2n
grep -rhoE 'RC[0-9]+' src/ | sort -u -V        # expect RC1 .. RC15
```

**Ground truth as far as it was verified — treat this as a starting point to confirm, not as authority:**

| Rule | Meaning | Anchor |
|---|---|---|
| RC2 | reuse `_is_add` from early detection | `chat_service.py:575` |
| RC3 | guard: `slide_context` was provided but parsing failed | `:547` |
| RC5 | validate and attempt to fix JS syntax errors in slide scripts | `src/utils/js_validator.py:3` |
| RC6 | the deck cache survives backend restarts | `:532` |
| RC7 | log script status before and after | `:582`, `:625` |
| RC10 | **edit intent WITHOUT a slide reference → clarify** | `:440`, `:962` |
| RC11 | conflict between UI selection and a text reference | `:727`, `:1067` |
| RC12 | generation intent with an existing deck → ask add-or-replace | `:408`, `:924` |
| RC13 | auto-create `slide_context` from a text reference | `:471`, `:992` |
| RC14 | frontend/backend deck-state mismatch | `:1032` |
| RC15 | canvas-ID rewriting | `:2552`, `:2577` |
| RC1 | **validate response is real slide HTML, retry once** | `agent.py:960` |
| RC4 | **unique canvas IDs to prevent collisions** | `agent.py:1005` |
| RC8 | **synthesise `slide_context` from a parsed reference** | `chat_service.py:1268` |
| RC9 | **add *with* a slide reference** | `chat_service.py:1325` |

**All fifteen RC rules are now mapped.** Record these meanings in `.ws4e-PLAN-CORRECTIONS.md` (they were already
found in `2026-08-09-pr3-langgraph-core.md:2739-2748` and verified). Note the table anchors most entries
in `chat_service.py` but **14 further RC markers in `src/services/agent.py`** and **1 in `src/api/mcp_server.py`**;
the four entries above straddle both files.

**Read each rule's meaning off the code, never infer it from the name.** That instruction is the whole
task.

**Behavioural tests: not one per rule.** Ruling R1 says "removed → delete it"; but RC7 is logging only
(no LLM behaviour to test), RC1/RC4/RC5/RC15 are builder script-integrity, not architect language handling,
RC6 is subsumed by row-per-slide persistence, and **RC11's precondition is retired** (`SelectionContext` is
gone and the only surviving `slide_context` producer carries no textual reference). Test the architect's
language handling: write behavioural tests for RC2, RC3, RC8, RC9, RC10, RC12, RC13, RC14, and (if needed)
RC6 — nine tests, not fifteen.

**Which of the nine run in CI is settled by one question: does the assertion need a model?** A rule whose
behaviour is a deterministic code path — a guard, a cache, a state-mismatch check — runs in CI: **RC3, RC6,
RC14**. Every rule asserted through the **architect's language handling** is layer 3 by E3's rule, so it
lives under `tests/agentic/`, carries both guards, and ships **skipped** until the real prompts land:
**RC2, RC8, RC9, RC10, RC12, RC13**. RC10 is the one that proves the rule — it is already E3's own first
layer-3 row (*"the architect asks rather than picking when a reference is ambiguous"*), so calling it
deterministic-in-CI put one test in two layers and left the executor no way to make it green except
weakening the assertion until a placeholder prompt satisfied it, which is exactly what E3 refuses. When
deriving each rule from the code, apply the same question to it and record the layer you assigned in
`.ws4e-PLAN-CORRECTIONS.md`.

---

## E6 — The release gate

**Neither PRD §3's no-regression gate nor the checkpointer's token path can be proven locally.** This
section is the deployment check, and it is the only place some of these can be observed at all.

Deploy per `.claude/skills/deploy-tellr-dev/` to a **devloop deployment** (copy-on-write branch per instance):

```bash
gh workflow run publish-dev.yml     # auto-increments the next .devN; note the version
./scripts/deploy_local.sh update --env devloop --profile tellr-dev --from-pypi <version>
```

**Note:** devloop forks an isolated copy-on-write branch per instance, which is necessary for reproducible
verification (no cross-contamination with other deployments). devtest reuses a shared schema and is not
suitable for this gate.

Then verify **in this order**, because an early failure invalidates the later checks:

1. **The app reaches RUNNING, and §E2's ConfigPrompts column DROP completed.** `create_all` runs before
   `_run_migrations`, so RUNNING alone proves only ORM convergence. Verify the material migration against the
   **two columns ws4b actually drops** — `system_prompt` and `slide_editing_instructions`
   (`src/database/models/prompts.py:39-40`):
   `SELECT COUNT(*) FROM information_schema.columns WHERE table_name='config_prompts'
   AND column_name IN ('system_prompt','slide_editing_instructions')` must return **0**. A non-zero count
   means the migration was skipped or rolled back and the check fails. Query no other column name: one ws4b
   never touches returns 0 unconditionally, so the gate would pass whether or not the migration ran.
2. **A monolith-mode turn is unchanged.** Send a message with no phrase; the deck builds as today. This
   is §D's comparison baseline — if it moved, the comparison is worthless and so is the dogfooding
   argument.
3. **A graph-mode turn builds a styled deck.** Send `USE AGENT MODE …`, then confirm: slides appear in
   **ascending** order; the session list does **not** show `0 slides` (`slide_count` is a column, not
   derived); the preview is **styled** (the §H defect); the spec view has data.
4. **Export to PPTX *and* Google Slides, and confirm charts render.** The `external_scripts_json` failure
   is **silent** — no exception, no empty-`<style>` symptom, just blank charts — so only looking at an
   export catches it. **Google Slides export could not be tested hermetically** (`HtmlToGoogleSlidesConverter`
   needs live Databricks *and* Google credentials), so this manual check is the only **end-to-end** coverage
   it has. (Unit tests exist for converter helpers in `test_google_slides_converter.py`.)
5. **A pinned-template deck is not washed out** in preview or either export path. This is the defect
   `ensure_deck_token_css` exists to catch — a deck referencing 57 `var(--…)` tokens while defining none.
6. **The checkpointer survives the OAuth refresh.** Leave a graph session open and exercise it again
   **past ~60 minutes, with several requests** (to land on different workers with independent jitter).
   Lakebase's token expires after an hour on a 50-minute refresh timer with ±5-minute jitter; several
   requests ensure at least one lands on a worker past refresh. **No local test can observe an expired token**
   — this is the only check that can, and it is the entire reason the saver goes through the engine rather
   than holding its own connection.
7. **A placeholder is honest.** This check requires injecting a builder failure into a live deployment
   — no fault-injection flag exists in any plan. Skip this check for now: it needs a mechanism (an env var
   or failing-prompt recipe) that this plan does not provide. Return when one lands.

**Final baseline comparison, by cause:**

Compare against the **committed** baseline artifact,
`docs/superpowers/baselines/pr3_ws4_collected.log`, created and committed by ws4a's Definition of Done.
**Do not re-capture a baseline with `git stash`.** ws4a–ws4d are already committed on this branch, so a
stash captures only this PR's uncommitted work: the "baseline" run is the after-state, the cause diff is
empty by construction, and the gate passes whatever ws4b–ws4d broke.

```bash
~/.pyenv/versions/3.11.0/bin/python -m pytest tests/ -n auto -q > pr3_after_ws4e.log 2>&1
diff <(grep -E '^(FAILED|ERROR)' docs/superpowers/baselines/pr3_ws4_collected.log | sort) \
     <(grep -E '^(FAILED|ERROR)' pr3_after_ws4e.log | sort)
grep -c 'UndefinedColumn' pr3_after_ws4e.log      # must be 0 — the cause a column drop mutates
~/.pyenv/versions/3.11.0/bin/python -m pytest tests/agentic -q   # all SKIPPED, none failed
```

**And account for the suite's size**, since ruling R1 means tests were deleted across ws4b:

```bash
git diff --stat main...HEAD -- tests/ | tail -1
git diff main...HEAD -- tests/ | grep -cE '^-\s*(def test_|    def test_)'   # top-level and class-method defs
```

**The gate:** no new cause, no change to the deploy-autoscaling cause, and **every deleted test
accounted for** — a shrinking suite explained rather than tolerated.

---

## Definition of done

- [ ] Both UI surfaces work against real data, with component tests and e2e specs, and **every new spec
      added to the CI matrix in the same commit** (ws4a's guard test enforces this). Spec view assertion for
      §7.2 (ws4d's feature, ws4e's test): after `clear_context`, the spec view still renders data while the
      transcript is **cleared down to the single earliest `role='user'` message**. Do not assert an empty
      transcript — ws4d D1 preserves that one row deliberately (it is the sticky engine-mode marker) and
      `_hydrate_chat_history`'s `HUMAN_TYPES` allowlist replays it, so "empty" is red by construction on
      every graph-mode session.
- [ ] `tests/agentic/` exists as a **sibling** of `tests/unit/`; every file carries both the marker and a
      self-skip guard; the whole suite reports **SKIPPED**, none failed; the disabled CI job is present
      and turning it on is a workflow-only change.
- [ ] **No layer-3 assertion was weakened to accommodate a placeholder prompt.** If one was tempting,
      the test is skipped instead and the reason recorded.
- [ ] Layer 4 passes, and the cross-process release test has been **sabotage-verified** with an
      in-process cache.
- [ ] All fifteen RC rules have their meanings **derived from the code** and recorded in `.ws4e-PLAN-CORRECTIONS.md`.
      Behavioural tests for the architect's language handling only (RC2, RC3, RC8, RC9, RC10, RC12, RC13,
      RC14, RC6 if needed — nine tests). **Model-free tests in CI (RC3, RC6, RC14 — three tests); the six
      that go through the architect's language handling (RC2, RC8, RC9, RC10, RC12, RC13) are layer 3 and
      ship SKIPPED.** No RC test appears in both layers.
      RC7 is logging only; RC1/RC4/RC5/RC15 are builder/infrastructure; RC11's precondition is retired.
- [ ] All seven release-gate checks pass on a devloop deployment, including the **past-50-minute** token
      check and a **manual Google Slides export**.
- [ ] Full suite compared **by cause**: no new cause, no change to the deploy-autoscaling cause, and the
      collected count reconciled against the deletions ruling R1 authorised.
