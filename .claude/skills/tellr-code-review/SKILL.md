---
name: tellr-code-review
description: Tellr-specific code-review checklist capturing tribal knowledge — recurring bug classes and fragile subsystems a reviewer should actively check. Load when reviewing a Tellr diff/PR, or when asked to review Tellr changes. Currently covers (1) multi-worker in-process state coherence and (2) the huashu PPTX-export bundling chain.
---

# Tellr code-review checklist (tribal knowledge)

These are Tellr-specific things that generic review misses. They are not
style rules — each one is a class of bug that has actually shipped and hurt.
When reviewing a diff, check whether it touches any of these areas and, if
so, apply the corresponding check. If a diff touches none of them, this skill
adds nothing — don't force it.

---

## 1. Multi-worker in-process state must be coherent with the database

**Why this exists.** Prod runs `uvicorn` with multiple worker *processes*
(`UVICORN_WORKERS`, default 4 — see
`packages/databricks-tellr-app/databricks_tellr_app/run.py`). Each worker is a
separate OS process with **separate memory**. Anything stored in a Python
attribute/dict/global lives in *one* worker only; the other workers never see
it. Requests are load-balanced across workers, so successive requests in the
same session routinely hit different workers.

**The recurring bug.** State cached in process memory goes stale on every
worker except the one that last wrote it. This has shipped repeatedly:
- `ChatService._deck_cache` served stale decks → reorder returned
  `400 Invalid reorder: wrong number of indices`, deleted slides reappeared
  after an LLM edit, and inserts landed at the wrong index. Fixed by
  version-checking the cache against the DB (`_get_or_load_deck` +
  `SessionManager.get_slide_deck_version`).
- Session locks — fixed earlier by moving them to the **database**
  (`session_manager.py` acquire_session_lock is DB-backed "to work across
  multiple uvicorn workers").
- MCP — fixed by running **stateless** ("survive multi-worker routing").

**The rule.** Any state shared *across requests* must either live somewhere
all workers can see (the database) or be a cache that can **detect its own
staleness**. In-process memory that is written by one request and read by a
later request, with no freshness check, is a bug under multiple workers.

**What to flag in review.** Raise a concern when a diff:
- adds or mutates a process-lifetime container on a service/singleton
  (`self._something = {}` / module-level dict/set/list) that holds
  per-session or per-deck state across requests;
- reads such a cache on a mutation path without validating it against the DB
  (e.g. a bare cache-hit return with no version/timestamp comparison);
- introduces a new "read cache → mutate → write back to DB" flow. Writing a
  stale cached object back to the DB is how deleted data resurrects.
- assumes a value written during one request will be visible to a later
  request in the same session (it won't, unless it round-trips the DB).

Cache-as-cache (rebuildable from the DB, validated on hit) is fine. Cache-as-
source-of-truth is not. When unsure, ask: "if request A hits worker 1 and
request B hits worker 2, do they still agree?" If the diff can't answer yes,
flag it.

**Guard pattern.** New cross-request caches should have a coherence test in
the style of `tests/unit/test_multiworker_cache_coherence.py`: two service
instances sharing one store, mutate via A, assert B's view matches the store.

---

## 2. The huashu PPTX-export bundling chain must not be silently broken

**Why this exists.** The HTML→PPTX export ("huashu", from
`alchaincyf/huashu-design`'s `html2pptx.js`) lives in
`services/pptx-emit-huashu/` and runs Playwright/Chromium. That can't be built
in CI (npm's "Exit handler never called!" bug) or shipped uncompressed (size
limits), so the pipeline depends on a fragile, easy-to-break bundling chain:

1. **Pre-built tarballs committed to git**:
   `services/pptx-emit-huashu/node_modules.tar.gz` (~12 MB) and
   `sys-libs-bullseye.tar.gz` (~18 MB). These are committed on purpose, *not*
   built in CI. Regen instructions live in the header comment of
   `services/pptx-emit-huashu/build-artifacts.sh`.
2. **Verify step** (`build-artifacts.sh`) runs in `publish.yml` /
   `publish-dev.yml` before `python -m build`: checks the tarballs exist, are
   >1 MB (not truncated/dir-only), and contain `playwright*/cli.js`.
3. **setup.py copies the sidecar into the wheel** at
   `databricks_tellr_app/_assets/sidecars/pptx-emit-huashu/`, but **only when
   `TELLR_INCLUDE_HUASHU_SIDECAR=1`** (the deployed-app path via CI; local
   `deploy_local` deliberately omits it because the tarballs exceed Apps
   workspace file limits).
4. **CI post-build verify**: the publish workflows assert the built wheel is
   ≥25 MB and contains the huashu tarballs, failing the release otherwise.
5. **`.databricksignore`** excludes the bulky uncompressed
   `services/pptx-emit-huashu/node_modules/` and `playwright-browsers/` from
   `deploy_local` uploads.

**What to flag in review.** Raise a concern when a diff touches any link in
this chain in a way that could break it silently:
- edits `services/pptx-emit-huashu/package.json` (Playwright/pptxgenjs
  version bumps) **without** regenerating and committing fresh
  `node_modules.tar.gz` / `sys-libs-bullseye.tar.gz`. A version bump with
  stale tarballs ships a mismatched pipeline.
- weakens or removes the `build-artifacts.sh` verification, the
  `TELLR_INCLUDE_HUASHU_SIDECAR` gate, the setup.py copy step, or the CI
  wheel-size / tarball-presence assertion (the ≥25 MB check exists to catch a
  wheel built without the sidecar).
- changes `.databricksignore` or setup.py `_SIDECAR_IGNORE` such that the
  uncompressed trees start getting uploaded (blows Apps file limits) or the
  tarballs stop being included (breaks deployed export).
- moves/renames `services/pptx-emit-huashu/` files without updating the
  references in `setup.py`, the publish workflows, and `.databricksignore`.

**Rule of thumb.** If a change touches `services/pptx-emit-huashu/` or the
packaging around it, confirm the whole chain still holds: committed tarballs
match `package.json`, the verify + include gates are intact, and CI would
still fail on a sidecar-less wheel. When in doubt, check whether the tarballs
were regenerated alongside a dependency bump.
