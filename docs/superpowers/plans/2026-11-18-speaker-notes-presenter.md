# Talk track, notes and presenter view Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Load `executing-plans-tellr` with it. Steps use checkbox (`- [ ]`) syntax for tracking.

Execution: single-session

**Goal:** Every Tellr deck arrives with an agent-written talk track and notes on each slide, people can edit both, and a private presenter window shows them while the audience sees only the slides.

**Architecture:** The builder ends each slide with two hidden asides marked `data-presenter="talk-track"` and `data-presenter="speaker-notes"`. Tellr moves each aside into its own slide field wherever slide HTML arrives, with a per-field author (`model` or `user`) so a person's save is never overwritten. A new `/sessions/:sessionId/present` page talks to presentation mode over a same-origin `BroadcastChannel`; presentation mode stays the only source of truth for the current slide.

**Tech Stack:** Python 3.11, FastAPI, SQLAlchemy, BeautifulSoup; React 18, TypeScript, Vitest, Playwright; the offline eval harness in `evals/` with MLflow.

**Spec:** `docs/superpowers/specs/2026-11-18-speaker-notes-presenter-design.md` (approved, all four sections). This branch already carries the single-field speaker-notes work (`speaker_notes`, `speaker_notes_source`, the Notes tab, the N panel, notes in exports). This plan extends it.

## Global Constraints

- `speaker_notes` keeps its name. The new field is `talk_track`, with `talk_track_source` in `{"model", "user", None}`.
- Builder asides are marked `data-presenter="talk-track"` and `data-presenter="speaker-notes"`, each with `hidden`. Never a class in builder output: the deck-style scorer fails classes the deck CSS does not define. Extraction also accepts `class="speaker-notes"` (design systems that already ask for it) and `class="talk-track"`.
- Never add `speaker_notes` or `talk_track` as an agent output field (`docs/superpowers/plans/2026-09-22-safe-output-schema-overlays.md:23`). They travel only inside the HTML as asides.
- Never hand-edit `src/services/agent_definition_manifest_v1.py`. The builder prompt changes only through `evals.harness.promote`.
- Never edit `evals/packs/`, `evals/fixtures/` or any scorer under `evals/harness/`. If a scorer penalises the asides, stop and report.
- Editor hint text, verbatim: "Chat rewrites the talk track only when it rebuilds the slide."
- Box labels and sublabels, verbatim: "Talk track" / "What you say." and "Notes" / "What you need to know."
- First-run presenter hint, verbatim: "Share only the slides window. Full screen on one screen will cover this window."
- Link status, verbatim: "Slides: linked" and "Slides: not linked", the second after 3 seconds with no state message.
- Export notes pane: the talk track, then a line `Notes:`, then the notes. When one field is empty, write only the other, with no heading.
- Python runs through the per-worktree `uv` venv (`uv sync --extra dev`, then `uv run`). Never `pip install`.
- Browser work attaches to an existing browser. No test or script in this plan launches a new browser locally.
- Every `<a>` or button text and every string a user reads is plain English with no internal terms.

## Review Focus

1. **A model aside on a slide whose other field is user-owned.** A rebuild that brings both asides must refresh only the model-owned field. Pinned in Task 2 (`test_rebuild_refreshes_model_field_only`).
2. **An old deck with no talk-track column value.** A slide stored before the migration reads `talk_track=""`, source `None`, on both read paths, and exports exactly as before. Pinned in Task 1 (`test_pre_migration_row_reads_empty_talk_track`) and Task 3 (`test_notes_only_slide_exports_unchanged`).
3. **The presenter window opened from a key press inside the sandboxed slide frame.** P is forwarded over the `tellr:slide-key` bridge, so `window.open` runs in a `message` handler. Browsers pass user activation from a child frame's keydown to its ancestors, but a pop-up blocker could still refuse. The toolbar button is the fallback, and `openPresenterWindow` returns `null` when blocked. Pinned in Task 6 (`returns null when the pop-up is blocked`), and checked live in Task 8.
4. **Presentation mode closed while the presenter stays open.** The presenter must show "Slides: not linked" and offer "Open presentation", and Next and Back must not throw. Pinned in Task 6 (`shows not linked after 3 seconds of silence`).
5. **A two-field save racing a chat rebuild.** Saving the talk track sends only `talk_track`, so the notes the rebuild just refreshed are not overwritten with a stale draft. Pinned in Task 2 (`test_notes_save_with_only_talk_track_leaves_notes`) and Task 4 (`saving the talk track sends only talk_track`).

---

## File map

| File | Responsibility | Task |
|---|---|---|
| `src/utils/html_utils.py` | Generic owned-aside extraction for both classes | 1 |
| `src/domain/slide.py`, `src/domain/slide_deck.py` | `talk_track` fields, parse, `to_dict`/`from_dict` | 1 |
| `src/database/models/session.py`, `src/core/database.py` | Columns and idempotent migration | 1 |
| `src/api/services/session_manager.py`, `src/api/services/slide_repository.py` | Row upsert, snapshot and both read paths | 1 |
| `src/services/graph/nodes.py`, `src/services/agent.py` | Agent-mode and Legacy-mode arrival paths | 2 |
| `src/api/services/chat_service.py`, `src/api/routes/slides.py` | Carry on replace, user HTML save, insert, notes-only save | 2 |
| `src/api/routes/export.py`, `frontend/src/services/presenterText.ts`, `frontend/src/services/domWalker.ts`, `frontend/src/services/api.ts` | Export pane text on every live route | 3 |
| `frontend/src/components/SlideViewer/FeedbackDrawer.tsx`, `SlideViewer.tsx` | Two boxes with separate saves (the `Slide` type fields land in Task 3) | 4 |
| `evals/configs/builder/presenter-text.{yaml,md}`, `src/core/skills/builder.py`, manifest via promote | Builder instruction | 5 |
| `frontend/src/services/presenterChannel.ts`, `frontend/src/components/Presenter/*`, `frontend/src/App.tsx`, `PresentationMode.tsx` | Presenter window and sync | 6 |
| `frontend/tests/e2e/presenter-view.spec.ts` | End-to-end step test | 7 |
| `docs/technical/export-features.md`, `docs/technical/presenter-view.md` | Docs | 3, 6 |

---

### Task 1: Talk track storage and extraction

Models: test=opus impl=sonnet

