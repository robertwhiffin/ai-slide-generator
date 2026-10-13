# Agent Definition Workbench and Graph Releases — Design

**Status:** Spec, ready for user review

**Date:** 2026-09-21

**Parent:** `2026-08-06-agentification-core-design.md`

**Scope:** Move the agentic graph's model-driven definitions into Lakebase and add
an admin workbench for editing, isolated testing, human approval, graph-level
publication, history, and rollback.

---

## 1. Decision summary

Tellr will manage the seven model-driven graph roles as deployment-wide **Agent
Definitions**. Each definition contains:

- authored prompt text;
- exact model endpoint;
- temperature, maximum tokens, and top-p;
- a protected output-schema overlay;
- declarative prompt-assembly rules; and
- the version and digest of the protected assembly and schema-contract bundles
  needed to execute it.

Admins edit one shared **Graph Draft**, test changed definitions in isolation, and
publish all changes as one atomic **Graph Release**. A graph-capable conversation pins
one release at creation and uses it for its lifetime. Lakebase is the only runtime source of
truth; code defaults never take over when configuration is missing.

The seven model-driven roles are:

1. Architect
2. Data Analyst
3. Builder
4. Build Reviewer
5. Fixer
6. Fix Reviewer
7. Deck Reviewer

Foreman remains a visible, deterministic Graph Node. It has no model, system prompt,
or Agent Definition and is not editable.

## 2. Why

The agentic rebuild currently defines every prompt, model setting, output contract,
and assembly rule in Python. There is no UI to inspect or tune them, no controlled
publication unit, and no way to identify the exact graph configuration used by a
conversation.

The existing implementation also creates two misleading impressions:

- `Skill.tool_grants` looks operational, but the LangGraph `call_skill` path binds no
  tools. UI-added tools therefore do not reach Data Analyst.
- Foreman sounds like a prompted role, but it is pure scheduling and routing code.

This design makes the actual configurable surface explicit without expanding into
tool routing or converting deterministic orchestration into model behavior.

## 3. Canonical language

The repository glossary is [`CONTEXT.md`](../../../CONTEXT.md). The load-bearing
distinctions are:

- An **Agent Definition** configures one model-driven role.
- A **Graph Node** may be model-driven or deterministic.
- A **Graph Draft** is mutable and never runs production conversations.
- A **Graph Release** is immutable and contains all seven definition references.
- A **Graph Version** is a UI ordinal, never a database identifier.
- A **Conversation Pin** is immutable for the lifetime of a conversation.

Do not reuse the existing `AgentConfig` name. That type configures per-session tools,
styles, design systems, templates, and deck prompts. The new domain is deployment-wide
graph behavior and is named `AgentDefinition` throughout.

## 4. Product boundary

### 4.1 Included

- Admin-only inspection and editing of all seven Agent Definitions.
- A read-only Foreman node in the graph navigation.
- One shared deployment-wide Graph Draft.
- Explicit per-agent draft saves.
- Isolated agent test cases and human-reviewed test runs.
- Deterministic checks; no automated quality judgement.
- Atomic graph-level publication and immutable history.
- Emergency rollback as a new Graph Release.
- Conversation pinning and release metadata in traces.
- Bootstrap creation of the new tables and Graph Version 1.

### 4.2 Excluded

- Tool assignment, tool toggles, or Data Analyst tool wiring.
- LLM-as-judge, quality scores, datasets, or analytics.
- Per-user, customer, profile, deck, or session definition overrides.
- Arbitrary executable assembly logic.
- Changes to code-owned required output fields, types, enums, or validators.
- Model-driven or configurable Foreman behavior.
- Migration of prior prompt state; this branch has no prior released state.
- Automatic model-family upgrades or conversation upgrades.
- Prompt-quality rewrites unrelated to moving the current definitions.

The disconnected UI-tool to Data Analyst path is a separate follow-up. It must not be
quietly folded into this project.

## 5. Chosen persistence architecture

Three designs were considered:

1. Per-agent SCD2 rows: rejected because independent validity windows contradict
   atomic graph publication and mix mutable drafts with production history.
2. One JSONB release bundle: rejected because constraints, querying, diffs, and
   per-agent history become opaque.
