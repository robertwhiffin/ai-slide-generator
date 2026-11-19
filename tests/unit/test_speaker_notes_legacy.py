"""Speaker notes on the Legacy (monolith) paths and on user HTML saves (Task 4).

Covers plan D1 (tri-state notes between parse and apply), D3 (asides move out of
the HTML), D5 (where "keep existing" lives) and D10 (who wrote the notes: a model
arrival never replaces notes a user typed; a user save always wins).

Harnesses:
* parsing: ``SlideDeck.from_html_string`` and the ``agent_stub`` shape of
  ``tests/unit/test_slide_replacements.py:13-16``;
* replacement, RC8 and HTML saves: ``ChatService.__new__`` with a cached deck and a
  recording session manager, the shape of ``tests/unit/test_deck_persistence.py:491-514``.
  The session manager is a ``MagicMock`` whose ``get_slide_deck_version`` answers
  None, so ``_get_or_load_deck`` serves the cached deck.

Every oracle is a literal. Each test names the one production change that should
turn it red (``# Sabotage:``).
"""
from __future__ import annotations

import threading
from typing import Any, Dict, List, Optional, Tuple
from unittest.mock import MagicMock, patch

import pytest

from src.api.services.chat_service import ChatService
from src.domain.slide import Slide
from src.domain.slide_deck import SlideDeck
from src.services.agent import SlideGeneratorAgent

SID = "speaker-notes-legacy"
EDITOR = "editor@test.com"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _slide_html(marker: str) -> str:
    return f'<div class="slide"><h1>{marker}</h1></div>'


def _deck(notes: List[Tuple[Optional[str], Optional[str]]]) -> SlideDeck:
    """A deck of ``len(notes)`` slides; ``notes[i]`` is ``(speaker_notes, source)``."""
    markers = ["MK-A", "MK-B", "MK-C", "MK-D"]
    return SlideDeck(
        title="Notes deck",
        slides=[
            Slide(
                html=_slide_html(markers[i]),
                slide_id=f"sid-{i}",
                speaker_notes=text,
                speaker_notes_source=source,
            )
            for i, (text, source) in enumerate(notes)
        ],
    )


#: The standard deck: three model-written notes.
MODEL_ABC = [("A", "model"), ("B", "model"), ("C", "model")]
#: Slide 1's notes were typed by the user.
USER_B = [("A", "model"), ("Typed.", "user"), ("C", "model")]


def _service() -> ChatService:
    service = ChatService.__new__(ChatService)
    service.agent = MagicMock()
    service._deck_cache = {}
    service._cache_lock = MagicMock()
    service._cache_lock.__enter__ = MagicMock(return_value=None)
    service._cache_lock.__exit__ = MagicMock(return_value=None)
    return service


def _session_manager() -> MagicMock:
    sm = MagicMock()
    # None: _get_or_load_deck serves the cached deck without a reload.
    sm.get_slide_deck_version.return_value = None
    sm.save_slide_deck.return_value = {"version": 2}
    return sm


def _notes(deck_dict: Dict[str, Any]) -> List[str]:
    return [s["speaker_notes"] for s in deck_dict["slides"]]


def _sources(deck_dict: Dict[str, Any]) -> List[Optional[str]]:
    return [s["speaker_notes_source"] for s in deck_dict["slides"]]


def _saved_deck_dict(sm: MagicMock) -> Dict[str, Any]:
    assert sm.save_slide_deck.called, "nothing was saved"
    return sm.save_slide_deck.call_args.kwargs["deck_dict"]


# ---------------------------------------------------------------------------
# Parsing: from_html_string and _parse_slide_replacements
# ---------------------------------------------------------------------------


