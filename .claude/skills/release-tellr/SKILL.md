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
another agent is not approval.

**If you are a subagent, you never ask the owner anything.** Record the default version (the last
tag plus one patch), run Steps 1–4 without stopping, and at the end of Step 4 hand your caller the
whole Step 4 hand-off (listed there). Then stop. Steps 5–7 are for the session that talks to the
owner.

Steps 1–4 write no files, create no branch and push nothing. The one thing they change is
`git fetch`, which updates the remote-tracking refs (`origin/main` and the tags). Every worktree
shares those refs. That is allowed. If you must stay strictly read-only, run
`git ls-remote origin refs/heads/main` and `git ls-remote --tags origin 'v*'` instead, and check
that they match your local refs. Run Steps 1–4 from whatever worktree you are in.

## The release

### 1. Account and state

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
git log -1 --format='%H %s' origin/main        # record this SHA, then use it below
git show <main sha>:packages/databricks-tellr/pyproject.toml | grep '^version'
git show <main sha>:packages/databricks-tellr-app/pyproject.toml | grep '^version'
```

Record these four facts. Later steps use them, and Step 4 shows them:

- **Last tag:** the newest `vX.Y.Z`. Ignore anything else (`ds-v1-checkpoint` is not a version).
- **Main SHA:** the `origin/main` SHA, in full. Steps 2–6 use this SHA, typed literally, never a
  moving `origin/main`: a peer session's `git fetch` can move `origin/main` under you.
- **Pyprojects:** both must say the last tag's version. If they don't, stop and tell the owner.
  (A subagent puts this in its hand-off instead.)
- **Default version:** the last tag plus one patch (after `v0.5.6`, `0.5.7`). That is the dev
  line: `publish-dev.yml` builds `<highest final + one patch>.devN`, so it matches the builds
  people have been testing.

Don't ask about the version yet. It is proposed in Step 4, next to the wording, once the owner
can see what ships.

### 2. PRs since the last tag

```bash
git log --first-parent --format='%H %s' <last-tag>..<main sha>
```

- `Merge pull request #N from …` is PR N.
- A subject ending in `(#N)` is a squash-merged PR N.
- Anything else is a **direct commit**. Read it with `git show --stat <sha>`, judge it like a
  PR, and list it to the owner as `direct commit <short sha>`.

The previous release's bump PR is not in the range, because the last tag sits on its merge commit.

Read every PR, one call each:

```bash
gh pr view <N> --json number,title,body,headRefName
```

Don't loop over the numbers: the worktree guard refuses `gh` and `git` inside a `for` loop or
`$(…)`. When the body doesn't make clear what changed for users, look at the files:
`gh pr diff <N> --name-only`.

**Stacked PRs.** A PR merged into another PR's branch is not on the first-parent list, because it
shipped inside that PR's merge. Check each PR both ways:

```bash
gh pr list --state merged --base <headRefName> --json number,title
git log --format='%H %s' '<merge sha>^1..<merge sha>^2' | grep -E 'Merge pull request|\(#[0-9]+\)$'
```

- The `gh` line lists every PR merged into that branch, however it was merged.
- The `git` line lists the branch's merge commits and its `(#N)` squash subjects.
- An empty result is normal and means nothing was stacked. `[]` from `gh`, and exit 1 from `grep`,
  are not failures.
- A squash-merged stacked PR leaves no merge commit. If its squash subject also lost its `(#N)`,
  only the `gh` line finds it. Run both.
- The `git` line is for PRs merged with a merge commit. A squash-merged PR (its first-parent
  subject ends in `(#N)`) has no `^2`, so `git log` fails with `unknown revision`. Use only the
  `gh` line for it.
- Commits on a long feature branch often end in `(#<issue>)`, so the `git` line can print one
  issue number many times. Read each number once. If `gh pr view <N>` says
  `Could not resolve to a PullRequest`, N is an issue, not a PR: skip it.

Read any stacked PR with `gh pr view`, and fold it into its parent's bullet.

If there are no PRs and no direct commits, tell the owner there is nothing to release and stop.

### 3. Draft the wording

Apply these rules to each PR (and direct commit):

