"""Contract for the tour demo's staged script (src/api/fixtures/tour_demo_deck.json).

The tour shows what a real graph turn produces, so every chat line the fixture
plays must be the graph's own wording, and only lines a deployed user actually
sees.  The deck reviewer advisory is copied from src/services/graph/nodes.py
(_advisory_text :1251-1269).  The foreman ("Building N slide(s).") and
build-reviewer ("Slide N reviewed: ...") lines are _emit-only and never reach a
polling client, so the fixture must not carry them.  If those formats change,
this test is the reminder to change the fixture.
"""
from __future__ import annotations

import json
import re
from html.parser import HTMLParser
from pathlib import Path

from src.domain.finding import CRITERIA, Finding

_FIXTURE = Path(__file__).resolve().parents[2] / "src/api/fixtures/tour_demo_deck.json"
_MARKDOWN = re.compile(r"\*\*|__|^#{1,6} |^\s*[-*] ", re.M)


def _fx() -> dict:
    return json.loads(_FIXTURE.read_text(encoding="utf-8"))


def _all_chat_lines(fx: dict) -> list[str]:
    s = fx["stages"]
    return [
        s["plan"]["architect_reply"],
        s["review"]["advisory"],
        s["edit"]["user_prompt"],
        s["edit"]["architect_reply"],
    ]


def test_legacy_single_reply_is_gone():
    assert "chat_reply" not in _fx()


def test_chat_prompt_is_kept_for_the_engine_selection_test():
    assert _fx()["chat_prompt"].startswith("Create 3 slides about the benefits of AI")


def test_emit_only_progress_lines_are_not_in_the_script():
    s = _fx()["stages"]
    assert "foreman_line" not in s["build"]
    assert "review_lines" not in s["build"]
    assert "review_line" not in s["edit"]


def test_the_demo_surfaces_at_least_one_finding_for_the_drawer_step():
    assert any(_fx()["stages"]["build"]["findings"].values())


def test_findings_are_keyed_by_real_slide_positions():
    fx = _fx()
    valid = {str(p) for p in range(len(fx["slides"]))}
    assert set(fx["stages"]["build"]["findings"]) <= valid


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


def test_findings_validate_as_domain_findings():
    # The registry validator on Finding is the authority the real reviewer goes
    # through; a fixture finding it would reject cannot be stored faithfully.
    for position, items in _fx()["stages"]["build"]["findings"].items():
        for ordinal, f in enumerate(items):
            Finding(id=f"tour-{position}-{ordinal}", slide_index=int(position), **f)


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
    assert edit["slide"]["index"] == edit["position"]
    assert edit["slide"]["slide_id"] == original["slide_id"]
    assert edit["slide"]["html"] != original["html"]
    assert len(edit["slide"]["html"]) < len(original["html"])
    assert 'class="slide' in edit["slide"]["html"] or "class='slide" in edit["slide"]["html"]
    assert edit["content_brief"] != fx["deck_spec"]["slides"][1]["content_brief"]


def _skeleton(html: str) -> list[tuple]:
    """Start/end tags with their attributes, text dropped."""
    out: list[tuple] = []

    class _P(HTMLParser):
        def handle_starttag(self, tag, attrs):
            out.append(("start", tag, tuple(attrs)))

        def handle_endtag(self, tag):
            out.append(("end", tag))

    _P().feed(html)
    return out


def test_edit_keeps_every_element_and_class_and_only_shortens_text():
    fx = _fx()
    original = fx["slides"][1]["html"]
    edited = fx["stages"]["edit"]["slide"]["html"]
    assert _skeleton(edited) == _skeleton(original)
    labels = re.compile(r"<strong>(.*?)</strong>")
    assert labels.findall(edited) == labels.findall(original)


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
