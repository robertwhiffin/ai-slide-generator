# Design System Library — Feature Spec (superseded)

**One-Line Summary:** This was the pre-implementation plan-gate spec. The feature has shipped; the sections below now live in the two documents named here.

---

## Where each section went

Source docstrings cite this file by section number, so the mapping is preserved rather than the file removed.

| Old section | Now documented in |
|---|---|
| §5 — the design system bundle | [Design System Bundle Format](./design-system-bundle-format.md) |
| §6 — data model | [Design System Library §6](./design-system-library.md) for the responsibility map; [Database Configuration](./database-configuration.md) for column-level schema |
| §7 — backend API | [Design System Library §5](./design-system-library.md) — all 15 routes |
| §8 — generation integration and the compiler | [Design System Library §8](./design-system-library.md) — including the version/currency contract |
| §9 — frontend UX | [Frontend Overview](./frontend-overview.md) |
| §11 — constraints | [Design System Library §7](./design-system-library.md) (retention) and §5.1 (authorization) |

---

## Why this file is not the source of truth

It was written at the plan gate and never updated, so it describes intent rather than behaviour. Several of its statements are now false, and two of them would actively mislead someone building a bundle:

- It documented a **`brand/`** folder. The importer allowlists **`assets/`** and **`fonts/`** only, so a bundle organised to this spec imports **no assets at all**, silently.
- It never mentioned **`templates/<slug>/.thumbnail`** — the dot-prefixed, extension-less convention a real bundle uses for template thumbnails.
- It described import as validated against a **JSON Schema**. There is no such gate; classification is an allowlist plus canonicality refusals.
- It predicted **three** tables where **five** ship, and listed **nine** routes where **fifteen** ship — one of the nine (`GET /design-systems/{id}/export`) does not exist.

The original content remains in Git history if the planning record is needed.

---

## Cross-References

- [Design System Library](./design-system-library.md) — the subsystem doc-of-record
- [Design System Bundle Format](./design-system-bundle-format.md) — the bundle contract
