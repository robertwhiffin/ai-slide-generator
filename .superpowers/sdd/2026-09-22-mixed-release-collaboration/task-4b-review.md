# Task 4 slice 4B — independent review

**Reviewer:** independent; did not write this code. Range reviewed
`f5ec0bfd56a0dbf96f20878b273039be7300cf96..6d9d154de4c6830125d45c3e0d361a453d60f936`
(the docs-only `a36433040` on top was read for C-29/C-30/C-31, not reviewed as code).

## VERDICTS

**Spec compliance: PASS.** Every clause of plan Task 4 bullets 1 and 2, and the runtime half of
bullet 7, is implemented and guarded by a mutation-verified test. The two plan defects the
controller ruled on (C-30, C-31) are real and both rulings are correct; I verified C-31's
discrimination independently and it holds on a wider selection than the author measured.

**Task quality: PASS WITH ONE CRITICAL AND THREE IMPORTANT FINDINGS.** The engineering is strong:
the hard constraint was honoured without weakening #265's guard, the mutation discipline is the
best I have seen in this epic, and the report's disclosures are accurate rather than
self-serving. But the slice puts two raw session identifiers into a production application-log
line, which **violates a written, PRD-derived prohibition on that exact sink**, and the existing
guard for that prohibition misses it purely because of field naming. That is not a judgement call
and it is not closed by disclosure. Three further Important findings concern a claim the slice
asserts but does not establish (AC4 agreement), a third divergent root resolver, and a clause
guarded only statically.

Nothing here is softened because it was disclosed.

---

## 1. Environment, tree state and provenance

Triple check before any action, after every mutation, and at the end:
`git status --porcelain` empty, `git diff HEAD` empty, `git diff --cached` empty,
`HEAD = a3643304064ab0ea2a0327e146b736203a030fa8`, branch `plan/conversation-collaboration-262`.
All seven touched files verified byte-identical to their committed blobs at the end
(`git hash-object` == `git rev-parse HEAD:<path>` for each).

Provenance proved once: `python 3.11.0`, `sys.prefix=/Users/robert.whiffin/.pyenv/versions/3.11.0`,
`databricks-sdk 0.112.0`, no `.venv`, `databricks_tellr` and `src.services.*` both resolving inside
this worktree. No `pip install`, no `uv`, no `.venv`, no frontend command, no subagent, no commit.

Per C-27/C-32's sibling rule: `cp` backups taken from the committed tree and asserted to reproduce
it (`git hash-object` of each backup == the tree blob), restore verified after every mutation via
`git diff --name-only HEAD` being empty. Driver lives at `/tmp/4b_review/`, outside the repo.

---

## 2. THE HARD CONSTRAINT — both halves verified

### #265's guard is byte-unchanged

`test_every_production_runtime_call_passes_all_four_pinned_arguments` extracted from
`tests/unit/test_graph_nodes.py` at all three commits and hashed:

| commit | start line | sha256 (first 16) |
|---|---|---|
| base `f5ec0bfd5` | 195 | `f47cdceb5b296e95` |
| slice `6d9d154de` | 222 | `f47cdceb5b296e95` |
| HEAD `a36433040` | 222 | `f47cdceb5b296e95` |

Byte-identical; it only moved down 27 lines because content was inserted above it. Still
`assert len(calls) == 10` and `assert all(len(call.args) == 4 and call.keywords == [] for call in calls)`.

The test file's diff over the range is **purely additive** apart from one import line
(`from src.domain.skill_io import AnalystOutput, ArchitectOutput` widened to a four-name
parenthesised import). No pre-existing assertion was deleted or relaxed. #262's
`DeckMutationContext` / `MutationActor` imports survive at `tests/unit/test_graph_nodes.py:74-75`
and are still used by the three boundary tests at `:130`, `:161`, `:191`.

### M19 reproduced — the guard is live, not vacuous

Anchor count 1 (asserted before patching). A fifth positional argument added to the architect's
`run(...)` call at `src/services/graph/nodes.py:1479-1487`.

GREEN control, unmutated:

```
233 passed, 125 warnings in 4.93s
```

RED under M19:

```
        assert len(calls) == 10
>       assert all(len(call.args) == 4 and call.keywords == [] for call in calls)
E       assert False
E        +  where False = all(<generator object TestAgentRuntimeSeam.test_every_production_runtime_call_passes_all_four_pinned_arguments.<locals>.<genexpr> at 0x12b2e1a80>)

tests/unit/test_graph_nodes.py:236: AssertionError
...
FAILED tests/unit/test_graph_nodes.py::TestAgentRuntimeSeam::test_every_production_runtime_call_passes_all_four_pinned_arguments
33 failed, 200 passed, 125 warnings in 8.41s
```

The author reported 23 collateral REDs; I measured 33. The difference is which of the ten sites is
mutated (the architect site is read by many more tests than, say, a retry site) — not a
discrepancy in the guard. The guard itself REDs in both cases, on the exact line.

### The ordering claim — verified, and verified to be *semantic* rather than textual

`src/services/graph/builder.py:302-303`: `pin_loader(...)` first, `root_loader(...)` second.
`test_a_null_pinned_legacy_root_runs_no_node_and_resolves_no_owner` asserts both
`fake_graph.calls == []` and `root_calls == []`.

