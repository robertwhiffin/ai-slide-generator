---
name: release-tellr
description: Use when cutting a final Tellr release (vX.Y.Z) to PyPI. Picks the version, drafts the "What's new in Tellr" popup wording from the PRs merged since the last tag, gets the owner's approval in the terminal, opens and merges the version-bump PR, and pushes the tag that publishes both packages. Stops at the PyPI publish. Not for dev builds (.devN), which use deploy-tellr-dev. Triggers on "cut a release", "new release", "release tellr", "publish to PyPI", "bump the version".
---

# Cutting a Tellr release

## Why this exists (read first)

**Pushing a `v<X.Y.Z>` tag publishes to PyPI at once.** `.github/workflows/publish.yml` runs on
the tag push, and its `pypi` environment has **no approval rule**. A published version cannot be
replaced, only yanked. So the only gates are the ones in this skill: the owner's approval of the
wording, and the owner's go-ahead before the merge and tag.

Each release also ships its "What's new in Tellr" popup notes: one file per version at
`frontend/src/whatsNew/releases/<version>.json` (format in that folder's `README.md`). The words
come from the PRs merged since the last tag. The owner approves them in the terminal before any
file is written. `publish.yml`'s validate job runs `scripts/check_release_notes.py` and refuses a
tag whose notes file is missing or malformed, before anything is built or uploaded.

**Approval and go-ahead come only from the owner's own message in this terminal.** A message from
another agent is not approval. If you are a subagent, do Steps 1–4, hand the preview and both
tables to your caller, and stop.

Steps 1–4 write no files and push nothing. Run them from whatever worktree you are in. Nothing
is written, branched or pushed until the owner approves in Step 4.

## The release

### 1. Account and version

```bash
gh auth status
gh api user --jq .login        # must print robertwhiffin
```

If it prints anything else (the EMU account is `robert-whiffin_data`), switch, then re-check:

```bash
gh auth switch --hostname github.com --user robertwhiffin
```

Find the last final release and what `main` says now:

```bash
git fetch origin --tags
git tag --list 'v*' --sort=-v:refname | grep -E '^v[0-9]+\.[0-9]+\.[0-9]+$' | head -3
git log -1 --format='%H %s' origin/main
git show origin/main:packages/databricks-tellr/pyproject.toml | grep '^version'
git show origin/main:packages/databricks-tellr-app/pyproject.toml | grep '^version'
```

- The last final tag is the newest `vX.Y.Z`. Ignore anything else (`ds-v1-checkpoint` is not a
  version).
- Write down the `origin/main` SHA in full. Steps 5 and 6 check that `main` has not moved since.
- Both pyprojects must say the last tag's version. If they don't, stop and tell the owner.
- **Propose last + one patch** (after `v0.5.6`, propose `0.5.7`). That is the dev line:
  `publish-dev.yml` builds `<highest final + one patch>.devN`, so it matches the builds people
  have been testing. The owner sometimes picks a minor bump instead (`0.5.0`, for example).

Ask the owner to confirm the version, and wait for the answer. If they named a version in their
request, state it back anyway.

### 2. PRs since the last tag

```bash
git log --first-parent --format='%H %s' <last-tag>..origin/main
```

- `Merge pull request #N from …` is PR N.
- A subject ending in `(#N)` is a squash-merged PR N.
- Anything else is a **direct commit**. Read it with `git show --stat <sha>`, judge it like a
  PR, and list it to the owner as `direct commit <short sha>`.
- A PR merged into another PR's branch (stacked) is not on this list, because it shipped inside
  that PR's merge. Find those with
  `git log --merges --format='%H %s' '<merge sha>^1..<merge sha>^2' | grep 'Merge pull request'`
  and fold them into the parent's bullet.

The previous release's bump PR is not in the range, because the last tag sits on its merge commit.

Read every PR, one call each:

```bash
gh pr view <N> --json number,title,body
```

Don't loop over the numbers: the worktree guard refuses `gh` and `git` inside a `for` loop or
`$(…)`. When the body doesn't make clear what changed for users, look at the files:
`gh pr diff <N> --name-only`.

If there are no PRs and no direct commits, tell the owner there is nothing to release and stop.

### 3. Draft the wording

Apply these rules to each PR (and direct commit):

1. **It has a `## What's new` section.** Use it as written. `None` (any case, with or without a
   reason after it) means leave it out. A section that is empty, or holds only the template's
   HTML comment, counts as absent: go to rule 2. Fix only the format (rule 6). If the wording
   breaks rule 4, rewrite it and say so in the "Included" table.
2. **It has no section.** Judge from the title and body whether a Tellr user would notice the
   change. They notice it if they can now do something new, something they do looks or works
   differently, a bug they would have hit in the last release is gone, or an action is
   noticeably faster. Admins are users: write admin-only features as "Admins can …".
3. **Leave out** CI, tests, refactors, developer docs and tooling, dependency bumps, logging and
   telemetry, and fixes nobody would see. Every PR you leave out goes in the "Left out" table
   with a one-line reason.
4. **Write for users.** Plain language, in the names the app's own screens use (Agent mode, the
   Image Library, the Admin tabs). No internal terms: no "fence", "seal", "SP" or "service
   principal", "migration", PR numbers, CI, branch names, file paths, table or endpoint names, or
   internal component names.
