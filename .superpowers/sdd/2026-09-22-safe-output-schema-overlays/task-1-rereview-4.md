# Task 1 re-review 4 — Pydantic-compatible protected-copy fix

## Scope and authority

- Fix package reviewed once: `review-2500b50f4..77223ae71.diff`.
- Base/head: `2500b50f4` →
  `77223ae71d0ed7157d579ea126284d3c0cca0b19`.
- Binding inputs: `task-1-brief.md`, `PLAN-CORRECTIONS.md`, the accumulated
  `task-1-report.md`, and the open finding in `task-1-rereview-3.md`.
- Review is limited to the open Pydantic-copy finding and Critical/Important
  regressions introduced by this fix in copy/update bookkeeping, protected
  supplied/omitted/null semantics, validation, serialization, and composition.
- No production or test change remains from this review; only this artifact is
  committed.

## Verdict

**APPROVED.** The round-4 copy kernel restores the installed Pydantic 2.12.4
shallow/deep copy, field-set, and trusted-update contract while retaining the
slot-backed semantic protection required by rounds 1–3. The prior Important
finding is **ADDRESSED**. No new Critical or Important regression was found.

## Prior finding verification

### Important 1 — Pydantic copy/update compatibility: ADDRESSED

The fix replaces serialize-and-revalidate copies with a narrow kernel in
`CanonicalFieldGuidance` (`agent_schema_types.py:50-89,207-324`). Installed
Pydantic source and direct behavior were independently re-probed from
`/Users/robert.whiffin/.pyenv/versions/3.11.0/lib/python3.11/site-packages`
at version `2.12.4`.

#### Shallow copies

Both `model_copy()` and `copy.copy()` now:

- allocate a distinct model;
- retain identity for `examples` and its nested frozen values;
- allocate a distinct outer protected extra mapping while retaining nested
  extra-value identity;
- preserve the complete, even caller-extended, Pydantic field set in a
  distinct mutable set;
- rebuild the dedicated semantic-state slot from the protected source rather
  than from mutable public storage.

Direct probes additionally confirmed `__pydantic_extra__` outer identity is
distinct and that mutating the copied field set does not affect the original.

#### Memo-aware deep copies

Both `model_copy(deep=True)` and `copy.deepcopy()` detach recursively frozen
nested mappings/tuples and copy Pydantic bookkeeping. The helper handles
`MappingProxyType`, dictionaries, lists, tuples, and arbitrary leaves without
asking pickle to copy a mapping proxy.

An independent probe supplied one repeated custom leaf through examples and
forbidden extras, pre-seeded the `deepcopy` memo with its replacement, and
proved every copied occurrence resolved to that single replacement. It also
proved `memo[id(original)]` was the copied model and the copied field set was
equal but independent. This exercises memo use beyond the committed unit test.

#### Trusted unvalidated updates and field sets

`model_copy(update=...)` no longer validates update keys or values. Direct and
committed probes accepted nonconforming canonical values, an arbitrary object
leaf, and unknown/protected-looking extra keys. Every update key was added to
the copied field set while the original remained unchanged.

Mutable JSON containers supplied by the caller are recursively frozen into the
protected semantic state. Mutating the caller's original nested list after the
copy did not change serialization. An explicit `PydanticUndefined` update was
retained as the protected value and added to the field set while preserving the
class's established omission semantics.

#### Supplied, omitted, explicit-null, and mutation protection

Independent probes covered omitted, explicit `None`, and explicit empty-list
values through shallow copy, deep copy, and update. They remained distinct in
`serialized_mutations()`.

The copied slot state resisted:

- normal frozen-field assignment;
- normal semantic-slot assignment and deletion;
- replacement of `__pydantic_private__` and `__pydantic_extra__`;
- semantic entry replacement/removal in `__dict__`;
- copied field-set clearing; and
- mutation of the caller-owned update container.

After these attempts, protected attribute reads and serialization still
returned the original copied semantics. The existing registry tests also keep
serialization, ordered overlay validation, and composed schema guidance bound
to that slot state, so the round-3 fix is not reopened.

## New Critical/Important breakage in this fix

None. The production change is confined to the protected type's copy seam;
identity literals, optional catalogs, registry ordering, diagnostics, raw-key
policy, and manifest/runtime integrations are unchanged by the package.

## Independent sabotage evidence

Target: shallow-copy outer-extra isolation at
`agent_schema_types.py:248`, distinct from the implementer's shallow
`examples=state.examples` sabotage and all prior reviewer targets. I
temporarily changed the executed line to:

```python
protected_extras = state.extra_properties  # TASK1_REREVIEW_4_OUTER_EXTRAS_SABOTAGE
```

`rg -n -C 4` located the marker in `CanonicalFieldGuidance.__copy__`. The
focused shallow-copy regression then failed at the outer-extra identity
assertion:

```text
FAILED test_guidance_shallow_copies_preserve_nested_identity_and_copy_field_set
assert copied.forbidden_properties() is not original.forbidden_properties()
1 failed, 5 warnings in 0.12s
```

I restored the exact `MappingProxyType(dict(state.extra_properties))` line
with `apply_patch`. The marker was absent, the production diff returned empty,
and the identical focused node was GREEN:

```text
1 passed, 5 warnings in 0.03s
```

## Verification and cause-set comparison

Every Python command used `/Users/robert.whiffin/.pyenv/shims/python` with
`.venv` absence guards before and after. The resolved executable was the
absolute shared pyenv interpreter; `sys.prefix == sys.base_prefix`, and no
install or environment mutation was performed.

- Independent copy/memo/update/mutation probe: `copy-probe: PASS`.
- Broad copy/mutation selection: `9 passed, 30 deselected, 5 warnings in
  0.14s`.
- Combined Task 1/manifest/runtime suite: `96 passed, 5 warnings in 6.94s`;
  no failures or skips.
- Ruff format check: `3 files already formatted`.
- Ruff lint: `All checks passed!`.
- `git diff --check 2500b50f4..77223ae71`: clean.

The five warning causes match the accumulated report rather than merely its
count: the two repository Pydantic class-config deprecations, the repository
`langchain-community` sunset warning, the third-party Unity Catalog
class-config deprecation, and the third-party Databricks AI Bridge v1-validator
deprecation. No failure, skip, or warning cause was added or replaced.

## Finding disposition

- Prior Important 1, shallow/deep copy, field-set, and trusted-update
  compatibility: **ADDRESSED**.
- Supplied/omitted/null and protected slot semantics: **PRESERVED**.
- New Critical/Important findings introduced by the fix: **none**.
- Scoped Task 1 fix-round-4 verdict: **APPROVED**.
