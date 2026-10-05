# Tellr — repo conventions for Claude

## Executing an implementation plan

Before executing any written plan in `docs/superpowers/plans/` via subagents, load the
**`executing-plans-tellr`** skill (`.claude/skills/executing-plans-tellr/`) alongside
`superpowers:subagent-driven-development`. It carries the practices that caught the real
defects on the last build: sabotage-verify every test a reviewer approves, run a
plan-vs-code corrections pre-pass before Task 1, treat baselines as failure *causes* not
counts, and re-probe any external-state fact a subagent volunteers.

Also load it when reviewing work a subagent produced here.

Every task in a plan must carry a `Models:` tag (`test=`/`impl=` tiers); the skill's §9
specifies the format and the model-tiering pipeline, and the pre-pass refuses to dispatch an
untagged task. Set the tiers when authoring the plan — they are a review point with the
author, not a dispatch-time afterthought.

Two environment facts it depends on: the Python env is a **shared pyenv site-packages**
(never `pip install` from an agent — it corrupts parallel agents' runs), and
`packages/databricks-tellr-app/pyproject.toml` is the file the Apps BUILD phase resolves,
not the repo-root dependency files.

## Deploying dev builds

To deploy a dev/test build of the app to a Databricks Apps dev workspace, use the
**`deploy-tellr-dev`** skill (`.claude/skills/deploy-tellr-dev/`), or read
`docs/technical/dev-deploy.md`.

Key rule: dev wheels are published to **real PyPI** as `.devN` pre-releases — the
Databricks Apps build proxy mirrors real PyPI only, so test-PyPI / custom-index
approaches do **not** work. The loop:

```bash
git push origin <branch>                                  # as the personal gh account (robertwhiffin), never EMU
gh workflow run publish-dev.yml --ref <branch>            # auto-increments the next .devN; note the published version
./scripts/deploy_local.sh create|update --env devloop --instance <id> --profile tellr-dev --from-pypi <version>
```

**Always deploy to `devloop`, never `devtest`.** A recreated `devtest` app gets a new
service principal that does not own `devtest_app_data`, so the startup migration crashes.

## Agent skills

### Issue tracker

GitHub Issues in `robertwhiffin/ai-slide-generator`, using the personal GitHub account. See `docs/agents/issue-tracker.md`.

### Triage labels

Use the five default Matt Pocock triage labels. See `docs/agents/triage-labels.md`.

### Domain docs

Use the single-context layout rooted at `CONTEXT.md`. See `docs/agents/domain.md`.
