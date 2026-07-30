
---

## Item 4 — the 120,000-character template layout cap

**Status: CAP REMOVED.** Spec: `tests/unit/test_design_system_templates.py`.

### RED first — codex's boundary reproduced exactly

```
layout_chars=120000 emitted=True
layout_chars=120001 emitted=False
   Pinned template 'Synthetic Template' layout is 120001 chars (cap 120000);
   generating without a template
```

One character decided whether a template the user **explicitly pinned** reached the
model at all. The new spec asserts emission at 120,000, 120,001 and 500,000; the last
two failed RED.

### Fix

`MAX_TEMPLATE_LAYOUT_CHARS` and its drop branch are removed from
`src/services/design_system_templates.py`. The layout is user-supplied brand layout
text and is not one of the deliberate binary OOM guards — those are the per-asset and
per-bundle BYTE limits in `design_system.py`, which I did not touch (they are the
other agent's, now 100 MB / 500 MB).

**No replacement bound was introduced, and I am flagging that as a decision rather
than making it silently.** If prompt assembly ever needs an upper bound, it must be a
VISIBLE, REPORTED condition — surfaced to the user, never a silent drop — and picking
a number is a product call. The `None` return remains for the genuine no-usable-layout
case (an empty/whitespace layout), where there is simply nothing to inject; LENGTH is
never a reason.

### Disappearance disclosed, with its stronger-successor argument

`TestBuildSelectedTemplateBlock::test_oversized_layout_falls_back_to_none_with_warning`
**is gone**. It asserted the defect itself — that a 120,001-character layout returns
`None`. Its successor,
`test_a_long_layout_is_never_turned_away[120000|120001|500000]`, is strictly stronger:
it covers the old boundary, one character past it and far past it, and additionally
asserts the layout arrives **in full** (`template.layout_html in block`), which the
old test never checked. `test_empty_layout_returns_none` is retained unchanged, so the
legitimate fallback is still pinned.

### Gates

| Gate | Before | After | Net-new |
|---|---|---|---|
| `pytest tests/unit` | 2492 passed, 11 skipped | 2495 passed, 11 skipped | +3 net (−1 superseded, +3 parametrized, +1 guard), 0 failures |
| `ruff check src tests` | 2176 | 2176 | **0** |
| `mypy src` | 551 in 84 files | 551 in 84 files | **0** |

---

## The UNIQUE-NAME question — REPORTED, not decided

### Evidence, measured on the live PostgreSQL 14.22

```
1000-byte compressible       bytes= 1000 ok=True  stored exact
5000-byte compressible       bytes= 5000 ok=True  stored exact
5000-byte INCOMPRESSIBLE     bytes= 5000 ok=False
   ProgramLimitExceeded: index row size 5016 exceeds btree version 4 maximum 2704
                         for index "design_system_name_key"
2704-byte INCOMPRESSIBLE     bytes= 2704 ok=False  (index row size 2720 > 2704)
2000-byte INCOMPRESSIBLE     bytes= 2000 ok=True  stored exact

largest INCOMPRESSIBLE name that inserts: ~2692 bytes
```

The key nuance codex's summary implies but does not state outright: **length alone
does not decide.** The btree index tuple is compressed (pglz), so a 5000-byte name of
one repeated character stores fine while a 5000-byte random one does not. The
practical bound applies only to *incompressible* names, and only to the DS **name** —
every other brand-text column is unbounded `TEXT` with no index.

### What the user saw — and the part I fixed now

`ProgramLimitExceeded` is raised from inside the INSERT, so it fell through
`import_bundle` into the import route's generic `except Exception`
(`design_systems.py:528-534`) and surfaced as:

> **HTTP 500** — `"Failed to import design system"`

Nothing actionable, for a legitimate upload. Per the instruction to cheaply convert
that, `_guard_indexable_name` now raises `DesignSystemImportError` (which the route
already maps to **HTTP 400**) before any expensive work, with:

> `The design system name is too long to index uniquely: it is 4000 bytes, and a
> unique name must compress to at most 2704 bytes. Import it with a shorter name (the
> brand's own text is stored uncapped everywhere else).`

Compressibility is **measured** (zlib as a stand-in for pglz — both LZ77-family, and
the guard only fires when the *compressed* form still overflows), so a long-but-
compressible name that Postgres genuinely stores is never turned away. The test
cross-validates both verdicts against the live database, so the guard cannot drift
from real Postgres behaviour. It fails loudly and never truncates.

### The three options, with trade-offs

| Option | Pros | Cons |
|---|---|---|
| **1. Keep as-is** (now with the clean 400) | Zero schema change; uniqueness stays a real DB invariant; failure is loud, never silent; ~2704-byte bound is unreachable for any plausible brand name | A cap on brand data remains, in principle contrary to "never turned away". Bound is fuzzy (compression-dependent), so the error message must quote a compressed limit |
| **2. Unique index on a hash/prefix expression** (e.g. `UNIQUE (md5(name))` or `UNIQUE (left(name, N))`) | Removes the length bound entirely; names of any size stay unique and uncapped | `md5`: a collision (astronomically unlikely, but a *wrong* 409 if it happened) and the index no longer supports prefix/range lookups on name. `left(name,N)`: two names sharing the first N chars would falsely conflict — a REAL user-visible bug, worse than the status quo. Needs a migration on a live table, and existing duplicate-by-hash rows would block index creation |
| **3. Enforce uniqueness in application code** | No index-size limit at all; error messages fully controllable | Loses the database invariant — concurrent imports can race past a check-then-insert and both commit (the current code already does a check-then-insert, so today the UNIQUE index is what actually saves it). Would need advisory locking or a serializable transaction to be correct |

**My read, for your decision:** option 1 is now the cheapest defensible position
because the 500 is gone — the residual cap is ~2704 bytes on a *name*, which no real
brand approaches, and it fails loudly with an actionable message. Option 2 via `md5`
is the only one that genuinely removes the bound without losing the DB invariant, and
would be my choice if the "no cap on brand data anywhere" rule must hold literally;
`left(name,N)` should be rejected outright, as it introduces false conflicts. Option 3
weakens a correctness guarantee to remove a bound nobody will hit. **Not decided —
yours to call.**
