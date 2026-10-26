# App Tour Rebuild for Graph Generation — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Also load `executing-plans-tellr` (repo CLAUDE.md). Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild the onboarding tour (`frontend/src/components/Tour/AppTour.tsx`) so it teaches how decks are generated today — the multi-agent ("graph") pipeline — using a deterministic, staged demo deck, and so it covers the features the old tour never reached (findings drawer, verification badge, Spec view, design systems, pinned graph version, editing a slide by asking).

**Architecture:** The backend tour route (`src/api/routes/tour.py`) grows from two phases to a forward-only sequence of idempotent **stages** (`prompt → plan → build → review → edit`). Each stage persists exactly what a real graph turn would leave behind at that point (chat lines, slides, deck spec, seeded reviewer findings and verification records) from a hand-authored fixture. The frontend tour advances one stage per demo step through a small runner module, reloads the session through the existing `tour:refresh-session` event, and drives two new UI bridges (`tour:show-view` for Slides/Spec, `tour:viewer` for slide index + feedback drawer). No LLM is called at any point.

**Tech Stack:** FastAPI + SQLAlchemy (pytest, in-memory engine fixtures in `tests/unit/conftest.py`); React 19 + Vite + react-joyride 3.0.2 (vitest + Testing Library); Playwright e2e with mocked API (`frontend/tests/e2e`).

**Spec:** No separate spec doc. This plan argues from the gap analysis agreed with the author on 2026-10-13 (conversation record), summarised in *Background* below. Author decisions: staged fixture (not a replayed stream, not real generation); **no** agent labels in `Message.tsx` — the tour copy explains who is speaking; this plan covers the **tour only** — the WelcomeModal and Help page get a separate follow-up plan; admin onboarding is out of scope.

## Background — the gaps this plan closes

1. The tour's generation story describes the retired single-shot mode ("type a request, the AI generates a full deck"). Today a turn runs the graph: the **architect** replies with a plan (or asks a clarifying question), the **foreman** posts `Building N slide(s).`, slides land one at a time, a **build reviewer** posts `Slide N reviewed: clean|surfaced.` for each, objective problems are auto-fixed, and a **deck reviewer** posts a deck-level advisory.
2. The demo (`tour.py`) writes one user message and one canned old-style reply, then drops three slides at once.
3. The Spec view (`view-toggle-spec`, `spec-view`) is never shown, although the fixture already ships a hand-authored `deck_spec`.
4. Editing: the main way to edit a slide is to **ask in chat** ("make slide 2 more concise") — the architect resolves the target. The tour never shows this. (Multi-select was removed.)
5. Design systems (sidebar page, config-bar picker, dependent template picker) are never covered; a design system takes precedence over a slide style.
6. The pinned-graph-version badge (`graph-version-status`) renders on every session and is unexplained; the mixed-release warning on shared decks likewise.
7. Findings drawer (Apply / Dismiss / Discuss), unread-finding dots on thumbnails, and the verification badge are never covered.
8. The demo reply uses `**markdown**` which `Message.tsx` renders literally.

## Global Constraints

- Python env is a **shared pyenv site-packages** — never `pip install` anything.
- Frontend type-check is `npm run typecheck` (= `tsc -b`) or `npm run build`. Root `tsc --noEmit` checks nothing. If this worktree has no `frontend/node_modules`, symlink `/Users/robert.whiffin/Documents/slide-generator/ai-slide-generator/frontend/node_modules` into a temp copy rather than installing.
- Frontend unit tests: `cd frontend && npx vitest run <path>`. E2E: `cd frontend && npx playwright test <spec>` (API is mocked with `page.route`; no backend needed).
- Backend tests: `pytest <path> -v` from the repo root.
- The tour must never trigger an LLM call: no `spec_sync.mark_dirty`, no chat request, and every demo slide must carry a stored verification record so `useAutoVerification` (fires on any slide whose `verification` is falsy — `frontend/src/hooks/useAutoVerification.ts:155-178`) skips it.
- Fixture chat lines must use the graph's real wording **byte-for-byte**: foreman `f"Building {len(batch)} slide(s)."` (`src/services/graph/nodes.py:2080`), build reviewer `f"Slide {position} reviewed: {verdict}."` (`nodes.py:2365`, `position` is **0-indexed**), deck reviewer advisory from `_advisory_text` (`nodes.py:1251-1269`; no-findings form `"Deck review complete: no narrative issues found across the deck."`).
- No markdown in any fixture chat line (`Message.tsx` renders `whitespace-pre-wrap` plain text).
- Tour copy is plain professional English, second person, ≤ 60 words per step, no emoji.
- All existing tour targets that are kept must still resolve; every new target must be a selector that already exists (or is added by this plan) in non-test source.
- The demo session is deleted at tour end (existing `scheduleDeleteTourDemoSession`); deletion cascades messages, slides and verification records (`src/database/models/session.py` cascades).

## Review Focus