**Files:**
- Modify: `src/utils/html_utils.py` (the speaker-notes block added on this branch)
- Modify: `src/domain/slide.py`, `src/domain/slide_deck.py`
- Modify: `src/database/models/session.py` (`SessionSlide`), `src/core/database.py` (`_migrate_session_slide_speaker_notes`)
- Modify: `src/api/services/session_manager.py` (`_upsert_slide_row`, `_snapshot_row`, the row read path near `slide_row.speaker_notes`, the dict read path near `F5 key parity`)
- Modify: `src/api/services/slide_repository.py` (`SlideWriter.write_slide`, `_row_to_dict`)
- Test: `tests/unit/test_talk_track_storage.py` (new), plus updates to `tests/unit/test_speaker_notes_extraction.py`

**Interfaces:**
- Consumes: the branch's `pop_speaker_notes`, `notes_for_root`, `extract_speaker_notes`, `_notes_text`, `SPEAKER_NOTES_CLASS`.
- Produces:
  - `TALK_TRACK_CLASS = "talk-track"` and `PRESENTER_ATTR = "data-presenter"` in `html_utils`. An aside belongs to a field when its `data-presenter` value or one of its classes equals that field's marker (`talk-track` or `speaker-notes`). Any other `data-presenter` value is left in place.
  - `pop_presenter_asides(soup) -> dict[str, list[tuple[Tag, str]]]`, keyed `"speaker_notes"` and `"talk_track"`.
  - `text_for_root(root: Tag, popped: Sequence[tuple[Tag, str]]) -> Optional[str]` (the renamed `notes_for_root`; keep `notes_for_root` as an alias).
  - `extract_presenter_text(html: str) -> tuple[str, Optional[str], Optional[str]]` returning `(html_without_asides, speaker_notes, talk_track)`. Each text is `None` when its aside is absent and `""` when empty. HTML is returned unchanged, never reserialised, when neither aside is present.
  - `extract_speaker_notes(html)` stays and returns `(html_without_both_asides, speaker_notes)`, so a stray talk-track aside never leaks.
  - `Slide(talk_track: Optional[str] = None, talk_track_source: Optional[str] = None)`.
  - Slide dicts carry `talk_track: str` (never `None`) and `talk_track_source` on both read paths.
  - `SlideWriter.write_slide(..., talk_track: Optional[str] = None, talk_track_source: str = "model")` with the same None-preserves, `""`-clears, user-wins rules as `speaker_notes`.

- [ ] **Step 1: Write the failing tests** in `tests/unit/test_talk_track_storage.py` (done during planning: the file exists with the cases below and more; do not overwrite it):

```python
from bs4 import BeautifulSoup
from src.utils.html_utils import extract_presenter_text, extract_speaker_notes, pop_presenter_asides
from src.domain.slide_deck import SlideDeck

SLIDE = (
    '<div class="slide"><h1>Q3</h1>'
    '<aside data-presenter="talk-track" hidden><p>Revenue grew 12%.</p><p>Which region led?</p></aside>'
    '<aside data-presenter="speaker-notes" hidden><p>Source: sales.q3</p></aside></div>'
)

def test_extract_presenter_text_moves_both_asides():
    html, notes, talk = extract_presenter_text(SLIDE)
    assert "aside" not in html and "Revenue" not in html
    assert notes == "Source: sales.q3"
    assert talk == "Revenue grew 12%.\n\nWhich region led?"

def test_absent_asides_return_none_and_unchanged_html():
    raw = '<div class="slide"><h1>x</h1></div>'
    assert extract_presenter_text(raw) == (raw, None, None)

def test_empty_talk_track_is_empty_string():
    _, notes, talk = extract_presenter_text('<div class="slide"><aside class="talk-track"></aside></div>')
    assert (notes, talk) == (None, "")

def test_extract_speaker_notes_strips_stray_talk_track():
    html, notes = extract_speaker_notes(SLIDE)
    assert "talk-track" not in html and notes == "Source: sales.q3"

def test_unowned_aside_is_left_in_place():
    raw = '<aside class="talk-track"><p>x</p></aside><div class="slide"></div>'
    assert extract_presenter_text(raw)[2] is None

def test_parse_assigns_each_slide_its_own_talk_track():
    deck = SlideDeck.from_html_string(
        "<html><body>" + SLIDE + SLIDE.replace("12%", "9%") + "</body></html>"
    )
    assert [s.talk_track.split(".")[0] for s in deck.slides] == ["Revenue grew 12%", "Revenue grew 9%"]
    assert all(s.talk_track_source == "model" for s in deck.slides)

def test_to_dict_from_dict_round_trip():
    deck = SlideDeck.from_html_string("<html><body>" + SLIDE + "</body></html>")
    d = deck.to_dict()["slides"][0]
    assert d["talk_track"].startswith("Revenue") and d["talk_track_source"] == "model"
    again = SlideDeck.from_dict(deck.to_dict()).slides[0]
    assert again.talk_track == deck.slides[0].talk_track

def test_from_dict_without_key_reads_empty():
    deck = SlideDeck.from_dict({"slides": [{"html": '<div class="slide"></div>'}]})
    assert deck.slides[0].talk_track == "" and deck.slides[0].talk_track_source is None
```

Add, in the same file, database tests that reuse the fixtures in `tests/unit/test_speaker_notes_persistence.py` (read it first and copy its session and engine fixtures):
- `test_migration_adds_talk_track_columns_idempotently`: create `session_slides` without the two columns, run `_migrate_session_slide_speaker_notes` twice, and assert both `talk_track` and `talk_track_source` exist with no error on the second run.
- `test_pre_migration_row_reads_empty_talk_track`: a row with `talk_track` NULL reads `talk_track == ""` and source `None` through `SessionManager.get_slide_deck` (row path) and through `_row_to_dict`.
- `test_upsert_user_talk_track_survives_model_write`: write a row with `talk_track="mine"`, source `user`; then write `talk_track="model text"`, source `model`. The row keeps `"mine"`.
- `test_upsert_none_preserves_and_empty_clears_talk_track`.
- `test_user_notes_do_not_freeze_model_talk_track`: notes source `user`, talk track source `model`; a model write of both changes the talk track and keeps the notes.

Also add: `class="speaker-notes"` still extracts into notes; an aside with `data-presenter="other"` stays in the HTML; a `data-presenter` talk track plus a `class` speaker-notes aside on one slide fills both fields.

