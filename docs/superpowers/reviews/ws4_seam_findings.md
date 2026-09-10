# ws4 — SEAM review (cross-document), 2026-09-10

One reviewer, all six documents, read-only. Axis: **the joins between plans** — defects invisible to
a reviewer holding one document. Per-document reviews had already run and been applied.

**18 findings + 4 minors. 10 of 18 are `[new]`** (not previously recorded by any single-document
reviewer), which is the number that says the seam axis was worth a pass.

Legend: `[new]` = no prior reviewer recorded it. `[already recorded]` = present in
`ws4_r1_*_findings.md`, unapplied or half-applied.

---

## OPEN — judgment calls for the human. Do NOT implement past these.

### S1. `invoke_graph`'s contract admits neither the event queue nor the principal, and ws4d puts it on a thread the principal cannot cross (ws4c C4 <-> ws4d D2/D3) `[new]` (queue half `[already recorded]`)

ws4c: `invoke_graph(session_id, initial)` — two parameters — and "Set in `invoke_graph` before
`graph.invoke()` runs". ws4d D3 defines `emit_slide_ready(queue, ...)` and D2 requires "invoke the
graph in a worker thread". The queue is created in ws4d's generator; `invoke_graph` has no slot for it.

Deeper: ws4c declares `initiated_by` "resolved once in `invoke_graph`" and makes `modified_by=initiated_by`
load-bearing. Identity is a ContextVar (`src/core/user_context.py:11`). **A bare `threading.Thread` does
not carry the parent's context**, so `get_current_user()` on the worker thread returns `None`.
`grep -rn initiated_by` over the five plans returns three hits, all ws4c — ws4d, the only caller, never
populates it.

Breaks: either events queue nowhere (no slide ever streams), or `invoke_graph` grows an undeclared
parameter mid-build. Independently every graph row insert lands `modified_by` NULL
(`slide_repository.py:91`, `:104-107`) and ws4c's own author test fails.

Decision needed: widen `invoke_graph`'s signature to take the emitter and the principal explicitly,
and state that ws4d resolves both **before** spawning the thread (`contextvars.copy_context()` is the
mechanism). Owner: ws4c.

### S2. `resolved_style` has a consumer, a payload slot and a test — and no producer in any plan (ws4c C1/C3/C4 <-> ws4d D2) `[new]`

`grep -rn resolved_style` over all six documents: three hits, all ws4c. C6's `resolve_template_bytes`
returns `(layout_html, <style> block, token_css)` — no style prose. C3 makes the **entire**
`_SLIDE_FRAME_CONSTRAINTS` decision turn on the resolved style's three cases and tests all three.
The real resolver is `agent_factory._get_prompt_content` — 237 lines, and C8 leaves it where it is.
ws4d D2 attributes resolution to `agent_resolution`, a module declared to hold only
`assemble_skill_prompt` and `get_structured_model`.

Breaks: `resolved_style` is `None`, so C3 injects frame constraints unconditionally or never, its
three-case test cannot be written, and §L5's "builder and reviewer get the same numbers or the
criterion is unfair" is unmet silently.

Decision needed: name the function that resolves style for the graph path, and whether it reads into
the moved `agent_factory` under R2's read-don't-modify licence. Owner: ws4c.

### S3. Deck-level findings have a writer and no reader (ws4b B2.2 <-> ws4c C4 <-> ws4e E2) `[new]`

ws4b defines `get_deck_review(session_id, deck_id)`; `grep -rn get_deck_review` over all six documents
returns two hits, both inside ws4b's own contract. ws4c writes via `save_deck_review` and emits once as
a "deck-level activity message". ws4e E2: "Deck-level findings do NOT come from here... The drawer must
never render one." No plan declares a `StreamEventType` for that message, and ws4d's own rule is that
"a new type that is not on the enum cannot be constructed."

Breaks: `deck_reviews`, its unique key, digest, restore-immunity and four tests are built for a table
nothing reads. A user who reloads sees nothing — the chat message is ephemeral by D3's own rejection of
persisting build mechanics, the drawer must not render it, no surface calls the getter. §F4's payoff
(edit-then-revert recall of the arc verdict) is unreachable.

Decision needed: name a reader (route + surface) and the event type, or state that `get_deck_review`
exists only for the next turn's architect and drop the unread-surface claim. Owner: ws4c or ws4e.

### S4. ws4c's layer-1 suite runs in no CI job, while ws4e's layer table marks it "In CI" `[new]`

`.github/workflows/test.yml`'s only directory-wide collection is `pytest tests/unit` (`:102`); every
integration job names **files**. ws4c C5 lands its harness and suite in `tests/integration/`. The only
new integration job in the set is ws4e E4's `pytest tests/integration -k layer4`, whose `-k` excludes
layer 1 by construction.