I did not take the author's M7a (which swaps the two statements and is trivially caught). I aimed
at the author's own *defence* — "`pin_loader` is still the first statement in `invoke_graph`" — by
keeping it textually first and breaking it semantically (mutation R3, §5). The test caught it with
its own named message. So the C-3 ordering guard is not satisfied by statement order alone; it is
a real ordering assertion. **C-3's precondition for slice 4B is met.**

### Hostile seeds — verified

`src/services/graph/builder.py:316-327`: `state = dict(initial or {})` then `state.update({... "root_session_id": root_session_id, "actor_session_id": session_id ...})`. Both keys are written
**after** `dict(initial)`, so a caller-seeded value is overwritten. Guarded by
`test_the_owner_is_resolved_once_and_hostile_ids_are_overwritten` (M6, and my R1).

---

## 3. SPEC COMPLIANCE, CLAUSE BY CLAUSE

### Bullet 1

| Clause | Where | Guarded by | Verdict |
|---|---|---|---|
| RED runtime test, contributor R2 graph on owner R1; sink root=owner, actor=contributor, release=R2 | `_collaboration` + `_assert_traced` (`test_graph_nodes.py:2560-2650`) | the 14 `TestRuntimeRootActorTrace` tests | **MET**. `_assert_traced` opens with an explicit anti-vacuity assertion that owner ≠ contributor, which is the right guard against the fixture collapsing the scenario. |
| handoff: `foreman_router` `Send("builder", build_branch_payload(state, position))` | `routers.py:123` (unchanged) carries the payload; `nodes.py:1331-1337` declares the keys | `test_the_fanned_branch_payload_declares_the_root_and_the_actor`, M8 | **MET**, transitively. No test asserts on `foreman_router`'s Send directly; covered because the payload is `build_branch_payload`'s output. Minor, noted below. |
| handoff: `build_branch_payload` | `nodes.py:1331-1337` | M8 (RED ×2) | **MET** |
| handoff: builder unsafe-output `retry_payload` | `nodes.py:2103-2113` | M10, and my R5 (RED ×2 behaviourally) | **MET** |
| handoff: build_reviewer `Send("build_reviewer", dict(record))` re-fan | `routers.py:189-205` | M9b/M9c/M9e, 2 tests | **MET** — see C-31 below |
| handoff: fixer `retry_payload` | `nodes.py:2473-2487` | M11, and my R4 (RED behaviourally) | **MET** |
| handoff: fix_reviewer record | `nodes.py:2614-2622` | M12 | **MET** |
| handoff: `rereview_committed_slides(session_id, spec, brand, graph_release_id, root_session_id, actor_session_id)` | `nodes.py:512-519` | M15, M16 | **MET**, and the parameter order matches the plan's literal signature. |
| exercise unsafe-output retry, surfaced finding to fixer/fix-reviewer, re-review | `test_the_whole_turn_records_one_immutable_root_actor_and_release` | REDs under 9 of 27 mutations, and under 3 of my 5 | **MET** |
| assert immutable root/actor/release/version in every recorded payload, identity-sink call, and downstream row/deck event | `_assert_traced` pins all four on every call; `test_the_persisted_mutation_event_agrees_with_the_runtime_trace` reads the real `SharedDeckMutationEvent` row | M17 | **MET on the letter, NOT on the substance for the event half** — Important finding 2. |

### Bullet 2

| Clause | Verdict |
|---|---|
| `invoke_graph` loads the actor pin via #261 | **MET**. `pin_loader=load_conversation_pin` (`builder.py:235`), called with `session_id` (the actor). Guarded by M7b and my R3. |
| resolve owner once | **MET**. `root_loader` called once (`builder.py:303`); my R1 REDs exactly one test on a duplicate call. |
| overwrite hostile initial root/actor IDs | **MET** (§2) |
| declare/copy them in all `Send` payloads and retry/fix/re-review records | **MET** for all seven named handoffs |
| IDs never select release; actor state pin does | **MET**. Runtime side: `AgentRuntime._run_resolved` copies them from the context onto the identity and never into resolution (`agent_runtime.py:605-612`); M3. Entry side: my R3 REDs on `pin_calls == ["contributor-session"]`. |
| extend identity sink only — no MLflow/Lakebase trace | **MET**. No MLflow or Lakebase symbol appears anywhere in the range's diff. |
| distinct sabotage removing root/actor/release from the reviewer `dict(record)` re-fan; only the re-review identity test goes RED | **MET as ruled by C-31**, not as literally worded. Verified independently, §6. |

### Bullet 7 — the runtime half

Plan bullet 7 is "Sabotage grouping by release without opaque actor identity …; Independently
replace `authorized_collaboration_root` …; Restore; run focused runtime/API Postgres/CI tests;
commit". The first two clauses are 4A's. The runtime half is the focused-runtime-test run, the
restore discipline and the commit.

- **Focused runtime tests run and green:** I measured the author's eight-module focus at **507
  passed, 0 failed** (the report says 506 — off by one, trivial). The 28 new tests: **28 passed**,
  matching the claimed class split (5 + 1 + 5 + 14 + 3).
- **Restore discipline:** `cp` backups, not `git checkout <commit> -- <paths>`; drift enumerated
  from `git diff --name-only HEAD`. I independently re-derived the same discipline and it held.