- [ ] **Step 2: Run the tests and confirm they fail**

Run: `uv run python -m pytest tests/unit/test_talk_track_storage.py -q`
Expected: FAIL, each test on its own missing name or field (the tests read new names off the module).

- [ ] **Step 3: Implement.** In `html_utils.py`, generalise `_owned_speaker_asides(soup)` to `_owned_asides(soup, marker)`, matching `soup.find_all("aside")` whose `data-presenter` equals `marker` or whose class list contains it. **Wrapper ownership (review B1):** when counting a `section`/`article` wrapper's other element children, exclude every presenter aside of either marker, so a wrapper holding one `.slide` plus both asides still owns them and is still promoted to the slide root. Add a test for that shape, with both the attribute form and a `class="speaker-notes"` plus attribute talk-track mix. Then add:

```python
TALK_TRACK_CLASS = "talk-track"
_PRESENTER_FIELDS = (("speaker_notes", SPEAKER_NOTES_CLASS), ("talk_track", TALK_TRACK_CLASS))


def pop_presenter_asides(soup: BeautifulSoup) -> Dict[str, List[Tuple[Tag, str]]]:
    """Remove owned talk-track and speaker-notes asides; return ``{field: [(owner, text)]}``."""
    popped: Dict[str, List[Tuple[Tag, str]]] = {}
    owned_by_field = {field: _owned_asides(soup, cls) for field, cls in _PRESENTER_FIELDS}
    for field, owned in owned_by_field.items():
        popped[field] = [(owner, _notes_text(aside)) for aside, owner in owned]
    for owned in owned_by_field.values():
        for aside, _ in owned:
            aside.decompose()
    return popped


def pop_speaker_notes(soup: BeautifulSoup) -> List[Tuple[Tag, str]]:
    """Back-compatible: pop both asides, return only the notes pairs."""
    return pop_presenter_asides(soup)["speaker_notes"]


def text_for_root(root: Tag, popped: Sequence[Tuple[Tag, str]]) -> Optional[str]:
    ...  # body of the current notes_for_root, unchanged

notes_for_root = text_for_root


def extract_presenter_text(html: str) -> Tuple[str, Optional[str], Optional[str]]:
    if not html or (SPEAKER_NOTES_CLASS not in html and TALK_TRACK_CLASS not in html):
        return html, None, None
    soup = BeautifulSoup(html, "html.parser")
    popped = pop_presenter_asides(soup)
    if not popped["speaker_notes"] and not popped["talk_track"]:
        return html, None, None

    def joined(pairs):
        if not pairs:
            return None
        return "\n\n".join(text for _, text in pairs if text)

    return str(soup), joined(popped["speaker_notes"]), joined(popped["talk_track"])


def extract_speaker_notes(html: str) -> Tuple[str, Optional[str]]:
    stripped, notes, _talk = extract_presenter_text(html)
    return stripped, notes
```

Callers that use `pop_speaker_notes` before `find_slide_roots` (`SlideDeck.from_html_string`, `SlideGeneratorAgent._parse_slide_replacements` in `agent.py`) switch to `pop_presenter_asides` and read both lists. Do that for `slide_deck.py` here. `agent.py` is Task 2.

Then add `talk_track` and `talk_track_source` beside every `speaker_notes` and `speaker_notes_source` occurrence in the files listed above, with identical rules: `_stored_talk_track_source`, the two columns (`Text` and `String(16)`, nullable), `("talk_track", "TEXT NULL")` and `("talk_track_source", "VARCHAR(16) NULL")` added to the migration's column tuple, and the user-wins check in `_upsert_slide_row`'s partial branch applied per field:

```python
for field in ("speaker_notes", "talk_track"):
    text_value = slide_dict.get(field)
    src = slide_dict.get(f"{field}_source")
    if text_value is not None and not (
        getattr(existing, f"{field}_source") == "user" and src != "user"
    ):
        setattr(existing, field, text_value or None)
        setattr(existing, f"{field}_source", (src or "model") if text_value else None)
```

- [ ] **Step 4: Run the tests and confirm they pass**

Run: `uv run python -m pytest tests/unit/test_talk_track_storage.py tests/unit/test_speaker_notes_extraction.py tests/unit/test_speaker_notes_domain.py tests/unit/test_speaker_notes_persistence.py -q`
Expected: PASS.

- [ ] **Step 5: Sabotage-verify.** Break each guarded line in turn: drop `talk_track` from `to_dict`; remove the user-wins check for `talk_track`; remove the migration column. Confirm a named test goes red each time, restore, and confirm green. Paste the output.

- [ ] **Step 6: Commit**

```bash
git add src/utils/html_utils.py src/domain/ src/database/models/session.py src/core/database.py src/api/services/session_manager.py src/api/services/slide_repository.py tests/unit/test_talk_track_storage.py tests/unit/test_speaker_notes_extraction.py
git commit -m "feat(notes): store a per-slide talk track beside the notes"
```

---

### Task 2: Every arrival path carries both fields

Models: test=opus impl=opus

**Files:**
- Modify: `src/services/graph/nodes.py` (`builder_node`, `build_reviewer_node`, `_write_reviewed_row`, `_land_original`, `fixer_node`, `fix_reviewer_node`, `_write_draft_row`; `notes_reset` already exists in `build_branch_payload` and needs no change)
- Modify: `tests/unit/test_speaker_notes_save.py` (its `update_slide_notes` stub near line 400 gains the `talk_track` keyword)
- Modify: `src/services/agent.py` (Legacy-mode parse, around `pop_speaker_notes`)
- Modify: `src/api/services/chat_service.py` (`_carry_speaker_notes`, the replace loop near `valid_refs`, `original_authors`, `update_slide`, `insert_slide`, `update_slide_notes`)
- Modify: `src/api/routes/slides.py` (`UpdateSlideNotesRequest`, `update_slide_notes`)
- Test: `tests/unit/test_talk_track_arrival.py` (new). Read `tests/unit/test_speaker_notes_graph.py`, `test_speaker_notes_legacy.py` and `test_speaker_notes_save.py` first and reuse their fixtures and fakes.

