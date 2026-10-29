# Prompt shipping — design

**Date:** 2026-10-29
**Status:** agreed in conversation with the repo owner. Calls I made without the owner are listed under "Calls made without the owner".
**Ships before:** the scopes-and-consent work and Genie One in agent mode. Genie One's "Source: Genie One" slide note is an architect prompt change, and today a prompt change cannot reach an existing install.

## Why

Agent-mode prompts are not read from code. Each install keeps them in Lakebase as graph releases: one release maps every one of the seven model-driven agents to one immutable definition revision. Code seeds release v1 exactly once, on an empty database (`GraphConfiguration.bootstrap_v1`, `src/services/graph_configuration_bootstrap.py:58`). After that, the only way to change the live prompts is an admin draft and publish in the workbench, gated by approved smoke runs.

So prompt work merged to main never reaches an install that already has a release:

- The #351 architect prompt (edit operations) is in the packaged manifest (`src/services/agent_definition_manifest_v1.py`, written by `evals/harness/promote.py`). Prod is still on the release it bootstrapped before #351.
- A devloop fork copies prod's database, so it inherits prod's old release and never runs the branch's prompts either. Testing a prompt change on devloop means a manual workbench publish.
- Genie One needs the architect to add a source note to slides. Without this work, that note would appear only after an admin on each install republishes by hand.

The owner wants both: admins can still edit prompts in place without an update, and code can still push new prompts out.

## Goals

- When an install deploys a version whose packaged prompts differ from its live release, and nobody has changed the live graph by hand, the packaged prompts go live on startup. No admin step.
- When a person has changed the live graph, the packaged prompts are not applied. Admins see a badge on the agent definitions admin page saying a newer shipped version is available, and can adopt it from there.
- Restarting with the same code does nothing: no new release and no churn.
- Admin editing in the workbench works exactly as today.

## Non-goals

- Shipping one agent at a time. The unit is the whole graph release.
- Changing the graph's shape: roles, assembly rules, Graph Version 2. The packaged manifest stays a Graph Version 1 manifest, as `promote.py` writes it today.
- Shipping changes to the smoke-test catalogue (`graph_configuration_seed.py`).
- Moving conversations already pinned to an older release onto the new one. Pinned conversations keep their release; new conversations use the new active release. This is today's behaviour.
- Any notice beyond the badge, such as email or a banner for non-admins.
- Changing how developers produce prompts. Evals plus `promote.py` stay the way packaged prompts change.

## Anti-goals (failures even if it "works")

- Code replacing anything a person chose. That covers an edited prompt, a changed model setting, and a rollback.
- A release that mixes some shipped definitions with some older ones because shipping half-applied.
- The app failing to start because a prompt update could not be applied.
- A new release on every restart.

## Decisions made with the owner

1. **All or nothing, at graph level.** The unit of update is a whole graph release, never one agent. If any part of the live graph was changed by a person, nothing ships automatically.
2. **Code-shipped releases skip the smoke-run approval.** The prompts were evaluated before they were promoted into the manifest.
3. **Untouched installs update on deploy.** Prompts shipped in code go live without an admin step when nobody has changed the live graph.
4. **Edited installs get a badge.** A small "update available" badge on the agent definitions admin page says the shipped version is there.
5. **In-place editing stays.** The workbench draft/publish flow is unchanged.
6. **This is its own project,** built before scopes/consent and Genie One.

## How it works

### The rule

At startup, compare the active release's seven definitions with the packaged manifest's seven (`load_graph_v1_manifest()`), by `content_hash`.

- **All seven match:** do nothing.
- **They differ, and the live graph is untouched:** publish the packaged manifest as the next release.
- **They differ, and the live graph was touched:** insert the packaged definitions as revisions, but publish nothing. The rows exist, nothing goes live, and the badge shows (see below).

**Shipped content is always written as `system:code-ship`.** It doesn't matter whether startup or an admin's adopt writes the shipped revisions. `created_by` records where the content came from (the code), and the release's `published_by` records who made it live. This is what lets an install count as untouched again after an admin adopts.

**"Untouched" means both of these hold:**

- Every definition revision in the active release has a `created_by` that starts with `system:`. The bootstrap writes `system:bootstrap`, and this work writes `system:code-ship`. Revisions are deduplicated by `(agent_key, content_hash)` (`materialize_or_reuse_revision`), so a prompt that an admin edited and later set back to the shipped text counts as untouched. That is correct, because the content is the shipped content.
- The active release is not a rollback, meaning its `restored_from_release_id` is null. A rollback is a person's decision. Without this check, a rollback from shipped v3 to shipped v2 would be undone on the next restart, because v2's revisions are all system-created.

A model-setting change counts as an edit with no special handling. The model is part of `DefinitionContent`, so changing it creates a revision created by the admin.

**Known edge case:** an admin might type the exact text of a future shipped prompt by hand before that code ships. Deduplication then keeps the admin as that revision's creator, and the shipped version reuses the admin's revision. The install counts as touched and the badge shows. One adopt of the next shipped version clears it. It needs no special handling, because it costs at most one extra click and never overrides a human choice.