- **Commit message:** the plan mandates `commit feat: expose mixed-release collaboration history`,
  which 4A used (`d888ff4ed`). 4B used a slice-specific message. Correct for a C-9 split — one
  commit per slice — not a deviation.
- **No PostgreSQL integration test for the runtime trace** was added. Disclosed (§8) and I confirm
  none exists. The downstream-event half *is* asserted against a real database inside the unit
  suite, so the substance is covered; the gap is the real-compiled-graph path (Important finding 4).

**Verdict: the runtime half of bullet 7 is MET.**

---

## 4. THE LOG DISCLOSURE SURFACE — my ruling

**Ruling: a raw session ID in this application-log line is NOT consistent with the ticket's
privacy posture. It is a disclosure surface that this ticket must close, and it is already a
breach of a written constraint rather than a new judgement call. Grade: Critical.**

The reasoning, with the evidence that decided it.

**1. There is an explicit, recorded prohibition, and it names this exact sink.**
`docs/superpowers/plans/2026-09-22-conversation-pins-runtime-v1.md:21`:

> The final #260 PRD amendment prohibits MLflow production/development tracing and retention of
> field-engineer work. **Production identity handling is a structured application-log sink
> containing only graph version, release ID, role, revision ID, content hash, outcome, and error
> class; it never logs payload, prompt, output, session/user ID, tools, or slide HTML**, and writes
> no Lakebase/UC trace row.

That is a closed allow-list of seven fields, with "session/user ID" named in the deny-list, for the
sink `LoggingAgentInvocationIdentitySink` implements. After slice 4B the sink emits nine fields,
two of which are session IDs. The constraint is traced to a **#260 PRD amendment**, not to a
reviewer's preference — so this is not a matter of taste.

**2. The existing guard for that prohibition is defeated by naming, not by argument.**
`tests/unit/test_persisted_agent_runtime.py:939-940`:

```python
for forbidden in ("prompt", "payload", "output", "session_id", "user_id", "response"):
    assert not hasattr(record, forbidden)
```

I probed the live sink with a production-shaped identity:

```
msg: persisted_agent_invocation
hasattr session_id        -> False      (the #261 guard's needle)
hasattr root_session_id   -> True   value: sess-owner-830471
hasattr actor_session_id  -> True   value: sess-contrib-830472
formatted: persisted_agent_invocation root=sess-owner-830471 actor=sess-contrib-830472
```

The guard was written to enforce "never logs session/user ID". It passes because the new fields are
spelled `root_session_id` and `actor_session_id`. This is the C-24 failure class one level up: the
guard pins a *name*, so the *property* it exists for is now unguarded and nothing went red. A
reviewer reading the green suite would conclude the prohibition still holds. That is the part I
grade Critical — not the severity of the leak, but that a documented constraint was breached
silently by a slice whose whole ticket is about not exposing session identifiers.

**3. The disclosure is real but latent today.** Per `tests/unit/test_logging_extra_reserved_keys.py`'s
docstring (verified: `setup_logging()` has no caller, `_otel_bootstrap` is imported by nothing,
`otel_logging.py` adds a handler without a root level), the root logger stays at `WARNING`, so
`logger.info("persisted_agent_invocation", ...)` short-circuits before `makeRecord`. The IDs are
therefore not currently written to any sink. The same docstring states the condition under which
that flips — "the moment anyone calls the `setup_logging()` that already exists" — and that
condition is a one-line change by someone with no reason to know about this contract.

**4. Slice 4A's privacy contract does not cover it, and the repo has no general "logs are a privacy
surface" rule.** 4A's contract is scoped to the HTTP response:
`tests/unit/test_collaboration_history.py:1651-1700` (`test_no_identifier_name_or_principal_appears_in_the_response_text`) forbids a needle list that
includes the literal strings `"session_id"` and `"actor_session_id"` — but only in `response.text`.
Nothing in 4A reaches the log. Elsewhere the repo *does* log `session_id` freely
(`src/api/routes/sessions.py:110`, `:700`, `src/utils/spotlight.py:42`,
`src/api/services/deck_level_writer.py:363`, and others), so "a session ID in a log line" is not a
class the repo treats as forbidden in general. The narrow, specific prohibition in §4.1 is
therefore the only authority — and it is exactly on point.

**5. So the design does not in fact "follow from the plan".** The report frames this as forced by
the plan (put root/actor on `AgentInvocationIdentity`; extend the identity sink only). Bullet 2 does
require the fields on the identity. It does not require the sink to *emit* them, and the two plans
conflict only if the sink projects its fields with `**identity.__dict__`
(`src/services/agent_runtime_identity.py:77` and `:86`). The conflict is resolvable inside 4B's own
file with no change to the dataclass and no change to any other slice:

```python
_LOGGED_FIELDS = ("graph_version", "graph_release_id", "agent_key",
                  "agent_definition_revision_id", "content_hash")
...
extra={**{f: getattr(identity, f) for f in _LOGGED_FIELDS}, "outcome": ..., "error_class": ...}
```

plus a test that asserts the **exact** emitted field set rather than a deny-list of names — which is
the fix for the C-24-class weakness in §4.2 as well, and would have caught this automatically.

**If the controller instead decides the IDs belong in the log**, then #262 must amend the #261 plan
text and the `test_persisted_agent_runtime.py` guard explicitly, so the next reader does not find a
green test asserting a contract the code no longer honours. Silent acceptance is the one option I
would reject.