**Interfaces:**
- Consumes: Task 1's `extract_presenter_text`, `pop_presenter_asides`, `text_for_root`, the `talk_track` slide fields, `SlideWriter.write_slide(talk_track=...)`.
- Produces:
  - Graph slide records carry `talk_track` beside `speaker_notes`; review entries carry `original_talk_track`.
  - `_carry_presenter_text(new_slide, orig_slide_like)` applies the carry rule per field (replaces `_carry_speaker_notes`; keep the old name as a thin wrapper only if a test imports it).
  - `ChatService.update_slide_notes(session_id, index, speaker_notes: Optional[str] = None, *, talk_track: Optional[str] = None, slide_id=None, expected_version=None)`. A field passed as `None` is left untouched. Returns `{index, slide_id, speaker_notes, talk_track, version}`.
  - `PATCH /api/slides/{index}/notes` body: `session_id`, optional `speaker_notes` (max 20000), optional `talk_track` (max 20000), `slide_id`, `expected_version`. At least one of the two text fields is required, or 422.

- [ ] **Step 1: Write the failing tests.** One test per arrival path, each asserting both fields and their sources:
  - `test_builder_moves_both_asides_before_gate`: a fake builder output with both asides. The gate's scanned HTML has no aside (spy on `gate_emitted_html`'s first argument), and the record has `talk_track` and `speaker_notes`.
  - `test_builder_retry_carries_talk_track`: the corrective retry's output brings a talk track; the record has the retry's text.
  - `test_build_turn_resets_missing_talk_track`: `notes_reset` set and no talk-track aside gives `talk_track == ""`.
  - `test_fixer_carries_talk_track` and `test_land_original_writes_original_talk_track`. Both assert the **stored row** through `SlideWriter.write_slide`'s recorded call, not only the state record.
  - `test_fix_reviewer_winning_fix_stores_talk_track` and `test_draft_row_fallback_stores_talk_track` (`fix_reviewer_node`, `_write_draft_row`; mirror `test_speaker_notes_graph.py` around lines 249 and 344-383).
  - `test_talk_track_never_reaches_a_model_payload`: extend the existing `test_notes_never_reach_a_model_payload` so neither `talk_track` nor `speaker_notes` appears in any agent payload.
  - `test_legacy_parse_reads_talk_track`: `SlideGeneratorAgent` replacement parse with both asides.
  - `test_rebuild_refreshes_model_field_only`: the original slide has a user talk track and model notes; the replacement brings both asides. Result: the user talk track is kept, the notes are refreshed.
  - `test_user_html_save_moves_talk_track_aside`: `update_slide` with a talk-track aside in the HTML sets source `user`. With no aside, it keeps the old pair.
  - `test_insert_with_talk_track_aside`.
  - `test_notes_save_with_only_talk_track_leaves_notes`: `update_slide_notes(..., talk_track="say this")` leaves `speaker_notes` text and source unchanged.
  - `test_notes_save_empty_talk_track_clears_it_and_source`.
  - `test_notes_route_requires_a_field`: a body with neither field gives 422.
  - `test_notes_route_old_client_body_still_works`: a body with only `speaker_notes` saves notes and leaves the talk track.

- [ ] **Step 2: Run and confirm red**

Run: `uv run python -m pytest tests/unit/test_talk_track_arrival.py -q`
Expected: FAIL (missing `talk_track` keys and the unknown `talk_track` keyword).

- [ ] **Step 3: Implement.** In `builder_node` and `fixer_node`, replace each `extract_speaker_notes(...)` call with `extract_presenter_text(...)` and keep a `captured = {"notes": ..., "talk": ...}` pair so the retry path wins for both. After the gate:

```python
if payload.get("notes_reset"):
    if speaker_notes is None:
        speaker_notes = ""
    if talk_track is None:
        talk_track = ""
record = {..., "speaker_notes": speaker_notes, "talk_track": talk_track}
```

Thread `talk_track` through `_write_reviewed_row(..., talk_track=None)` into `SlideWriter.write_slide(talk_track=...)`, and through the review entry as `original_talk_track`. In `chat_service.py`:

```python
_PRESENTER_FIELDS = ("speaker_notes", "talk_track")

def _carry_presenter_text(new_slide: Slide, orig: Any) -> None:
    """Per field: user text always survives; model text is kept only when the replacement brought none."""
    for field in _PRESENTER_FIELDS:
        orig_text = getattr(orig, field, None) if not isinstance(orig, dict) else orig.get(field)
        orig_src = (
            getattr(orig, f"{field}_source", None) if not isinstance(orig, dict) else orig.get(f"{field}_source")
        )
        if orig_src == "user" or getattr(new_slide, field) is None:
            setattr(new_slide, field, orig_text)
            setattr(new_slide, f"{field}_source", orig_src)
```

`update_slide_notes` saves each field that is not `None` exactly as it saves `speaker_notes` today (strip-empty to `""`, source `user` or `None`), and restores both old pairs on failure. Use a Pydantic `model_validator(mode="after")` on `UpdateSlideNotesRequest` to reject a body with both fields `None`.

- [ ] **Step 4: Run and confirm green**, together with the branch's existing notes suites:

Run: `uv run python -m pytest tests/unit/test_talk_track_arrival.py tests/unit/test_speaker_notes_graph.py tests/unit/test_speaker_notes_legacy.py tests/unit/test_speaker_notes_save.py tests/unit/test_slide_writer.py -q`
Expected: PASS.

- [ ] **Step 5: Sabotage-verify** at least: the per-field user check in `_carry_presenter_text`, the `talk_track` reset under `notes_reset`, the retry capture in `builder_node`, and the route validator. Paste the output.

- [ ] **Step 6: Commit**

```bash
git add src/services/graph/nodes.py src/services/agent.py src/api/services/chat_service.py src/api/routes/slides.py tests/unit/test_talk_track_arrival.py tests/unit/test_speaker_notes_save.py tests/unit/test_speaker_notes_graph.py
git commit -m "feat(notes): carry the talk track on every arrival path, each field protected on its own"
```

---

### Task 3: Exports write talk track, then "Notes:", then notes

Models: test=opus impl=haiku

**Files:**
- Modify: `src/api/routes/export.py` (`slide_notes_text`)
- Create: `frontend/src/services/presenterText.ts`
- Modify: `frontend/src/services/domWalker.ts` (`buildCompositeHtml` notes JSON), `frontend/src/services/api.ts` (the from-images `notes` list), `frontend/src/types/slide.ts`
- Modify: `docs/technical/export-features.md` ("Speaker Notes" section)
- Test: `tests/unit/test_speaker_notes_exports.py` (extend), `frontend/src/services/__tests__/speakerNotesExport.test.ts` (extend)