### Publishing a code-shipped release

Do it the way rollback does. `restore_release` (`src/services/graph_configuration_rollback.py`) is a thin caller of the publication core `_commit_locked_publication` (`src/services/graph_configuration_publication.py:483`), runs no approval gate, and makes no model or endpoint call. Code shipping does the same with the packaged contents:

- Use the same global lock order and the same single transaction, so a ship either lands complete or not at all.
- Use the same three-way draft rebase as rollback (`_draft_effect`): a pending admin edit is kept, a clean role whose content changes is reset, and a clean role with identical content is unchanged.
- Set `published_by` to `system:code-ship`. My call: the release note reads `Shipped with Tellr <databricks-tellr-app version>`.
- No evidence links and no smoke runs.
- No remote endpoint check, matching bootstrap v1.

### When it runs

It runs in `packages/databricks-tellr-app/databricks_tellr_app/run.py`, right after `bootstrap_graph_configuration`. That step already runs once, before the uvicorn workers fork, and already takes the bootstrap advisory lock. It runs on every startup: `tellr.update()`, an Apps redeploy, or a restart. On a fresh database, bootstrap seeds v1 from the current manifest and the comparison then finds everything matching, so nothing extra happens.

### The badge

The workbench snapshot (`GET /workbench`, `src/api/routes/agent_definitions.py:579`) gains a field saying whether a shipped version is available. "Available" means the packaged manifest differs from the active release, regardless of why it wasn't auto-applied. The field also lists the agents that differ.

The agent definitions admin page (`frontend/src/components/Admin/AgentDefinitionWorkbench/`) shows the badge while the field is set. The badge says why the update wasn't applied automatically: it names the hand-edited agents, says the live release is a rollback, or says the last ship attempt failed. From the badge, an admin can:

- **Review:** see a per-field diff of shipped vs live, reusing the release-comparison diff view (`frontend/src/components/Admin/GraphRelease/FieldDiffView.tsx`).
- **Adopt:** publish the shipped version as the next release through the same core as code shipping. This means no smoke runs and the three-way draft rebase, with `published_by` set to the admin.

Adoption publishes `system:code-ship` revisions. If the startup step didn't already insert them, adoption writes them with that creator itself. Afterwards the install counts as untouched again, and later shipped versions apply automatically. An admin who wants their own edits on top of the shipped version adopts first, then edits and publishes through the normal flow.

## Constraints

- Migration and bootstrap code runs only in `run.py` before the workers fork, never in workers. Four workers racing startup migrations once wedged boot.
- The global lock order in `graph_configuration_publication.py`'s module docstring applies. No model, runtime or network call is made while a lock is held.
- Integrity failures in bootstrap's `_validate_current_graph` stay fatal, as today.
- The release tables are immutable and SCD2-style (`effective_from`/`effective_to`). A ship is a new release, never an edit to an existing one.
- `PACKAGED_V1_CONTENT_HASHES` in `tests/unit/test_packaged_release_loader.py` and `tests/unit/test_graph_definition_manifest.py` pin the manifest; `promote.py` keeps them in step. Nothing here changes that.

## Calls made without the owner

1. **Rollbacks block auto-shipping.** This is needed so a rollback isn't silently reversed on the next restart. The badge still shows.
2. **The adopt action exists and skips smoke runs.** "A little badge" alone would leave an admin with no way to take the update except copying prompts by hand. Adopting publishes exactly the shipped content, which decision 2 already lets skip smoke runs.
3. **A failed ship does not stop startup.** The ship transaction rolls back, an error is logged, and the app starts on its current release. The badge then shows, because the manifest still differs. This is separate from bootstrap integrity failures, which stay fatal.
4. **The release note names the app version,** so release history shows where a release came from.
5. **"Untouched" is a check on who created each revision, not on its content.** You described it as "the same as the previous one in the codebase", which is a content check. An install has no record of every version code ever shipped, though, so a revision's creator is the nearest available equivalent. The two differ only in the edge case above. A true content check would need a new table of every hash ever shipped.
6. **Devloop gets branch prompts as a side effect.** A devloop fork of an untouched prod picks up the branch's packaged prompts on deploy. A fork of a prod that has been edited does not, and shows the badge.

## Left to the builder

- Where the comparison and ship code lives. A method on `GraphConfiguration` beside `bootstrap_v1` is the obvious place.
- The exact API field shape and the badge's look and wording.
- Whether the adopt endpoint shares a preview step with rollback's `preview_rollback`.
- Test layout. At minimum, cover these cases:
  - untouched → ships;
  - edited prompt → shipped revisions inserted as `system:code-ship`, no release, badge shown;
  - shipped text hand-applied by an admin earlier → badge shown, and the next adopt clears it;
  - edited model only → no ship;
  - rollback → no ship;
  - adopt → untouched again, next ship applies;
  - matching content → no-op;
  - restart idempotence;
  - pending draft edits are kept across a ship;
  - a failed ship leaves the active release unchanged and startup continues.