3. Immutable definition revisions plus SCD2 Graph Releases: selected.

SCD2 validity describes when a **Graph Release** was deployment-active. An Agent
Definition revision is immutable content and has no independent activation interval.

### 5.1 `agent_definition_revision`

One immutable revision of a model-driven role:

| Field | Contract |
|---|---|
| `id` | Internal primary key; never displayed as a Graph Version |
| `agent_key` | One of the seven code-owned model-driven role keys |
| `content_hash` | Hash of canonical prompt/model/schema/assembly content and protected runtime-contract identities |
| `prompt_text` | Authored base instructions |
| `endpoint_name` | Exact Databricks or custom serving endpoint name |
| `temperature` | Validated model parameter |
| `max_tokens` | Validated positive integer |
| `top_p` | Validated model parameter |
| `schema_overlay` | JSONB overlay constrained by the code-owned schema |
| `assembly_rules` | JSONB declarative ordered block plan |
| `protected_assembly_version`, `protected_assembly_digest` | Immutable identity of the code-owned protected prompt-block bundle |
| `schema_contract_version`, `schema_contract_digest` | Immutable identity of the code-owned canonical-schema evaluator/builder |
| `created_by`, `created_at` | Audit metadata |

`(agent_key, content_hash)` is unique so unchanged content can be reused. Published
rows are never updated or deleted.

The versioned protected bundles are release inputs, not deployment-global mutable
defaults. `AgentRuntime` resolves the exact bundle named by a revision and fails
explicitly if that version is unavailable; a deployment must retain prior bundle
implementations. Changing protected prompt material or a schema evaluator therefore
creates a new version/digest and a new definition revision rather than silently
changing a historical release's behavior.

### 5.2 `graph_release`

One immutable publication event and the SCD2 active interval:

| Field | Contract |
|---|---|
| `id` | Internal primary key |
| `version_number` | Unique, monotonic UI Graph Version |
| `previous_release_id` | Direct publication predecessor |
| `restored_from_release_id` | Historical release restored by rollback, nullable |
| `release_note` | Required free-form text |
| `published_by`, `published_at` | Audit metadata |
| `effective_from`, `effective_to` | SCD2 deployment-active interval |

Exactly one release has `effective_to IS NULL`. Closing an interval never makes that
release unreadable: pinned conversations and history continue resolving it by ID.
Enforce the single active interval with a PostgreSQL partial unique index rather than
an application-only check.

### 5.3 `graph_release_agent`

Maps every Graph Release to exactly one revision for each of the seven Agent
Definitions. It has non-null foreign keys `graph_release_id -> graph_release.id` and
`agent_definition_revision_id -> agent_definition_revision.id`, both `ON DELETE
RESTRICT`; its primary key is `(graph_release_id, agent_key)`. The revision table
exposes a unique `(id, agent_key)` target, and a composite foreign key requires the
mapping's `agent_key` to equal the referenced revision's key. A database `CHECK` closes
`agent_key` to the seven code-owned keys, and publication also rejects any release
whose key set is incomplete. Neither a release nor a revision can be removed through
cascade.

### 5.4 `graph_draft` and `graph_draft_agent`

There is one shared Graph Draft:

- `graph_draft` holds `base_release_id`, `lock_version`, and update metadata.
- `graph_draft_agent` holds mutable candidate content and its canonical hash.

Draft saves use optimistic concurrency. A stale `lock_version` returns `409` and does
not overwrite the newer draft. One person is expected to edit at a time; this guard
prevents accidental loss without introducing private drafts or merging.

Publishing materializes immutable revisions only for changed definitions and reuses
the base release's unchanged revisions. The draft is then rebased onto the new release.

### 5.5 Test persistence

`agent_test_case` stores:

- agent key, name, version, and active/required flags;
- synthetic JSON payload;
- declarative assembly context, such as design-system activity; and
- author and timestamps.

At least one active required smoke case is seeded for every editable agent.

`agent_test_run` stores:

- test case ID and version;
- candidate definition hash;
- compared published release and definition revision;
- candidate and stored-baseline raw/structured outputs;
- deterministic check results;
- latency and token usage when available;
- execution status and errors;
- human verdict, reviewer, review time, and optional notes.