**Interfaces:**
- Consumes: slide dicts with `talk_track` and `speaker_notes` strings.
- Produces:
  - Python `slide_notes_text(slide: dict) -> str`.
  - TS `presenterPaneText(slide: { talk_track?: string; speaker_notes?: string; notes?: string }): string`, exported from `presenterText.ts`.
  - TS `Slide.talk_track?: string` and `Slide.talk_track_source?: 'model' | 'user' | null`.

- [ ] **Step 1: Write the failing tests.** Python:

```python
from src.api.routes.export import slide_notes_text

def test_pane_has_talk_track_then_notes_heading_then_notes():
    assert slide_notes_text({"talk_track": "Say A.", "speaker_notes": "Know B."}) == "Say A.\n\nNotes:\nKnow B."

def test_talk_track_only_has_no_heading():
    assert slide_notes_text({"talk_track": "Say A.", "speaker_notes": ""}) == "Say A."

def test_notes_only_slide_exports_unchanged():
    assert slide_notes_text({"speaker_notes": "Know B."}) == "Know B."

def test_legacy_notes_key_still_read_when_speaker_notes_absent():
    assert slide_notes_text({"notes": "old"}) == "old"

def test_cleared_notes_stay_cleared():
    assert slide_notes_text({"speaker_notes": "", "notes": "old"}) == ""
```

Add route-level cases for `huashu/from-html` and `google-slides/from-huashu` with a two-field slide, reusing the existing tests' fakes. TS: the same five cases for `presenterPaneText`, plus a `buildCompositeHtml` case where the embedded `speaker-notes` JSON holds the combined text with `<` escaped, plus the from-images request body holding the combined text.

- [ ] **Step 2: Run and confirm red**

Run: `uv run python -m pytest tests/unit/test_speaker_notes_exports.py -q` and `cd frontend && npx vitest run src/services/__tests__/speakerNotesExport.test.ts`
Expected: FAIL on the combined-text cases.

- [ ] **Step 3: Implement**

```python
def slide_notes_text(slide: dict) -> str:
    """Notes pane text: the talk track, then "Notes:", then the notes. Either part may be absent."""
    sn = slide.get("speaker_notes")
    notes = sn if isinstance(sn, str) else (slide.get("notes") or "")
    talk = slide.get("talk_track") if isinstance(slide.get("talk_track"), str) else ""
    talk, notes = talk.strip(), notes.strip()
    if talk and notes:
        return f"{talk}\n\nNotes:\n{notes}"
    return talk or notes
```

```ts
export function presenterPaneText(slide: { talk_track?: string; speaker_notes?: string; notes?: string }): string {
  const notes = (typeof slide.speaker_notes === 'string' ? slide.speaker_notes : slide.notes || '').trim();
  const talk = (typeof slide.talk_track === 'string' ? slide.talk_track : '').trim();
  if (talk && notes) return `${talk}\n\nNotes:\n${notes}`;
  return talk || notes;
}
```

Use `presenterPaneText` in `domWalker.ts` and in the from-images `notes` list in `api.ts`. Update the export doc's table intro to say the pane holds the talk track, then "Notes:", then the notes.

Trimming surrounding whitespace in the helper is a deliberate small change; say so in the export doc.

- [ ] **Step 4: Run and confirm green** (same commands). Expected: PASS.
- [ ] **Step 5: Sabotage-verify:** swap the order in each helper, and drop the `.strip()` in one. Paste the output.
- [ ] **Step 6: Commit**

```bash
git add src/api/routes/export.py frontend/src/services/presenterText.ts frontend/src/services/domWalker.ts frontend/src/services/api.ts frontend/src/types/slide.ts docs/technical/export-features.md tests/unit/test_speaker_notes_exports.py frontend/src/services/__tests__/speakerNotesExport.test.ts
git commit -m "feat(export): notes pane holds the talk track, then Notes:, then the notes"
```

---

### Task 4: Editor Notes tab with two boxes

Models: test=opus impl=sonnet

**Files:**
- Modify: `frontend/src/components/SlideViewer/FeedbackDrawer.tsx`, `frontend/src/components/SlideViewer/SlideViewer.tsx`, `frontend/src/services/api.ts` (`updateSlideNotes`)
- Test: `frontend/src/components/SlideViewer/FeedbackDrawer.test.tsx`, `SlideViewer.test.tsx`

**Interfaces:**
- Consumes: Task 2's route; Task 3's `Slide.talk_track`.
- Produces:
  - `api.updateSlideNotes(index, fields: { speaker_notes?: string; talk_track?: string }, sessionId, slideId?, expectedVersion?)`. It sends only the keys present.
  - `FeedbackDrawer` props: `speakerNotes`, `talkTrack`, `slideKey`, `onSaveNotes?: (fields: { speaker_notes?: string; talk_track?: string }) => Promise<void>`.
  - Test ids: `drawer-talk-input`, `drawer-talk-save`, `drawer-talk-error`, `drawer-notes-input`, `drawer-notes-save`, `drawer-notes-error`, `drawer-notes-hint`, read-only `drawer-talk`, `drawer-notes`, `drawer-notes-empty`.

- [ ] **Step 1: Write the failing tests:**
  - Both boxes render with the labels "Talk track" / "What you say." and "Notes" / "What you need to know.", and the hint reads exactly "Chat rewrites the talk track only when it rebuilds the slide."
  - Each Save is disabled until its own box is dirty, and disabled while that box saves.
  - `saving the talk track sends only talk_track`: `onSaveNotes` is called with `{ talk_track: 'x' }`, with no `speaker_notes` key, and vice versa.
  - A failed talk-track save shows `drawer-talk-error` only, and the notes draft is untouched.
  - A slide switch resets both drafts.
  - Read-only: no textareas. The talk track and notes show as text, or "No speaker notes for this slide." when both are empty.
  - In `SlideViewer.test.tsx`, `api.updateSlideNotes` is called with the fields object, and the deck refresh follows.