def test_from_html_string_moves_each_aside_onto_its_slide():
    # Sabotage: drop `speaker_notes=notes_for_root(...)` from the Slide built in from_html_string.
    html = (
        "<html><head><title>T</title></head><body>"
        '<div class="slide"><h1>One</h1><aside class="speaker-notes"><p>A</p></aside></div>'
        '<div class="slide"><h1>Two</h1></div>'
        "</body></html>"
    )

    deck = SlideDeck.from_html_string(html)

    assert deck.slides[0].speaker_notes == "A"
    assert "speaker-notes" not in deck.slides[0].html
    assert deck.slides[1].speaker_notes is None
    assert _notes(deck.to_dict()) == ["A", ""]


def test_from_html_string_tags_aside_notes_as_model_written():
    # Sabotage: leave speaker_notes_source unset on a slide that got notes from an aside.
    html = (
        '<div class="slide"><h1>One</h1><aside class="speaker-notes"><p>A</p></aside></div>'
        '<div class="slide"><h1>Two</h1></div>'
    )

    deck = SlideDeck.from_html_string(html)

    assert deck.slides[0].speaker_notes_source == "model"
    assert deck.slides[1].speaker_notes_source is None
    assert _sources(deck.to_dict()) == ["model", None]


def test_from_html_string_keeps_the_section_root_when_the_aside_is_its_sibling():
    # Sabotage: call pop_speaker_notes after find_slide_roots in from_html_string.
    html = (
        '<section class="ground"><div class="slide"><h1>One</h1></div>'
        '<aside class="speaker-notes"><p>Say one.</p></aside></section>'
    )

    deck = SlideDeck.from_html_string(html)

    assert len(deck.slides) == 1
    assert deck.slides[0].html.startswith("<section")
    assert 'class="ground"' in deck.slides[0].html
    assert "speaker-notes" not in deck.slides[0].html
    assert deck.slides[0].speaker_notes == "Say one."


@pytest.fixture
def agent_stub() -> SlideGeneratorAgent:
    """A SlideGeneratorAgent without running __init__ (test_slide_replacements.py:13-16)."""
    return SlideGeneratorAgent.__new__(SlideGeneratorAgent)  # type: ignore[call-arg]


def test_parse_slide_replacements_extracts_notes(agent_stub):
    # Sabotage: drop the pop_speaker_notes / notes_for_root lines from _parse_slide_replacements.
    response = (
        '<div class="slide"><h1>R0</h1><aside class="speaker-notes"><p>A</p></aside></div>'
        '<div class="slide"><h1>R1</h1></div>'
    )

    result = agent_stub._parse_slide_replacements(response, [1])

    slides = result["replacement_slides"]
    assert slides[0].speaker_notes == "A"
    assert "speaker-notes" not in slides[0].html
    assert slides[1].speaker_notes is None


def test_parse_slide_replacements_tags_aside_notes_as_model_written(agent_stub):
    # Sabotage: leave speaker_notes_source unset in _parse_slide_replacements.
    response = (
        '<div class="slide"><h1>R0</h1><aside class="speaker-notes"><p>A</p></aside></div>'
        '<div class="slide"><h1>R1</h1></div>'
    )

    slides = agent_stub._parse_slide_replacements(response, [1])["replacement_slides"]

    assert slides[0].speaker_notes_source == "model"
    assert slides[1].speaker_notes_source is None


def test_parse_slide_replacements_keeps_the_section_root_when_the_aside_is_its_sibling(agent_stub):
    # Sabotage: call pop_speaker_notes after find_slide_roots in _parse_slide_replacements.
    response = (
        '<section class="ground"><div class="slide"><h1>R0</h1></div>'
        '<aside class="speaker-notes"><p>Say R0.</p></aside></section>'
    )

    slides = agent_stub._parse_slide_replacements(response, [0])["replacement_slides"]

    assert len(slides) == 1
    assert slides[0].html.startswith("<section")
    assert "speaker-notes" not in slides[0].html
    assert slides[0].speaker_notes == "Say R0."


# ---------------------------------------------------------------------------
# Legacy replacement carry: _apply_slide_replacements
# ---------------------------------------------------------------------------