`graph_release_test_run` links a published release to its evidence. It has non-null
foreign keys to both release and test run with `ON DELETE RESTRICT`, plus an
`evidence_kind` closed to `approval` and `historical_restore`, and a
`source_release_id -> graph_release.id ON DELETE RESTRICT` that is non-null only for
`historical_restore`. `approval` links only an approved run that met the candidate's
readiness gate; `historical_restore` records rollback reuse and its source release,
and never satisfies a new candidate's readiness query. It is the retention and audit
anchor: release history does not infer evidence from whichever test runs happen to
remain.

Every run referenced by a published release is retained. For unpublished work, retain
the latest 20 runs per test case **without deleting** either (a) a run linked through
`graph_release_test_run`, or (b) an approved run still eligible for an active required
case and the current shared-draft candidate hash. The bounded cleanup selection must
express both exclusions (`NOT EXISTS` a release-evidence link and not-current-eligible
approval), and the foreign key makes an accidental deletion of linked evidence fail.
Publication locks and revalidates the exact eligible approval rows before linking
them, while cleanup uses the same lock boundary; a cleanup race cannot remove
evidence that a publish is about to consume.

### 5.6 Conversation pin

`user_sessions.graph_release_id` is a non-null foreign key for new graph-capable
conversations. Legacy-only conversations are an explicit, preserved no-graph state
while the existing database is upgraded; they may retain a null pin and continue on
their legacy invocation path.

For every new root, chat auto-created, contributor, or duplicated conversation,
session creation locks the current active release row (`SELECT ... FOR UPDATE`),
verifies it is still active, and writes that ID before commit. Publication locks and
closes that same row. The row lock is the linearization point: a session either commits
with the release active while it held the lock, or retries and pins the newly active
release. This applies to all four creation paths, not just the explicit root-session
endpoint. Existing conversations never change release. Duplicating or starting a new
root conversation is the explicit upgrade path.

Mixed-release collaboration is intentional: a newly joining contributor can therefore
write the shared root deck under a newer release than its owner. A shared deck has no
single inferred Graph Version. Every deck mutation and trace records the root deck ID,
actor session ID, and actor's pinned release; the conversation surface shows the
actor's pinned version and warns participants when the shared deck has writers on more
than one version. History and audit views group this evidence by actor/release rather
than attributing a deck mutation to the root session's pin.

## 6. Bootstrap and source of truth

The established startup path creates missing ORM tables and then seeds default data.
For a fresh database it will also:

1. create these tables through the registered SQLAlchemy models;
2. insert the current seven definitions from a packaged bootstrap manifest;
3. create Graph Version 1 and all seven mappings;
4. make v1 the sole active SCD2 release;
5. create the shared draft based on v1; and
6. seed one required synthetic test case per agent.

For an existing deployment, an idempotent migration runs before the bootstrap seed:

1. add `user_sessions.graph_release_id` as a nullable foreign key;
2. bootstrap v1 and its complete mapping;
3. backfill v1 only onto existing sessions that select the agentic graph; preserve
   every legacy-only session as the explicit no-graph/null state; and
4. enforce non-null pins for all new graph-capable creation paths, and make the column
   globally `NOT NULL` only after no preserved legacy/null rows remain.

`Base.metadata.create_all()` is not the upgrade mechanism for this column; the
registered migration path owns the `ALTER`, backfill, idempotence, and verification.

The manifest is bootstrap input, not a runtime fallback. It is read only when no Graph
Release exists. Once v1 exists, every production invocation reads Lakebase. Missing
configuration is an explicit failure.

The seeded endpoint is the exact current Claude Opus endpoint
`databricks-claude-opus-4-6`. The label "Claude Opus" never floats to a newer model.
New system endpoints appear in discovery and require an explicit edit, test, approval,
and publication.

## 7. Runtime module design

### 7.1 External interface

The deep runtime module exposes one production interface and one explicit
admin-workbench candidate interface:

```python
AgentRuntime.run(
    agent_key,
    graph_release_id,
    payload,
    assembly_context,
) -> AgentInvocationResult

AgentRuntime.run_candidate(
    agent_key,
    candidate_definition,
    candidate_hash,
    payload,
    assembly_context,
) -> AgentInvocationResult
```