Breaks: ws4c's DoD ("the layer-1 suite runs against the compiled graph, all eleven behaviours") is
satisfiable locally and never runs in CI. These are the tests the five-PR split exists to protect —
spec §8's whole point is that scheduler unit tests pass while shipped behaviour degrades.

Decision needed: ws4c adds a job for its own suite, or ws4e E4 widens its job. Either way ws4e's table
must stop claiming a green tick. Round 1 caught this class for layer 4; the fix covered only layer 4.

### S5. E2b's "review in progress" flag has no data path, and ws4b asserts a test forbidding the obvious one (ws4b B2.3 <-> ws4e E2b) `[new]`

ws4b B2.3: "Not deck presentation state, so deliberately absent from `get_slide_deck`'s dict. **Assert
that.**" ws4e E2b asserts the flag appears when a marker exists, disappears when it clears, and stays
on when a failed review keeps the marker. `grep -rn spec_dirty` across the plans: ws4b B2.3 and ws4d D5
only — no route, no response key, no read function.

Breaks: two of E2b's four assertions need the client to observe server-side transitions it cannot see.
An implementer invents a read path (which ws4b's own test then fails) or fakes it from local state (at
which point three of four tests are untestable).

Decision needed: ws4b adds a non-presentation read and relaxes the assertion to the deck dict
specifically, or ws4e scopes E2b to what a client can observe.

---

## APPLIED — verified defects with a forced fix (see the follow-up commit)

- **S6** ws4e E6's migration check queries `config_prompts.disabled_at` — a column that does not exist
  repo-wide and that ws4b never drops. ws4b drops `system_prompt` and `slide_editing_instructions`
  (`src/database/models/prompts.py:39-40`). The one gate proving ws4b's only behaviour-changing
  migration landed returned 0 unconditionally. `[new]`
- **S7** ws4e E6 captured its "baseline" with `git stash` on a branch where ws4a-d are already
  committed, so baseline == after and the diff was empty by construction. The index designates
  `docs/superpowers/baselines/pr3_ws4_collected.log`, owned by ws4a's DoD. `[already recorded]`
- **S8** ws4d D4 calls `_get_deck_owner_session(session_id)`; the real signature is
  `(self, db: Session, session: UserSession)` (`session_manager.py:709`). ws4b and ws4c both carry the
  warning; ws4d writes the broken call — the shape agents copy literally. `[already recorded]`
- **S9** ws4b B3.2's premise "the frontend's `Slide` type lists **both** keys" is false:
  `frontend/src/types/slide.ts:3-14` has `verification?` and `content_hash?`, no `findings`. Stated as a
  choice between two existing keys when only one exists, so an implementer leaves findings server-only
  and ws4e E2 has no typed field. `npm run typecheck` fails at the last PR. `[new]`
- **S10** `f3` is double-bound: ws4b keeps ~10 e2e assertions on it AND forbids deck-level assertions
  from it; ws4e E2 builds exactly that assertion. Making ws4e pass breaks
  `frontend/tests/e2e/slide-viewer.spec.ts:314-359` — in a spec ws4a just made collectable. `[new]` for
  the e2e-breakage consequence.
- **S11** The vitest job is co-owned by ws4b and disclaimed by ws4e, with an "earliest merge wins" rule
  for a race that cannot happen (ws4b always precedes ws4e). If ws4b's job slips, both plans point at
  the other and ws4e's component tests run nowhere. `[already recorded]`
- **S12** `make_finding_id` is three-part in ws4b (`criterion, subject_hash, ordinal=0`) and two-part in
  both consumers. `ordinal` defaults, so both compile and two `overflow` findings on one slide mint the
  **same id** — ids collide in `build_verification_record`, and dismissing one marks the other seen.
  ws4b's own uniqueness test passes because it calls the helper directly. `[new]`
- **S13** ws4b's `stub_writer` and the release-order fixtures are declared in `tests/unit/conftest.py`,
  which their only consumers (ws4c/ws4d integration tests) provably cannot see — so ws4b builds a
  fixture no test uses and ws4c silently rebuilds it. `tests/integration/conftest.py` is edited by three
  plans and absent from the index's contention list. `[new]` for the duplicate-ownership half.
- **S14** Index carry-forward #15 assigns ws4d "re-audit the full inventory before repointing";
  `grep -c repoint ws4d` = 0. ws4c C7 answered the repointing half (nothing moves). `[new]`
- **S15** The index's "re-derive these anchors" list omits eight anchors that ws4a's insertions shift —
  ws4b `:1549`/`:1585`/`:1637-1650`/`:1939-1951`/`:2240`, ws4c `:1549` (ws4c is not even listed as a
  citer), ws4d `:1761`. The index's own words: "A broken anchor is a silent misfile." `[new]`
