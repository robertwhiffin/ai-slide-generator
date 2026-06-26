# Tellr — repo conventions for Claude

## Deploying dev builds

To deploy a dev/test build of the app to a Databricks Apps dev workspace, use the
**`deploy-tellr-dev`** skill (`.claude/skills/deploy-tellr-dev/`), or read
`docs/technical/dev-deploy.md`.

Key rule: dev wheels are published to **real PyPI** as `.devN` pre-releases — the
Databricks Apps build proxy mirrors real PyPI only, so test-PyPI / custom-index
approaches do **not** work. The loop is: `gh workflow run publish-dev.yml` →
note the version → `./scripts/deploy_local.sh update --env devtest --profile
tellr-dev --from-pypi <version>`.