1. **It has a `## What's new` section.** Use it, keeping the author's meaning. `None` (any case,
   with or without a reason after it) means leave it out. The section counts as absent (go to
   rule 2) when it is empty, or holds only the unedited parts of `.github/pull_request_template.md`.
   Those are its HTML comment, which starts
   `This text is shown to Tellr users in the in-app "What's new in Tellr" popup`, and the
   placeholder `- **Bold lead-in.** One short sentence.` Fix the format (rule 6) and the length
   (rule 7). If the wording breaks rule 4 or rule 7, rewrite it and say so in the "Included"
   table.
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
   internal component names. If you are unsure what the screen calls something, search
   `frontend/src` for the label.
5. **One bullet per user-facing feature.**
   - Several PRs that make up one feature for the user (a feature plus its follow-up fixes)
     become one bullet. A follow-up fix to a feature that is new in this release doesn't get a
     bullet of its own. List it under that feature's bullet in the "Included" table.
   - A single PR with several user-facing changes may give several bullets, one per change. A
     change too small for its own bullet goes as a note in that PR's "Included" row.
   - Put the most noticeable bullet first.
6. **Format.** A title of a few words, sentence case, with **no trailing period**. Titles must
   differ within a release.
7. **A short body.** The body is ONE short sentence of at most about 20 words. It ends with a
   period and says what the user can now do. Ideally it gives a concrete example of what to type
   or press.
   - No "and also" chains. If the sentence needs ", and" to add a second thing, cut the second
     thing or give it a bullet of its own.
   - Leave out secondary details unless they are the point. These are things like admin
     switches, rollback guarantees, and sub-features such as each Image Library button.
8. **Nothing user-facing** is a valid outcome. Propose an empty list, and say that this release
   adds nothing to the popup.

**The target style** is the owner's own wording for 0.5.7:

- **Native image generation in chat.** Ask for things like "make an image that represents this slide" or "give me an image of a monkey at a keyboard".
- **Chat cancellation.** Hit Esc to cancel a generation mid-flow.
- **MCP tool calling in Agent mode.** Add any MCP from the Gateway to your slide agent.

Too long, from the first dry run. Don't write bullets like this one:

- **Generate images.** In Agent mode, ask the chat for a picture or press Generate image and pick from the options it makes, and in the Image Library use Generate or Edit with prompt.

It is 33 words, it chains two things with ", and", and it lists sub-features. The first target
bullet says the same thing to a user.

A PR section bullet `- **Faster deck opening.** Large decks open in seconds.` becomes
`{ "title": "Faster deck opening", "body": "Large decks open in seconds." }`. The popup adds the
period after the title itself.

More examples, from 0.5.3:

| PR | Draft | Why |
|---|---|---|
| #366 perf: deck open downloads the deck once, without html_content, gzipped | **Faster deck opening.** Large decks now open in a few seconds instead of half a minute. | The user sees the speed, not the payload. |
| #363 feat(architect): a short starter deck instead of 14 to 20 slides | **Shorter first drafts.** New decks start with 5–8 slides plus ideas for what to add next. | No "architect", no prompt talk. |
| #361 ci: run tests alongside unit tests, shard E2E into six jobs, … | Left out: CI only. | |
| #365 fix(spec-sync): stop retrying the arc review of a deck with no graph pin | Left out: stops a log flood nobody saw. | |

**After-deploy notes.** While reading each PR, collect anything an operator must know or do after
deploying. Each note names its PR. The notes appear in the Step 4 output and the bump PR body,
never in the popup. Check every PR for:

- migrations: new tables or columns, backfills, and what a rollback leaves behind;
- new settings or environment variables;
- an admin Adopt, for example of a prompt that ships on a deployment whose active release was
  edited by hand;
- a `tellr.update` requirement;
- rollback limits: data that an older build rejects or drops;
- removed or changed API routes, which break external callers;
- new user API scopes, which existing users must re-consent to after `tellr.update`;
- paid or Gateway-cost features that are on by default, with their off switch and any model
  access they need.

### 4. Approval in the terminal

Read the release date **once**, now. Step 5 reuses it, so the file carries the month the owner
approved, even if the approval crosses midnight UTC:

```bash
date -u +%F        # the release date, e.g. 2026-11-13; the popup shows it as "November 2026"
```

Propose the version: by default, the next patch recorded in Step 1. The owner sometimes picks a
minor bump for a big feature set (`0.5.0` was one). That is their call. Propose the default, and
mention the option.

Once the version is proposed, check that its notes file is not already on the recorded main
SHA (Step 1). This is the first point where the version is known:

```bash
git ls-tree <main sha> frontend/src/whatsNew/releases/
```

