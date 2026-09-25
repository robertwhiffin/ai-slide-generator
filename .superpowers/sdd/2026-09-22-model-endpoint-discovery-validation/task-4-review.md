# Task 4 review: typed discovery client and Model-tab endpoint controls (#266)

- Reviewer: independent task reviewer
- Range: `TASK_BASE=95b867c2c` .. `TASK_HEAD=aee017ca7`. Product commit: `b6c1ae2bd`. The worktree HEAD at review time was `1b08498f4`, which adds 7 lines to `progress.md` only (`git diff --stat aee017ca7 HEAD`).
- Read: `task-4-brief.md`, PLAN-CORRECTIONS C10, C15–C19 and C21–C23 (including the Task 4 pre-brief), the "Task 4" section of `progress.md`, `task-4-report.md`, and the full product diff for all 7 files.
- Blast radius also checked:
  - the server policy, `src/services/model_endpoint_catalog.py:81-103`;
  - the route and envelope, `src/api/routes/agent_definitions.py:129-138, 453-478`;
  - the schemas, `src/api/schemas/agent_definitions.py:448-478`;
  - `isPlainRecord`/`hasExactKeys` (`agentDefinitions.ts:352-361`);
  - the `AdminPage` mount (`AdminPage.tsx:208`);
  - `forbiddenActionNames.ts`.

## Spec Compliance: ✅ (with ⚠️ items)

| Requirement | Verdict | Evidence |
| --- | --- | --- |
| Exported client types and `getSystemModelEndpoints` | ✅ | `agentDefinitions.ts:877-990`. The interface, the two error classes and the function match the brief's signature. |
| Strict parser: exact top and item keys, primitive or null values, arrays and class instances rejected, JSON read once | ✅ | The parser reuses `isPlainRecord` (prototype check) and `hasExactKeys`. It rejects an empty name and duplicate names; this is stricter than the brief, but the server sorts unique workspace names and rejects blank ones (`model_endpoint_catalog.py:192-197`), so it is safe. It calls `response.json()` exactly once. |
| Valid 403/503 → `ModelEndpointCatalogApiError`; malformed 2xx → Invalid; anything else → error, never empty | ✅ | Each status is paired with exactly one code and one `retryable` value (`CATALOG_FAILURE_CONTRACT`), which matches `_catalog_failure_response` and the service's `(forbidden, False)` / `(unavailable, True)` pairs. An admin-denial 403 `{detail}` falls through to `AgentDefinitionApiError`. A 204 is Invalid. An unparseable 200 is Invalid. A transport failure propagates unchanged. All of these are tested. |
| No cache or coalesce; one GET per click; a freshness token drops out-of-order responses | ✅ | `useModelEndpointCatalog`, `AgentDefinitionWorkbench.tsx:39-72`. Mutations S06, S07 and S30 were RED, per the implementer. |
| C15: catalog stays out of `pendingSave`, `nextRequestIdRef` and `operationBlocked()` | ✅ | The hook imports nothing from `useDraftEditor` or the reducer. There is one reducer, one counter and one gate, unchanged. `catalogRequestTokenRef` is the permitted private freshness token. My mutation M2 (below) went RED. |
| C16: catalog owned once per workbench; first Model-tab opening of any role → one GET; only Refresh re-reads | ✅ | The hook is called in `WorkbenchContent`. `open()` fires only while the token is 0. `AdminPage` keeps the workbench mounted, so switching Admin tabs does not refetch. A test cycles 4 roles × Model/Prompt and still counts exactly 1 GET. |
| UI: Refresh models (always enabled), labelled search (local, case-insensitive), exact-name radios, separate Advanced "Custom endpoint name" | ✅ | `DefinitionEditor.tsx:405-477`. The radio's name is `item.name`; `display_name` and `description` are only its accessible description; `docs` is never rendered. |
| Selection is a setter only: exact `name`, numerics untouched, no PUT | ✅ | `onChange={() => onEdit(agentKey, 'endpoint_name', item.name)}`. The controller's sabotage and mine (M1) were both RED. |
| Empty copy, error with preserved endpoint and retry, last good list kept through loading and failure | ✅ | Exact empty string. Every error path ends in `role="alert"` and never shows the empty state. |
| Newer item never moves the seed until explicit select plus Save; same-content Save stays enabled | ✅ | Both are tested with an exact PUT body. |
| C18: local URL/path policy in `validateDraftForm`, mirroring C4 exactly; zero PUT | ✅ | `draftEditorState.ts:533-573`. I compared it with `_URL_PREFIX` and `_PATH_METACHARACTERS` (`[/\\?#%\x00-\x1f\x7f]`) and `_DOT_SEGMENTS`. Every clause matches, and the message is byte-identical. The `\s` and Unicode-case difference in the prefix regex cannot change a verdict, because any prefix match contains `/`. |
| C10: five-leaf body only on seed/v1 roles; serializer neither widened nor narrowed | ✅ | The only change to `validateDraftForm` is the new policy branch, which sits in the `else` of the blank check. Accepted candidates are byte-identical. Every five-leaf assertion uses Architect, a v1 seed role with no overlay. |
| Manual-entry success flow and 422 correction flow | ✅ ⚠️ | See Minor-3: the "no secret/provider payload" check is vacuous. |
| C17 harness migration | ✅ ⚠️ | See Minor-2. There is 0 of the old `name: 'Endpoint'` (grep across `src` and `tests`), no assertion was deleted, and the e2e default route sits beside the workbench route. |
| C19 text-read files and strict-JSON blocks untouched | ✅ | The `mocks.ts` diff has 0 removed lines; it adds one type import plus fixtures appended at the end. `CUSTOM_ANCHORS` is untouched. The Python joins give 270 passed. |
| Controller ruling: automated TS↔Python endpoint-policy join | ❌ (outstanding) | See Important-1. |