**One further, smaller disclosure in the same family** (graded Minor, finding 5): the deck
**owner's** session ID now reaches the model. `build_branch_payload` declares both keys
(`nodes.py:1331-1337`), `builder_node` passes `skill_payload = dict(payload)` to `run`
(`nodes.py:2090`), and v1 prompt assembly json-dumps the whole payload into the prompt
(`src/services/prompt_assembler.py:689` and `:782-783`). Measured end to end with a throwaway probe
(since deleted): the builder's prompt contains both the owner's and the contributor's session IDs.
The report discloses this correctly in §2.3. The **commit message does not** — it states "the IDs
reach the identity sink and nothing else: no prompt, no model", which is false for the builder role,
and that message becomes the PR body. Before this slice the builder payload carried only the
*actor's* `session_id`; it now also carries a *different user's* identifier, so "the disclosure class
is unchanged, not widened" is not quite right either.

---

## 5. MY TWO MUTATION TARGETS (plus three supplementary)

Anchor counts asserted before every patch (C-27); the harness refuses on any count but the expected
one. Every mutation restored from `cp` backups and the restore verified. All five hit their intended
anchor; none needed a re-aim, and none REDed nothing.

**GREEN control (unmutated, committed tree), `test_graph_nodes.py test_graph_routers.py test_graph_builder.py`:**

```
233 passed, 125 warnings in 4.93s
```

### Target 1 — is the owner genuinely resolved ONCE?

**R1 — a second query.** `src/services/graph/builder.py`, anchor
`    root_session_id = root_loader(get_session_local(), session_id)` duplicated. `ANCHOR COUNT 1, expected 1`.

```
>       assert root_calls == ["contributor-session"]
E       AssertionError: assert ['contributor...utor-session'] == ['contributor-session']
E         Left contains one more item: 'contributor-session'

tests/unit/test_graph_nodes.py:2793: AssertionError

FAILED tests/unit/test_graph_nodes.py::TestInvokeGraphResolvesTheTrace::test_the_owner_is_resolved_once_and_hostile_ids_are_overwritten
1 failed, 232 passed, 125 warnings in 5.13s
```

**RED ×1, exactly the clause's test, zero collateral.** "Resolved once" is genuinely and precisely
guarded at the entry point.

**R2 — a per-branch RE-DERIVATION instead of the turn's single resolution.**
`src/services/graph/routers.py`, anchor `                "root_session_id": state.get("root_session_id") or "",`
→ `dict(record).get("session_id") or ""` — i.e. the failure the author's own comment warns about
("a branch that looked it up again could disagree with its siblings"). `ANCHOR COUNT 1, expected 1`.

```
calls = [AgentInvocationIdentity(graph_version=2, graph_release_id=2, agent_key='build_reviewer', ...,
         root_session_id='contrib-5a972b7938', actor_session_id='contrib-5a972b7938')]
collab = namespace(owner_session_id='graph-141d835685', ..., contributor_session_id='contrib-5a972b7938', ...)

        for call in calls:
>           assert call.root_session_id == collab.owner_session_id
E           AssertionError: assert 'contrib-5a972b7938' == 'graph-141d835685'
E             - graph-141d835685
E             + contrib-5a972b7938

tests/unit/test_graph_nodes.py:2648: AssertionError

FAILED tests/unit/test_graph_nodes.py::TestRuntimeRootActorTrace::test_the_refanned_build_review_records_root_actor_and_the_actors_release
FAILED tests/unit/test_graph_nodes.py::TestRuntimeRootActorTrace::test_the_whole_turn_records_one_immutable_root_actor_and_release
2 failed, 231 passed, 125 warnings in 5.00s
```

**RED ×2 — the clause is guarded. But the test that exists to guard it stayed GREEN.**
`test_the_refan_overwrites_a_hostile_root_actor_and_release_in_the_record` — the test whose stated
purpose is that the re-fan re-declares provenance *from state* rather than from the record — does
not fail, because its record's `session_id` defaults to `graph_env.session_id`, which **is** the
owner session, so sourcing the root from the record yields the expected answer. Minor finding 6.

### Target 2 — IDs never select the release; the pin loader is called with the actor's session

**R3 — break the ordering semantically while keeping it textually.**
`src/services/graph/builder.py`, anchor
`    graph_release_id = pin_loader(get_session_local(), session_id)` →
`pin_loader(get_session_local(), root_loader(get_session_local(), session_id))`.
`pin_loader(...)` remains the first statement. `ANCHOR COUNT 1, expected 1`.

```
>       assert pin_calls == ["contributor-session"]
E       AssertionError: assert ['owner-session'] == ['contributor-session']
E         At index 0 diff: 'owner-session' != 'contributor-session'
tests/unit/test_graph_nodes.py:2815: AssertionError

>       assert root_calls == [], "the owner was resolved before the pin was checked"
E       AssertionError: the owner was resolved before the pin was checked
E       assert ['legacy-session'] == []
tests/unit/test_graph_nodes.py:2839: AssertionError

FAILED ...::TestInvokeGraphResolvesTheTrace::test_the_owner_is_resolved_once_and_hostile_ids_are_overwritten
FAILED ...::TestInvokeGraphResolvesTheTrace::test_the_release_is_the_actors_pin_and_the_root_never_selects_it
FAILED ...::TestInvokeGraphResolvesTheTrace::test_a_null_pinned_legacy_root_runs_no_node_and_resolves_no_owner
FAILED tests/unit/test_graph_builder.py::TestInvokeGraphConfig::test_loads_the_persisted_pin_and_overwrites_hostile_initial_state
4 failed, 229 passed, 125 warnings in 4.96s
```