If `<proposed version>.json` is in the listing, stop and tell the owner. Something put it on
`main` already, for example a throwaway preview branch merged by mistake, and the bump PR
would overwrite it instead of adding it.

Print these five things, in this order.

**1. The facts:** the last tag, the main SHA in full, the release date, and the proposed version.

**2. The popup**, exactly as users will read it. The layout follows
`frontend/src/components/WhatsNew/WhatsNewModal.tsx`. If the modal has changed, follow the
modal:

```
What's new in Tellr
Highlights from each release

<version>  [New]  <Month YYYY>
- **<Title>.** <Body>
- **<Title>.** <Body>
```

Write the bullets as markdown, so the titles show in bold. For an empty release, print
`(no entry in the popup for <version>)` instead of the bullets.

**3 and 4. Two tables**, so the owner can see nothing was missed. Every PR and direct commit from
Step 2 appears in exactly one of them:

- **Left out**: PR, title, and a one-line reason.
- **Included**: each bullet's title, and the PRs it came from. Note any section wording you
  rewrote, and any change too small for a bullet (rule 5).

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

**5. After deploying** (for the bump PR only, not the popup): the Step 3 notes, each with its PR.
If there are none, say "Nothing to do: no migrations, no new settings, nothing to Adopt".

**If you are a subagent, stop here.** Don't ask. Hand your caller the five things above: the
facts, the popup, both tables and the after-deploy notes. Also include anything from Step 1 that
would have stopped you, such as pyprojects that don't match the last tag.

Otherwise, ask:

> Approve this wording, and version <version>? On approval I write the notes file, bump both
> versions, push `release/v<version>` and open the bump PR, with the "After deploying" notes
> above in its body. Nothing merges, tags or publishes until you give a separate go-ahead.

Wait. If the owner edits anything, apply the edits and print all five things again. That includes
a different version, which changes the popup header. Repeat until the owner explicitly approves.
"Looks fine apart from X" is an edit, not an approval. Use the owner's wording as given. If their
title ends with a period, drop the period and say so.

**Write nothing before approval:** no notes file, no worktree, no branch.

### 5. Bump PR

Check that `main` has not moved past the main SHA recorded in Step 1:

```bash
git fetch origin
git log --oneline <main sha>..origin/main      # must print nothing
```

If it prints commits, those PRs would ship without being in the notes. Go back to Step 2 for
them, with the new main SHA, and get the owner's approval again.

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
order. `date` is the release date read in Step 4. Don't read the clock again. Escape any double
quote inside a string as `\"`.

```json
{
  "version": "<version>",
  "date": "<release date from Step 4>",
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
- <the approved Step 4 "After deploying" notes, each with its PR number>, or
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

If it says `no checks reported` straight after `gh pr create`, CI hasn't registered yet. Wait a
minute and run it again.

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
git log -1 --format=%P <merge sha>             # must print: <main sha> <full head sha>
git show <merge sha>:packages/databricks-tellr/pyproject.toml | grep '^version'
git show <merge sha>:packages/databricks-tellr-app/pyproject.toml | grep '^version'
git show <merge sha>:frontend/src/whatsNew/releases/<version>.json
git ls-remote --tags origin v<version>         # must print nothing
```

Both versions must be `<version>`, and the notes must be the approved ones. The merge's first
parent must be the main SHA from Step 1. `main` has no up-to-date rule, so if a peer merged
something after your last check, GitHub still merges, and the tag would ship PRs that are not in
the notes. If anything is off, stop and tell the owner. Don't tag.

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
| `main` can move between drafting and merging, and a peer's `git fetch` moves your `origin/main` too. | Draft against the main SHA recorded in Step 1, typed literally. Re-check `git log --oneline <main sha>..origin/main` before branching and before merging, and check the merge commit's first parent before tagging. New commits mean new PRs to draft. |
| The harness can refuse `gh pr merge` on an unreviewed PR. | Ask the owner to run the exact command as `! gh pr merge …`. |
| The bump PR now runs the frontend suites and E2E, which bump PRs used to skip. | Wait for green. The What's new E2E spec runs for real for the first time on it. |
| Old tags include `ds-v1-checkpoint`. | Only `vX.Y.Z` tags are releases. Filter them as in Step 1. |
| Notes files are only written by this skill, after approval. | Never write or edit one by hand, or outside Step 5. The publish guard refuses a tag without one. |
