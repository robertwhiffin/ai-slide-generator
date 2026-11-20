"""Each hostile slide-root fixture is its benign twin plus one ``<script>``, byte for byte.

The hostile-realm suites compare a hostile fixture's export with its benign
twin's and read any difference as what the hostile script did
(``test_export_accessor_hostile_realm.py``,
``test_export_canvas_preflight_hostile_realm.py``,
``test_export_collection_iteration_hostile_realm.py``,
``test_export_snapshot_hostile_realm.py``). That holds only while the two
documents differ by that script alone: an edit made to one copy of a shared
comment or rule and not the other would be read as the script's doing. So each
fixture here must be its twin with exactly one ``<script>`` element inserted,
and nothing else changed.

Files only: no browser, no sidecar.
"""

from __future__ import annotations

from pathlib import Path

import pytest

FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "export_slide_root"

# Each hostile fixture that is a copy of a benign twin plus its script, and that twin.
TWIN_COPIES = {
    "hostile_canvas_iterator_stall": "every_collection_pass",
    "hostile_canvas_selector_stall": "every_collection_pass",
    "hostile_canvas_selector_throw": "every_collection_pass",
    "hostile_foreach_endless": "every_collection_pass",
    "hostile_foreach_silent": "every_collection_pass",
    "hostile_selector_all_decoy": "every_collection_pass",
    "hostile_selector_decoy": "every_collection_pass",
    "hostile_collection_passes": "collection_passes",
    "hostile_range_rects": "collection_passes",
    "hostile_text_nodes": "collection_passes",
    "hostile_fallback_selector_decoy": "fallback_div_ground",
    "hostile_wrapper_selector_all": "wrapped_nested_bare_slide",
}


def _inserted(benign: str, hostile: str) -> str | None:
    """What ``hostile`` holds that ``benign`` does not, when it is ``benign`` with one insertion."""
    prefix = 0
    while prefix < min(len(benign), len(hostile)) and benign[prefix] == hostile[prefix]:
        prefix += 1
    suffix = 0
    while (
        suffix < min(len(benign), len(hostile)) - prefix
        and benign[-1 - suffix] == hostile[-1 - suffix]
    ):
        suffix += 1
    if prefix + suffix != len(benign):
        return None
    return hostile[prefix : len(hostile) - suffix]


@pytest.mark.parametrize(("hostile", "benign"), sorted(TWIN_COPIES.items()))
def test_a_hostile_fixture_is_its_twin_plus_one_script(hostile: str, benign: str) -> None:
    benign_text = (FIXTURE_DIR / f"{benign}.html").read_text(encoding="utf-8")
    hostile_text = (FIXTURE_DIR / f"{hostile}.html").read_text(encoding="utf-8")

    inserted = _inserted(benign_text, hostile_text)

    assert inserted is not None, (
        f"{hostile}.html is no longer {benign}.html with one insertion: a shared line "
        "differs between the two, so the hostile suites would read that difference "
        "as the hostile script's doing"
    )
    script = inserted.strip()
    assert script.startswith("<script>") and script.endswith("</script>"), (
        f"what {hostile}.html adds to {benign}.html is not one <script> element: "
        f"{script[:80]!r} … {script[-40:]!r}"
    )
    # A script element ends at its first "</script", so one closing tag is one element.
    assert script.count("</script") == 1, (
        f"{hostile}.html adds more than one <script> element to {benign}.html"
    )