**RED ×4.** This is the strongest single result in the review. It establishes two things the
author's own M7a/M7b cannot: (a) the pin is loaded with the **actor's** session and only that —
`pin_calls == ['owner-session']` is caught — and (b) C-3's ordering is guarded *semantically*, so
the author's defence ("`pin_loader` is still the first statement") is not what the test relies on.
The fourth RED is the pre-existing `test_loads_the_persisted_pin_and_overwrites_hostile_initial_state`
failing because `fake_graph`'s stub answers the root query with a `PinnedRow` object — i.e. the
fixture defect the author disclosed (§8.6), surfacing under load. Confirms that disclosure.

### Supplementary (used for the C-29 audit)

**R4 — blank the fixer-retry trace while satisfying the AST substring guard.** `nodes.py`,
`state.get("root_session_id")` → `state.get("root_session_id_TYPO")` at the fixer retry site only.
`ANCHOR COUNT 1, expected 1`.

```
FAILED tests/unit/test_graph_nodes.py::test_no_node_or_router_reads_a_key_graphstate_does_not_declare
FAILED tests/unit/test_graph_nodes.py::TestRuntimeRootActorTrace::test_the_fixer_and_its_unsafe_output_retry_record_one_identity
2 failed, 231 passed
```

**R5 — the same, at the builder retry, via `payload.get(...)`** — which evades *all four* structural
guards (arity still 4/0; still one `_assembly_context` with 3 args; the substring
`"root_session_id"` is still present; and `_state_read_keys` deliberately ignores `payload` reads,
`tests/unit/test_graph_nodes.py:2394-2400`). `ANCHOR COUNT 1, expected 1`.

```
FAILED tests/unit/test_graph_nodes.py::TestRuntimeRootActorTrace::test_the_builder_and_its_unsafe_output_retry_record_one_identity
FAILED tests/unit/test_graph_nodes.py::TestRuntimeRootActorTrace::test_the_whole_turn_records_one_immutable_root_actor_and_release
2 failed, 231 passed
```

**Both caught behaviourally.** So the structural guard's substring weakness (Minor finding 7) is not
load-bearing: the chain tests bite on their own at the two retry sites I probed. This is a genuinely
good result for the slice — the coverage is behavioural, not merely AST-shaped.

---

## 6. C-29 AUDIT OF THE AUTHOR'S 27 ROWS

C-29 as applied to my own five: none REDed nothing, so the rule's trigger never fired for me. I
still checked each for a RED another path could have supplied — R2's result is exactly that class,
reported above.

Against the author's rows. All 27 anchor counts are as claimed (26 × 1, M17 × 2 — I verified the
counts for M9e and M19 directly, and the harness refuses on a mismatch). Blank count 0 as claimed.
Four rows have the shape C-29 warns about:

**1. M17 — the clearest case, and it turns into an Important finding.** The clause is "the
downstream mutation event's actor is the actor session (AC4: trace and evidence agree)". The
mutation replaces the first argument of `_deck_mutation_context` with `payload["root_session_id"]`
and REDs ×4. But the unmutated first argument is `payload["session_id"]`
(`src/services/graph/nodes.py:2078-2083` and `:2200-2205`) — a **pre-existing Task-3 path that slice
4B did not touch**. The RED proves only that the event's actor is not the root. It proves nothing
about `actor_session_id`, and the agreement the clause claims holds only because
`invoke_graph` writes `"session_id": session_id` and `"actor_session_id": session_id` from the same
variable. The compensating path is the thing the clause was supposed to pin — C-29's "more
dangerous reading", precisely. Consequence: Important finding 2.

**2. M9b / M9c — disclosed, and the disclosure is accurate.** The author states plainly that under
M9c the identity test stays green "because `dict(record)` still carries correct values". That is the
honest reading: part of the identity test's RED under M9a/M9e is supplied by the record, not by the
re-declaration. Correct handling, nothing to add.

**3. M10–M15 (six rows) — each gets one free RED from the structural guard.** Every one of these
blanks a site's context as `_assembly_context(dsa, "", "")`, which necessarily REDs
`test_every_call_site_sources_both_ids_from_its_state_or_payload` because the textual reference is
gone. So the reported counts (RED ×2 to ×4) overstate the *behavioural* coverage by one per row, and
M11's "RED ×2" is behaviourally a RED ×1. I closed this by re-aiming two of them (R4, R5) at
mutations that leave the structural guard green: the behavioural tests RED on their own at both
sites. **Conclusion: the rows are sound, the counts are imprecise.** Minor, reporting only.

**4. M5 — both REDs are static.** The clause is "`GraphState` declares both keys (undeclared keys
are dropped silently)". Its two REDs are `test_root_and_actor_are_declared_single_writer_keys` (a
`get_type_hints` assertion) and the pre-existing
`test_no_node_or_router_reads_a_key_graphstate_does_not_declare` (an AST sweep,
`tests/unit/test_graph_nodes.py:2394-2430`). Neither runs a graph. Consequence: Important finding 4.

