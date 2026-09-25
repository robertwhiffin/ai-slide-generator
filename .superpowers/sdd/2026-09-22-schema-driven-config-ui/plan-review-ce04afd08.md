# Plan review — issue #264 at `ce04afd08`

## Verdict

**CHANGES_REQUIRED**

Finding count: **1 Critical, 3 Important, 1 Minor**.

The requested file `docs/superpowers/plans/2026-09-22-schema-driven-config-ui.md`
does not exist at `ce04afd0820189e4f63fa7103be16900a5fa968d`. The issue-264 plan
actually changed by that commit, and reviewed here, is
`docs/superpowers/plans/2026-09-22-safe-output-schema-overlays.md`.

I re-probed GitHub issues #258, #264, and #265 on 2026-09-22. I also re-probed
the local refs rather than relying on plan prose: `feat/langgraph-core` is still
`774703e4487877bf65e0eeff173892d3e00ceac5`, contains reviewed #260, and does
not contain current #261 (`439971b3448fd6d0d64a9993305da47193754a56`) or
current #263 (`771910ca1045d165a54e794f48fd4f0c206e4fa7`). The plan's hard
local-integration gate is therefore necessary and correctly prevents Tasks 2–7
from starting against today's root branch. The #265 plan reviewed for shared
ownership/order was `plan/prompt-assembly-265` at
`ae3d09f3437eb9ce45a6ac52c992c03a3a00c6ca`.

## Critical

### C1. The planned save/error wire contract contradicts both landed #263 and corrected #265

The plan declares a #263 `invalid_definition` envelope, error entries shaped as
`{path, code, message}`, and paths beginning `schema_overlay...`
(`docs/superpowers/plans/2026-09-22-safe-output-schema-overlays.md:42`). Task 5
then requires both routes to emit that invented envelope
(`docs/superpowers/plans/2026-09-22-safe-output-schema-overlays.md:96-100`), and
Task 6 builds the client/tests on the same unprefixed request path
(`docs/superpowers/plans/2026-09-22-safe-output-schema-overlays.md:107-112`).

The actual #263 contract is different:

- `feat/shared-graph-draft-editor-263:src/api/routes/agent_definitions.py:66-70`
  emits `code="invalid_draft"`.
- `feat/shared-graph-draft-editor-263:src/api/schemas/agent_definitions.py:218-220`
  puts editable content under `candidate`.
- `feat/shared-graph-draft-editor-263:src/api/schemas/agent_definitions.py:229-237`
  names the error location property `field`, not `path`.
- `feat/shared-graph-draft-editor-263:frontend/src/components/Admin/AgentDefinitionWorkbench/useDraftEditor.ts:53-57`
  sends `{lock_version, candidate}`.
- `feat/shared-graph-draft-editor-263:frontend/src/components/Admin/AgentDefinitionWorkbench/draftEditorState.ts:205-218`
  consumes `item.field` with `candidate.*` locations.

The corrected #265 plan deliberately preserves this contract: its stable error
table uses `candidate.assembly_rules...` fields and its exact envelope is
`{"code":"invalid_draft","errors":[...]}`
(`plan/prompt-assembly-265:docs/superpowers/plans/2026-09-22-declarative-prompt-assembly.md:138-155`).

Following #264 as written would either break the existing #263/#265 parser and
reducer or create a second incompatible error convention in the same aggregate.
Correct the plan to preserve `invalid_draft`, `{field, code, message}`, and
`candidate.schema_overlay...` for editable-save errors. Define the schema-upgrade
route's 422/409 bodies explicitly in that same established family, including the
ordered multi-error and seven-role stale snapshot contracts.

## Important

### I1. Task 1 is dispatched before the mandatory corrections pre-pass exists

The plan calls Task 1 the only pre-integration task
(`docs/superpowers/plans/2026-09-22-safe-output-schema-overlays.md:15`) and does
not run the SDD corrections pre-pass until before Task 2
(`docs/superpowers/plans/2026-09-22-safe-output-schema-overlays.md:24-32`). This
also contradicts its own requirement to attach `PLAN-CORRECTIONS.md` to every
implementer and reviewer brief (`:24`), because Task 1 and its reviewer run
before that file is created.

The loaded Tellr skill requires a corrections file before dispatching anything
(`/Users/robert.whiffin/.codex/skills/executing-plans-tellr/SKILL.md:41-45`), and
the SDD skill requires the per-task and pairwise producer/consumer table before
Task 1
(`/Users/robert.whiffin/.codex/plugins/cache/isaac-sync-claude-plugins-official/superpowers/6.3.0/skills/subagent-driven-development/SKILL.md:162-181`).