Only graph nodes call `run`, and its `graph_release_id` is always a published release.
Only the admin isolated-test operation calls `run_candidate`, with a validated immutable
candidate snapshot and its canonical hash; it cannot be used by a production
conversation. Both public operations delegate to the same private resolved-definition
execution path, so isolated testing exercises the same assembler, schema composition,
model adapter, validation, and tracing seam without pretending that a draft is a
release. Callers do not know storage tables, prompt blocks, model construction, or
schema composition.

`AgentInvocationResult` contains the canonical code-owned output, additional optional
fields, raw/structured diagnostic material when available, definition identity, model
metadata, latency, token usage, and deterministic validation results.

### 7.2 Internal modules

- **GraphConfiguration** owns active-release resolution, immutable release loading,
  draft saves, readiness, publication, and rollback.
- **AgentSchemaRegistry** owns the seven canonical Pydantic contracts and composes
  safe model-facing schema overlays.
- **PromptAssembler** evaluates the declarative block plan against an allowlisted
  assembly context.
- **ModelCatalog** discovers Databricks `system.ai` endpoints and validates manual
  endpoint names.
- **AgentTestWorkbench** executes Agent Test Cases through `AgentRuntime` and records
  deterministic results and human verdicts.

The graph and routes depend on these interfaces, not their storage implementation.
Databricks model invocation and endpoint discovery are injected ports; production uses
Databricks adapters and automated tests use deterministic fake adapters.

### 7.3 Graph integration

- Session creation writes the Conversation Pin.
- Graph invocation loads the pinned `graph_release_id` into `GraphState`.
- Every `Send` fan-out payload carries that release ID because fan-out nodes cannot
  read unspecified parent state.
- Every model-driven node calls `AgentRuntime`; Foreman continues executing its
  deterministic code.
- Release definitions are immutable, so a process may cache a fully loaded release by
  release ID without invalidation races.
- Traces record Graph Version, release ID, agent key, definition revision ID, and
  content hash. Test traces also record test-run ID.

This work changes only the LangGraph agentic runtime. Legacy monolith calls, export
models, feedback models, and the LLM judge keep their existing configuration unless a
separate project changes them.

## 8. Output-schema overlays

The Python schemas remain executable domain contracts. Routers and nodes rely on
specific fields, Pydantic validators enforce cross-field behavior, and the frontend
mirrors some closed enums. Database configuration cannot replace those contracts.

An overlay may:

- change descriptions and examples shown to the model;
- add optional fields; and
- remove optional fields previously added by an overlay.

An overlay may not change a code-owned field's name, type, requiredness, enum, default,
or validator. Publish-time validation compares the overlay against the canonical
registry and reports field-level errors.

The model-facing schema combines the canonical schema and overlay. For each resolved
definition, `AgentSchemaRegistry` builds a dynamic Pydantic model that contains the
allowlisted overlay fields; arbitrary undeclared extras remain forbidden. On return it
validates canonical fields and overlay fields separately, retains the latter in the
invocation's `additional_fields`, and serializes both into diagnostics, test output,
and traces. It must not rely on constructing a canonical Pydantic output model with
unknown extras, because that model may discard them. Graph logic consumes canonical
fields; added optional fields do not change routing or node behavior until code
explicitly adopts them.

## 9. Declarative prompt assembly

Assembly is an ordered list of allowlisted blocks and conditions. It executes no
stored code, expression language, or arbitrary template logic.

### 9.1 Protected stages and blocks

The UI displays these stages and blocks but does not permit removal, editing, or invalid
placement:

- runtime payload serialization;
- security and untrusted-data notices;
- generated reviewer criteria;
- frame constraints and design-system precedence rules;
- conditional build-reviewer deck-brief instructions; and
- a terminal structured-output binding stage after prompt assembly.

Protection first requires separating today's composite Data Analyst security text and
generated Build Reviewer criteria from their authored prompt text.