def _replace(
    deck: SlideDeck,
    replacement_slides: List[Slide],
    *,
    start_index: int = 1,
    original_count: int = 1,
    is_add_operation: bool = False,
) -> Dict[str, Any]:
    service = _service()
    service._deck_cache[SID] = deck
    info: Dict[str, Any] = {
        "replacement_slides": replacement_slides,
        "replacement_css": "",
        "start_index": start_index,
        "original_count": original_count,
    }
    if is_add_operation:
        info["is_add_operation"] = True
        info["add_position"] = ("after", None)
    with patch(
        "src.api.services.chat_service.get_session_manager",
        return_value=_session_manager(),
    ), patch("src.api.services.chat_service.get_current_username", return_value=EDITOR):
        return service._apply_slide_replacements(info, SID)


def _new(marker: str, notes: Optional[str], source: Optional[str] = None) -> Slide:
    """A parsed replacement slide: notes None = no aside, "" = empty aside."""
    if source is None and notes is not None:
        source = "model"
    return Slide(html=_slide_html(marker), speaker_notes=notes, speaker_notes_source=source)


def test_a_replacement_without_an_aside_keeps_the_replaced_slides_notes():
    # Sabotage: drop the `speaker_notes is None` carry line in _apply_slide_replacements.
    result = _replace(_deck(MODEL_ABC), [_new("MK-NEW", None)])

    assert _notes(result) == ["A", "B", "C"]


def test_a_replacement_without_an_aside_keeps_the_replaced_slides_source():
    # Sabotage: carry the original notes but not the original speaker_notes_source.
    result = _replace(_deck(MODEL_ABC), [_new("MK-NEW", None)])

    assert _sources(result) == ["model", "model", "model"]


def test_a_replacement_with_an_aside_replaces_model_notes():
    # Sabotage: carry the original notes even when the replacement brought its own.
    result = _replace(_deck(MODEL_ABC), [_new("MK-NEW", "B2")])

    assert _notes(result) == ["A", "B2", "C"]
    assert _sources(result) == ["model", "model", "model"]


def test_an_empty_aside_clears_model_notes():
    # Sabotage: treat "" like None (carry) in _apply_slide_replacements.
    result = _replace(_deck(MODEL_ABC), [_new("MK-NEW", "")])

    assert _notes(result) == ["A", "", "C"]
    assert _sources(result) == ["model", None, "model"]


def test_a_replacement_beyond_the_originals_inherits_nothing():
    # Sabotage: carry original_notes[-1] (or any original) to a slide with idx >= len(original_notes).
    result = _replace(_deck(MODEL_ABC), [_new("MK-NEW1", None), _new("MK-NEW2", None)])

    assert _notes(result) == ["A", "B", "", "C"]
    assert _sources(result) == ["model", "model", None, "model"]


def test_an_added_slide_gets_only_its_own_notes():
    # Sabotage: apply the replacement carry in the add-operation branch.
    result = _replace(
        _deck(MODEL_ABC),
        [_new("MK-ADD1", None), _new("MK-ADD2", "Own.")],
        is_add_operation=True,
    )

    assert _notes(result) == ["A", "B", "", "Own.", "C"]
    assert _sources(result) == ["model", "model", None, "model", "model"]


def test_a_replacement_with_an_aside_never_replaces_user_notes():
    # Sabotage: drop the `orig.speaker_notes_source == "user"` guard in _apply_slide_replacements.
    result = _replace(_deck(USER_B), [_new("MK-NEW", "B2")])

    assert _notes(result) == ["A", "Typed.", "C"]
    assert _sources(result) == ["model", "user", "model"]
    assert "MK-NEW" in result["slides"][1]["html"]


def test_a_replacement_with_an_empty_aside_never_clears_user_notes():
    # Sabotage: let an empty model aside through the user guard in _apply_slide_replacements.
    result = _replace(_deck(USER_B), [_new("MK-NEW", "")])

    assert _notes(result) == ["A", "Typed.", "C"]
    assert _sources(result) == ["model", "user", "model"]