- [ ] **Step 2: Run and confirm red:** `cd frontend && npx vitest run src/components/SlideViewer/FeedbackDrawer.test.tsx src/components/SlideViewer/SlideViewer.test.tsx`
- [ ] **Step 3: Implement.** Two independent `{draft, saving, failed}` states. Pull the box into a local `PresenterTextBox` component in the same file (label, sublabel, textarea `maxLength={20000}`, Save button, error) to avoid repeating it. The existing single-box tests are updated to the new ids and labels, not deleted.
- [ ] **Step 4: Run and confirm green**, plus `npx tsc --noEmit`.
- [ ] **Step 5: Sabotage-verify:** send both keys from the talk save; share one `saving` flag across both boxes. Paste the output.
- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/SlideViewer/ frontend/src/services/api.ts
git commit -m "feat(editor): Notes tab has a talk track box and a notes box, each saved on its own"
```

---

### Task 5: Builder instruction through the eval harness

Models: test=opus impl=opus

**Files:**
- Already created during planning (check, do not recreate): `evals/configs/builder/presenter-text.md` (a copy of `one-footer-source.md` plus one block), `evals/configs/builder/presenter-text.yaml`. First confirm `one-footer-source.md` still byte-matches the manifest's builder `prompt_text` and that `diff one-footer-source.md presenter-text.md` shows only the PRESENTER TEXT block.
- Modify via promote only: `src/services/agent_definition_manifest_v1.py`, `tests/unit/test_packaged_release_loader.py`, `tests/unit/test_graph_definition_manifest.py`
- Modify by hand after promote: `src/core/skills/builder.py` `INSTRUCTIONS`, `HEAD_OTHER_ROLE_CONTENT_HASHES["builder"]` wherever it is pinned (`grep -rn HEAD_OTHER_ROLE_CONTENT_HASHES tests`), `frontend/tests/fixtures/graphLifecycleContract.json` (re-recorded)
- Modify: `evals/README.md` (a new dated section with the numbers)

**Interfaces:**
- Consumes: Tasks 1 and 2 (the asides are extracted on arrival, so they never reach the gate or the reviewers).
- Produces: a builder v1 prompt that asks for both asides.

- [ ] **Step 1: Check the builder is not a `LegacyV1PromptTransition` source.** `grep -n 'agent_key=' src/services/prompt_assembler.py` shows only `data_analyst` and `build_reviewer`. If `builder` appears, stop and report.
- [ ] **Step 2: Confirm the candidate.** `presenter-text.md` already holds this block once, directly after the `DATA ABSENT FALLBACK:` block, and nothing else differs from `one-footer-source.md`. Confirm with `diff`; never insert it a second time:

```
PRESENTER TEXT (every slide):
  - End the slide's root element with two hidden asides, talk track first:
    <aside data-presenter="talk-track" hidden><p>First beat.</p><p>Second beat.</p></aside>
    <aside data-presenter="speaker-notes" hidden><p>Source: ...</p><p>Likely question: ...</p></aside>
  - talk-track is what the presenter says: two to four short spoken beats, one <p> each, using the slide's own figures and names; lead into hands_off, and end on the question the slide answers when it poses one
  - Never write "click", "tap" or "on the slide" in the talk track
  - speaker-notes is what the presenter needs to know: the source of each figure from data_references, the likely question with a short answer, and what to stress
  - Neither aside says that data was unavailable