Every role receives a protected trust boundary, not only Data Analyst: serialized
payload material is wrapped in an untrusted-data delimiter and preceded by a
non-editable instruction that payload text is data, not instructions. The protected
bundle defines the role-specific wrapper/notice, its order, and its digest. Raw JSON
may never be appended outside that wrapper. Adversarial test payloads that ask to
ignore instructions or impersonate a protected block must prove that the protected
notice and terminal schema binding remain present and ordered.

### 9.2 Editable blocks

Admins may:

- edit the authored base prompt;
- add custom text blocks;
- edit or delete custom blocks;
- reorder custom blocks within valid protected anchors; and
- apply an allowlisted condition.

Initial condition vocabulary:

- `always`
- `design_system_active`
- `design_system_inactive`
- `payload_has_deck_brief`

The assembler rejects unknown block types, conditions, missing protected blocks, and
duplicate singleton blocks before a model call.

## 10. Model configuration

The model editor contains:

- a searchable, refreshable list of Databricks `system.ai` models;
- an advanced manual endpoint-name field for custom models;
- temperature;
- maximum tokens; and
- top-p.

Stored definitions always carry an exact endpoint name, not a model-family alias.
Manual entry accepts an endpoint name, never a URL. Parameter ranges are validated
locally and server-side. Endpoint connectivity and structured-output support are
tested through the workbench before an edited definition can be approved.

## 11. Draft, test, approval, and publication

### 11.1 Draft editing

The centre workbench saves one selected Agent Definition explicitly. Autosave does
not write each keystroke into shared state. A successful save:

1. validates fields and computes the canonical candidate hash;
2. increments the draft lock version; and
3. makes prior approvals for that agent inapplicable because they reference the old
   hash.

Old test runs remain immutable evidence; no invalidation update is required.

### 11.2 Isolated testing

An isolated test calls `AgentRuntime.run_candidate` with the saved draft candidate,
candidate hash, and selected Agent Test Case. It does not execute a graph node, route
the graph, write a deck, or persist chat messages.

The right pane shows:

- editable synthetic input and assembly context;
- the assembled prompt;
- stored approved output from the published baseline;
- candidate raw and structured output;
- deterministic checks and field-level errors;
- latency and token usage; and
- Approve and Reject controls with optional notes.

The published baseline is stored evidence, not an automatic fresh model call. An admin
may explicitly rerun it. This avoids presenting nondeterministic variation as a config
regression.

Graph Version 1 has no pre-existing approved output. Its test cases show "baseline not
recorded" until an admin explicitly runs the published definition; absence of a v1
baseline does not waive candidate checks or human approval.

### 11.3 Readiness

A changed agent is ready only when every active required test case has an approved run
whose:

- candidate hash matches the currently saved draft;
- test case version matches the current case;
- model call completed; and
- deterministic checks passed.

The same admin may edit, run, approve, and publish. The audit trail records each role;
a four-eyes rule is out of scope.

### 11.4 Publication transaction

Publication requires a non-blank free-form release note. In one transaction it:

1. locks the singleton draft and active release;
2. verifies the submitted draft lock version;
3. recomputes changed agents and readiness, locks the exact eligible approved runs,
   and revalidates their hash, case version, verdict, and deterministic checks;
4. materializes or reuses immutable definition revisions;
5. allocates the next Graph Version once;
6. closes the former active SCD2 interval;
7. inserts the new active Graph Release;
8. inserts the complete seven-agent release mapping;
9. links the approved runs used for every changed definition; and
10. rebases the shared draft onto it.

Any failure rolls back the whole transaction. No conversation can observe a partially
published graph.

## 12. Rollback

Rollback is an emergency publication path from Release History:

1. The admin selects a historical Graph Version.
2. The UI shows definition and lineage differences.
3. The admin confirms and supplies or accepts a generated rollback note.
4. The backend performs structural validation.
5. One transaction publishes the selected seven-definition mapping as the next Graph
   Version, with `restored_from_release_id` set, and links the restored release's
   evidence as `historical_restore` (including its source release) rather than a new
   `approval`.

Rollback bypasses model tests and human test approvals. Historical content already
passed its original publication gate, and a nondeterministic test requirement would
make the emergency escape hatch unreliable. Rollback still creates a new Graph
Release; it never reopens an SCD2 interval or reuses a UI version number.