def test_a_replacement_without_an_aside_keeps_user_notes_and_source():
    # Sabotage: carry the notes but reset the source to "model" on the replacement.
    result = _replace(_deck(USER_B), [_new("MK-NEW", None)])

    assert _notes(result) == ["A", "Typed.", "C"]
    assert _sources(result) == ["model", "user", "model"]


# ---------------------------------------------------------------------------
# RC8: send_message_streaming's synthetic-context branch (chat_service.py ~:1546-1578)
# ---------------------------------------------------------------------------
#
# RC13 (~:1292) turns "edit slide N" into a slide_context BEFORE the LLM runs, so
# RC8 (which needs `not slide_context`) is reached only when the deck was absent
# at RC13 and present after the LLM call (a deck written during the turn). The
# driver reproduces that: _get_or_load_deck answers None until the agent has run.


def _drive_rc8(deck: SlideDeck, llm_html: str) -> Dict[str, Any]:
    """Run one monolith turn "edit slide 2" that lands in the RC8 branch; return the saved deck dict."""
    service = _service()
    sm = _session_manager()
    sm.get_session.return_value = {
        "id": SID,
        "message_count": 4,
        "genie_conversation_id": None,
    }

    agent_ran = threading.Event()

    def _generate(**kwargs):
        agent_ran.set()
        return {"html": llm_html, "replacement_info": None}

    agent = MagicMock()
    agent.generate_slides_streaming.side_effect = _generate

    def _load(session_id):
        return deck if agent_ran.is_set() else None

    with patch(
        "src.api.services.chat_service.get_session_manager", return_value=sm
    ), patch(
        "src.api.services.chat_service.get_current_username", return_value=EDITOR
    ), patch(
        "src.core.settings_db.get_settings", return_value=MagicMock()
    ), patch.object(
        service, "_get_or_load_deck", side_effect=_load
    ), patch.object(
        service, "_detect_edit_intent", return_value=True
    ), patch.object(
        service, "_detect_generation_intent", return_value=False
    ), patch.object(
        service, "_detect_add_intent", return_value=False
    ), patch.object(
        service, "_detect_explicit_replace_intent", return_value=False
    ), patch.object(
        service, "_parse_slide_references", return_value=([1], None)
    ), patch.object(
        service, "_build_agent_for_session", return_value=(agent, {}, None)
    ), patch.object(
        service, "_persist_genie_conversation_ids"
    ), patch.object(
        service, "_get_deck_version", return_value=None
    ), patch.object(
        service, "_ensure_pinned_template_token_css", return_value=False
    ), patch.object(
        service, "create_save_point"
    ), patch.object(
        service,
        "_substitute_images_for_response",
        side_effect=lambda d, h=None, *, session_id: (d, h),
    ):
        list(
            service.send_message_streaming(
                SID, "edit slide 2", request_id="req-rc8"
            )
        )

    saved = _saved_deck_dict(sm)
    # The RC8 branch ran: slide 2 now holds the LLM's slide, the others are untouched.
    assert [("MK-REWRITE" in s["html"]) for s in saved["slides"]] == [False, True, False]
    return saved


RC8_NO_ASIDE = '<div class="slide"><h1>MK-REWRITE</h1></div>'
RC8_ASIDE = (
    '<div class="slide"><h1>MK-REWRITE</h1>'
    '<aside class="speaker-notes"><p>B2</p></aside></div>'
)


def test_an_rc8_edit_without_an_aside_keeps_the_notes():
    # Sabotage: drop the RC8 carry before `existing_deck.slides[slide_idx] = new_deck.slides[idx]`.
    saved = _drive_rc8(_deck(MODEL_ABC), RC8_NO_ASIDE)

    assert _notes(saved) == ["A", "B", "C"]
    assert _sources(saved) == ["model", "model", "model"]