**5. M1 — noted, not faulted.** The non-nullability guard compares the *annotation string*
(`field.type == "str"`), which works only because `agent_runtime_identity.py` uses
`from __future__ import annotations`. Adequate for a declarative clause; it is not a runtime
guarantee and should not be read as one. Minor finding 8.

**Rows I checked and found clean:** M2 (×12), M3 (×15), M4, M6, M7a, M7b, M8, M9a, M9e, M16, M18,
M19, M20, M21, M22 — each RED is produced by the mutated value reaching the assertion under test,
with no plausible alternative supplier. M16 deserves credit: the author hit a zero at a correct
anchor count, suspected coverage rather than the clause, and closed it by adding the test that makes
the architect drive the re-review pass from inside the node. That is C-29's prescribed handling,
applied before C-29 existed.

---

## 7. THE TWO PLAN RULINGS

### C-30 — **CORRECT.** Both files are genuinely required, and nothing else was touched.

Bullet 1 names seven handoffs. Six live in `src/services/graph/nodes.py`
(`build_branch_payload`, the builder retry, the build-reviewer record, the fixer retry, the
fix-reviewer record, `rereview_committed_slides`) and the `dict(record)` re-fan bullet 2 names
explicitly lives in `src/services/graph/routers.py:189`. Neither appears in C-9's Modify list for
either slice, nor in the plan's Task 4 Files block — I confirmed both by reading the plan at
`docs/superpowers/plans/2026-09-22-mixed-release-collaboration.md:172-173`. Bullets 1 and 2 are
unsatisfiable without them.

Nothing else was touched. `git diff --name-only f5ec0bfd5..6d9d154de` is exactly the five files C-9
granted, plus those two, plus the report. `src/services/collaboration_history.py` and every other
4A file is untouched; `frontend/src/api/agentDefinitions.ts` is untouched, so `CUSTOM_ANCHORS` order
is intact. Both added files are disjoint from #265's integrated diff.

### C-31 — **CORRECT, and I verified the discrimination independently on a wider selection.**

I reproduced M9e (filter root/actor from the `**dict(record)` spread **and** delete the two
re-declarations, release intact). Both anchor counts 1 as expected.

On the author's 233-test focus:

```
FAILED ...::TestRuntimeRootActorTrace::test_the_refanned_build_review_records_root_actor_and_the_actors_release
FAILED ...::TestRuntimeRootActorTrace::test_the_refan_overwrites_a_hostile_root_actor_and_release_in_the_record
FAILED ...::TestRuntimeRootActorTrace::test_the_whole_turn_records_one_immutable_root_actor_and_release
3 failed, 230 passed, 125 warnings in 5.56s
```

The author measured only those three modules, so I widened to 11 (624 tests, adding
`test_graph_state`, `test_agent_runtime`, `test_persisted_agent_runtime`,
`test_deck_level_spec_change`, `test_prompt_assembler`, `test_graph_safety`,
`test_collaboration_history`, `test_shared_deck_attribution`):

```
FAILED ...::test_the_refanned_build_review_records_root_actor_and_the_actors_release
FAILED ...::test_the_refan_overwrites_a_hostile_root_actor_and_release_in_the_record
FAILED ...::test_the_whole_turn_records_one_immutable_root_actor_and_release
3 failed, 621 passed, 130 warnings in 9.66s
```

Identical three. **Zero pre-existing tests, zero other node's identity test** — the architect,
data-analyst, builder, fixer, fix-reviewer, deck-reviewer and `rereview` identity tests all stay
green. The discrimination the ruling identifies as the requirement's substance holds. The ruling
that two clauses genuinely share the one expression is also correct on inspection: the reviewer must
*receive* the provenance and the re-fan must *re-declare* it from state, and no sabotage of a single
expression can separate those.

---

## 8. BASELINES AND THE TWO INTEGRATION FAILURES

Measured with the same command and environment throughout
(`python -m pytest tests/unit -q -p no:randomly`).

| tree | result |
|---|---|
| pristine base (the seven files restored from `f5ec0bfd5`) | **6 failed, 5609 passed, 110 skipped** in 300s |
| committed slice `a36433040` | **6 failed, 5637 passed, 110 skipped** in 307s |

Both claims confirmed exactly. Delta is **+28 passed, zero new failures** = the 28 tests this slice
adds. The six failures are identical before and after and match the documented set by *cause*, not
just by count:

- `test_deploy_autoscaling.py` ×2 — `assert 'provisioned' == 'autoscaling'`, and
  `Expected '_get_or_create_lakebase_provisioned' to have been called once. Called 0 times.`
- `test_style_exclusivity_chokepoint.py` ×3 — `AttributeError: '_FakeSession' object has no attribute 'execute'` at `src/services/conversation_pins.py:79`
- `test_style_exclusivity_persistence_boundary.py` ×1 — `ConversationGraphReleaseIntegrityError: no active Graph Release`, the raise at `src/services/conversation_pins.py:83`

`test_deck_permission_routes.py::test_create_session_no_profile_params` is absent from both lists —
**C-10's cause is gone**, repaired by slice 4A as C-10 assigned. #265's integration added no new
failure cause.

### The two inherited INTEGRATION failures — **CONFIRMED PRE-EXISTING**