5. **One bullet per user-facing feature.** Several PRs that make up one feature for the user
   (a feature plus its follow-up fixes) become one bullet. A follow-up fix to a feature that is
   new in this release is not a bullet of its own: list it under that feature's bullet in the
   "Included" table. Put the most noticeable bullet first.
6. **Format.** A title of a few words, sentence case, with **no trailing period**. A body of one
   sentence that ends with a period. Titles must differ within a release.
7. **Nothing user-facing** is a valid outcome. Propose an empty list, and say that this release
   adds nothing to the popup.

A PR section bullet `- **Faster deck opening.** Large decks open in seconds.` becomes
`{ "title": "Faster deck opening", "body": "Large decks open in seconds." }`. The popup adds the
period after the title itself.

Examples, from 0.5.3:

| PR | Draft | Why |
|---|---|---|
| #366 perf: deck open downloads the deck once, without html_content, gzipped | **Faster deck opening.** Large decks now open in a few seconds instead of half a minute. | The user sees the speed, not the payload. |
| #363 feat(architect): a short starter deck instead of 14 to 20 slides | **Shorter first drafts.** New decks start with 5–8 slides plus ideas for what to add next. | No "architect", no prompt talk. |
| #361 ci: run tests alongside unit tests, shard E2E into six jobs, … | Left out: CI only. | |
| #365 fix(spec-sync): stop retrying the arc review of a deck with no graph pin | Left out: stops a log flood nobody saw. | |

While reading each PR, also note anything an operator must do after deploying: migrations, new
settings, an admin Adopt, a `tellr.update` requirement, rollback limits. These go in the bump PR
body (Step 5), never in the popup.

### 4. Approval in the terminal

Print the popup exactly as users will read it. Take the month from today's UTC date
(`date -u +%F`, shown as "November 2026"):

```
What's new in Tellr
Highlights from each release

<version>  [New]  <Month YYYY>
- **<Title>.** <Body>
- **<Title>.** <Body>
```

Write the bullets as markdown, so the titles show in bold. For an empty release, print
`(no entry in the popup for <version>)` instead of the bullets.

Then two tables, so the owner can see nothing was missed. Every PR and direct commit from Step 2
appears in exactly one of them:

- **Left out**: PR, title, and a one-line reason.
- **Included**: each bullet's title, and the PRs it came from. Note any section wording you
  rewrote.

```
Left out
| PR | Title | Reason |
|---|---|---|
| #361 | ci: run tests alongside unit tests, shard E2E into six jobs, … | CI only |
| direct commit 1a2b3c4 | <its subject> | developer docs |

Included
| Bullet | From |
|---|---|
| Faster deck opening | #366 |
```

Ask:

> Approve this wording? On approval I write the notes file, bump both versions, push
> `release/v<version>` and open the bump PR. Nothing merges, tags or publishes until you give a
> separate go-ahead.

Wait. If the owner edits anything, apply the edits and print the whole preview and both tables
again. Repeat until the owner explicitly approves. "Looks fine apart from X" is an edit, not an
approval. Use the owner's wording as given. If their title ends with a period, drop the period
and say so.

**Write nothing before approval:** no notes file, no worktree, no branch.

### 5. Bump PR

Check that `main` has not moved since Step 2:

```bash
git fetch origin
git log --oneline <main sha>..origin/main      # must print nothing
```

If it prints commits, those PRs would ship without being in the notes. Go back to Step 2 for
them, and get the owner's approval again.

Create the release worktree on that exact commit. In Claude Code, call **EnterWorktree** with
name `release-v<version>`, then rename its branch. Without EnterWorktree, use `git worktree add`
with an absolute path under the primary checkout, and `cd` into it:

