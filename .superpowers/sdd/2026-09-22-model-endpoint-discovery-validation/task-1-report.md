# Task 1 report — exact model endpoint catalog (#266)

**Base:** `0cfc80472d74c83d37b1281c9faad872cdb033bc`

## Scope and constraints honored

- Created only `src/services/model_endpoint_catalog.py` and
  `tests/unit/test_model_endpoint_catalog.py`; no predecessor/shared file or
  execution ledger was modified.
- Used `/Users/robert.whiffin/.pyenv/shims/python`; did not install packages, run
  uv/pip, create `.venv`, contact a remote, push, open a PR, or merge.
- Read the Task 1 brief and binding `PLAN-CORRECTIONS.md` before implementation.
  `AGENTS.md` is absent from this worktree; its supplied repository instructions
  were honored.

## RED

Command:

```bash
/Users/robert.whiffin/.pyenv/shims/python -m pytest -q tests/unit/test_model_endpoint_catalog.py
```

Exact result before the module existed: collection stopped with
`ModuleNotFoundError: No module named 'src.services.model_endpoint_catalog'` at
`tests/unit/test_model_endpoint_catalog.py:7`; summary was `1 error in 0.13s`.
The warning set was the five Task-0 baseline causes: two local Pydantic
class-based-Config deprecations, the established `langchain-community` sunset
warning, Unity Catalog's Pydantic class-based-Config deprecation, and Databricks
AI Bridge's Pydantic-v1 `@validator` deprecation.

## GREEN

Command:

```bash
/Users/robert.whiffin/.pyenv/shims/python -m pytest -q tests/unit/test_model_endpoint_catalog.py
```

Exact result after the minimal implementation: `19 passed, 5 warnings in 0.04s`.
The five warnings were exactly the recorded baseline causes above; there were zero
failures and zero skips.

## Independent falsification

I did not run either reserved sabotage. I temporarily replaced the local URL-prefix
regular expression with `$^` and marked that exact executable line
`TASK1_LOCAL_URL_POLICY_BYPASS_SABOTAGE`.

Verification command:

```bash
rg -n 'TASK1_LOCAL_URL_POLICY_BYPASS_SABOTAGE' src/services/model_endpoint_catalog.py
/Users/robert.whiffin/.pyenv/shims/python -m pytest -q \
  tests/unit/test_model_endpoint_catalog.py -k url_shape
```

Exact sabotage result: marker found at line 67; all four URL-policy cases failed
with `Failed: DID NOT RAISE EndpointValidationFailure`; summary was
`4 failed, 15 deselected, 5 warnings in 0.11s`. I restored the production regex,
verified absence with:

```bash
! rg -n 'TASK1_(LOCAL_URL_POLICY_BYPASS|CONTROLLER_TASK_HEURISTIC|REVIEWER_EXACT_NAME)_SABOTAGE' \
  src/services/model_endpoint_catalog.py tests/unit/test_model_endpoint_catalog.py
```

The restored focused suite again produced `19 passed, 5 warnings in 0.04s`.

## Static and whitespace checks

```bash
ruff check src/services/model_endpoint_catalog.py tests/unit/test_model_endpoint_catalog.py
git diff --check
```

Ruff reported `All checks passed!`. `git diff --check` produced no output. The
initial Ruff run identified import order, the two plan-mandated `*Failure` names,
and one overlong test signature; imports were mechanically formatted, the mandated
names retain scoped `# noqa: N818`, and the signature was wrapped before the clean
rerun.

## Self-review

- The list path invokes only argument-free `serving_endpoints.list()` once, selects
  only non-null `foundation_model`, preserves exact parent endpoint names, deduplicates
  per parent, carries metadata only from the foundation-model object, returns tuples,
  and leaves forbidden/unavailable observable.
- The local policy is SDK-free and preserves accepted text verbatim. Remote validation
  calls exact `get(name)` once, rejects alias responses, and maps only the named SDK
  exception/state categories to the specified typed failures.
- The fake uses queued discovery outcomes, name-keyed validation outcomes, and explicit
  call evidence without an SDK mock.

## Concerns

None. The five warnings are the unchanged Task-0 baseline causes.