For example, restoring v3 while v7 is active produces **v8 — restores v3**. Internal
Lakebase row IDs are never exposed as Graph Versions.

## 13. Admin user experience

The feature lives in the existing admin area and uses the selected three-pane
workbench.

### 13.1 Workbench

- **Left:** graph navigation and status. Foreman is visible, labelled deterministic,
  and read-only.
- **Centre:** Prompt, Model, Output Schema, and Assembly tabs for the selected agent.
- **Right:** persistent Input, Compare, and Checks views for isolated testing and
  human review.
- **Header:** base Graph Version, changed-agent count, draft controls, and Review &
  Publish.

Status vocabulary is: Clean, Unsaved, Needs test, Test failed, Awaiting review, and
Approved.

### 13.2 Dedicated release page

Review & Publish opens a dedicated page rather than a drawer or modal. It has:

- Changes & Approvals;
- Definition Diff; and
- Release History tabs.

It shows all changed agents, required-case readiness, field-level diffs, release note,
next UI version, and publication action. Release History shows author, note, changed
agents, timestamps, predecessor, and rollback lineage.

### 13.3 Conversation surface

A conversation displays its pinned Graph Version. When it is older than the active
version, the UI offers **Start new conversation with latest version**. It never mutates
the existing conversation.

## 14. Backend interface shape

Exact route names may follow existing admin conventions, but the backend must expose
these operations as distinct interfaces:

- read graph topology, active release, shared draft, and readiness;
- read and save one draft Agent Definition with an optimistic lock version;
- discover system models and validate a manual endpoint;
- create, update, version, and deactivate Agent Test Cases;
- execute an isolated Agent Test Run;
- approve or reject one completed run;
- preview release changes and field-level diffs;
- publish the current draft;
- list and inspect immutable releases; and
- roll back to a historical release.

Every interface is backend-enforced admin-only. UI hiding is not authorization.

## 15. Failure behavior

| Condition | Required behavior |
|---|---|
| Stale draft save | `409`; preserve both versions and require reload |
| Invalid schema overlay or assembly | Field/block-level `422`; no save |
| Unknown model endpoint during test | Failed test run with clear endpoint error |
| Missing approval at publish | `409` readiness response naming exact agent/case gaps |
| Concurrent publication | One transaction wins; the other receives a stale-version conflict |
| Missing active release at session creation | Fail creation clearly; no fallback |
| Missing pinned release at invocation | Fail the turn, preserve conversation state |
| Lakebase unavailable | Fail explicitly; no code defaults or latest-release substitution |
| Endpoint removed after publication | Pinned invocation fails and records endpoint identity |
| Rollback structural invalidity | Refuse rollback; retain current active release |

Test-call failures are persisted as runs but cannot receive an Approved verdict.

## 16. Security and audit

- All definition, test, release, and rollback interfaces require the existing admin
  authorization dependency.
- Non-admin conversation users see only the pinned Graph Version.
- Test cases are deployment-wide admin artifacts and must use synthetic,
  non-sensitive data. The UI displays this warning beside saved payloads.
- Custom endpoints are Databricks endpoint names, not arbitrary URLs.
- Assembly conditions come from a closed vocabulary and execute no stored code.
- Every write records the authenticated principal and timestamp.
- Every Graph Release records its note, predecessor, changed agents, definition
  hashes, test evidence, and rollback lineage.

## 17. Verification strategy

### 17.1 Unit tests

- canonical definition hashing and deduplication;
- schema-overlay acceptance and rejection for every protected property;
- assembly ordering, protected blocks, and condition evaluation;
- model parameter validation;
- readiness keyed by definition hash and test-case version;
- stored-baseline comparison semantics;
- release resolution and immutable caching;
- Graph Version display independent of row IDs;
- candidate execution uses the dynamic overlay model, preserves only allowlisted
  optional fields in `additional_fields`, and rejects undeclared extras;
- protected-bundle version/digest resolution, including explicit failure when a
  historical bundle is unavailable; and
- adversarial payload wrapping and ordering for every agent role.

### 17.2 PostgreSQL integration tests

