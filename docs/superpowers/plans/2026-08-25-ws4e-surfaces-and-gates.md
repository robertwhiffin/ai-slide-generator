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

**Spec:** §7.1, §7.2, §7.5, §F1–§F4, §G1–§G3, §9, §M7, PRD §3, PRD §12.1.

---

## E1 — The spec view toggle

**Contract:** a `SpecView` component reading `slideDeck.deck_spec` — ws4b's new read-path key, so **no
new endpoint** — and a toggle in `AppLayout.tsx` beside the existing view controls.

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
read-only viewer links included — and the spec rides `get_slide_deck`'s dict, which already enforces
deck permission. Nothing to add; assert it rather than implement it.

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

**Test intent:**

| Assertion | Why |
|---|---|
| findings render from the slide's verification records, not from a test global | The wiring itself |
| findings are scoped to the current slide by `slideIndex` | |
| a finding **travels with its slide across a reorder** | §F3's non-obvious property, and the 0a defect |
| a deck-level finding (`slideIndex: -1`) **never** appears in the drawer | PRD §3's grain routing |
| Apply / Dismiss / Discuss call real handlers, not `console.info` | |
| Dismiss persists to seen-state keyed `(deckKey, finding.id)` | `seenState.ts`'s store shape |
| **a re-review of an UNCHANGED slide does not re-highlight a dismissed finding** | §K9, half one |
| **a finding re-raised after an EDIT reads as unseen** | §K9, half two |

**Those last two are the pair that justify ws4b's id rule**, and they are the reason it had to be settled
before any code bound to it. A `(criterion, slide_content_hash)` composite is what makes both true at
once; either alone is satisfiable by a simpler scheme that breaks the other.

**Note ws4b already delivered the `status` branch** (fixed findings render read-only) and the `hasUnseen`
rule (a fixed finding does not count as unseen). This task wires real data into that behaviour; it does
not re-implement it.

---

## E3 — `tests/agentic/`: layer 3, honest and skipped

**§G's four layers, organised by what each needs in order to run** — not by marker. The spec conflated
"excluded from CI" with "rarely run"; the real constraint is environmental.

| Layer | Needs | In CI | Owned by |
|---|---|---|---|
| 1. Orchestration | nothing — stub agents, real compiled graph | ✅ | ws4c |
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

**Built CI-ready now, enabled later — and "enabled" means two mechanisms, not one.**

- **The workflow gate** is a **new job** running `pytest tests/agentic -m live` with real credentials,
  added **disabled** (`if: false`). When the repo moves to a company org, turning this on must be a
  workflow change and **nothing else** — no test rewrites.
- **Every layer-3 test also carries a self-skip guard**, so a test somehow collected without a reachable
  endpoint skips rather than fails. **Marker for selection, guard for safety** — ship both, because the
  marker alone is not load-bearing in this repo.

**The trap to refuse, stated as a rule.** Layer-3 tests are written against **real prompts** and ws4c
ships **placeholders**, so they will not pass. **Mark them skipped and enable them with the real
prompts.** The failure mode to refuse is **weakening a layer-3 assertion until a placeholder satisfies
it** — that manufactures exactly the "test that cannot fail" class this project has already paid for
twice. **A skipped honest test beats a passing dishonest one.**

**§G2: assert structure AND behavioural outcomes, never wording.** §9's "structure, never wording" is
necessary but insufficient — it can confirm a reviewer returns valid JSON, not that it reviews well. So:

| Behaviour | Assertion shape |
|---|---|
| the architect **asks** rather than picking when a reference is ambiguous | intent is `discuss`, and the message contains a question |
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

**Sabotage the cross-process one.** Add an in-process cache in front of the release query and confirm the
second-process test goes red. If it stays green the test is not actually crossing a process boundary —
fix the test, because that is the exact defect it exists to catch.

---

## E5 — The retired-regex regression checklist

**PRD §12.1 is explicit** that the retired regex rules "each encode a previously-shipped bug fix" and are
"a test checklist for the supervisor's intent handling, not merely dead code to delete."

**There are RC1–RC15, not six** — verified by grepping the in-code markers. And **all six RC10–RC15
mappings in the superseded plan were wrong**: it had ordinals, ranges and relative references.
**Wrong-but-plausible mappings are the worst class of defect here, because a test written against the
wrong semantics ships the regression green.**

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

**RC1, RC4, RC8 and RC9 are not mapped above and must be derived.** Do not skip them and do not write
"pending" into the plan — Step 1 is not complete until all fifteen have a stated meaning recorded in
`.PLAN-CORRECTIONS.md`. Note also that the table anchors everything in `chat_service.py` while there are
**14 further RC markers in `src/services/agent.py`** and **1 in `src/api/mcp_server.py`**; read those
before concluding a rule's meaning.