def test_an_rc8_edit_with_an_aside_replaces_model_notes():
    # Sabotage: carry the existing notes in RC8 even when the new slide brought an aside.
    saved = _drive_rc8(_deck(MODEL_ABC), RC8_ASIDE)

    assert _notes(saved) == ["A", "B2", "C"]
    assert _sources(saved) == ["model", "model", "model"]
    assert "speaker-notes" not in saved["slides"][1]["html"]


def test_an_rc8_edit_never_replaces_user_notes():
    # Sabotage: drop the `speaker_notes_source == "user"` guard in the RC8 carry.
    saved = _drive_rc8(_deck(USER_B), RC8_ASIDE)

    assert _notes(saved) == ["A", "Typed.", "C"]
    assert _sources(saved) == ["model", "user", "model"]


# ---------------------------------------------------------------------------
# User HTML saves: update_slide
# ---------------------------------------------------------------------------


def _update(deck: SlideDeck, index: int, html: str) -> Dict[str, Any]:
    service = _service()
    service._deck_cache[SID] = deck
    sm = _session_manager()
    with patch(
        "src.api.services.chat_service.get_session_manager", return_value=sm
    ), patch("src.api.services.chat_service.get_current_username", return_value=EDITOR):
        service.update_slide(SID, index, html)
    return _saved_deck_dict(sm)


def test_update_slide_moves_an_aside_into_notes():
    # Sabotage: skip extract_speaker_notes in update_slide.
    saved = _update(
        _deck(MODEL_ABC),
        1,
        '<div class="slide"><p>x</p><aside class="speaker-notes"><p>Say x.</p></aside></div>',
    )

    assert saved["slides"][1]["speaker_notes"] == "Say x."
    assert saved["slides"][1]["html"] == '<div class="slide"><p>x</p></div>'


def test_update_slide_tags_aside_notes_as_user_written():
    # Sabotage: tag update_slide's aside notes "model" (or leave the source unset).
    saved = _update(
        _deck(MODEL_ABC),
        1,
        '<div class="slide"><p>x</p><aside class="speaker-notes"><p>Say x.</p></aside></div>',
    )

    assert _sources(saved) == ["model", "user", "model"]


def test_update_slide_with_an_aside_replaces_user_notes():
    # Sabotage: apply the model-arrival user guard to update_slide (a user save always wins).
    saved = _update(
        _deck(USER_B),
        1,
        '<div class="slide"><p>x</p><aside class="speaker-notes"><p>Retyped.</p></aside></div>',
    )

    assert _notes(saved) == ["A", "Retyped.", "C"]
    assert _sources(saved) == ["model", "user", "model"]


def test_update_slide_with_an_empty_aside_clears_notes_and_source():
    # Sabotage: treat an empty aside like no aside (keep the original notes) in update_slide.
    saved = _update(
        _deck(USER_B),
        1,
        '<div class="slide"><p>x</p><aside class="speaker-notes"></aside></div>',
    )

    assert _notes(saved) == ["A", "", "C"]
    assert _sources(saved) == ["model", None, "model"]
    assert saved["slides"][1]["html"] == '<div class="slide"><p>x</p></div>'


def test_update_slide_without_an_aside_keeps_the_notes():
    # Sabotage: build new_slide with `speaker_notes=notes` (drop the original_slide fallback).
    saved = _update(_deck(MODEL_ABC), 1, '<div class="slide"><p>x</p></div>')

    assert _notes(saved) == ["A", "B", "C"]
    assert _sources(saved) == ["model", "model", "model"]


def test_update_slide_without_an_aside_keeps_user_notes_and_source():
    # Sabotage: keep the original notes but not the original speaker_notes_source in update_slide.
    saved = _update(_deck(USER_B), 1, '<div class="slide"><p>x</p></div>')

    assert _notes(saved) == ["A", "Typed.", "C"]
    assert _sources(saved) == ["model", "user", "model"]