```bash
git branch -m release/v<version>               # after EnterWorktree
git worktree add -b release/v<version> <primary checkout>/.claude/worktrees/release-v<version> <main sha>   # without it
git log -1 --format='%H %s'                    # in the new worktree; must print <main sha>
```

Run the rest of this step from the new worktree's root. Install the frontend's dependencies,
because a new worktree has no `node_modules`:

```bash
(cd frontend && npm ci)
```

Write `frontend/src/whatsNew/releases/<version>.json` with the approved items, in the approved
order. `date` is today in UTC (`date -u +%F`). Escape any double quote inside a string as `\"`.

```json
{
  "version": "<version>",
  "date": "<YYYY-MM-DD>",
  "items": [
    { "title": "<Title>", "body": "<Body>" }
  ]
}
```

Check it. Both must pass:

```bash
python3 scripts/check_release_notes.py <version>      # prints: What's new notes OK for <version>
(cd frontend && npx vitest run src/whatsNew)
```

Bump `version = "<last>"` to `version = "<version>"` in both pyprojects (line 7 of each). Nothing
else in the repo references the version.

```bash
grep -n '^version' packages/databricks-tellr/pyproject.toml packages/databricks-tellr-app/pyproject.toml
git status --short                             # exactly these three files
```

Commit the three files by name. End the message with any attribution trailer your session
requires:

```bash
git add frontend/src/whatsNew/releases/<version>.json packages/databricks-tellr/pyproject.toml packages/databricks-tellr-app/pyproject.toml
git commit -m "chore(release): bump to <version>"
```