**Read each rule's meaning off the code, never infer it from the name.** That instruction is the whole
task.

**One behavioural test per rule, against the COMPILED graph** — the point is that the architect's
language handling preserves each shipped fix, and only the compiled graph exercises that. Fifteen tests.
Mark the ones needing a real model as layer 3 (E3); keep the deterministic ones — RC3, RC5, RC6, RC7,
RC14, RC15 — in CI.

---

## E6 — The release gate

**Neither PRD §3's no-regression gate nor the checkpointer's token path can be proven locally.** This
section is the deployment check, and it is the only place some of these can be observed at all.

Deploy per `.claude/skills/deploy-tellr-dev/`:

```bash
gh workflow run publish-dev.yml     # auto-increments the next .devN; note the version
./scripts/deploy_local.sh update --env devtest --profile tellr-dev --from-pypi <version>
```

Then verify **in this order**, because an early failure invalidates the later checks:

1. **The app reaches RUNNING.** Every step in `run.py::init_database` is `SystemExit(1)` on failure, so
   RUNNING is proof all four migrations applied against real Lakebase.
2. **A monolith-mode turn is unchanged.** Send a message with no phrase; the deck builds as today. This
   is §D's comparison baseline — if it moved, the comparison is worthless and so is the dogfooding
   argument.
3. **A graph-mode turn builds a styled deck.** Send `USE AGENT MODE …`, then confirm: slides appear in
   **ascending** order; the session list does **not** show `0 slides` (`slide_count` is a column, not
   derived); the preview is **styled** (the §H defect); the spec view has data.
4. **Export to PPTX *and* Google Slides, and confirm charts render.** The `external_scripts_json` failure
   is **silent** — no exception, no empty-`<style>` symptom, just blank charts — so only looking at an
   export catches it. **Google Slides export could not be tested hermetically** (`HtmlToGoogleSlidesConverter`
   needs live Databricks *and* Google credentials), so this manual check is the only coverage it has.
5. **A pinned-template deck is not washed out** in preview or either export path. This is the defect
   `ensure_deck_token_css` exists to catch — a deck referencing 57 `var(--…)` tokens while defining none.
6. **The checkpointer survives the OAuth refresh.** Leave a graph session open and exercise it again
   **past 50 minutes**. Lakebase's token expires after an hour on a 50-minute refresh timer, and **no
   local test can observe an expired token** — this is the only check that can, and it is the entire
   reason the saver goes through the engine rather than holding its own connection.
7. **A placeholder is honest.** Force a builder failure; confirm the deck completes, the failed position
   shows as a placeholder, and the rest released past it.

**Final baseline comparison, by cause:**

```bash
~/.pyenv/versions/3.11.0/bin/python -m pytest tests/ -n auto -q > /tmp/after_ws4e.log 2>&1
diff <(grep -E '^(FAILED|ERROR)' /tmp/pr3_baseline.log | sort) \
     <(grep -E '^(FAILED|ERROR)' /tmp/after_ws4e.log | sort)
grep -c 'UndefinedColumn' /tmp/after_ws4e.log      # must be 0 — the cause a column drop mutates
~/.pyenv/versions/3.11.0/bin/python -m pytest tests/agentic -q   # all SKIPPED, none failed
```

**And account for the suite's size**, since ruling R1 means tests were deleted across ws4b:

```bash
git diff --stat main...HEAD -- tests/ | tail -1
git diff main...HEAD -- tests/ | grep -c '^-def test_'   # every deletion must be named in a commit
```

**The gate:** no new cause, no change to the deploy-autoscaling cause, and **every deleted test
accounted for** — a shrinking suite explained rather than tolerated.

---

## Definition of done

- [ ] Both UI surfaces work against real data, with component tests and e2e specs, and **every new spec
      added to the CI matrix in the same commit** (ws4a's guard test enforces this).
- [ ] `tests/agentic/` exists as a **sibling** of `tests/unit/`; every file carries both the marker and a
      self-skip guard; the whole suite reports **SKIPPED**, none failed; the disabled CI job is present
      and turning it on is a workflow-only change.
- [ ] **No layer-3 assertion was weakened to accommodate a placeholder prompt.** If one was tempting,
      the test is skipped instead and the reason recorded.
- [ ] Layer 4 passes, and the cross-process release test has been **sabotage-verified** with an
      in-process cache.
- [ ] All fifteen RC rules have a meaning **derived from the code** and recorded in
      `.PLAN-CORRECTIONS.md`, with fifteen behavioural tests — the deterministic six in CI.
- [ ] All seven release-gate checks pass on a devloop deployment, including the **past-50-minute** token
      check and a **manual Google Slides export**.
- [ ] Full suite compared **by cause**: no new cause, no change to the deploy-autoscaling cause, and the
      collected count reconciled against the deletions ruling R1 authorised.