## Strengths

- The C15 and C16 structure is clean. The catalog is a plain read with a private token, owned once, and it does not touch the draft machinery at all. The "both directions" gate test is real: my M2 caught a subtle join that leaves the button enabled.
- The parser is genuinely strict. It checks prototypes, exact keys and pairs each status with its code and `retryable` value. An admin-denial 403 is correctly **not** typed as `catalog_forbidden`.
- Choosing radios is well justified: "checked" is exactly `local === name`, so a manual name checks nothing and re-clicking the seed makes no edit.
- The implementer's 31-row mutation table matches the diff everywhere I spot-checked (S11 and S30 match what I would have predicted). It also flagged its own over-rejection gap (concern 3), which I then ran as M3.
- Accessible-name hygiene:
  - The only exact-name locators are the new names.
  - "Custom endpoint name" is the only textbox containing "endpoint".
  - Search is a `searchbox`, not a textbox.
  - "Discovered models" is a `radiogroup`, so it avoids the `group`/`/^Custom block/` regexes.
  - The only other "Custom" names in the e2e spec (`/^Custom block…/`, `Custom blocks: …`) are anchored or group-scoped and cannot match `Custom endpoint name`.
  - Nothing matches `FORBIDDEN_ACTION_STEMS`: "Refresh models" was added to the spare list, and the fixture radio names are clean.

## Issues

### Critical

None.

### Important

**I-1. No automated TS↔Python endpoint-policy join** (controller ruling in `progress.md` Task 4).
- **Where:** `frontend/src/components/Admin/AgentDefinitionWorkbench/draftEditorState.ts:536-537` against `src/services/model_endpoint_catalog.py:81, 88, 89`.
- **What:** two hand-maintained copies of a security policy, with nothing tying them together.
- **Why it matters beyond style:**
  - The server backstops the client only in the *accept* direction.
  - In the *reject* direction the client is final. `validateDraftForm` disables Save and sends zero PUT, so a TS copy that drifts stricter makes legitimate names unsaveable, with no server involvement and no server-side test able to see it.
  - My M3 shows the TS tests catch one such drift (space). But a future server change, for example adding a character, would leave the TS tests green and the two copies silently diverged.
- **I agree with the ruling.**
- **Fix:** add a Python test in the `test_prompt_assembler.py` `_read_client` style.
  - It reads `draftEditorState.ts` as text and extracts the `ENDPOINT_URL_PREFIX` and `ENDPOINT_PATH_METACHARACTERS` literals and `ENDPOINT_URL_NOT_ALLOWED_MESSAGE`.
  - It asserts they are equivalent to `_URL_PREFIX.pattern`, `_PATH_METACHARACTERS` (the TS splits controls into `hasAsciiControlCharacter`), `_DOT_SEGMENTS` and the server message.
  - The most robust version drives a shared case table (the 15 reject and 7 accept cases already in the Vitest file) through `validate_endpoint_name_policy`, and asserts that the same table text appears in the TS test file.
  - Anchor the literals so the new text-read obeys C19: no reflow, and a unique `const NAME =` anchor.
  - This belongs in Task 4's fix round, per the ruling.

### Minor

**M-1. `retryable` is parsed but not used in the UI.**
- **Where:** `DefinitionEditor.tsx:427-429`, `AgentDefinitionWorkbench.tsx:22-29`.
- **What:** a `catalog_forbidden` (`retryable: false`) alert still ends "Use Refresh models to try again."
- **Why:** it misleads the user for a non-retryable permission failure. Refresh must stay enabled, which is correct, but the copy should differ.
- **Fix:** append the retry sentence only when the error is not a typed non-retryable one.

**M-2. The narrowed GET counts no longer count *every* GET.**
- **Where:** `AgentDefinitionWorkbench.test.tsx:855-856, 1142-1143, 1459-1460`. Previously these were a filter on `method === 'GET'`.
- **What:** the migration replaced "all GETs == 1" with "workbench GETs == 1 && catalog calls == 0". A GET to any third URL used to fail these tests and now would not.
- **Why:** today the client has only these two GET URLs (`agentDefinitions.ts:709, 976`), so nothing is lost now. But it is a latent weakening of #263's "no second read" assertions.
- **Fix:** keep both new assertions and add back `expect(allGets(fetchMock)).toHaveLength(1)`.

