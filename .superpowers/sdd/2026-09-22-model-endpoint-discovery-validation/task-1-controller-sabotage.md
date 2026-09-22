# Task 1 controller sabotage — exact model endpoint catalog

Production target: the executed foundation-model classification in
`DatabricksModelEndpointCatalog.list_system_models()`.

The controller temporarily replaced served-entity `foundation_model` inspection with
the endpoint-level `task` heuristic and placed
`TASK1_CONTROLLER_TASK_HEURISTIC_SABOTAGE` on that executed line. `rg` confirmed the
marker at `src/services/model_endpoint_catalog.py:104`.

Focused command:

```bash
/Users/robert.whiffin/.pyenv/shims/python -m pytest -q -p no:cacheprovider \
  tests/unit/test_model_endpoint_catalog.py \
  -k selects_foundation_endpoints_once_and_sorts_exact_names
```

Sabotaged result: **1 failed, 18 deselected**. The discovered result contained only
`task-only`, proving the test rejects the forbidden task heuristic and requires actual
foundation-model metadata.

After exact restoration, `rg` found no marker and the same command returned
**1 passed, 18 deselected** with the unchanged five baseline warning causes.
`git diff --check` was clean and the worktree returned to a clean state.

This target is distinct from the implementer's URL-prefix-policy sabotage. The task
reviewer retains the reserved exact detail-name-equality sabotage.
