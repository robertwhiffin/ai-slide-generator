"""CI placeholders for RC3, RC6 and RC14 — all three on the graph path.

WHY EVERY TEST HERE IS SKIPPED
-------------------------------
The brief (task-E5-brief.md) requires that RC3, RC6 and RC14 be tested against the
GRAPH path, not the monolith's copy.  Existing tests in
``tests/unit/test_slide_editing_robustness.py`` and ``test_add_position_bug.py``
already pin the monolith's versions; those files are not repointed here and are not
duplicated.

Investigation of the graph path found that none of the three guards has a direct
counterpart under ``src/services/graph/``.  Each reason is recorded below as the
skip text and in the task-E5 report.  The honest form is a named skip rather than
silence: a missing test with a cause on record is preferable to a test that
claims to cover the graph path by quietly running the monolith.

RC10 IS NOT THIS FILE'S BUSINESS
---------------------------------
RC10 was written by the previous task as its own first layer-3 behaviour:
``tests/agentic/test_architect_asks_when_reference_is_ambiguous.py::
test_the_architect_asks_which_slide_rather_than_choosing_one``.
It is one test, not two; this file does not write a second.

SABOTAGE-VERIFY NOTE
---------------------
The task brief requires CI tests to be sabotage-verified (break the production guard,
confirm the test reddens for the right reason, restore).  Because all three guards in
this file are skipped — the production guard they would cover lives on the monolith
path, not the graph path — there is no guard on the executed path to sabotage, and
the sabotage step therefore does not apply.  This is recorded in the task-E5 report
rather than faked.
"""

from __future__ import annotations

import pytest

# ---------------------------------------------------------------------------
# RC3 — graph path
# ---------------------------------------------------------------------------

_RC3_SKIP_REASON = (
    "RC3's guard ('slide_context was provided but LLM parsing failed') has no "
    "counterpart on the graph path.  The graph path invokes invoke_graph with only "
    "{'architect_message': message}; no slide_context is supplied by the frontend, "
    "and the architect generates its own target_positions independently.  The "
    "precondition for RC3 (slide_context not None, replacement_info None) cannot "
    "arise on the graph path.  The graph's deck-preservation property is structural: "
    "slides are individual database rows and a failed turn leaves them untouched "
    "rather than relying on an explicit guard. "
    "Existing coverage: tests/unit/test_slide_editing_robustness.py covers RC3 on "
    "the monolith (chat_service.py:707 sync, :1461 streaming)."
)


@pytest.mark.skip(reason=_RC3_SKIP_REASON)
def test_rc3_slide_context_parsing_failure_preserves_deck_on_graph_path():
    """RC3 on the graph path: slide_context provided but parsing failed → preserve deck.

    Skipped: precondition unreachable on the graph path — no slide_context is
    supplied to invoke_graph.  See module docstring for the full analysis.
    """
    raise AssertionError("not reachable while skipped")


# ---------------------------------------------------------------------------
# RC6 — graph path
# ---------------------------------------------------------------------------

_RC6_SKIP_REASON = (
    "RC6's guard ('deck cache survives backend restarts') is subsumed by "
    "row-per-slide persistence on the graph path.  The monolith holds an "
    "in-process cache (ChatService._deck_cache) that must survive restarts by "
    "falling back to the database via _get_or_load_deck.  The graph path holds no "
    "such cache: architect_node calls _committed_slide_rows which reads the "
    "session_slides table directly on every turn, and the checkpointer likewise "
    "reads from its own table.  After a backend restart the graph path reads fresh "
    "rows unconditionally; there is nothing to 'survive' because there is nothing "
    "in-process to lose. "
    "Existing coverage: tests/unit/test_slide_editing_robustness.py covers RC6 on "
    "the monolith (chat_service.py:692 sync, :1443 streaming)."
)


@pytest.mark.skip(reason=_RC6_SKIP_REASON)
def test_rc6_deck_cache_survives_backend_restart_on_graph_path():
    """RC6 on the graph path: deck cache survives backend restarts.

    Skipped: the graph path has no deck cache — row-per-slide persistence in the
    database subsumes this protection entirely.  See module docstring.
    """
    raise AssertionError("not reachable while skipped")


# ---------------------------------------------------------------------------
# RC14 — graph path
# ---------------------------------------------------------------------------

_RC14_SKIP_REASON = (
    "RC14's guard ('frontend/backend deck-state mismatch') has no counterpart on "
    "the graph path.  RC14 sits at chat_service.py:1258 (streaming only) and "
    "validates slide_context.indices supplied by the frontend against the backend "
    "deck's actual slide count.  The graph path is reached through "
    "send_message_streaming_graph, which calls invoke_graph with only "
    "{'architect_message': message}; no slide_context.indices travels from the "
    "frontend to the graph path, so the index-validation precondition cannot arise. "
    "The graph path's protection against stale frontend state is architectural: "
    "the architect is told committed_slide_count from the database directly "
    "(architect_node:1369), so it works from the backend's actual count rather than "
    "a frontend-provided claim.  A related but distinct guard (spec_positions_stale "
    "at nodes.py:1446-1482) detects spec-vs-rows mismatches on the graph path; it "
    "is not RC14, which is specifically about slide_context.indices from the "
    "frontend. "
    "Existing coverage: tests/unit/test_add_position_bug.py::TestRC14StateValidation "
    "covers RC14 on the monolith (chat_service.py:1258 streaming)."
)


@pytest.mark.skip(reason=_RC14_SKIP_REASON)
def test_rc14_frontend_backend_deck_state_mismatch_on_graph_path():
    """RC14 on the graph path: frontend/backend deck-state mismatch raises error.

    Skipped: slide_context.indices is not supplied to invoke_graph, so the
    frontend/backend mismatch precondition cannot arise on the graph path.
    See module docstring for the full analysis.
    """
    raise AssertionError("not reachable while skipped")