```

`presenter-text.yaml`:

```yaml
# Builder v1 prompt plus a PRESENTER TEXT block: each slide ends with a hidden talk-track aside
# and a hidden speaker-notes aside, which Tellr moves into the slide's fields on arrival.
agent_key: builder
name: builder-presenter-text
base: v1
prompt_file: presenter-text.md
```

- [ ] **Step 3: Baseline and candidate on train.** Profile `<profile>`, a workspace profile the author chooses, which must serve `databricks-claude-sonnet-5-5` and the judge `databricks-claude-sonnet-5`.

```bash
uv run python -m evals.run_eval --agent builder --config v1-baseline --repeats 3 --profile <profile>
uv run python -m evals.run_eval --agent builder --config evals/configs/builder/presenter-text.yaml --repeats 3 --profile <profile>
```

Acceptance: no train case drops by more than one repeat against the baseline, and at least 90% of candidate rows carry both asides on every slide root. Count this from the run's MLflow traces (`mlflow.db` at the repo root, experiment `tellr-agent-eval`, filtered by run id) with a throwaway script outside the repo; never add it to `evals/`. Locally the renderer must attach to the shared browser on port 9555, so run the harness through a wrapper outside the repo that points Playwright's `chromium.launch` at `connect_over_cdp`; a run whose rows show `render-failure` is void. Spend cap USD 15 for the pass. If a scorer fails rows because of the asides, stop and report. Never edit the scorer.
- [ ] **Step 4: Held-out once on the finalist.**

```bash
uv run python -m evals.run_eval --agent builder --calibrate --split heldout --profile <profile>
uv run python -m evals.run_eval --agent builder --config evals/configs/builder/presenter-text.yaml --repeats 3 --split heldout --profile <profile>
```

Report only the aggregate line. The bar is the current v1 prompt on the same model, judge and day: run `--config v1-baseline --split heldout --repeats 3` once as well, and a candidate below it by more than one row means stop and report.
- [ ] **Step 5: Promote.**

```bash
uv run python -m evals.harness.promote --config builder=evals/configs/builder/presenter-text.yaml --run-id builder=<train run id> --dry-run
uv run python -m evals.harness.promote --config builder=evals/configs/builder/presenter-text.yaml --run-id builder=<train run id>
DATABASE_URL=sqlite:////tmp/tellr-contract-rerecord.db uv run python -m tests.integration.graph_lifecycle_journey --write-contract frontend/tests/fixtures/graphLifecycleContract.json
```

Then make `src/core/skills/builder.py` `INSTRUCTIONS` byte-match the promoted prompt, and update `HEAD_OTHER_ROLE_CONTENT_HASHES["builder"]` and `OUTSIDE_DECK_STYLE_DIGESTS["builder"]` (`tests/unit/test_builder_deck_style_prompt.py` near line 1230; also check `tests/unit/test_architect_edit_prompt.py` near line 81).
- [ ] **Step 6: Tests.** `uv run python -m pytest tests/unit/test_packaged_release_loader.py tests/unit/test_graph_definition_manifest.py tests/unit/test_agent_runtime.py tests/unit/test_builder_deck_style_prompt.py tests/unit/test_architect_edit_prompt.py -q` and `cd frontend && npx vitest run --reporter=dot -t "lifecycle contract"` pass. Sabotage: flip one character in `INSTRUCTIONS` and confirm the skill-match test or the promote warning fires; restore.
- [ ] **Step 7: Record** in `evals/README.md` a section "Builder: talk track and notes asides, 2026-11-18" with the run ids, pass rates, mean and median latency, and mean input and output tokens for the baseline and the candidate, the held-out aggregate, and spend. Use the table shape of "Builder on Sonnet (Task 9b)".
- [ ] **Step 8: Commit**

```bash
git add evals/configs/builder/presenter-text.* evals/README.md src/services/agent_definition_manifest_v1.py src/core/skills/builder.py tests/unit/ frontend/tests/fixtures/graphLifecycleContract.json
git commit -m "feat(builder): each slide ends with a hidden talk track and notes"
```

---

### Task 6: Presenter window and sync

Models: test=opus impl=opus

**Files:**
- Create: `frontend/src/services/presenterChannel.ts`, `frontend/src/services/__tests__/presenterChannel.test.ts`
- Create: `frontend/src/components/Presenter/PresenterPage.tsx`, `frontend/src/components/Presenter/PresenterPage.test.tsx`, `frontend/src/components/Presenter/index.ts`
- Modify: `frontend/src/App.tsx` (route), `frontend/src/components/PresentationMode/PresentationMode.tsx` (+ its test)
- Create: `docs/technical/presenter-view.md`

**Interfaces:**
- Consumes: `api.getSlides(sessionId)` (view access is enough), `buildSlideDocument` and `slideHostFrameStyle` from `services/slideDocument.ts`, Task 1 and 3 slide fields.
- Produces:

```ts
// presenterChannel.ts
export type PresenterState = { type: 'state'; index: number; total: number; deckVersion: number | null };
export type PresenterCmd = { type: 'cmd'; action: 'next' | 'prev' | 'goto'; index?: number };
export type PresenterMessage = PresenterState | PresenterCmd;
export const channelName = (sessionId: string) => `tellr-present:${sessionId}`;
export const presenterWindowName = (sessionId: string) => `tellr-presenter-${sessionId}`;
export const PRESENTER_FEATURES = 'popup,width=1200,height=760';
export const LINK_TIMEOUT_MS = 3000;
export const STATE_HEARTBEAT_MS = 1000;
/** Opens or focuses the presenter window. Returns null when the browser blocked it. */
export function openPresenterWindow(sessionId: string): Window | null;
/** Opens the channel; returns a close function. Ignores malformed messages. */
export function joinPresenterChannel(sessionId: string, onMessage: (m: PresenterMessage) => void): {
  post: (m: PresenterMessage) => void;
  close: () => void;
};
```

- [ ] **Step 1: Write the failing tests.** Use a small in-memory `BroadcastChannel` fake installed on `globalThis` in each test file. Two instances with the same name deliver to each other, not to themselves.
  - `presenterChannel.test.ts`: messages round-trip; malformed messages (`{}`, `{type:'state'}` without an index, a string) are ignored; `openPresenterWindow` calls `window.open` with the exact URL `/sessions/<id>/present`, name and features, then `focus()`s the result; a second call while the window it returned is open and not `closed` calls only `focus()` on it, with no second `window.open` (a same-name `window.open` would reload the window and reset its clock); `returns null when the pop-up is blocked` (`window.open` returns `null`).
  - `PresenterPage.test.tsx` (mock `api.getSlides` with a three-slide deck that has talk tracks and notes):
    - Renders "Slide 2 of 3", the slide title (the first `h1`/`h2` text of the slide HTML, or "Slide 2"), an elapsed clock in `m:ss` that advances with fake timers, the **Read aloud** talk track, **Coming up** with the next slide's title and the first paragraph of its talk track, two preview iframes titled "On screen now" and "Up next" with `sandbox="allow-scripts"`, and the bottom bar.
    - On the last slide, Coming up reads "End of deck" and the Up next preview is absent.
    - Next and Back buttons, Right/Left/Space/Backspace keys post `cmd` messages and do not change the shown slide until a `state` message arrives.
    - N toggles the Notes drawer (`presenter-notes-drawer`) showing the notes; Esc closes it.
    - `shows not linked after 3 seconds of silence`: after a state message, "Slides: linked"; advance 3000 ms with no message, "Slides: not linked" and an "Open presentation" button that focuses the opener (`window.opener?.focus()`) or, with no opener, opens `/sessions/<id>/edit` in a new tab, never replacing the presenter.
    - A `state` message with a new `deckVersion` triggers a second `api.getSlides` call. `deckVersion` is the `version` of the deck snapshot presentation mode took when it opened (`SlideDeck.version`), so both windows show the same deck; when the fetched deck's `version` differs from the posted one, the presenter shows "Slides changed. Reopen the presentation to see them."
    - A **Notes** button in the bottom bar toggles the drawer, like N.
    - The first-run hint shows the exact text once, and is gone after reload (`localStorage` key `tellr-presenter-hint-seen`).
    - No textarea or editor control is rendered.
  - `PresentationMode.test.tsx`:
    - P and the "Presenter view" toolbar button (aria-label "Open presenter view") call `openPresenterWindow(sessionId)`. A second press calls it again; the window name makes the browser focus the same window.
    - On mount, on each slide change, and every second, it posts a `state` message with the right index, total and deck version.
    - A `cmd` `next`, `prev` or `goto` moves the slide, clamped to the deck.
    - The N panel shows the talk track and starts hidden; with no talk track it falls back to the notes, then to "No speaker notes for this slide."
    - A forwarded `tellr:slide-key` with key `p` opens the presenter window.

- [ ] **Step 2: Run and confirm red:** `cd frontend && npx vitest run src/services/__tests__/presenterChannel.test.ts src/components/Presenter src/components/PresentationMode`
- [ ] **Step 3: Implement.**
  - `PresentationMode` gains a `sessionId?: string` prop, passed from its two callers, `SlideViewer.tsx` and `SlidePanel.tsx` (grep `<PresentationMode` to confirm). Without a `sessionId` the presenter button is hidden and P does nothing.
  - The P key handling lives in the same `handleKeyDownRef` switch (`case 'p': case 'P':`).
  - The channel is joined in one `useEffect` keyed on `sessionId`. Use a heartbeat `setInterval(STATE_HEARTBEAT_MS)`, plus an immediate post on index change.
  - `PresenterPage` reads `sessionId` from `useParams`. It is rendered by a new route `<Route path="/sessions/:sessionId/present" element={<PresenterPage />} />` placed before the `*` route and outside `AppLayout`.
  - Layout, top to bottom: header row ("Slide N of M", title, clock); Read aloud (large type, about 24px, one paragraph per beat); Coming up; a two-column row of previews (each a 16:9 box scaling a 1280×720 `buildSlideDocument` frame with `slideHostFrameStyle`, `sandbox="allow-scripts"`, `pointer-events:none`); the Notes drawer; the bottom bar (Back, Next, "← → move · N notes", link status).
  - Before the first state message arrives, show slide 1 and "Slides: not linked".
  - Write `docs/technical/presenter-view.md`: the route, the channel name and message shapes, the heartbeat and timeout, why presentation mode is the only source of truth, and the read-only scope.
- [ ] **Step 4: Run and confirm green**, plus `npx tsc --noEmit` and `npx eslint` on the touched files.
- [ ] **Step 5: Sabotage-verify:** make the presenter move on its own Next without a state message; drop the heartbeat; change the timeout to 30 s; render the N panel from notes first. Paste the output.
- [ ] **Step 6: Commit**

```bash
git add frontend/src/services/presenterChannel.ts frontend/src/services/__tests__/presenterChannel.test.ts frontend/src/components/Presenter/ frontend/src/App.tsx frontend/src/components/PresentationMode/ frontend/src/components/SlideViewer/ frontend/src/components/SlidePanel/ docs/technical/presenter-view.md
git commit -m "feat(present): presenter window with read-aloud talk track, previews and two-way stepping"
```

---

### Task 7: End-to-end presenter test

Models: test=opus impl=sonnet

**Files:**
- Create: `frontend/tests/e2e/presenter-view.spec.ts`

**Interfaces:**
- Consumes: Task 6's route, test ids and channel; the mocking helpers used by `frontend/tests/e2e/findings-drawer.spec.ts` (read it first and reuse its route mocks and fixtures).

- [ ] **Step 1: Write the test.** Mock with `context.route`, not `page.route`, so the presenter pop-up's own requests are mocked too (review B3). Mock the session and slides API with a three-slide deck that has a talk track and notes on each slide. Open `/sessions/<id>/edit`, start presenting, press P, and catch the pop-up with `context.waitForEvent('page')`. In the presenter page, assert "Slide 1 of 3" and slide 1's talk track. Press ArrowRight in the presenter, then assert both windows show slide 2: the presentation counter reads "2 / 3", and the presenter shows "Slide 2 of 3" and slide 2's talk track. Press ArrowLeft in the presentation window and assert both windows show slide 1. Open the Notes drawer with N and assert slide 1's notes text.
- [ ] **Step 2: Run it.** In CI it uses the repo's Playwright config. Locally it must attach to the shared browser on port 9555, never launch one. A Playwright config cannot override fixtures, so use an untracked local spec wrapper outside `frontend/tests/` that imports the spec's test body and runs it with a `test.extend` worker fixture `browser: chromium.connectOverCDP('http://127.0.0.1:9555')`, against the local dev server. If that is not workable, run the same steps as a standalone script over CDP and record it; never launch a browser.
Expected: PASS. Sabotage: comment out the presenter's state handler and confirm red; restore.
- [ ] **Step 3: Commit**

```bash
git add frontend/tests/e2e/presenter-view.spec.ts
git commit -m "test(e2e): presenter window steps both ways with presentation mode"
```

---

### Task 8: Full suites, live check, PR materials

Models: test=opus impl=opus

- [ ] **Step 1: Full suites.** `uv run python -m pytest -q -n 8 -m "not live and not integration"`, `cd frontend && npx tsc --noEmit && npx vitest run`, `npx eslint` on every touched frontend file. Treat each failure by cause: a failure the branch does not touch, which passes alone, is recorded, not fixed.
- [ ] **Step 2: Live check on a local Tellr.** The promoted builder prompt reaches a local install through `ship_packaged_graph_configuration` at startup only on an untouched database; on the existing local database, adopt it as an admin (the packaged-update badge), then confirm the builder definition's content hash matches the promoted one. Pass conditions, each with a saved log or screenshot outside the repo:
  1. A new Agent-mode deck with no design system: every slide has a non-empty model talk track and notes, and no slide HTML contains `data-presenter` or a presenter aside.
  2. Every talk track has two to four paragraphs and contains none of "click", "tap", "on the slide".
  3. A deck built from a data source: every figure on a data slide appears in its notes with a source from the slide's `data_references`.
  4. A typed talk track and typed notes both survive a chat rebuild of that slide; model text on another slide changes.
  5. Saving one box leaves the other box's text and source unchanged (read the row).
  6. P inside the slide frame, and the toolbar button, open one presenter window; a second press focuses it without reloading (the clock keeps counting).
  7. Next and Back in each window move both. "Slides: linked" shows, and "Slides: not linked" within 4 seconds of leaving presentation mode.
  8. Read aloud, Coming up, both previews, the clock and the Notes drawer match the current slide.
  9. The first-run hint shows once. The N panel starts hidden and shows the talk track.
  10. The PowerPoint notes pane holds the talk track, then "Notes:", then the notes, on every slide.
  11. A view-only user can open the presenter window and sees no editor.
  12. Build time over at least three decks each, before and after the builder change, from `chat_requests` timestamps. Output tokens per slide come from the Task 5 eval runs (the `chat_requests` table stores no token counts).
  13. The author tries it before anything is pushed.
- [ ] **Step 3: PR body** with `## What's new` (one bullet each for the talk track and notes on every slide, the two editor boxes, the presenter window, and the export pane), the deferral in `docs/superpowers/specs/2026-08-03-flip-through-viewer-design.md` section 1.1 as the opening, how the new builder version reaches users (`ship_packaged_graph_configuration` for an untouched install, the admin badge and Adopt for a running one, per `src/services/graph_configuration.py`), and the eval numbers. Written outside the repository, in the author's working folder beside the build handoff, as `PR-BODY-speaker-notes-presenter.md`, with the Slack note to Robert and Tariq in `SLACK-robert-tariq-speaker-notes-pr.md` in the same folder, for the author's approval. Commit any doc fixes from the live check with `git commit -m "docs: presenter view live-check fixes"`. Nothing is pushed or opened without the author's go.