- bootstrap creates v1, seven mappings, shared draft, and required cases exactly once;
- each release mapping references a revision of the same closed-set agent key;
- one-active-release enforcement;
- atomic multi-agent publication;
- optimistic draft-save and publish conflicts;
- reuse of unchanged definition revisions;
- rollback creates a new release and closes the prior active interval;
- pinned historical releases remain readable;
- existing-schema upgrade adds a nullable pin, bootstraps/backfills v1 for graph
  sessions, and preserves legacy/no-graph sessions until a safe NOT NULL migration;
- root, chat auto-created, contributor, and duplicate conversations serialize with
  publication at the active-release row lock;
- mixed-release contributor writes retain their distinct actor/release trace and show
  the shared-deck version warning;
- missing configuration never falls back;
- cleanup leaves a release-linked run outside the latest 20 intact, and preserves a
  current-draft eligible approval even after more than 20 later runs;
- rollback evidence is labelled `historical_restore` and cannot satisfy a new
  candidate's readiness gate.

Counts are insufficient for concurrency tests: assert exact release identities,
mappings, intervals, and conversation pins. The session/publication interleaving test
must force each lock order and prove that no session commits a stale pin after the
publication linearization point.

### 17.3 Route and authorization tests

- every read and write rejects non-admin callers;
- validation errors identify exact fields, blocks, agents, and test cases;
- stale writes return `409` without mutation;
- publication and rollback audit the authenticated principal; and
- conversation responses expose Graph Version without configuration content.

### 17.4 Frontend tests

- graph navigation includes seven editable agents and read-only Foreman;
- explicit Save Draft and stale-save recovery;
- editor behavior for protected and optional schema fields;
- locked and custom assembly blocks;
- endpoint discovery, refresh, manual entry, and exact selection;
- approval invalidation after every configurable-field change;
- published-baseline versus candidate comparison;
- release readiness and field-level diff;
- immutable history and rollback confirmation; and
- old-conversation version badge and start-latest action.

### 17.5 End-to-end flow

Exercise:

1. edit multiple agents in one Graph Draft;
2. save each definition;
3. run and approve all required cases;
4. review the graph-level diff;
5. publish once;
6. create a new conversation and verify its pin;
7. verify an older conversation retained its release;
8. roll back to a historical version; and
9. verify the rollback produced a new UI Graph Version.

Automated tests inject a deterministic fake model adapter. CI asserts schema and
workflow behavior, never subjective or nondeterministic output quality. Live isolated
tests remain human-reviewed product behavior.

## 18. Acceptance criteria

The feature is complete when:

1. All current graph definitions are seeded into Lakebase as v1 and the LangGraph
   runtime has no configuration fallback to their former code values.
2. An admin can edit any configurable field for any of the seven Agent Definitions.
3. Protected output contracts and assembly blocks cannot be weakened through UI or
   direct backend calls.
4. An admin can run one agent in isolation without routing the graph or mutating a
   deck or conversation.
5. A saved definition change invalidates approvals tied to its old hash.
6. Publication remains disabled until every changed agent's required cases are
   approved for its current hash.
7. One publication creates exactly one new Graph Version containing all seven exact
   definition revisions.
8. New graph-capable conversations pin that release; existing conversations keep their
   prior pin.
9. History exposes release notes, authorship, diffs, evidence, and rollback lineage.
10. Rollback produces a new Graph Version without rewriting prior releases.
11. Foreman remains visible, deterministic, and uneditable.
12. Non-admins cannot read prompts or mutate any graph configuration artifact.

## 19. Follow-up

The current product UI can add Genie, Vector Search, MCP, model endpoint, and Agent
Bricks tools to per-session `AgentConfig`. The agentic graph does not carry that config
into state or bind tools in `call_skill`; Data Analyst's grants are metadata only.

`tool_grants` remain code-owned legacy metadata, intentionally inert, and are neither
persisted in an Agent Definition nor editable in this workbench. The existing Data
Analyst `TOOLS AVAILABLE` prose has no runtime capability semantics; the workbench must
not render it as a grant or imply that `AgentRuntime` can bind it. Until the separate
tool-resolution project exists, tests assert that every Agent Definition invocation
receives no tools.

A separate project must define tool resolution, grant enforcement, Data Analyst
binding, toggles, and tests. This workbench neither solves nor obscures that gap.