The review range touches only seven files, so restoring those seven from `f5ec0bfd5` reproduces the
pristine base tree exactly (verified by blob hash). Same two tests, same identifiers, same causes,
on both trees:

| tree | result |
|---|---|
| committed slice | `2 failed, 1 passed` in 27.7s |
| pristine base | `2 failed, 1 passed` in 28.4s |

```
FAILED tests/integration/test_graph_orchestration.py::test_a_position_left_uncommitted_by_a_completed_batch_is_placeheld_by_the_stall_path
FAILED tests/integration/test_persisted_graph_runtime_failures_postgres.py::test_persisted_corruption_escapes_later_node_recovery[deck_reviewer-deck_reviewer-_wrong_hash_revision]
```

with, on the base tree,
`TypeError: ... only_the_foreman_may_placehold() got an unexpected keyword argument 'mutation'`
→ `langgraph.errors.GraphRecursionError: Recursion limit of 10007 reached`, and
`ValueError: mutation actor pin does not match its persisted pin` out of
`src/services/shared_deck_attribution.py:100`.

Both are Task-3-era fixture drift of C-11's class, unowned by any open slice. **They do not belong
to slice 4B.** The author is also right that nobody had measured them before: every earlier baseline
in this ticket was unit-only.

PostgreSQL: fixtures made their own throwaway databases; I migrated, altered and dropped nothing,
and did not touch `ai_slide_generator` (C-22).

---

## 9. FINDINGS

### Critical

**C1 — the identity log sink now emits two raw session IDs, breaching a written PRD-derived
prohibition, and the guard for that prohibition is defeated by field naming.**
`src/services/agent_runtime_identity.py:34-35` (the two fields) → `:77-83` and `:86-92`
(`**identity.__dict__` into `logger.info`'s `extra`). Prohibition at
`docs/superpowers/plans/2026-09-22-conversation-pins-runtime-v1.md:21`. Defeated guard at
`tests/unit/test_persisted_agent_runtime.py:939-940`. Full reasoning and the three-line fix in §4.
Latent today only because the root logger stays at `WARNING`.

### Important

**I1 — AC4's "trace and evidence agree" is asserted but not established.** The build-reviewer
re-fan re-declares `graph_release_id`, `root_session_id` and `actor_session_id` from state
(`src/services/graph/routers.py:189-203`) but **not** `session_id` — and `session_id` is the key the
mutation event's actor is built from (`src/services/graph/nodes.py:2200-2205` →
`_deck_mutation_context` at `:104-117` → `MutationActor(session_id, graph_release_id)`). Measured
with a hostile record:

```
re-fanned Send payload, provenance-relevant keys:
   session_id           = 'attacker-session'
   root_session_id      = 'owner-session'
   actor_session_id     = 'contributor-session'
   graph_release_id     = 2
```

So under the exact threat model the author's own docstring invokes ("a resumed or hand-forced
[record] can carry any release, root or actor at all"), the runtime trace would say
`contributor-session` while the persisted evidence row says `attacker-session`. Three of the four
provenance keys were hardened; the one the evidence row actually reads was not.
`test_the_persisted_mutation_event_agrees_with_the_runtime_trace` cannot see this because it passes
a record whose `session_id` is already correct. **Fix:** add `"session_id": state["session_id"],` to
the re-fan dict and assert it in the hostile-record test. (A `session_id` trusted from the record
also drives the row write itself, which is pre-existing and larger; that part belongs to the
whole-branch review, not to this slice.)

**I2 — a third root resolver, and it is fail-OPEN where slice 4A is fail-closed.**
`src/services/graph/builder.py:195-222` (`load_collaboration_root`) joins on
`coalesce(requested.parent_session_id, requested.id)` but omits the
`root.parent_session_id IS NULL` requirement that `collaboration_history.authorized_collaboration_root`
carries. C-16 already records the divergence between the two existing resolvers as an open
pre-existing defect; this makes it three, with three different behaviours on a hand-forced depth-2
row: `_resolve_root_session` (`src/services/permission_service.py:217-231`) walks to the real root,
`authorized_collaboration_root` returns `None` (404), and the new one returns **the intermediate
contributor as the root** — silently recording a non-root session as the deck owner in the trace,
which is the one thing AC4 exists to prevent. C-16's one-hop ruling justifies the join shape; it
does not justify dropping 4A's fail-closed guard. **Fix:** add
`.where(root.parent_session_id.is_(None))` and keep the raise, matching 4A's posture.

**I3 — the `GraphState` declaration clause is guarded statically only.**
`src/services/graph/state.py:186-204`. LangGraph builds channels from the schema and drops
undeclared keys, so losing either declaration blanks the trace at all five state-reading nodes
(architect, data_analyst, fixer, fix_reviewer, deck_reviewer) — and because every read is
`.get(...) or ""` by design, nothing would raise. M5's two REDs are a `get_type_hints` assertion and
an AST sweep. No test drives the real compiled graph with these keys. The vehicle exists —
`TestARealTurn` (`tests/unit/test_graph_builder.py:508-515`) builds and invokes the real graph — but
it is in a file C-9 did not grant slice 4B, so this gap is boundary-caused rather than negligent.
It should still be closed before merge: one assertion in `TestARealTurn` that the trace survives the
channel.

### Minor