**M-3. The 422-correction flow's "no secret/provider payload" check is vacuous.**
- **Where:** `AgentDefinitionWorkbench.test.tsx`, test "binds a typed server endpoint issue…".
- **What:** it asserts only that the alert omits the entered endpoint. The fixture message is benign, and the client renders the server's `message` verbatim, so no provider or secret text could ever appear in this test.
- **Why:** sanitisation is really the server's job (the Task 1 table), so this is scope clarity, not a defect.
- **Fix:** either note in the test that sanitisation is server-owned, or add a server-side assertion in Task 6's matrix.

**M-4. `docs` values from the catalog are parsed and discarded without comment in the UI.**
- **What:** this is fine and intended (no links). Recording it only so Task 6 does not start rendering `docs` as a link without re-running the forbidden sweep.

## Sabotage evidence

Environment and cleanliness checks:
- `lsof -i :3000` was empty before and after, with exit 1 both times.
- The triple check (`git status --porcelain`, `git diff HEAD | wc -l`, `git diff --cached | wc -l`) was empty and 0/0 before and after every mutation.
- `node_modules` is the `issue-260-bootstrap` symlink. I installed nothing.

Scope for M1–M3: `(cd frontend && npx vitest run src/components/Admin/AgentDefinitionWorkbench/AgentDefinitionWorkbench.test.tsx)`. Baseline GREEN: **149/149**.

All three mutations used the same pin and restore steps:
- `PIN=1b08498f4c4dee5a1fb75ff1ffe072c665e2d9f7`.
- Each anchor count was 1 and each marker `grep -c` was 1.
- Each file was restored with `git checkout $PIN -- <file>`, after which the marker count was 0 and the triple check was empty.

| # | Target | File:line and mutation | RED | Failing tests | GREEN after restore |
| --- | --- | --- | --- | --- | --- |
| M1 | Plan reviewer target: autosave from selection | `DefinitionEditor.tsx:446`: `onChange={() => { onEdit(agentKey, 'endpoint_name', item.name); void onSave(agentKey); /* TASK4_REVIEWER_SELECTION_AUTOSAVE_SABOTAGE */ }}` | **3/149** | (1) "selection never saves: no PUT after the selection settles, and Save stays an explicit action" (the no-autosave test), (2) "selection copies exactly the item name into the endpoint form value and nothing else", (3) "a newer discovered item never moves the seed until it is explicitly selected and saved" | 149 (after M3) |
| M2 | Mine: catalog refresh joins the pending gate at the handler, with the button still enabled (distinct from the implementer's S11, which used `disabled=`) | `AgentDefinitionWorkbench.tsx:191`: `onRefreshModels={() => { if (!operationsDisabled) modelCatalog.refresh(); /* TASK4_REVIEWER_REFRESH_GATE_SABOTAGE */ }}` | **1/149** | "the catalog read stays outside the one pending gate in both directions" | **149/149** (final run) |
| M3 | Mine: local URL policy over-rejects a legitimate name with spaces | `draftEditorState.ts:537`: `/[/\\?#% ]/; // TASK4_REVIEWER_SPACE_OVERREJECT_SABOTAGE` | **4/149** | "accepts \"Team Shared Endpoint (EU)\" verbatim", "accepts \" leading and trailing \" verbatim", "saves a manual exact name as only the lock plus the five editable leaves and retains it", "binds a typed server endpoint issue to the custom field, keeps every unsaved value, and retries without remount" | covered by the final run |

After the last restore, `grep -rc TASK4_REVIEWER frontend/src` found no non-zero file, and the scoped suite was GREEN at 149/149.

Further gates, run at HEAD `1b08498f4`, which has the same tree as `aee017ca7` apart from `progress.md`:

| Gate | Result |
| --- | --- |
| `npm run test:unit` | 14 files, **407 passed** |
| `npm run typecheck` | exit 0 |
| ESLint on the 4 paths | exit 0 |
| `npx playwright test tests/e2e/agent-definition-workbench.spec.ts --project=chromium --workers=1` | **60 passed**, port 3000 free afterwards |
| `PYTHONPATH=<wt>:<wt>/packages/databricks-tellr …/python -m pytest -q -p no:randomly tests/unit/test_prompt_assembler.py tests/unit/test_agent_definition_workbench_routes.py` | **270 passed**, 10 warnings (pre-existing Pydantic and langchain causes). There is no `.venv`. |

Final tree: `git status --porcelain` is empty; this review file sits under the git-ignored `.superpowers/`. There is no tracked diff, nothing is staged, and no marker remains.

## Task quality: Needs fixes

The only blocking item is I-1, the TS↔Python policy join ordered by the controller. M-1 and M-2 are cheap and worth folding into the same fix round. M-3 and M-4 are notes.