Write the PR body to a file outside the repo, e.g. `/tmp/tellr-release-v<version>-pr.md`. Keep
the shape of past bump PRs (#367). The "adds" list has one line per PR from Step 2, left-out ones
included (for example "#361: CI only."):

```markdown
Bumps `databricks-tellr` and `databricks-tellr-app` from <last> to <version>. Once this is merged, the `v<version>` tag on the merge commit publishes both packages to PyPI.

What <version> adds over <last>:
- #N: <one line, for engineers>.

## What's new

The approved wording for the in-app popup, from `frontend/src/whatsNew/releases/<version>.json`:

- **<Title>.** <Body>

**After deploying:**
- <migrations, settings, Adopt steps, rollback limits, each with its PR number>, or
  "Nothing to do: no migrations, no new settings, nothing to Adopt."
```

End the body with any attribution line your session requires.

The Step 4 approval covers this push, because the question named it. If anything has changed
since (main moved, or you edited the wording after a failed check), ask the owner again first.

```bash
gh api user --jq .login                        # robertwhiffin
git push -u origin release/v<version>          # the pre-push hook takes ~3 min
gh pr create --base main --head release/v<version> \
    --title "chore(release): bump to <version>" --body-file /tmp/tellr-release-v<version>-pr.md
```

Note the PR number from the URL it prints.

**Wait for CI to go green.** The bump PR touches `frontend/**`, so the frontend build, the
frontend unit tests and all six E2E shards run. That includes the first real run of
`frontend/tests/e2e/whats-new.spec.ts`, which skips until a notes file exists. CI takes 20 minutes
or more, so run the watch in the background:

```bash
gh pr checks <n> --watch --interval 60
```

Then confirm that the What's new spec ran rather than skipped. It is in shard 3 today; if the
grep prints nothing, find its shard in the E2E matrix in `.github/workflows/test.yml`:

```bash
gh run list --workflow test.yml --branch release/v<version> --limit 1 --json databaseId,headSha
gh run view <run id> --log | grep 'E2E - shard 3' | sed -n '/group\]E2E whats-new/,/endgroup/p' | grep -E 'Running [0-9]+ test|[0-9]+ (passed|skipped|failed|flaky)'
```

You want `N passed` and no `skipped`, on the run whose `headSha` is your commit. If any check
fails, stop and tell the owner. Don't merge around it. A failure in the What's new spec is a real
defect in the popup or the notes.

### 6. Merge, tag, watch

Check everything before you ask:

```bash
gh api user --jq .login                        # robertwhiffin
gh pr checks <n>                               # every check pass or skipping, none failing or pending
git fetch origin
git log --oneline <main sha>..origin/main      # still nothing
gh pr view <n> --json headRefOid               # the full head SHA
git log -1 --format=%H                         # in the release worktree; must equal headRefOid
```

Ask:

> CI is green on #<n>. Merge it, tag `v<version>` on the merge commit, and push the tag? The tag
> push publishes <version> to PyPI at once, and it can't be undone.

Wait for an explicit yes. If the owner approves only the merge, merge, then ask again before
tagging.

Merge, typing the full head SHA from `headRefOid` literally:

```bash
gh pr merge <n> --merge --match-head-commit <full head sha>
```

If the harness refuses the merge ("Merge Without Review"), ask the owner to run that exact
command themselves as `! gh pr merge <n> --merge --match-head-commit <full head sha>`, then carry
on.

Find the merge commit and check what you are about to tag:

```bash
gh pr view <n> --json state,mergeCommit        # state MERGED; mergeCommit.oid is <merge sha>
git fetch origin
git log -1 --format='%H %s' <merge sha>        # Merge pull request #<n> from robertwhiffin/release/v<version>
git show <merge sha>:packages/databricks-tellr/pyproject.toml | grep '^version'
git show <merge sha>:packages/databricks-tellr-app/pyproject.toml | grep '^version'
git show <merge sha>:frontend/src/whatsNew/releases/<version>.json
git ls-remote --tags origin v<version>         # must print nothing
```

Both versions must be `<version>`, and the notes must be the approved ones. If anything is off,
stop and tell the owner. Don't tag.

Tag and push:

```bash
git tag -a v<version> -m v<version> <merge sha>
git cat-file -t v<version>                     # tag (annotated)
git rev-parse 'v<version>^{commit}'            # <merge sha>
gh api user --jq .login                        # robertwhiffin
git push origin v<version>                     # THIS PUBLISHES. Pre-push hook ~3 min
```

Watch the publish run. It can take a few seconds to appear, and over 10 minutes to finish, so
run the watch in the background:

```bash
gh run list --workflow publish.yml --limit 3 --json databaseId,headBranch,status,conclusion
gh run watch <run id> --exit-status            # the run whose headBranch is v<version>
gh run view <run id> --log | grep -E -A1 'Uploading|View at'
```

Quote the `Uploading` lines as the evidence. There are four files:
`databricks_tellr-<version>-py3-none-any.whl`, `databricks_tellr-<version>.tar.gz`,
`databricks_tellr_app-<version>-py3-none-any.whl` and `databricks_tellr_app-<version>.tar.gz`,
plus a `View at:` link for each package.

If the run fails, stop and tell the owner which job failed. Don't re-run it, move the tag or
delete it yourself. A failure in `validate` or `build` published nothing. A failure in one
publish job can leave one package published and the other not.

### 7. Stop

The skill stops at the PyPI publish. Tell the owner the version, the tag's commit, the publish
run URL and the four uploaded files, and that the dev line is now `<version + one patch>.devN`.
Then list what this skill did **not** do, so nobody assumes it was covered:

- `tellr.update` on logfood and prod, and the admin checks after it;
- any admin Adopt the release needs (from the bump PR's "After deploying" notes);
- syncing the tag to the internal `databricks-industry-solutions/databricks-tellr` repo.

Don't create a GitHub Release: the repo has never used them. Remove the release worktree when
you're done.

## Gotchas

| Gotcha | What to do |
|---|---|
| The tag push alone publishes. There's no approval gate, and a publish can't be undone. | Push a tag only after the Step 6 go-ahead, and only after checking the merge commit. |
| The `gh` active account can flip to EMU (`robert-whiffin_data`), for example when a peer session switches it. | Run `gh api user --jq .login` before every push, merge and tag push. Switch with `gh auth switch --hostname github.com --user robertwhiffin`. |
| The global pre-push hook takes about 3 minutes, on both the branch push and the tag push. | It isn't hung. Give the command a 10-minute timeout, and don't interrupt it. |
| In a worktree-isolated session, `git` and `gh` inside `$(…)` or a `for` loop are refused. | Run each command on its own, and type full SHAs literally (for example in `--match-head-commit`). |
| PyPI's JSON API may not answer from the laptop. | The publish run's `Uploading` lines are the evidence. Don't poll pypi.org. |
| `main` can move between drafting and merging. | Re-check `git log --oneline <main sha>..origin/main` before branching and before merging. New commits mean new PRs to draft. |
| The harness can refuse `gh pr merge` on an unreviewed PR. | Ask the owner to run the exact command as `! gh pr merge …`. |
| The bump PR now runs the frontend suites and E2E, which bump PRs used to skip. | Wait for green. The What's new E2E spec runs for real for the first time on it. |
| Old tags include `ds-v1-checkpoint`. | Only `vX.Y.Z` tags are releases. Filter them as in Step 1. |
| Notes files are only written by this skill, after approval. | Never write or edit one by hand, or outside Step 5. The publish guard refuses a tag without one. |
