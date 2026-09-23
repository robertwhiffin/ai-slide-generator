# Task 1 review — exact model endpoint catalog (#266)

**Scope:** Task 1 only.  Reviewed frozen range
`0cfc80472d74c83d37b1281c9faad872cdb033bc..3b6542cacee893a4a8e6409e6aff0a3b65aa3926`.

## Verdicts

- **Spec Compliance: APPROVED.** The implementation is limited to the two
  authorized new files and fulfils the Task 1 brief and binding corrections.
- **Task Quality: APPROVED.** The adapter is small, deterministic, typed, and
  has focused SDK-shaped unit coverage.

## Findings

### Critical

None.

### Important

None.

### Minor

None.

## Strengths

- `src/services/model_endpoint_catalog.py:83` makes exactly one argument-free
  `list()` call; `:101-131` selects only non-null `foundation_model`, preserves
  the exact nonblank parent name, copies only foundation-model metadata,
  deduplicates each parent, and locally sorts to the specified stable key.
- `src/services/model_endpoint_catalog.py:133-188` calls exact `get(name)`
  once, checks exact returned-name equality before state evaluation, and maps
  only the named SDK failures and update/ready states to typed outcomes.
- `src/services/model_endpoint_catalog.py:66-76` is SDK-free and rejects all
  specified left-whitespace-tolerant URL prefixes without mutating accepted
  text. `:199-231` supplies the deterministic, outcome-queued fake with exact
  call evidence.
- `tests/unit/test_model_endpoint_catalog.py:70-217` covers classification,
  deterministic ordering, typed discovery failures, URL policy, remote table
  outcomes, and fake behavior. Its recording serving client rejects unexpected
  serving-API attributes, covering the OpenAPI/query prohibition.

## Verification

Initial scoped command:

```text
/Users/robert.whiffin/.pyenv/shims/python -m pytest -q tests/unit/test_model_endpoint_catalog.py
19 passed, 5 warnings in 0.03s
```

The five warnings are the pre-recorded Task-0 warning causes. `ruff check
src/services/model_endpoint_catalog.py tests/unit/test_model_endpoint_catalog.py`
reported `All checks passed!`; `git diff --check` for the frozen range had no
output.

## Required independent falsification

I temporarily replaced the exact returned-name condition at
`src/services/model_endpoint_catalog.py:153` with the deliberately false
condition below, which removes the equality guard. The marker was on the
evaluated conditional line for the selected alias response.

```python
if False:  # TASK1_REVIEWER_EXACT_NAME_SABOTAGE
```

Exact sabotage command:

```text
rg -n 'TASK1_REVIEWER_EXACT_NAME_SABOTAGE' src/services/model_endpoint_catalog.py && /Users/robert.whiffin/.pyenv/shims/python -m pytest -q tests/unit/test_model_endpoint_catalog.py -k endpoint_name_mismatch
```

Exact relevant output:

```text
153:        if False:  # TASK1_REVIEWER_EXACT_NAME_SABOTAGE
FAILED tests/unit/test_model_endpoint_catalog.py::test_validate_custom_endpoint_remote_maps_exact_outcomes[detail0-None-endpoint_name_mismatch-False]
E       Failed: DID NOT RAISE <class 'src.services.model_endpoint_catalog.EndpointValidationFailure'>
1 failed, 18 deselected, 5 warnings in 0.09s
```

Restoration proof: restored exactly
`if getattr(detail, "name", None) != name:`, verified no reviewer marker by
`rg`, then reran:

```text
/Users/robert.whiffin/.pyenv/shims/python -m pytest -q tests/unit/test_model_endpoint_catalog.py -k endpoint_name_mismatch
1 passed, 18 deselected, 5 warnings in 0.02s
```

## ⚠️ Items

None. The only lasting worktree mutation from this review is this report;
the reviewed production and test files are restored exactly to the frozen
head.
