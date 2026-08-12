# Tellr — repo conventions for Claude

## Executing an implementation plan

Before executing any written plan in `docs/superpowers/plans/` via subagents, load the
**`executing-plans-tellr`** skill (`.claude/skills/executing-plans-tellr/`) alongside
`superpowers:subagent-driven-development`. It carries the practices that caught the real
defects on the last build: sabotage-verify every test a reviewer approves, run a
plan-vs-code corrections pre-pass before Task 1, treat baselines as failure *causes* not
counts, and re-probe any external-state fact a subagent volunteers.

Also load it when reviewing work a subagent produced here.

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
gh workflow run publish-dev.yml          # auto-increments the next .devN; note the published version
./scripts/deploy_local.sh update --env devtest --profile tellr-dev --from-pypi <version>
```
