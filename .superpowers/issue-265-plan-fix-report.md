# Issue #265 plan-fix report

**Plan:** `docs/superpowers/plans/2026-09-22-declarative-prompt-assembly.md`

## Current correction

The fresh full review at
`.superpowers/sdd/2026-09-22-declarative-prompt-assembly/plan-review-ae3d09f34.md` is mapped in
`plan-correction-report.md`. The plan now defines local versus post-stale validator phases,
non-prompt terminal binding metadata, nullable upgrade conflicts, final reviewed predecessor
evidence, explicit #261 PostgreSQL coverage, a complete dotted-path validation contract, a
typed unavailable-bundle exception, and seven-role persisted-v2 runtime coverage.

## Local-only execution gate

Task 0 resolves final reviewed #260/#261/#263 heads from review evidence, records one concrete
reviewed **local** `feat/langgraph-core` integration commit, proves all predecessor heads are
ancestors, and rebases #265 onto that commit. It must not fetch, name, create, or use
`origin/integration/261-263`.

At this correction, local `feat/langgraph-core` is
`76a88f238e84f17cc60eba8a62e00dc80fc26115`. It contains final #263
`1d706e21b92aad68314da2e79bb4d1d5626663b7` but not reviewed #261
`785d9aaca35a3a9103cd4283afdc6bda3b679882`, so implementation remains blocked. Active #261
`77e42b3c170373407afddc1c98d982af5c3806fa` is only an observed unreviewed fix head until a
review names it or a successor as final.

## Verification scope

This correction changes only the plan and its two tracked reports. It performs no production
implementation, dependency installation, remote operation, push, PR, or integration merge.