Keep Task 1 collision-free and pre-integration, but add a Task 0 that performs
the Task-1-relevant scan/cause baseline against the reviewed #260 base before
Task 1. Refresh and expand that same corrections file against the concrete
#260+#261+#263+#265 integration commit immediately before Task 2.

### I2. The plan explicitly defers a #264 acceptance criterion and leaves output-validation trace ordering unsafe

Issue #264 requires overlay values to be preserved in diagnostics **and traces**.
The binding design says the canonical and optional portions are serialized into
diagnostics, test output, and traces
(`docs/superpowers/specs/2026-09-21-agent-definition-workbench-design.md:382-388`).
The plan instead limits this slice to
`AgentInvocationDiagnostics.additional_fields` and defers trace serialization to
a future sink (`docs/superpowers/plans/2026-09-22-safe-output-schema-overlays.md:119`).
That cannot close #264 as specified.

There is already a concrete tracing boundary to extend: #261's
`AgentInvocationIdentitySink` wraps the model callback
(`feat/conversation-pins-runtime-261:src/services/agent_runtime_identity.py:21-26`),
and its logging implementation records success as soon as that callback returns
(`feat/conversation-pins-runtime-261:src/services/agent_runtime_identity.py:47-75`).
The current runtime calls that sink before constructing diagnostics
(`feat/conversation-pins-runtime-261:src/services/agent_runtime.py:634-663`). The
#264 Task 3 text says to validate the adapter result, but does not require
`validate_output` to run inside the wrapped callback or test what the sink
observes on invalid canonical/optional output
(`docs/superpowers/plans/2026-09-22-safe-output-schema-overlays.md:72-77`). An
implementation following that order can log a successful invocation and only
then reject its output contract.

Add the trace boundary to this plan (or obtain an explicit issue/spec scope
change). Require output validation/projection to complete inside the sink's
success boundary, trace the frozen allowlisted `additional_fields` on success,
and test both recording and logging sinks: invalid canonical/optional output is
observed as an error, while successful absent/null/empty-list values retain their
distinct trace representation.

### I3. The exact verification commands do not select the declared environments

The global constraint names `/Users/robert.whiffin/.pyenv/shims/python`, but all
backend task commands invoke bare `python`
(`docs/superpowers/plans/2026-09-22-safe-output-schema-overlays.md:18,51,63,75,87,99,117`).
There is no `command -v` assertion or PATH setup making those equivalent. The
corrected #265 plan uses the absolute interpreter throughout, which is important
in this repository's shared-pyenv environment.

The browser command is also rooted incorrectly:
`npx playwright test frontend/tests/e2e/agent-definition-workbench.spec.ts`
(`docs/superpowers/plans/2026-09-22-safe-output-schema-overlays.md:112`). The
repository root has neither `package.json` nor `playwright.config.ts`; both the
dependency and config live under `frontend/` (`frontend/package.json:1-21`,
`frontend/playwright.config.ts:1-6`). Corrected #265 accordingly runs from
`frontend` and addresses the test as `tests/e2e/...`.

Replace every backend invocation with the absolute pyenv interpreter and add
`test ! -e .venv` at the gates. Run Playwright as
`(cd frontend && npx playwright test tests/e2e/agent-definition-workbench.spec.ts --project=chromium --workers=1)`
(or an explicitly equivalent checked-in script). This avoids `npx` attempting a
root-level package resolution/install, which execution is forbidden to perform.

## Minor

### M1. One named specification input is not available in the review/execution worktree

The plan names `.superpowers/issue-264-optional-catalog-ruling.md` from the #260
worktree as a specification source
(`docs/superpowers/plans/2026-09-22-safe-output-schema-overlays.md:11`), but that
file is neither present at `ce04afd08` nor tracked in this worktree. The plan does
embed the apparent ruling's exact catalog strings and examples at `:20` and
`:40`, so this is not currently load-bearing. Still, execution cannot independently
verify the cited source. Check the ruling into a durable docs/spec location or
remove the unreachable citation and state that the embedded literals are the
authoritative decision.

## Areas otherwise sound

- The local dependency order #265 → #264 → #266 matches corrected #265, and the
  current `feat/langgraph-core` ancestry check correctly blocks premature shared
  integration.
- Task 1's new-file-only boundary is compatible with the #260 tree and can survive
  the later rebase without shared-file conflicts.
- Tasks 2–6 identify the right broad owners after #265, preserve #261's exact
  four-argument runtime and persisted loader, reuse #263's one locked writer and
  #265's aggregate frontend controller, and forbid a second writer/state machine.
- The plan requires cause-based baselines, exact-base review packages, distinct
  controller/reviewer sabotage targets, PostgreSQL execution without skips, and a
  most-capable whole-branch review with no-write/writer comparison evidence.

No implementation tests were run: this was a read-only plan/code/interface review,
and the review contract forbade `uv`, dependency installation, and implementation
changes.
