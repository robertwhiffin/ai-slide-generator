# Task 1 re-review 2 — value-owned omission fix

## Scope and authority

- Fix package reviewed once: `review-abbf212c6..82417e533.diff`.
- Base/head: `abbf212c60ef31b4482ee6ee13d4d2ea8d5ca4aa` →
  `82417e533a0d356aa110e736db5fb099b9586cac`.
- Review is limited to the two Important findings in `task-1-rereview-1.md`
  and Critical/Important regressions introduced by this fix diff.
- Production/test changes in the package are limited to
  `src/services/agent_schema_types.py` and
  `tests/unit/test_agent_schema_registry.py`; the package also adds the SDD
  ledger and accumulated report artifacts.

## Verdict

**CHANGES_REQUIRED.** Pydantic compatibility and public
`model_copy(update=...)` behavior are restored, but the replacement semantic
source of truth is still mutable through Pydantic's publicly reachable field
storage. Direct `__dict__` replacement changes omission/presence in all three
required semantic paths.

## Prior finding verification

### Important 1 — immutable supplied-mutation semantics: NOT ADDRESSED

The fix removes `_supplied_mutations` and derives semantic presence from whether
the field value is the `PydanticUndefined` singleton
(`agent_schema_types.py:63-65,89-93`). This closes the two exact round-1 routes:
arbitrary `_supplied_mutations` assignment and replacement of
`__pydantic_private__` no longer affect semantics. Normal assignment to
`description`/`examples` is also rejected with Pydantic's `frozen_instance`
error, and changes to `model_fields_set` are ignored.

However, Pydantic stores those field values in the model's ordinary, publicly
reachable mutable `__dict__`. `frozen=True` intercepts attribute assignment; it
does not freeze that mapping. A direct probe, without `object.__setattr__`,
demonstrated both directions:

```python
guidance.__dict__["description"] = PydanticUndefined
guidance.__dict__["examples"] = PydanticUndefined
```

changed an originally supplied overlay from:

```text
serialization: {'description': 'kept', 'examples': ['example']}
validation:    no issues
composition:   description='kept', examples=['example']
```

to:

```text
serialization: {}
validation:    no issues
composition:   no replacement description/examples
```

The inverse mutation on an omitted guidance value:

```python
guidance.__dict__["description"] = "injected"
guidance.__dict__["examples"] = ("injected example",)
```

changed serialization from `{}` to the injected values and caused composition
to install those values, again with no validation issue. Thus the source of
semantic presence remains replaceable through the Pydantic field-state mapping
and can alter serialization, overlay validation, and schema composition.

The amended regression exercises normal field assignment, former private-state
locations, and Pydantic's fields-set, but never mutates the `__dict__` that now
owns the semantic state. Its positive result therefore does not establish the
required immutability.

### Important 2 — preserve Pydantic fields-set/model-copy behavior: ADDRESSED

The fix no longer replaces `__pydantic_fields_set__`. A direct probe confirmed
it is an ordinary mutable `set`; `add()` and `clear()` both succeed, and neither
operation changes omission semantics. The focused regression also now performs
those mutations successfully instead of swallowing an exception.

`CanonicalFieldGuidance.model_copy(update=...)` works again. Independently
re-probed values serialized distinctly as:

```text
omitted:       {}
explicit null: {'description': None}
supplied:      {'description': 'copied'}
```

The copied supplied value also passes overlay validation and supplies the
expected description/examples to composed JSON Schema. This addresses the
round-1 Pydantic compatibility regression.

## New Critical/Important breakage in this fix

None beyond the still-open Important 1 above. The plain model serializer hides
the omission sentinel on the exercised paths, and no regression was found in
the scoped `model_copy(update=...)` behavior.

## Independent sabotage evidence

Target: the new value-owned `PydanticUndefined` presence branch, distinct from
the implementer/controller targets and from re-review 1's live-fields-set
target. I temporarily inverted only the description branch to:

```python
return self.description is PydanticUndefined  # TASK1_REREVIEW_2_VALUE_SENTINEL_SABOTAGE
```

`rg` located the marker at the executed `mutation_is_supplied("description")`
branch on line 91. The focused copied-value regression then failed because the
copied description disappeared from serialization:

```text
FAILED test_guidance_model_copy_update_preserves_pydantic_and_omission_semantics
assert {'examples': ['Example']} ==
       {'description': 'Copied', 'examples': ['Example']}
1 failed, 5 warnings in 0.12s
```

The failure at the first copied-value serialization assertion proves the
marked branch executed. I restored the exact `is not PydanticUndefined`
expression with `apply_patch`; `rg` proved the marker absent, the production
diff returned clean, and the identical focused command was GREEN:
`1 passed, 5 warnings in 0.05s`.

## Verification and report comparison

Every Python command used `/Users/robert.whiffin/.pyenv/shims/python` with
`.venv` absence checks before/after; no install or environment mutation was
performed.

- Both amended regressions: `2 passed, 5 warnings in 0.06s`.
- Full Task 1 suite: `32 passed, 5 warnings in 0.38s`.
- Combined Task 1/manifest/runtime suite: `89 passed, 5 warnings in 6.61s`.
- Ruff format check: `3 files already formatted`.
- Ruff lint: `All checks passed!`.
- `git diff --check abbf212c6..82417e533`: clean.

The five warning causes match the report rather than merely its count: the two
repository Pydantic class-config warnings, the repository
`langchain-community` sunset warning, and the two established third-party
Pydantic warnings. There were no failures or skips in the restored suites.

## Finding disposition

- Important 1, genuinely immutable/non-replaceable semantic presence:
  **NOT ADDRESSED** — one load-bearing finding remains.
- Important 2, mutable Pydantic-owned fields-set and working public model copy:
  **ADDRESSED**.
- New Critical/Important findings introduced by the fix: **none**.