**M-a — the commit message contradicts the measured behaviour.** It states the IDs reach "the
identity sink and nothing else: no prompt, no model". Measured: the builder's model prompt carries
both, including the deck owner's — `nodes.py:1331-1337` → `:2090` →
`src/services/prompt_assembler.py:689,782-783`. The report discloses this (§2.3); the commit message,
which becomes the PR body, does not. Also, the report's "the disclosure class is unchanged, not
widened" understates it: a *third party's* identifier now goes to the model where only the actor's
did before.

**M-b — `test_the_refan_overwrites_a_hostile_root_actor_and_release_in_the_record` does not
discriminate the root's source.** Demonstrated by R2 (§5): it stays green when the root is sourced
from `record["session_id"]`, because `_branch_payload`'s default `session_id` is
`graph_env.session_id`, which *is* the owner. Give that record a distinct `session_id`.

**M-c — `test_every_call_site_sources_both_ids_from_its_state_or_payload` is a substring check.**
`"root_session_id" in ast.unparse(context.args[1])` passes for `state.get("root_session_id_TYPO")`
or any key containing the name. R4/R5 show the behavioural tests catch such a blank anyway, so this
is not load-bearing — but the report's claim (c) reads stronger than the assertion is.

**M-d — M1's non-nullability guard is an annotation-string comparison** (`field.type == "str"`),
dependent on `from __future__ import annotations`. Fine for a declarative clause; not a runtime
guarantee.

**M-e — `test_graph_builder.py`'s `fake_graph` now misleads, and it bites under mutation.** Its
`_PinnedSession.scalar()` answers every statement with a pin row
(`tests/unit/test_graph_builder.py:172-183`), so `state["root_session_id"]` receives that row
object. All 15 tests stay green as disclosed, but my R3 made the pre-existing
`test_loads_the_persisted_pin_and_overwrites_hostile_initial_state` fail through it. Confirms
disclosure §8.6 and raises it slightly: the fixture is not merely cosmetic, it will produce
confusing failures for the next person to touch `invoke_graph`.

**M-f — two DB round-trips per turn.** `src/services/graph/builder.py:302-303` calls
`get_session_local()` twice; the pin and the owner could share one session (or one statement).
Acceptable on a per-turn path; noted for the whole-branch review.

**M-g — `foreman_router`'s `Send` is covered only transitively.** No test asserts that
`routers.py:123`'s Sends carry root/actor; the coverage comes from `build_branch_payload`'s own
test. Low risk (the Send passes the payload verbatim) but bullet 1 names the Send.

**M-h — small reporting inaccuracies.** The eight-module focus measures **507**, not 506. M19's
collateral is site-dependent (33 on the architect site, 23 on the author's). Neither affects a
conclusion.

### Assessed and NOT faulted

- **Defaulted rather than required dataclass fields** (report §8.4). I counted the out-of-boundary
  construction sites: **59** `AgentAssemblyContext(...)` constructions outside `nodes.py` across 13
  modules, 38 of them single-argument. Required fields would break all of them, several in files
  neither #262 nor #265 owns. The choice is forced, the structural mitigation is real, and R4/R5
  show it is backed behaviourally. Correct call.
- **All 4B tests placed in `test_graph_nodes.py`** (report §8.2), including `invoke_graph` and router
  tests. Awkward but correct: C-9 granted exactly one test file, and the author flagged the
  placement rather than editing files outside the boundary. Prefer this over a silent boundary
  breach.
- **No MLflow or Lakebase trace, no new row the history API reads.** Verified: no such symbol in the
  range's diff, and both sinks still persist nothing.
- **The `.get(...) or ""` tolerance at read sites.** The stated reason — a strict read inside
  `build_reviewer_node` lands in an exception handler that placeholds the user's slide — is correct
  on inspection of `nodes.py:2236-2260`. Trace is evidence about a mutation, not a precondition for
  one. Right trade.

---

## 10. CANNOT VERIFY

1. **The #260 PRD amendment itself.** My §4 ruling rests on the #261 plan's restatement of it
   (`docs/superpowers/plans/2026-09-22-conversation-pins-runtime-v1.md:21`). The PRD is not in the
   repo, so I cannot confirm the amendment's exact wording or whether it was later revised. If it
   was, C1's grade should be revisited — but the restatement is the standing authority in-repo and
   the `test_persisted_agent_runtime.py:939` guard was clearly written to it.
2. **Whether the log line can be emitted in the deployed Databricks Apps configuration.** I verified
   from the repo that nothing sets the root logger to INFO, which is why I graded C1's runtime
   impact latent. I did not inspect the deployed app's logging configuration, and an Apps platform
   handler could differ from what the repo configures.
3. **The runtime trace under the real compiled graph end to end.** No test exercises it (I3) and I
   did not add one; I established the mechanism by reading LangGraph's channel semantics and the
   `_state_read_keys` contract, not by measurement.
4. **Integration coverage under mutation.** My mutation runs covered up to 624 unit tests. I did not
   re-run the graph integration suites under any mutation, so "zero pre-existing tests affected" for
   M9e is verified for unit only (on a selection three times wider than the author's).
5. **The 594-test "affected-suite focus" figure in the dispatch.** I could not reproduce it from any
   module set I tried; I measured 233 (3 modules), 507 (the author's 8), and 624 (11). No conclusion
   depends on it.
