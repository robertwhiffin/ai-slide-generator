# ws4 — SEAM review (cross-document), 2026-09-10

One reviewer, all six documents, read-only. Axis: **the joins between plans** — defects invisible to
a reviewer holding one document. Per-document reviews had already run and been applied.

**18 findings + 4 minors. 10 of 18 are `[new]`** (not previously recorded by any single-document
reviewer), which is the number that says the seam axis was worth a pass.

Legend: `[new]` = no prior reviewer recorded it. `[already recorded]` = present in
`ws4_r1_*_findings.md`, unapplied or half-applied.

---

## RESOLVED — all five decided 2026-09-10, with probes. Nothing here blocks implementation.

Each was a contract hole needing a human decision. The original statements are preserved in git
(`9c73d58f`); what follows is the decision and the evidence behind it.

### S1 — `invoke_graph(session_id, initial, *, emitter=None, principal=None)` — commit `a63124e9`

**Probed on langgraph 1.2.10:** a ContextVar set before `graph.invoke()` was read by **all six**
`Send`-fanned nodes through a `threading.Thread(target=ctx.run)`, and a node-local `.set()` leaked
neither back nor sideways. Cause: LangChain fans out via `ContextThreadPoolExecutor`, whose `submit`
wraps every task in `copy_context().run(...)` (`langchain_core/runnables/config.py:607-628`).

So the ContextVar mechanism works and the principal needs no payload field. ws4c's stated reason for
carrying `initiated_by` — *"`get_current_user()` returns `None` inside the graph"* — was **measurably
false**: it returns `None` only when the caller failed to copy its context.

**Decided:** ws4c owns the emitter's lifecycle via an explicit parameter, so the dependency is visible in
a signature and testable. `emitter=None` means nodes **skip** emission rather than raise — emission is an
optional side channel, which the sweeper path and every state-asserting layer-1 test need. ws4d must
`contextvars.copy_context()` before spawning, exactly as the monolith already does
(`chat_service.py:1133` *"Capture context BEFORE starting thread to preserve user auth"*, `:1187`). D5's
sweeper passes `principal=marker.spec_dirty_by` and no emitter.

### S2 — `resolve_slide_style` delegates; it does not reimplement — commit `830b4590`

The producer already existed: `_get_prompt_content(config)` returns a `"slide_style"` key, and style is
resolved **before** its mode split, so `generate` and `edit` yield the same bytes.

**Decided:** `agent_resolution.resolve_slide_style(config)` is one line delegating to it. C8 documents why
a second copy is unsafe — resolution is a **branch, not a ladder** (an inactive `design_system_id` does
not fall through), `_design_system_is_active` fails **closed** on a tombstone, and a stale
`compiled_style_content` is lazily recompiled. That branch has already shipped a measured defect once. The
plan therefore adds a test asserting the graph and the monolith resolve **identical bytes** from the same
config — the only guard against someone later "optimising away" the delegation. The `AgentConfig` comes
from the session via `resolve_agent_config` (`agent_config.py:238`), **not** through `GraphState`.
Accepted cost: one discarded system-prompt assembly per turn.

### S3 — two readers, two purposes, no new machinery — commit `a24aa2b2`

**Probed:** `message_type="info"` is already the shipped vehicle for machine-generated advisories the user
must see (`chat_service.py:758` RC11 conflict note, `:793` safety notice); the frontend **never inspects
`message_type`** (`ChatPanel.tsx:101` maps `msg.role`), so any persisted `role="assistant"` message
renders; and `_hydrate_chat_history` skips `info` by an explicit rule.

**Decided:** `deck_reviewer_node` persists the verdict as `role="assistant", message_type="info"` — no new
`StreamEventType`, no route, no UI work. `architect_node` reads the structured row via `get_deck_review`
at turn start, which is that function's **only** production caller and the reason the table is
content-addressed and survives a restore; without it turn *n+1* re-proposes an arc the reviewer already
rejected, indefinitely. D3's rejection of persisting *slide-ready* stands: that is 15–40 mechanical events
per turn, this is one content message.

### S4 — ws4c adds its own CI job; ws4a adds the guard that makes the gap loud — commit `6678c997`

**Measured:** `tests/integration/` holds **17** `test_*.py` files, the workflow names **7**, and **10 run
in no job** — including PR1's `test_slide_row_identity_and_verdicts.py` (the foundation every plan here
builds on), PR1's dual-write and row-read suites, PRD §3's `test_export_parity.py`, and
`test_mcp_endpoint.py`, which **ws4d's own DoD names as a gate**.

**Decided:** ws4c adds an `integration-graph` job with the suite (cloning `integration-slides`
`:306-345` for the Postgres service that "turn 2 against a real checkpointer" needs anyway) — parking it
in ws4e's layer-4 job would leave ws4c's headline DoD unverifiable in CI for three PRs. ws4a gains
**Task A5**, the exact analogue of its e2e matrix guard, landing **first** so ws4c's and ws4e's new files
cannot silently join the graveyard. The index now records that **four** of the five PRs edit `test.yml`.

### S5 — the §7.4 flag is derived from the turn, not read from the sweeper — commit `ee2bc8e9`

E2b was bound to the wrong thing. §7.4 gives the flag to *"the whole-deck pass"* — the deck review inside
a turn — but E2b bound it to ws4d D4's `spec_sync.mark_dirty`, the **sweeper's** between-turns marker, then
asserted transitions no client can observe: that needs a server read ws4b deliberately refuses **and** an
idle poll loop that does not exist (`startPolling` takes a message and runs only during a turn).

**Decided:** derive it —
`reviewInProgress = releasedPositions.size === deckSpec.slides.length && !turnComplete`. Exact, not a
heuristic: ws4c's topology after the last commit is `all_positions_committed → deck_reviewer → END`, so
once every position is released the only remaining work *is* the deck review. No endpoint, no response
key, no server change, and ws4b's assertion stands untouched. Sweeper-driven reviews are not visible in
this PR and §7.4 never asked them to be. Two unsatisfiable assertions dropped; two added that can fail —
the flag must be **off** mid-build, and "non-blocking" is now falsifiable as *no control's `disabled` prop
reads it*.

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