1. **Back / Next re-entry.** react-joyride runs a step's `before` hook every time the step is entered, including via Back. Re-running a stage must be a no-op server-side and must not duplicate chat lines. Pinned by Task 2 (`test_rerunning_a_stage_is_a_noop`) and Task 3 (`runStage is idempotent`).
2. **Out-of-order stage call** (e.g. a step's `before` hook fails and the user presses Next, so `build` is requested before `plan`). Expect a 409 and an unchanged session, and the frontend tour must keep going instead of hanging. Pinned by Task 2 (`test_stage_out_of_order_is_409_and_writes_nothing`) and Task 3 (`a failed stage resolves and does not throw`).
3. **Auto-verification firing on demo slides**, including the slide rewritten by the `edit` stage, whose content hash is new. Every slide must have `verification` after every stage. Pinned by Task 2 (`test_every_slide_is_verified_after_every_stage`).
4. **Skipping the tour mid-demo** (after `build`, before `edit`) must still delete the demo session and leave the user on an empty workspace. The deletion path is unchanged, but Task 6's e2e skips mid-demo and asserts DELETE was called.
5. **A user who already has the drawer open or Spec showing** from earlier use. Both are persisted or local state, so the bridges must set state explicitly rather than toggle it. Pinned by Task 4 (`tour:viewer sets drawerOpen=true even when already open`, and `tour:show-view spec is idempotent`).

---

## File Structure

| File | Change | Responsibility |
|---|---|---|
| `src/api/fixtures/tour_demo_deck.json` | Modify | Hand-authored demo: deck, spec, and a `stages` script (chat lines, findings, verification, edit) |
| `src/api/routes/tour.py` | Modify | Stage runner: `STAGES`, `_run_stage(session_id, stage, created_by)`, `POST /api/tour/demo-deck/{session_id}/stages/{stage}`; remove `/slides` |
| `tests/unit/test_tour_fixture_script.py` | Create | Fixture content contract (wording, findings validity, edit differs, no markdown) |
| `tests/unit/test_tour_staged_demo.py` | Create | Stage persistence, ordering, idempotency, verification coverage |
| `tests/unit/test_tour_ships_a_spec.py` | Modify | Re-point `_run_the_tour` at the stage runner; keep every existing pin |
| `tests/unit/test_authz_tour.py` | Modify | Gate test on the new stage endpoint |
| `frontend/src/services/api.ts` | Modify | `runTourDemoStage`; remove `addTourDemoSlides` |
| `frontend/src/components/Tour/tourDemo.ts` | Create | Demo runner: create, idempotent `runStage`, view/viewer helpers, delete |
| `frontend/src/components/Tour/tourDemo.test.ts` | Create | Runner unit tests |
| `frontend/src/components/Layout/AppLayout.tsx` | Modify | `tour:show-view` listener |
| `frontend/src/components/SlideViewer/SlideViewer.tsx` | Modify | `tour:viewer` listener inside `ViewerBody` |
| `frontend/src/components/SlideViewer/TourViewerBridge.test.tsx` | Create | Bridge unit tests |
| `frontend/src/components/Tour/tourSteps.ts` | Create | The step list (data only), exported `TOUR_STEPS` |
| `frontend/src/components/Tour/tourSteps.test.ts` | Create | Step contract: targets exist in source, order, stale-claim guards |
| `frontend/src/components/Tour/AppTour.tsx` | Modify | Render `TOUR_STEPS`; keep Joyride options and end handling |
| `frontend/tests/e2e/app-tour.spec.ts` | Create | Full tour walk with mocked staged API |

---

### Task 1: Author the staged demo script in the fixture

**Models:** `test=opus impl=sonnet`. The copy and the reviewer finding need judgement. The wording rules are mechanical and pinned by the tests.

**Files:**
- Modify: `src/api/fixtures/tour_demo_deck.json`
- Create: `tests/unit/test_tour_fixture_script.py`

**Interfaces:**
- Produces: fixture keys consumed by Task 2.
  - Unchanged: `title`, `css`, `external_scripts`, `scripts`, `slides`, `deck_spec`, `chat_prompt`. `chat_prompt` is kept verbatim because `tests/integration/test_conversation_creator_exclusions_postgres.py:145` reads it.
  - Removed: `chat_reply`.
  - New: `stages`:

```jsonc
"stages": {
  "plan": {
    "architect_reply": "<plain text, 2-4 sentences: who the deck is for, the argument, '3 slides: a title, four present-day advantages, and a forward look.'>"
  },
  "build": {
    "foreman_line": "Building 3 slide(s).",
    "review_lines": ["Slide 0 reviewed: clean.", "Slide 1 reviewed: clean.", "Slide 2 reviewed: surfaced."],
    "findings": {               // keyed by 0-indexed position (string keys, JSON)
      "2": [{ "criterion": "brief_not_delivered", "category": "content", "objective": false,
               "message": "<one sentence: the slide names future developments but not when the reader should expect them, which the brief asked for>" }]
    },
    "verification": { "rating": "unknown", "score": 0,
                      "explanation": "No source data to check: this deck was written without data tools." }
  },
  "review": {
    "advisory": "Deck review complete: no narrative issues found across the deck."
  },
  "edit": {
    "user_prompt": "Make slide 2 more concise",
    "architect_reply": "Editing slide 2.",
    "position": 1,
    "slide": { "index": 1, "slide_id": "<same id as slides[1]>", "html": "<slides[1].html with each advantage reduced to its bold label plus a 3-6 word phrase>", "scripts": "" },
    "content_brief": "Four bolded items, each with a short phrase: early disease detection, personalized treatment plans, operational efficiency, drug discovery acceleration.",
    "review_line": "Slide 1 reviewed: clean."
  }
}
```

Note on `verification.rating = "unknown"`: this is the honest result. The real judge returns `unknown` when there is no source data (`frontend/src/types/verification.ts:8`), and the demo deck has none. The author may switch it to `green` at review. If they do, change the test below too.

- [ ] **Step 1: Write the failing test** `tests/unit/test_tour_fixture_script.py`:

```python
"""Contract for the tour demo's staged script (src/api/fixtures/tour_demo_deck.json).

The tour shows what a real graph turn produces, so every chat line the fixture
plays must be the graph's own wording.  Formats are copied from
src/services/graph/nodes.py (foreman :2080, build reviewer :2365 — 0-indexed
position — deck reviewer _advisory_text :1251-1269).  If those formats change,
this test is the reminder to change the fixture.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from src.domain.finding import CRITERIA

_FIXTURE = Path(__file__).resolve().parents[2] / "src/api/fixtures/tour_demo_deck.json"
_MARKDOWN = re.compile(r"\*\*|__|^#{1,6} |^\s*[-*] ", re.M)


def _fx() -> dict:
    return json.loads(_FIXTURE.read_text(encoding="utf-8"))


def _all_chat_lines(fx: dict) -> list[str]:
    s = fx["stages"]
    return [
        s["plan"]["architect_reply"],
        s["build"]["foreman_line"],
        *s["build"]["review_lines"],
        s["review"]["advisory"],
        s["edit"]["user_prompt"],
        s["edit"]["architect_reply"],
        s["edit"]["review_line"],
    ]


def test_legacy_single_reply_is_gone():
    assert "chat_reply" not in _fx()


def test_chat_prompt_is_kept_for_the_engine_selection_test():
    assert _fx()["chat_prompt"].startswith("Create 3 slides about the benefits of AI")


def test_foreman_line_is_the_real_format_for_the_real_slide_count():
    fx = _fx()
    assert fx["stages"]["build"]["foreman_line"] == f"Building {len(fx['slides'])} slide(s)."


def test_one_review_line_per_slide_in_position_order_with_real_verdicts():
    fx = _fx()
    lines = fx["stages"]["build"]["review_lines"]
    assert len(lines) == len(fx["slides"])
    for position, line in enumerate(lines):
        m = re.fullmatch(r"Slide (\d+) reviewed: (clean|surfaced)\.", line)
        assert m, line
        assert int(m.group(1)) == position  # 0-indexed, as nodes.py:2365 emits


def test_surfaced_verdict_iff_the_slide_has_findings():
    fx = _fx()
    findings = fx["stages"]["build"]["findings"]
    for position, line in enumerate(fx["stages"]["build"]["review_lines"]):
        has = bool(findings.get(str(position)))
        assert line.endswith("surfaced.") == has, (position, line)
    assert any(findings.values()), "the demo must surface at least one finding for the drawer step"


def test_findings_use_real_subjective_slide_criteria():
    # An objective finding would have been auto-fixed by the fixer before the
    # user saw it, so a demo that surfaces one would teach the wrong thing.
    for items in _fx()["stages"]["build"]["findings"].values():
        for f in items:
            crit = CRITERIA[f["criterion"]]
            assert crit.level == "slide"
            assert crit.objective is False and f["objective"] is False
            assert f["category"] == crit.category
            assert 20 <= len(f["message"]) <= 240


def test_deck_advisory_is_the_real_no_findings_sentence():
    assert _fx()["stages"]["review"]["advisory"] == (
        "Deck review complete: no narrative issues found across the deck."
    )


def test_edit_targets_slide_two_by_its_human_number_and_changes_only_its_html():
    fx = _fx()
    edit = fx["stages"]["edit"]
    assert edit["position"] == 1
    assert "slide 2" in edit["user_prompt"].lower()
    assert edit["architect_reply"] == "Editing slide 2."
    original = fx["slides"][1]
    assert edit["slide"]["slide_id"] == original["slide_id"]
    assert edit["slide"]["html"] != original["html"]
    assert len(edit["slide"]["html"]) < len(original["html"])
    assert 'class="slide' in edit["slide"]["html"] or "class='slide" in edit["slide"]["html"]
    assert edit["review_line"] == "Slide 1 reviewed: clean."
    assert edit["content_brief"] != fx["deck_spec"]["slides"][1]["content_brief"]


def test_every_slide_html_is_distinct_so_verification_hashes_do_not_collide():
    fx = _fx()
    htmls = [s["html"] for s in fx["slides"]] + [fx["stages"]["edit"]["slide"]["html"]]
    assert len(set(htmls)) == len(htmls)


def test_no_chat_line_contains_markdown():
    for line in _all_chat_lines(_fx()):
        assert not _MARKDOWN.search(line), line


def test_verification_seed_is_a_valid_rating():
    v = _fx()["stages"]["build"]["verification"]
    assert v["rating"] in {"green", "amber", "red", "unknown"}
    assert isinstance(v["score"], (int, float)) and v["explanation"]
```

- [ ] **Step 2: Run it and check it fails**

Run: `pytest tests/unit/test_tour_fixture_script.py -v`
Expected: FAIL. Most tests fail with `KeyError: 'stages'`, and `test_legacy_single_reply_is_gone` fails too.

- [ ] **Step 3: Edit the fixture.** Delete `chat_reply`. Add `stages` exactly as in the Interfaces block, filling the `<…>` text by these rules:
  - **architect_reply:** plain prose, no markdown, no lists.
  - **Finding message:** one sentence that is true of the actual `slides[2]` HTML. Read the slide first.
  - **Edited slide 2:** keep every element, class and the `slide_id` of `slides[1].html`. Shorten only the explanatory clause after each bold label.

- [ ] **Step 4: Run the tests and check they pass**

Run: `pytest tests/unit/test_tour_fixture_script.py tests/unit/test_tour_ships_a_spec.py::TestTheFixtureShipsAHandAuthoredArc -v`
Expected: PASS. The existing arc tests must stay green.

- [ ] **Step 5: Sabotage-check, then commit.** Change `"Slide 2 reviewed: surfaced."` to `"Slide 3 reviewed: surfaced."`, run the tests, and confirm they go red. Revert. Then:

```bash
git add src/api/fixtures/tour_demo_deck.json tests/unit/test_tour_fixture_script.py
git commit -m "feat(tour): script the demo as staged graph output in the fixture"
```

---

### Task 2: Stage runner and endpoint in `tour.py`

**Models:** `test=opus impl=sonnet`. The persistence semantics are subtle: `save_slide_deck` replaces every slide row, and verification is keyed by content hash.

**Files:**
- Modify: `src/api/routes/tour.py`
- Create: `tests/unit/test_tour_staged_demo.py`
- Modify: `tests/unit/test_tour_ships_a_spec.py:37,85-91` (imports and `_run_the_tour`), `tests/unit/test_authz_tour.py`

**Interfaces:**
- Consumes: the fixture `stages` from Task 1. Also these existing functions:
  - `SessionManager.add_message(session_id, role, content, message_type=None, metadata=None, request_id=None)` (`session_manager.py:1462`)
  - `save_slide_deck(...)` (`:1542`), which **replaces** all slide rows
  - `write_slide_verification(session_id, position, verification_record)` (`:2068`), which **merges** into `{content_hash: slot}`
  - `get_slide_deck(session_id)`, which returns `slides[i].verification` and a flat `findings` list
  - `write_deck_level_columns(session_id, *, deck_spec=..., modified_by=..., mutation=...)` (`deck_level_writer.py:153`)
  - `compute_slide_hash(html)` (`src/utils/slide_hash.py:52`)
  - `Finding`, `make_finding_id(criterion, subject_hash, ordinal)`, `build_verification_record(*, content_hash, findings, verdict)` (`src/domain/finding.py`)
- Produces:
  - `STAGES: tuple[str, ...] = ("prompt", "plan", "build", "review", "edit")`
  - `class StageOrderError(Exception)`
  - `_phase1_create_session(created_by) -> {"session_id", "title"}`. Unchanged signature. It now also tags the user message `metadata={"tour_stage": "prompt"}`.
  - `_run_stage(session_id: str, stage: str, created_by: str) -> {"session_id": str, "stage": str, "applied": bool, "slide_count": int}`
  - Route `POST /api/tour/demo-deck/{session_id}/stages/{stage}`. It requires `CAN_EDIT` and returns the dict above. It returns 404 for an unknown stage and 409 for `StageOrderError`.
  - `_phase2_add_slides` and the `/slides` route are **removed**.

What each stage writes. Every chat row carries `metadata={"tour_stage": <stage>, "node": <node>}`. Architect rows use `message_type="llm_response"`. Foreman and reviewer rows use `message_type="info"`. The user row uses `"chat"`.

| Stage | Rows (role / node) | Deck writes |
|---|---|---|
| prompt | user `chat_prompt` | — (phase 1) |
| plan | assistant/architect `plan.architect_reply` | — |
| build | assistant/foreman `foreman_line`; then assistant/build_reviewer `review_lines[*]` | `save_slide_deck` (all 3 slides) → `write_deck_level_columns(deck_spec=fixture.deck_spec)` → verification for **every** slide |
| review | assistant/deck_reviewer `review.advisory` | — |
| edit | user `edit.user_prompt`; assistant/architect `edit.architect_reply`; assistant/build_reviewer `edit.review_line` | `save_slide_deck` with slide `edit.position` swapped → `write_deck_level_columns(deck_spec=spec with slides[position].content_brief = edit.content_brief)` → verification for **every** slide |

Verification for a slide is one `write_slide_verification` call. Its record is `{hash: {**judge, "tellr_review": {"verdict": v, "findings": [...]}}}`, where:
- `judge = {"score", "rating", "explanation"}` from `build.verification`, plus `"issues": [], "duration_ms": 0, "error": False`.
- `v` is `"surfaced"` if the position has findings in this stage's state, otherwise `"clean"`.
- The findings are built with `Finding(id=make_finding_id(criterion, hash, ordinal=i), slide_index=position, ...)`.

Build the nested part with `build_verification_record` and merge `judge` into the same slot. That is the documented shared slot (`session_manager.py:2088-2093`). In the `edit` stage, slide 1's findings are `[]`, and slide 2's finding still applies (same HTML, same hash).

Idempotency and ordering:
- **Re-run:** if any message in the session has `metadata.tour_stage == stage`, return `applied: False` and write nothing.
- **Order:** otherwise, the previous stage in `STAGES` must have a tagged message, or raise `StageOrderError`.
- **Atomicity:** check before writing anything, so a rejected call writes nothing.

- [ ] **Step 1: Write the failing tests** `tests/unit/test_tour_staged_demo.py`:

```python
"""The tour's staged demo: each stage persists one beat of a graph turn."""
from __future__ import annotations

import contextlib

import pytest
from unittest.mock import patch

from src.api.routes.tour import STAGES, StageOrderError, _phase1_create_session, _run_stage
from src.api.services.deck_level_writer import read_deck_spec
from src.api.services.session_manager import get_session_manager
from src.api.routes.tour import _load_fixture
from tests.unit.conftest import _make_fake_db, _make_factory, _make_in_memory_engine

_USER = "tour-taker@example.com"
_PATCHES = (
    "src.api.services.session_manager.get_db_session",
    "src.api.services.deck_level_writer.get_db_session",
)


@contextlib.contextmanager
def _patched(factory):
    fake = _make_fake_db(factory)
    with contextlib.ExitStack() as stack:
        for target in _PATCHES:
            stack.enter_context(patch(target, fake))
        yield


@pytest.fixture
def db():
    engine = _make_in_memory_engine()
    try:
        factory = _make_factory(engine)
        from src.services.graph_configuration import bootstrap_graph_configuration
        bootstrap_graph_configuration(factory)
        with _patched(factory):
            yield factory
    finally:
        engine.dispose()


def _start() -> str:
    return _phase1_create_session(_USER)["session_id"]


def _run_through(sid: str, last: str) -> None:
    for stage in STAGES[1 : STAGES.index(last) + 1]:
        _run_stage(sid, stage, _USER)


def _chat(sid):
    return [(m["role"], m["content"]) for m in get_session_manager().get_messages(sid)]


def test_stage_order_is_the_documented_one():
    assert STAGES == ("prompt", "plan", "build", "review", "edit")


def test_full_run_leaves_the_chat_a_real_graph_turn_would_show(db):
    fx = _load_fixture()["stages"]
    sid = _start()
    _run_through(sid, "edit")
    assert _chat(sid) == [
        ("user", _load_fixture()["chat_prompt"]),
        ("assistant", fx["plan"]["architect_reply"]),
        ("assistant", fx["build"]["foreman_line"]),
        *[("assistant", line) for line in fx["build"]["review_lines"]],
        ("assistant", fx["review"]["advisory"]),
        ("user", fx["edit"]["user_prompt"]),
        ("assistant", fx["edit"]["architect_reply"]),
        ("assistant", fx["edit"]["review_line"]),
    ]


def test_message_types_and_nodes_mirror_the_graph(db):
    sid = _start()
    _run_through(sid, "edit")
    rows = get_session_manager().get_messages(sid)
    by_node = {}
    for m in rows:
        if m["role"] == "assistant":
            by_node.setdefault(m["metadata"]["node"], set()).add(m["message_type"])
    assert by_node == {
        "architect": {"llm_response"},
        "foreman": {"info"},
        "build_reviewer": {"info"},
        "deck_reviewer": {"info"},
    }


def test_no_slides_before_build_and_three_after(db):
    sid = _start()
    _run_through(sid, "plan")
    assert not (get_session_manager().get_slide_deck(sid) or {}).get("slides")
    _run_stage(sid, "build", _USER)
    assert len(get_session_manager().get_slide_deck(sid)["slides"]) == 3


def test_build_persists_the_spec(db):
    sid = _start()
    _run_through(sid, "build")
    assert read_deck_spec(sid)["narrative_arc"] == _load_fixture()["deck_spec"]["narrative_arc"]


@pytest.mark.parametrize("last", ["build", "review", "edit"])
def test_every_slide_is_verified_after_every_stage(db, last):
    # useAutoVerification fires an LLM judge on any slide whose verification is
    # falsy; the demo must never cost a model call.
    sid = _start()
    _run_through(sid, last)
    deck = get_session_manager().get_slide_deck(sid)
    for slide in deck["slides"]:
        assert slide.get("verification"), slide["index"]
        assert slide["verification"]["rating"] == _load_fixture()["stages"]["build"]["verification"]["rating"]


def test_the_surfaced_finding_reaches_the_flat_findings_list(db):
    sid = _start()
    _run_through(sid, "build")
    findings = get_session_manager().get_slide_deck(sid)["findings"]
    assert [(f["slideIndex"], f["criterion"], f["status"]) for f in findings] == [
        (2, "brief_not_delivered", "open")
    ]
    assert findings[0]["id"].startswith("brief_not_delivered:")


def test_edit_changes_only_the_target_slide_and_its_brief(db):
    fx = _load_fixture()
    sid = _start()
    _run_through(sid, "review")
    before = get_session_manager().get_slide_deck(sid)["slides"]
    _run_stage(sid, "edit", _USER)
    after = get_session_manager().get_slide_deck(sid)["slides"]
    assert after[1]["html"] == fx["stages"]["edit"]["slide"]["html"]
    assert [after[0]["html"], after[2]["html"]] == [before[0]["html"], before[2]["html"]]
    spec = read_deck_spec(sid)
    assert spec["slides"][1]["content_brief"] == fx["stages"]["edit"]["content_brief"]
    assert spec["slides"][0] == fx["deck_spec"]["slides"][0]
    # slide 3's finding survives the edit
    assert [f["slideIndex"] for f in get_session_manager().get_slide_deck(sid)["findings"]] == [2]


def test_rerunning_a_stage_is_a_noop(db):
    sid = _start()
    _run_through(sid, "build")
    snapshot = _chat(sid)
    result = _run_stage(sid, "build", _USER)
    assert result["applied"] is False
    assert _chat(sid) == snapshot
    assert _run_stage(sid, "plan", _USER)["applied"] is False  # Back past an earlier stage
    assert _chat(sid) == snapshot


def test_stage_out_of_order_is_409_and_writes_nothing(db):
    sid = _start()
    snapshot = _chat(sid)
    with pytest.raises(StageOrderError):
        _run_stage(sid, "build", _USER)
    assert _chat(sid) == snapshot
    assert not (get_session_manager().get_slide_deck(sid) or {}).get("slides")


def test_unknown_stage_raises_value_error(db):
    with pytest.raises(ValueError):
        _run_stage(_start(), "bogus", _USER)


def test_stages_never_mark_the_spec_dirty(db):
    with patch("src.services.spec_sync.mark_dirty") as dirty:
        _run_through(_start(), "edit")
    dirty.assert_not_called()
```

Add to `tests/unit/test_authz_tour.py`. Keep the file's existing `client` fixture, and replace `test_add_demo_slides_requires_can_edit` with:

```python
@pytest.mark.parametrize("stage", ["plan", "build", "review", "edit"])
def test_run_stage_requires_can_edit(client, monkeypatch, stage):
    calls = []

    def gate(session_id, min_permission=PermissionLevel.CAN_VIEW):
        calls.append((session_id, min_permission))
        raise HTTPException(status_code=403, detail="denied")

    monkeypatch.setattr("src.api.routes.tour._check_deck_permission_for_session", gate)
    resp = client.post(f"/api/tour/demo-deck/victim-session/stages/{stage}")
    assert resp.status_code == 403
    assert calls == [("victim-session", PermissionLevel.CAN_EDIT)]


def test_legacy_slides_route_is_gone(client):
    assert client.post("/api/tour/demo-deck/any/slides").status_code in (404, 405)
```

In `tests/unit/test_tour_ships_a_spec.py`:
- Change the import on line 37 to `from src.api.routes.tour import STAGES, _load_fixture, _phase1_create_session, _run_stage`.
- Change `_run_the_tour` so it runs `_run_stage(session_id, s, _TOUR_USER)` for `s in ("plan", "build")` in place of `_phase2_add_slides`.
- In `test_phase2_calls_the_deck_level_writer_not_the_trigger` (line 108), change the function it inspects from `_phase2_add_slides` to `_run_stage`.
- Every other assertion stays as it is.

- [ ] **Step 2: Run them and check they fail**

Run: `pytest tests/unit/test_tour_staged_demo.py tests/unit/test_authz_tour.py tests/unit/test_tour_ships_a_spec.py -v`
Expected: collection error `ImportError: cannot import name 'STAGES'`.

- [ ] **Step 3: Implement** in `tour.py`:

```python
STAGES: tuple[str, ...] = ("prompt", "plan", "build", "review", "edit")


class StageOrderError(Exception):
    """A stage was requested before the stage it follows has run."""


def _applied_stages(sm, session_id: str) -> set[str]:
    return {
        (m.get("metadata") or {}).get("tour_stage")
        for m in sm.get_messages(session_id)
    } - {None}


def _say(sm, session_id, stage, node, content, message_type, role="assistant"):
    sm.add_message(
        session_id=session_id,
        role=role,
        content=content,
        message_type=message_type,
        metadata={"tour_stage": stage, "node": node},
    )
```

Write `_save_deck(sm, session_id, slides, deck_spec, created_by)`. It calls `save_slide_deck` with the same `deck_dict` shape `_phase2_add_slides` used, then `write_deck_level_columns(deck_spec=…, mutation=sm.deck_mutation_context(session_id, operation="write_deck_level", object_type="deck"))`. Move the existing long comment explaining the second write onto this function, verbatim.

Write `_seed_verification(sm, session_id, slides, findings_by_position)`. It loops over every slide and calls `write_slide_verification` with the merged record described above.

Then write `_run_stage`, which does three things:
1. **Validate:** check `stage in STAGES and stage != "prompt"`, else raise `ValueError`.
2. **Gate:** return `applied=False` if the stage is in `_applied_stages`. Raise `StageOrderError` if the previous stage isn't.
3. **Dispatch:** run the stage per the table.

Tag the phase-1 user message with `metadata={"tour_stage": "prompt", "node": "user"}`. Add the route:

```python
@router.post("/demo-deck/{session_id}/stages/{stage}")
async def run_demo_stage(session_id: str, stage: str):
    """Advance the demo deck by one stage of a scripted graph turn."""
    # SDR-4437 HIGH-1 class: writes into an arbitrary session_id.
    _check_deck_permission_for_session(session_id, PermissionLevel.CAN_EDIT)
    if stage not in STAGES or stage == "prompt":
        raise HTTPException(status_code=404, detail="Unknown tour stage")
    current_user = get_current_user()
    try:
        result = await asyncio.to_thread(_run_stage, session_id, stage, current_user)
    except StageOrderError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    except Exception as e:
        logger.error(f"Tour demo stage {stage} failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to run demo stage") from e
    logger.info("Tour demo stage", extra={"session_id": session_id, "stage": stage})
    return result
```

Delete `_phase2_add_slides` and `add_demo_slides`. Update the module docstring to describe the stages.

If `test_every_slide_is_verified_after_every_stage` fails after `edit` while the others pass, `save_slide_deck`'s row upsert has reset the verification records. Check that `_seed_verification` runs **after** every `_save_deck`, for all slides. Do not touch `save_slide_deck` itself (see the existing rationale comment).

- [ ] **Step 4: Run the tests and check they pass**

Run: `pytest tests/unit/test_tour_staged_demo.py tests/unit/test_authz_tour.py tests/unit/test_tour_ships_a_spec.py tests/unit/test_tour_fixture_script.py tests/unit/test_spec_sync_placement.py -v`
Expected: all PASS.

- [ ] **Step 5: Sabotage-check, then commit.**
  - Remove the `_applied_stages` early return and confirm `test_rerunning_a_stage_is_a_noop` goes red.
  - Seed verification only for the edited slide in `edit` and confirm `test_every_slide_is_verified_after_every_stage[edit]` goes red.
  - Revert both, then:

```bash
git add src/api/routes/tour.py tests/unit/test_tour_staged_demo.py tests/unit/test_authz_tour.py tests/unit/test_tour_ships_a_spec.py
git commit -m "feat(tour): stage the demo deck as an idempotent scripted graph turn"
```

---

### Task 3: Frontend demo runner

**Models:** `test=opus impl=haiku`. The plan gives the code.

**Files:**
- Modify: `frontend/src/services/api.ts:771-782`. Replace `addTourDemoSlides`.
- Create: `frontend/src/components/Tour/tourDemo.ts`, `frontend/src/components/Tour/tourDemo.test.ts`

**Interfaces:**
- Consumes: `POST /api/tour/demo-deck/{sid}/stages/{stage}` (Task 2), plus the existing `api.createTourDemoDeck` and `api.deleteSession`.
- Produces (used by Task 5):

```ts
export type DemoStage = 'plan' | 'build' | 'review' | 'edit';
export function startDemo(): Promise<void>;                 // create + 'tour:load-demo-deck'
export function runStage(stage: DemoStage): Promise<void>;  // idempotent; refreshes session
export function showView(view: 'slides' | 'spec'): Promise<void>;          // 'tour:show-view'
export function focusViewer(opts: { index?: number; drawerOpen?: boolean; tab?: 'feedback' }): Promise<void>; // 'tour:viewer'
export function endDemo(): void;                            // replaces scheduleDeleteTourDemoSession
export function _resetDemoForTests(): void;
```

`api.ts` addition:

```ts
  async runTourDemoStage(
    sessionId: string,
    stage: 'plan' | 'build' | 'review' | 'edit',
  ): Promise<{ session_id: string; stage: string; applied: boolean; slide_count: number }> {
    const response = await fetch(
      `${API_BASE_URL}/api/tour/demo-deck/${sessionId}/stages/${stage}`,
      { method: 'POST', headers: { 'Content-Type': 'application/json' } },
    );
    if (!response.ok) {
      throw new ApiError(response.status, `Failed to run tour demo stage ${stage}`);
    }
    return response.json();
  },
```

- [ ] **Step 1: Write the failing test** `tourDemo.test.ts`:

```ts
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

vi.mock('../../services/api', () => ({
  api: {
    createTourDemoDeck: vi.fn(),
    runTourDemoStage: vi.fn(),
    deleteSession: vi.fn(),
  },
}));

import { api } from '../../services/api';
import { startDemo, runStage, showView, focusViewer, endDemo, _resetDemoForTests } from './tourDemo';

const events: { type: string; detail: unknown }[] = [];
const record = (e: Event) => events.push({ type: e.type, detail: (e as CustomEvent).detail });
const TYPES = ['tour:load-demo-deck', 'tour:refresh-session', 'tour:show-view', 'tour:viewer',
  'tour:demo-session-deleted', 'tour:sessions-list-refresh', 'tour:navigate-main'];

beforeEach(() => {
  vi.useFakeTimers();
  _resetDemoForTests();
  events.length = 0;
  TYPES.forEach(t => window.addEventListener(t, record));
  vi.mocked(api.createTourDemoDeck).mockResolvedValue({ session_id: 'demo-1', title: 'Demo' });
  vi.mocked(api.runTourDemoStage).mockResolvedValue({ session_id: 'demo-1', stage: 'plan', applied: true, slide_count: 0 });
  vi.mocked(api.deleteSession).mockResolvedValue(undefined as never);
});
afterEach(() => {
  TYPES.forEach(t => window.removeEventListener(t, record));
  vi.useRealTimers();
  vi.clearAllMocks();
});

const settle = async (p: Promise<void>) => { await vi.runAllTimersAsync(); await p; };

describe('tourDemo', () => {
  it('startDemo creates the deck and opens it', async () => {
    await settle(startDemo());
    expect(events.map(e => e.type)).toEqual(['tour:load-demo-deck']);
    expect(events[0].detail).toEqual({ sessionId: 'demo-1' });
  });

  it('runStage posts the stage then refreshes the session', async () => {
    await settle(startDemo());
    events.length = 0;
    await settle(runStage('build'));
    expect(api.runTourDemoStage).toHaveBeenCalledWith('demo-1', 'build');
    expect(events).toEqual([{ type: 'tour:refresh-session', detail: { sessionId: 'demo-1' } }]);
  });

  it('runStage is idempotent: a second call (Back then Next) neither posts nor refreshes', async () => {
    await settle(startDemo());
    await settle(runStage('plan'));
    events.length = 0;
    await settle(runStage('plan'));
    expect(api.runTourDemoStage).toHaveBeenCalledTimes(1);
    expect(events).toEqual([]);
  });

  it('runStage without a demo session is a no-op', async () => {
    await settle(runStage('plan'));
    expect(api.runTourDemoStage).not.toHaveBeenCalled();
  });

  it('a failed stage resolves (the tour keeps going) and can be retried', async () => {
    await settle(startDemo());
    vi.mocked(api.runTourDemoStage).mockRejectedValueOnce(new Error('409'));
    await expect(settle(runStage('build'))).resolves.toBeUndefined();
    await settle(runStage('build'));
    expect(api.runTourDemoStage).toHaveBeenCalledTimes(2);
  });

  it('a failed startDemo falls back to the main view', async () => {
    vi.mocked(api.createTourDemoDeck).mockRejectedValueOnce(new Error('500'));
    await settle(startDemo());
    expect(events.map(e => e.type)).toEqual(['tour:navigate-main']);
  });

  it('showView and focusViewer dispatch their bridge events with explicit state', async () => {
    await settle(showView('spec'));
    await settle(focusViewer({ index: 2, drawerOpen: true, tab: 'feedback' }));
    expect(events).toEqual([
      { type: 'tour:show-view', detail: { view: 'spec' } },
      { type: 'tour:viewer', detail: { index: 2, drawerOpen: true, tab: 'feedback' } },
    ]);
  });

  it('endDemo deletes the session, then refreshes the list, and forgets stages', async () => {
    await settle(startDemo());
    await settle(runStage('plan'));
    events.length = 0;
    endDemo();
    await vi.runAllTimersAsync();
    expect(events.map(e => e.type)).toEqual(['tour:demo-session-deleted', 'tour:sessions-list-refresh']);
    expect(api.deleteSession).toHaveBeenCalledWith('demo-1');
    await settle(runStage('plan'));
    expect(api.runTourDemoStage).toHaveBeenCalledTimes(1);
  });

  it('endDemo with no demo does nothing', () => {
    endDemo();
    expect(events).toEqual([]);
    expect(api.deleteSession).not.toHaveBeenCalled();
  });
});
```

- [ ] **Step 2: Run it and check it fails**

Run: `cd frontend && npx vitest run src/components/Tour/tourDemo.test.ts`
Expected: FAIL, because the module `./tourDemo` is not found.

- [ ] **Step 3: Implement** `tourDemo.ts`:

```ts
import { api } from '../../services/api';

export type DemoStage = 'plan' | 'build' | 'review' | 'edit';

// Settle times are the existing tour's measured values (AppTour.tsx before this
// change): long enough for the double-navigate refresh to remount the session.
const OPEN_MS = 1500;
const REFRESH_MS = 1200;
const BRIDGE_MS = 300;

let demoSessionId: string | null = null;
const applied = new Set<DemoStage>();

const wait = (ms: number) => new Promise<void>(r => setTimeout(r, ms));
const emit = (type: string, detail?: unknown) =>
  window.dispatchEvent(detail === undefined ? new Event(type) : new CustomEvent(type, { detail }));

export async function startDemo(): Promise<void> {
  if (demoSessionId) return;
  try {
    const result = await api.createTourDemoDeck();
    demoSessionId = result.session_id;
    emit('tour:load-demo-deck', { sessionId: demoSessionId });
    await wait(OPEN_MS);
  } catch (err) {
    console.error('Failed to create tour demo deck:', err);
    emit('tour:navigate-main');
    await wait(400);
  }
}

/** Advance the demo by one scripted stage. Idempotent: react-joyride re-runs
 *  `before` hooks on Back, and the server also no-ops a repeated stage. */
export async function runStage(stage: DemoStage): Promise<void> {
  if (!demoSessionId || applied.has(stage)) return;
  try {
    await api.runTourDemoStage(demoSessionId, stage);
    applied.add(stage);
    emit('tour:refresh-session', { sessionId: demoSessionId });
    await wait(REFRESH_MS);
  } catch (err) {
    console.error(`Failed to run tour demo stage ${stage}:`, err);
  }
}

export async function showView(view: 'slides' | 'spec'): Promise<void> {
  emit('tour:show-view', { view });
  await wait(BRIDGE_MS);
}

export async function focusViewer(opts: { index?: number; drawerOpen?: boolean; tab?: 'feedback' }): Promise<void> {
  emit('tour:viewer', opts);
  await wait(BRIDGE_MS);
}

/** Leave the demo session in the UI, then delete it server-side (errors ignored).
 *  The sidebar refresh runs only after DELETE succeeds so the list does not still show the demo. */
export function endDemo(): void {
  const sid = demoSessionId;
  demoSessionId = null;
  applied.clear();
  if (!sid) return;
  emit('tour:demo-session-deleted', { sessionId: sid });
  void api
    .deleteSession(sid)
    .then(() => emit('tour:sessions-list-refresh'))
    .catch(() => {});
}

export function _resetDemoForTests(): void {
  demoSessionId = null;
  applied.clear();
}
```

Replace `addTourDemoSlides` in `api.ts` with `runTourDemoStage`. Leave `AppTour.tsx` alone in this task. It still imports `api.addTourDemoSlides`, so `npm run typecheck` fails until Task 5. To keep each commit type-clean, temporarily point `AppTour.tsx`'s `loadDemoSlides` at `await api.runTourDemoStage(_demoSessionId, 'plan'); await api.runTourDemoStage(_demoSessionId, 'build');`. Task 5 deletes it.

- [ ] **Step 4: Run the tests and type-check, and check they pass**

Run: `cd frontend && npx vitest run src/components/Tour/tourDemo.test.ts && npm run typecheck`
Expected: PASS, and `tsc -b` exits 0.

- [ ] **Step 5: Sabotage-check, then commit.** Remove `applied.has(stage) ||` and confirm the idempotency test goes red. Revert, then:

```bash
git add frontend/src/services/api.ts frontend/src/components/Tour/tourDemo.ts frontend/src/components/Tour/tourDemo.test.ts frontend/src/components/Tour/AppTour.tsx
git commit -m "feat(tour): frontend runner for the staged demo deck"
```

---

### Task 4: UI bridges for Spec view, slide index and feedback drawer

**Models:** `test=opus impl=sonnet`. `ViewerContext` sits below `SlideViewer`'s early return, so where the bridge lives matters.

**Files:**
- Modify: `frontend/src/components/Layout/AppLayout.tsx`. Add a listener next to the other tour listeners (`:410-481`). `showSpec` is declared at `:1021`, so put the effect after that declaration.
- Modify: `frontend/src/components/SlideViewer/SlideViewer.tsx`. Put the listener inside `ViewerBody` (`:86`), which is where `useViewer()` is available. `SlideViewer` itself returns the empty state before `ViewerProvider` mounts (`:541-555`).
- Create: `frontend/src/components/SlideViewer/TourViewerBridge.test.tsx`

**Interfaces:**
- Consumes these event payloads (Task 3):
  - `tour:show-view` `{ view: 'slides' | 'spec' }`
  - `tour:viewer` `{ index?: number; drawerOpen?: boolean; tab?: 'feedback' }`
- Produces: no exports. The behaviour is that Spec/Slides follows the event, and the viewer index, drawer state and drawer tab are **set** to the given values.

- [ ] **Step 1: Write the failing test** `TourViewerBridge.test.tsx`. Reuse the harness pattern in `SlideViewer.test.tsx`: mock `../../services/api`, wrap in `ToastProvider`, use a deck of 3 slides, noop `DrawerCallbacks`, one finding on `slideIndex: 2`, and clear `localStorage` in `beforeEach`.

```tsx
import { render, screen, act } from '@testing-library/react';
import { SlideViewer } from './SlideViewer';
import { ToastProvider } from '../../contexts/ToastContext';
import type { SlideDeck } from '../../types/slide';
import type { DrawerCallbacks, SlideFinding } from '../../types/finding';

vi.mock('../../services/api', () => ({
  api: { getSlides: vi.fn().mockResolvedValue({ slide_deck: null }), verifySlide: vi.fn().mockResolvedValue({}) },
}));

const noop = () => undefined;
const callbacks: DrawerCallbacks = { onApplyFinding: noop, onDismissFinding: noop, onDiscussFinding: noop } as DrawerCallbacks;
const finding: SlideFinding = { id: 'brief_not_delivered:abc:0', slideIndex: 2, category: 'content',
  criterion: 'brief_not_delivered', message: 'Demo finding message.', objective: false, status: 'open', seen: false };
const deck = {
  title: 'Demo', css: '', external_scripts: [], scripts: '', slide_count: 3,
  slides: [0, 1, 2].map(i => ({ index: i, slide_id: `s${i}`, html: `<div class="slide">S${i}</div>`, scripts: '',
    content_hash: `h${i}`, verification: { score: 0, rating: 'unknown', explanation: '', issues: [], duration_ms: 0, error: false } })),
  findings: [finding],
} as unknown as SlideDeck;

function renderViewer() {
  return render(
    <ToastProvider>
      <SlideViewer slideDeck={deck} deckKey="demo" findings={[finding]} callbacks={callbacks} sessionId="demo-1" />
    </ToastProvider>,
  );
}
const fire = (detail: object) => act(() => { window.dispatchEvent(new CustomEvent('tour:viewer', { detail })); });

beforeEach(() => localStorage.clear());

it('tour:viewer selects the slide by index', () => {
  renderViewer();
  fire({ index: 2 });
  expect(screen.getByTestId('ribbon-thumb-2')).toHaveAttribute('data-current', 'true');
});

it('tour:viewer opens the drawer on the feedback tab and shows the slide finding', () => {
  renderViewer();
  fire({ index: 2, drawerOpen: true, tab: 'feedback' });
  expect(screen.getByTestId(`finding-${finding.id}`)).toBeVisible();
});

it('tour:viewer sets drawerOpen=true even when already open (set, not toggle)', () => {
  renderViewer();
  fire({ index: 2, drawerOpen: true, tab: 'feedback' });
  fire({ index: 2, drawerOpen: true, tab: 'feedback' });
  expect(screen.getByTestId(`finding-${finding.id}`)).toBeVisible();
});

it('the listener is removed on unmount', () => {
  const { unmount } = renderViewer();
  unmount();
  expect(() => fire({ index: 1 })).not.toThrow();
});
```

Before relying on `SlideViewerProps`, `DrawerCallbacks` or the `ribbon-thumb-N`/`data-current` attributes, check their exact shapes against `SlideViewer.tsx`, `types/finding.ts` and `findings-drawer.spec.ts:52-60`. If anything differs, fix the test harness, but don't weaken any assertion.

The AppLayout `tour:show-view` handler is too entangled to unit-test cheaply (AppLayout is about 1,500 lines with many contexts). Task 6's e2e pins it, including the "already on Spec" case (Review Focus 5).

- [ ] **Step 2: Run it and check it fails**

Run: `cd frontend && npx vitest run src/components/SlideViewer/TourViewerBridge.test.tsx`
Expected: FAIL. The index and drawer don't change.

- [ ] **Step 3: Implement.** In `ViewerBody`, take `setCurrentIndex`, `setDrawerOpen` and `setActiveTab` from `useViewer()`, then add:

```tsx
  // App tour bridge: the tour sets (never toggles) viewer state so a user whose
  // drawer was already open, or who sits on another slide, lands where the
  // step expects. ViewerContext exists only inside this subtree.
  useEffect(() => {
    const handler = (e: Event) => {
      const { index, drawerOpen: open, tab } =
        (e as CustomEvent<{ index?: number; drawerOpen?: boolean; tab?: DrawerTab }>).detail ?? {};
      if (typeof index === 'number') setCurrentIndex(index);
      if (typeof open === 'boolean') setDrawerOpen(open);
      if (tab) setActiveTab(tab);
    };
    window.addEventListener('tour:viewer', handler);
    return () => window.removeEventListener('tour:viewer', handler);
  }, [setCurrentIndex, setDrawerOpen, setActiveTab]);
```

`DrawerTab` is exported from `contexts/ViewerContext.tsx`. Import it if it isn't already in scope.

In `AppLayout.tsx`, after `const [showSpec, setShowSpec] = useState(false);`, add:

```tsx
  // App tour bridge: switch the main panel between Slides and Spec.
  useEffect(() => {
    const handler = (e: Event) => {
      const { view } = (e as CustomEvent<{ view?: 'slides' | 'spec' }>).detail ?? {};
      if (view === 'spec' || view === 'slides') setShowSpec(view === 'spec');
    };
    window.addEventListener('tour:show-view', handler);
    return () => window.removeEventListener('tour:show-view', handler);
  }, []);
```

- [ ] **Step 4: Run the tests and check they pass**

Run: `cd frontend && npx vitest run src/components/SlideViewer && npm run typecheck`
Expected: PASS. The existing `SlideViewer.test.tsx`, `FeedbackDrawer.test.tsx` and `FindingsE2.test.tsx` stay green.

- [ ] **Step 5: Sabotage-check, then commit.** Change `setDrawerOpen(open)` to `setDrawerOpen(prev => !prev)` and confirm the "set, not toggle" test goes red. Revert, then:

```bash
git add frontend/src/components/SlideViewer/SlideViewer.tsx frontend/src/components/SlideViewer/TourViewerBridge.test.tsx frontend/src/components/Layout/AppLayout.tsx
git commit -m "feat(tour): event bridges for spec view, slide index and feedback drawer"
```

---

### Task 5: Rewrite the tour steps

**Models:** `test=opus impl=haiku`. The plan gives the full step list and copy.

**Files:**
- Create: `frontend/src/components/Tour/tourSteps.ts`, `frontend/src/components/Tour/tourSteps.test.ts`
- Modify: `frontend/src/components/Tour/AppTour.tsx`. Delete `TOUR_STEPS`, `loadDemoPrompt`, `loadDemoSlides`, `scheduleDeleteTourDemoSession` and `_demoSessionId`. Import `TOUR_STEPS` from `./tourSteps` and `endDemo` from `./tourDemo`, and call `endDemo()` where `scheduleDeleteTourDemoSession()` was called. Keep the `Joyride` props, options, locale and styles unchanged.

**Interfaces:**
- Consumes: `startDemo`, `runStage`, `showView` and `focusViewer` (Task 3), plus the bridges (Task 4).
- Produces: `export const TOUR_STEPS: Step[]` and `export const DEMO_DECK_SLIDE_COUNT = 3`.

The step list. Keep `clickNav`, `navigateToMain` and `expandAgentConfig` from the old `AppTour.tsx`, moved verbatim into `tourSteps.ts`. Every step has `skipBeacon: true`.

| # | target | title | placement | before | content |
|---|---|---|---|---|---|
| 1 | `[data-tour="sidebar"]` | The App at a Glance | right | — | The sidebar on the left is for navigation: new decks, your deck history and configuration. The workspace on the right is where you chat with the AI and see your slides. Let's walk through both. |
| 2 | `[data-tour="new-deck"]` | Navigation | right | — | "New Deck" starts a fresh deck with a new conversation. "View All Decks" lists every deck you have created or that has been shared with you. |
| 3 | `[data-tour="deck-history"]` | Recent Decks | right | — | Your recent decks are listed here. Click one to pick up where you left off, with its conversation and slides intact. |
| 4 | `[data-tour="configure-section"]` | Configuration | right | — | These pages control what the AI works with and how your decks look. Let's visit each one. |
| 5 | `[data-tour="page-profiles"]` | Agent Profiles | center | `clickNav('nav-profiles')` | A profile saves a combination of tools, design system or slide style, and deck prompt, so you can switch set-ups in one click, for example "Sales Deck" or "Technical Review". |
| 6 | `[data-tour="page-deck-prompts"]` | Deck Prompts | center | `clickNav('nav-deck_prompts')` | Deck prompts are reusable instructions for how a deck should be structured, such as a required narrative or a standard section order. |
| 7 | `[data-tour="page-design-systems"]` | Design Systems | center | `clickNav('nav-design_systems')` | A design system packages your brand: colours, fonts, logos and slide templates. Decks built with one come out on-brand. When a deck uses a design system, it takes the place of any slide style. |
| 8 | `[data-tour="page-slide-styles"]` | Slide Styles | center | `clickNav('nav-slide_styles')` | Slide styles are lighter-weight visual themes. A slide style is used only when no design system is selected. |
| 9 | `[data-tour="page-images"]` | Image Library | center | `clickNav('nav-images')` | Upload logos, diagrams and photos here so the AI can place them on your slides. |
| 10 | `[data-tour="page-settings"]` | Settings | center | `clickNav('nav-settings')` | Connect or disconnect your Google account here for Google Slides export. Admins upload the app-wide OAuth client credentials on the Admin page. |
| 11 | `[data-tour="chat-panel"]` | The AI Workspace | right | `navigateToMain` | You chat here and your deck appears on the right. Behind the chat is a team of AI agents: one plans the deck, others build the slides in parallel, and reviewers check each slide and the deck as a whole. |
| 12 | `[data-tour="agent-config"]` | Agent Config Bar | bottom | `expandAgentConfig` | This bar sets what the agents can use for this deck: tools, look and instructions. Your choices stay in place for every message in this deck until you change them. |
| 13 | `[data-tour="agent-tools"]` | Tools | bottom | — | Tools give the agents access to your data and documents: Genie agents, vector search indexes, MCP servers and model endpoints. Each tool appears as a chip. Click it to edit, or click the X to remove it. |
| 14 | `[data-tour="agent-design-system-selector"]` | Design System | bottom | — | Pick a design system for this deck. If it has templates, a Template picker appears next to it. |
| 15 | `[data-tour="agent-style-selector"]` | Slide Style | bottom | — | Pick a slide style if you are not using a design system. Leave it as "None" for the default look. |
| 16 | `[data-tour="agent-prompt-selector"]` | Deck Prompt | bottom | — | Choose a deck prompt to shape the deck's structure, for example a fixed narrative or a set number of slides. |
| 17 | `[data-tour="agent-profile-actions"]` | Save & Load Profiles | bottom | — | Save this combination as a profile, or load one to restore a set-up instantly. |
| 18 | `[data-tour="chat-panel"]` | Let's Try It | right | — | Let's watch the agents build a deck. We'll send an example request for you. |
| 19 | `[data-tour="chat-panel"]` | Your Request | right | `startDemo` | We asked for "3 slides about the benefits of AI in modern healthcare, with a title slide, key advantages, and future outlook." Plain language is all you need. |
| 20 | `[data-tour="chat-panel"]` | The Architect Plans | right | `() => runStage('plan')` | The architect agent replies first with its plan: who the deck is for, the argument it will make, and what each slide must do. If your request is unclear, it asks you a question instead of guessing. |
| 21 | `[data-tour="slide-viewer"]` | Slides Arrive One by One | left | `() => runStage('build')` | Builder agents now write the slides in parallel, and each one appears here as soon as it is ready. The chat shows "Building 3 slide(s)." and then a review line for each slide. |
| 22 | `[data-tour="chat-panel"]` | Every Slide Is Reviewed | right | — | A reviewer checks every slide as it lands. "clean" means nothing to report. Mechanical problems such as overflowing text are fixed automatically. "surfaced" means the reviewer found something that needs your judgement. |
| 23 | `[data-testid="thumbnail-ribbon"]` | Browse Your Slides | left | — | Click a thumbnail to jump to that slide, or drag it to reorder the deck. A dot on a thumbnail means that slide has review feedback you haven't read yet. |
| 24 | `[data-testid="feedback-drawer"]` | Review Feedback | top | `() => focusViewer({ index: 2, drawerOpen: true, tab: 'feedback' })` | The feedback drawer lists the reviewer's findings for the current slide. Apply asks the agents to make the change, Dismiss hides the finding, and Discuss moves it into the chat so you can talk it through first. |
| 25 | `[data-testid="stage-verification-badge"]` | Data Check | bottom | — | This badge checks the slide's facts against the data your tools returned, shown as green, amber or red. This demo deck uses no data tools, so there is nothing to check yet. |
| 26 | `[data-tour="chat-panel"]` | Whole-Deck Review | right | `() => runStage('review')` | When every slide is in, a deck reviewer reads the deck as a whole for gaps in the argument, repeated points and a missing conclusion. Its verdict appears in the chat. |
| 27 | `[data-testid="spec-view"]` | The Deck Spec | left | `() => showView('spec')` | The Spec shows the plan the agents work from: audience, purpose, argument, narrative arc and a brief for every slide. To change it, ask in the chat, for example "make this for a board audience". The agents then update the spec and the slides it affects. |
| 28 | `[data-tour="slide-viewer"]` | Edit by Asking | left | `async () => { await showView('slides'); await runStage('edit'); await focusViewer({ index: 1, drawerOpen: false }); }` | To change a slide, just ask. We sent "Make slide 2 more concise". The architect works out which slide you mean, and only that slide is rebuilt and re-reviewed. The rest of the deck is untouched. |
| 29 | `[data-tour="slide-viewer"]` | Hands-On Changes | left | — | For direct changes, the toolbar above the slide lets you edit its HTML, delete it, or use Optimize layout to tidy spacing and text flow without changing the content. |
| 30 | `[data-testid="graph-version-status"]` | Pinned Agent Version | bottom | — | Each deck stays on the version of the AI agents it started with, so updates an admin publishes never change a deck halfway through. This demo deck shows its version here. If a newer version exists, "Start latest" opens a new deck on it, and this deck is left as it is. |
| 31 | `[data-tour="header-title"]` | Deck Title & Save Points | bottom | — | Click the title to rename your deck. The save point menu lets you browse earlier versions and revert to any of them. |
| 32 | `[data-tour="header-actions"]` | Export & Share | bottom | — | When your deck is ready:\n• Export: PPTX, PDF, HTML or Google Slides\n• Copy Link: a read-only view link\n• Share: add viewers or editors\n• Present: full-screen in the browser |
| 33 | `[data-tour="feedback-button"]` | Feedback | top | — | Spotted a bug or have an idea? Send it to the team from here at any time. |
| 34 | `[data-tour="page-help"]` | Help & Documentation | center | `clickNav('nav-help')` | Guides for every feature live here. |
| 35 | `[data-tour="page-help"]` | You're All Set | center | — | That's the tour. The example deck is removed when you finish.\n\nTo make your own, click "New Deck" and describe what you want in the chat.\n\nYou can replay this tour any time from "App Tour" at the bottom of the sidebar. |

- [ ] **Step 1: Write the failing test** `tourSteps.test.ts`:

```ts
/**
 * Contract for the tour's step list. Targets are checked against NON-TEST source,
 * because a Joyride step whose target never mounts is silently skipped as
 * `target_not_found`, and the tour then quietly drops a feature.
 */
import { readFileSync, readdirSync, statSync } from 'node:fs';
import { join } from 'node:path';
import { describe, it, expect } from 'vitest';
import { TOUR_STEPS } from './tourSteps';

vi.mock('../../services/api', () => ({ api: {} }));

const SRC = join(__dirname, '..', '..');
function sources(dir: string): string[] {
  return readdirSync(dir).flatMap(name => {
    const p = join(dir, name);
    if (statSync(p).isDirectory()) return sources(p);
    return /\.tsx?$/.test(name) && !/\.test\./.test(name) && !p.includes(`${join('components', 'Tour')}`) ? [p] : [];
  });
}
const corpus = sources(SRC).map(p => readFileSync(p, 'utf8')).join('\n');
const titles = TOUR_STEPS.map(s => s.title as string);
const text = TOUR_STEPS.map(s => `${s.title} ${s.content}`).join('\n');

function selectorIsRendered(target: string): boolean {
  const m = target.match(/^\[data-(tour|testid)="([^"]+)"\]$/);
  if (!m) return false;
  const [, kind, value] = m;
  if (kind === 'tour' && value.startsWith('nav-')) return /data-tour=\{`nav-\$\{item\.viewId\}`\}/.test(corpus);
  return corpus.includes(`data-${kind}="${value}"`);
}

describe('TOUR_STEPS', () => {
  it('every target is a data-tour/data-testid selector rendered by non-test source', () => {
    const missing = TOUR_STEPS.map(s => s.target as string).filter(t => !selectorIsRendered(t));
    expect(missing).toEqual([]);
  });

  it('teaches the graph flow in order', () => {
    const order = ['Your Request', 'The Architect Plans', 'Slides Arrive One by One', 'Every Slide Is Reviewed',
      'Review Feedback', 'Whole-Deck Review', 'The Deck Spec', 'Edit by Asking'];
    const idx = order.map(t => titles.indexOf(t));
    expect(idx.every(i => i >= 0)).toBe(true);
    expect([...idx].sort((a, b) => a - b)).toEqual(idx);
  });

  it('covers the features the old tour missed', () => {
    for (const t of ['Design Systems', 'Design System', 'Pinned Agent Version', 'Data Check', 'Review Feedback', 'The Deck Spec']) {
      expect(titles).toContain(t);
    }
  });

  it('runs each demo stage exactly once, in stage order', () => {
    const hooks = TOUR_STEPS.map(s => String(s.before ?? ''));
    const stageAt = (stage: string) => hooks.findIndex(h => h.includes(`runStage('${stage}')`) || h.includes(`runStage("${stage}")`));
    const at = ['plan', 'build', 'review', 'edit'].map(stageAt);
    expect(at.every(i => i >= 0)).toBe(true);
    expect([...at].sort((a, b) => a - b)).toEqual(at);
    expect(hooks.filter(h => /runStage\(/.test(h))).toHaveLength(4);
    expect(hooks.findIndex(h => h.includes('startDemo'))).toBeLessThan(at[0]);
  });

  it('no step makes a claim about retired behaviour', () => {
    expect(text).not.toMatch(/select multiple|selection ribbon|click (directly )?on any slide to edit|duplicate/i);
    expect(text).not.toMatch(/generates a full deck in response/i);
  });

  it('teaches editing by asking in chat', () => {
    const edit = TOUR_STEPS.find(s => s.title === 'Edit by Asking');
    expect(String(edit?.content)).toMatch(/make slide 2 more concise/i);
  });

  it('copy stays short and plain', () => {
    for (const s of TOUR_STEPS) {
      expect(String(s.content).split(/\s+/).length, String(s.title)).toBeLessThanOrEqual(60);
      expect(String(s.content)).not.toMatch(/\*\*/);
    }
  });

  it('every step skips the beacon', () => {
    expect(TOUR_STEPS.every(s => s.skipBeacon === true)).toBe(true);
  });
});
```

Step 30 (Pinned Agent Version) deliberately comes after the demo starts: before a deck is persisted, `graphVersion` is null and the badge reads "Pinned Graph Version unavailable" (`GraphVersionStatus.tsx:18-21`).

Note: `String(s.before)` stringifies the arrow function source. That is why stage hooks must be written inline as `() => runStage('plan')` and not bound through a helper.

- [ ] **Step 2: Run it and check it fails**

Run: `cd frontend && npx vitest run src/components/Tour/tourSteps.test.ts`
Expected: FAIL, because the module `./tourSteps` is not found.

- [ ] **Step 3: Implement** `tourSteps.ts` from the table, in table order, with the `\n` line breaks shown. Then update `AppTour.tsx` as described under **Files**.

- [ ] **Step 4: Run the tests and type-check, and check they pass**

Run: `cd frontend && npx vitest run src/components/Tour src/components/Layout/app-sidebar.test.tsx && npm run typecheck`
Expected: PASS.

- [ ] **Step 5: Sabotage-check, then commit.**
  - Change step 24's (Review Feedback) target to `[data-testid="feedback-drawr"]` and confirm the target test goes red.
  - Swap the `review` and `build` hooks and confirm the stage-order test goes red.
  - Revert both, then:

```bash
git add frontend/src/components/Tour/tourSteps.ts frontend/src/components/Tour/tourSteps.test.ts frontend/src/components/Tour/AppTour.tsx
git commit -m "feat(tour): rebuild the tour around graph generation"
```

---

### Task 6: End-to-end tour walk

**Models:** `test=opus impl=sonnet`. This is the only test that proves every step's target actually mounts at step time. A red result usually means a timing or mount bug in Tasks 3 to 5, so the fix needs judgement.

**Files:**
- Create: `frontend/tests/e2e/app-tour.spec.ts`
- Possibly modify, if the walk exposes a mount or timing bug: `tourDemo.ts` timings, `tourSteps.ts` hooks. Never loosen the spec to get a pass.

**Interfaces:**
- Consumes these existing helpers: `test`/`expect` from `../fixtures/base-test`, `setupMocks` from `../helpers/setup-mocks`, `apiPath` from `../helpers/api-route`, and the `session-helpers` mocks. Read `findings-drawer.spec.ts:1-60` for the pattern.

Design:
- **Clear the tour flag.** The suite-wide `storageState` sets `tellr-app-tour-completed=true` (`playwright.config.ts`). Override it for this file with `test.use({ storageState: { cookies: [], origins: [] } })`.
- **Mock the staged backend statefully.** Keep a `stage` variable in the test.
  - `POST /api/tour/demo-deck` returns `{session_id:'tour-demo', title}` and sets `stage='prompt'`.
  - `POST …/stages/:s` advances `stage` and returns `{applied:true, slide_count}`.
  - `GET /api/sessions/tour-demo` returns the messages for the current stage. Build them from the real fixture JSON (`import fixture from '../../../src/api/fixtures/tour_demo_deck.json'`), with roles and content exactly as Task 2's table describes.
  - `GET /api/slides?session_id=tour-demo` returns 404 before `build`. From `build` on, it returns the fixture slides, each with `content_hash` and a `verification` from `stages.build.verification`, plus `findings` holding one camelCase finding for `slideIndex: 2`. After `edit` it returns the edited slide 1.
  - `DELETE /api/sessions/tour-demo` is recorded.
  - Fail the test if `POST /api/verification/**` or `POST /api/chat**` is ever called (no LLM).

Tests:
1. **Full walk.** The welcome modal appears. Click "Take the Tour". For each of the 35 `TOUR_STEPS`, assert the tooltip title is visible (`page.getByRole('heading', { name: title })` inside the Joyride tooltip), then click "Next". The last button reads "Get Started". At these steps, assert:
   - **"The Architect Plans":** the chat shows `stages.plan.architect_reply`.
   - **"Slides Arrive One by One":** `ribbon-thumb-2` is visible.
   - **"Review Feedback":** `finding-<id>` is visible.
   - **"The Deck Spec":** `spec-view` is visible.
   - **"Edit by Asking":** `spec-view` is hidden, the chat shows "Editing slide 2.", and `ribbon-thumb-1` has `data-current="true"`.
   - **At the end:** DELETE was called once, and no verification or chat POST was made.
2. **Back re-entry.** Walk to "Every Slide Is Reviewed", press Back twice and Next twice. Assert the stage POSTs were `plan` and `build` once each, and the chat has no duplicate `Building 3 slide(s).` line.
3. **Skip mid-demo.** Walk to "Review Feedback" and click "Skip Tour". Assert DELETE was called and the workspace shows `slide-viewer-empty`.
4. **Spec already open.** Before starting, set `localStorage` so the drawer is already open (`tellr-viewer-view-state` = `{"drawerOpen":true,"drawerHeight":200,"activeTab":"feedback"}`). Walk to "Edit by Asking". Assert `spec-view` is hidden and the slide stage is visible. This covers Review Focus 5 for the AppLayout bridge.

- [ ] **Step 1:** Write `app-tour.spec.ts` per the design above.
- [ ] **Step 2: Run it** with `cd frontend && npx playwright test tests/e2e/app-tour.spec.ts`. Before Tasks 3 to 5 land it should fail. On this branch, read each failure for its *cause*, either a target not found or a missing hook, rather than counting failures.
- [ ] **Step 3: Fix the real causes** in `tourDemo.ts` and `tourSteps.ts`. Joyride's `targetWaitTimeout` and `beforeTimeout` (5000 ms default) are the knobs. A slow refresh is fixed by awaiting a DOM condition in the hook, not by a longer sleep.
- [ ] **Step 4: Run it** with `npx playwright test tests/e2e/app-tour.spec.ts tests/e2e/findings-drawer.spec.ts tests/e2e/navigation.spec.ts`. Expected: PASS.
- [ ] **Step 5: Sabotage-check, then commit.** Delete the `focusViewer` hook from step 24 (Review Feedback) and confirm test 1 goes red at "Review Feedback". Revert, then:

```bash
git add frontend/tests/e2e/app-tour.spec.ts frontend/src/components/Tour
git commit -m "test(e2e): walk the rebuilt app tour against a staged demo"
```

---

## Out of scope (follow-up plans)

- **WelcomeModal copy:** fix "click any slide to edit HTML inline" and "duplicate", and add design systems, the agent pipeline, review and spec.
- **Help page:** the Generator tab still teaches the selection ribbon (`HelpPage.tsx:162-188`) and says "Select a profile (top-right)" (`:92`). There's no Design Systems tab and nothing on graph versions or the mixed-release warning.
- **Admin onboarding:** agent workbench, test runs and readiness, review and publish, release history, org defaults.
- **Product issue found while planning:** the build reviewer's live chat line uses the 0-indexed position (`nodes.py:2365`). The first slide is announced as "Slide 0 reviewed: clean.", while users and the architect say "slide 1" for it. The demo mirrors the real wording, so Task 1 pins `Slide 0`. If the line is changed to 1-based, update the fixture and `test_one_review_line_per_slide_in_position_order_with_real_verdicts` in the same PR.
- **Persistence difference (accepted):** live, the foreman and build-reviewer lines are emitted as events only (`nodes.py:2080`, `:2365`), so they don't survive a reload of a real session. The demo persists them because the tour shows them after a reload. The demo session is deleted at tour end.