- **S16** ws4e's DoD asserts an empty transcript after `clear_context`; ws4d D1 deliberately preserves
  the earliest user row. A concrete e2e failure at the last PR. `[new]`
- **S17** ws4e E5 marks six RC tests "deterministic in CI" while ws4c ships placeholder prompts, and
  E3's own rule forbids "weakening a layer-3 assertion until a placeholder satisfies it". `[new]` for
  the placeholder conflict.
- **S18** ws4d D2 builds the initial state with `design_contract`, which `GraphState` does not declare
  (silently dropped), and re-resolves template bytes ws4c assigns single-writer to `architect_node`.
  On turn 1 there is no committed spec to resolve from. Resolution: architect is sole resolver. `[new]`
- **Minors:** ws4d's `spec_dirty_claimed_at` anchor cites ws4b `:497-498` (that is B2.1's `Send(timeout=)`
  trap; the migration is ws4b `:574`). ws4d calls `delete_thread` "a base-class no-op"; probed on
  langgraph-checkpoint 4.1.1 it **raises `NotImplementedError`** — and ws4b's claim that
  `get_next_version` "contains a raise" is false, the base class has a working increment.
  `.PLAN-CORRECTIONS.md` has no naming convention: only ws4a namespaces it, so stacked branches collide.
  §K6 (tone-vs-BRAND-MANUAL precedence, §E1) is claimed by no plan and is not on the exclusions list.

---

## Seams verified clean — do not spend another pass here

- The `emitted_style_blocks` / B3.3 re-scope round-trip. **This is the model the other escalations
  should follow**: ws4c answers ws4b's explicit request, and ws4b carries the answer.
- The eight deck-level columns: ws4b's five-pre / three-post table matches ws4c's two bullets exactly,
  including `scripts_content` derived from `SlideDeck(...).scripts`, and ws4d's "two version bumps per
  turn" against B3.1's "bumps exactly once per call".
- ws4a -> ws4b's `merge_css` chain: the empty-replacement early return, the pairwise-fold constraint it
  forces on B3.3, and both dedupe limits are in ws4a's DoD and inherited by B3.3's test intent.
  `slide-viewer.spec.ts` is already in `tests/e2e/`, so ws4a adds it to the matrix and ws4b edits its
  body — no contention.
- `spec_dirty_claimed_at` agrees across ws4b B2.3 and ws4d D5 (only the anchor is stale).
- `tests/integration/conftest.py` as ws4b's deliverable — consistently attributed by ws4c and ws4e.
- `SlideWriter`'s API: `commit_placeholder` (`slide_repository.py:275`), `deck_spec_slide` (`:91`,
  `:104`), `is_placeholder_record` (`:41`); `SlideDeck.from_dict` (`slide_deck.py:111`), `scripts`
  (`:80`), `knit` (`:323`), `insert_slide` (`:251`).
- All 16 test files named across the five DoDs resolve on disk; ws4d's MCP gate has real targets.
- The `Depends on:` / `Blocks:` headers form a DAG and agree with the index's sequencing. The only
  inversion is S1's ws4c-needs-ws4d emission pattern.
- Carry-forward items 10-14, 17-22, 24-29 each land as a named item in their owning plan. #15 is the
  sole exception (S14).
- Spec coverage: every §-reference in the five `Spec:` lines maps to a real heading; the overlaps
  (§A1/§A2 in b+c, §F1-§F4 in b+e, §L2a/§L8/§C in a+b, §B5 in a+d) are deliberate schema-vs-consumer
  splits with declared ordering. §K6 is the only unclaimed bullet.
- ws4a's measurements re-verified independently: 23 matrix entries, the `backend` paths filter at
  `:36-39`, `prompts.py:39-40`, `session_slide_decks.session_id` as an Integer FK.

## Could not verify — what would settle each

- Whether `slides_since_cursor`'s "reusing `releasable_positions`' prefix rule" means code reuse or a
  SQL re-implementation. ws4c's is a pure function over state; ws4d's is a row query. Settled by ws4d
  naming the SQL predicate and ws4e naming the function it calls.
- Whether ws4e E4's asserted **409** is reachable: `write_deck_level_columns` is a service, the graph
  never routes. Settled by ws4e naming the route under test.
- The `findings` read-path shape (per-position index vs flat list). ws4b B3.2 leaves it open; ws4e E2's
  "scoped by `slideIndex`" implies flat. Settled by ws4b deciding.
- **Whether ws4d's polling transport delivers slides at all.** D3 says both "the polling path does not
  deliver incremental slides — `poll_chat` has no `slide_cursor` parameter, no new response field" AND,
  four lines later, "the polling path reads committed `session_slides` rows directly via
  `slides_since_cursor`", while ws4d's DoD requires "both transports". No `poll_chat` signature or
  response-key change appears in any Files table. ws4d-internal, so unscored — but the one gate that
  reconciles with no task in the set.
