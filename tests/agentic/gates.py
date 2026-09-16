"""Layer 3's three gates, defined once so seven modules cannot drift apart.

WHAT LAYER 3 IS
---------------
The suite has four layers, organised by *what each needs in order to run* rather
than by marker:

======  ==========================================  ======
Layer   Needs                                       In CI
======  ==========================================  ======
1       nothing — stub agents, real compiled graph   yes (``integration-graph``)
2       nothing — canned payloads                    yes
3       **a real model via Databricks**              no
4       a database, no model                         yes
======  ==========================================  ======

This directory is layer 3.  Every module here calls ``call_skill`` against a real
serving endpoint and asserts what the *agent* did — so it cannot run on a runner
with no credentials, and it costs real money where it can.

WHY THIS DIRECTORY IS A SIBLING OF ``tests/unit/``, NOT A SUBDIRECTORY
---------------------------------------------------------------------
Measured, not assumed: the ``unit-tests`` job runs ``pytest tests/unit -v
--tb=short -n auto`` with **no ``-m`` filter and no Databricks credentials at
all**.  Under ``tests/unit/`` the ``live`` marker is therefore **not a CI gate** —
it selects nothing and excludes nothing.  The repo documents the consequence
against itself in ``tests/unit/test_dependencies_resolve.py``: those tests *are*
collected in CI and are saved "only incidentally because the Databricks proxy
host is unreachable".  A layer-3 suite parked under ``tests/unit/`` would be
collected on day one, and would be saved only by an accident of network
topology.

THE THREE MECHANISMS, AND WHY NONE OF THEM SUBSTITUTES FOR ANOTHER
------------------------------------------------------------------
Each carries a different meaning.  Collapsing them into one is the mistake this
module exists to prevent:

``live`` (:data:`LIVE`)
    **Selection.**  How the future CI job picks these tests
    (``pytest tests/agentic -m live``), and how ``-m "not live"`` deselects them
    everywhere else.

``skipif`` on endpoint reachability (:data:`ENDPOINT_GATE`)
    **Safety.**  A module collected on a machine that cannot reach a Databricks
    endpoint skips rather than fails.  This is a *reachability* probe, not an
    env-var presence check, and deliberately so: six CI jobs export
    ``DATABRICKS_HOST: https://test.cloud.databricks.com`` with
    ``DATABRICKS_TOKEN: test-token``, so a presence check would report "credentials
    present" on a runner and let a real model call be attempted with a fake host.

unconditional ``skip`` (:data:`PLACEHOLDER_GATE`)
    **Honesty**, and it is the one that actually applies today.  The local
    ``.env`` supplies ``DATABRICKS_HOST``, so the endpoint gate *passes* on a
    developer's laptop.  The real barrier is elsewhere: the seven skills ship
    **placeholder prompts** — substantive, functional instruction text that has
    not been prompt-engineered.  ``src/core/skills/__init__.py`` says so itself
    ("C9 replaces these placeholder strings with the authored prose; the graph
    runs on placeholders until then"), and so does ws4c's handover.  Layer-3
    assertions are written against the *real* prompts, so they will not pass
    against placeholders.

    The failure mode being refused is **weakening a layer-3 assertion until a
    placeholder satisfies it**, which manufactures a test that cannot fail.  A
    skipped honest test beats a passing dishonest one, so the tests keep their
    real assertions and ship skipped.

HOW TO RETIRE THE PLACEHOLDER GATE (the only edit inside ``tests/``)
-------------------------------------------------------------------
When the authored prompts land, delete :data:`PLACEHOLDER_GATE` from
:data:`LAYER3_MARKS` **here** — one edit, in one file, for the whole layer.  No
test file changes, no marker changes, no assertion changes.
``tests/unit/test_agentic_layer_is_placed_and_gated.py`` pins the skill versions
that shipped with placeholders, so re-authoring the prompts turns that guard red
and puts this decision in front of whoever changed them.

Enabling the CI *job* is a separate, workflow-side change — see that job's own
comment in ``.github/workflows/test.yml``.
"""

from __future__ import annotations

import os
import socket
from urllib.parse import urlsplit

import pytest

# ``src/core/database.py`` calls ``load_dotenv()``, but only once something
# imports it — so at module scope the local ``.env`` may not be loaded yet and the
# endpoint gate below would report "unreachable" on a machine that actually has
# credentials.  Load it here so the gate is independent of import order.  This is
# the same accommodation ``tests/integration/test_graph_live_real_model.py``
# makes, for the same reason.
try:
    from dotenv import load_dotenv

    load_dotenv()
except Exception:  # python-dotenv absent is not a reason to fail collection
    pass


#: A short timeout: the probe runs at import time, and a slow one would tax
#: every ``pytest tests/`` baseline run.
_PROBE_TIMEOUT_SECONDS = 1.5

#: HTTPS.  A Databricks workspace endpoint is not reachable on any other port.
_PROBE_PORT = 443


def _host_from_env() -> str | None:
    """The bare hostname of ``DATABRICKS_HOST``, or ``None`` when unusable.

    ``DATABRICKS_HOST`` is spelled both ways in this repo's environments —
    ``https://adb-….azuredatabricks.net`` and a bare host — so parse rather than
    assume.  ``DATABRICKS_TOKEN`` must be present too: a reachable host with no
    token cannot authenticate, and the resulting failure would look like a
    behavioural finding rather than a missing credential.
    """
    host = (os.environ.get("DATABRICKS_HOST") or "").strip()
    token = (os.environ.get("DATABRICKS_TOKEN") or "").strip()
    if not host or not token:
        return None
    parsed = urlsplit(host if "//" in host else f"//{host}")
    return parsed.hostname


def _probe() -> tuple[bool, str]:
    """Return ``(reachable, reason)``; the reason describes the *unreachable* case.

    Computed ONCE, at import of this module, and shared by every layer-3 module —
    so a whole ``pytest tests/agentic`` run makes at most one TCP connection, not
    one per file.  When the environment carries no credentials there is no network
    call at all, which is what keeps this module importable from ``tests/unit/``
    (where the placement guard reads it) without CI reaching the network.
    """
    host = _host_from_env()
    if host is None:
        return False, (
            "layer 3 needs DATABRICKS_HOST and DATABRICKS_TOKEN; a local .env "
            "supplies both (src/core/database.py calls load_dotenv())"
        )
    try:
        with socket.create_connection((host, _PROBE_PORT), _PROBE_TIMEOUT_SECONDS):
            return True, ""
    except OSError as exc:
        return False, (
            f"layer 3 needs a reachable Databricks endpoint: {host}:{_PROBE_PORT} "
            f"did not accept a connection within {_PROBE_TIMEOUT_SECONDS}s ({exc})"
        )


ENDPOINT_REACHABLE, _ENDPOINT_UNREACHABLE_REASON = _probe()

#: Kept verbatim in the skip reason so ``pytest -rs`` explains itself, and so a
#: reader who greps for the phrase in the plan finds the mechanism.
PLACEHOLDER_SKIP_REASON = (
    "real prompts pending: the seven skills ship placeholder prompts by design "
    "(src/core/skills/__init__.py, ws4c handover), and no assertion here will be "
    "weakened until one satisfies it. Retire this gate in tests/agentic/gates.py "
    "when the authored prompts land."
)

#: Selection — the marker the future CI job filters on.
LIVE = pytest.mark.live

#: Safety — a collected module with no reachable endpoint skips, never fails.
ENDPOINT_GATE = pytest.mark.skipif(
    not ENDPOINT_REACHABLE,
    reason=_ENDPOINT_UNREACHABLE_REASON
    or "a Databricks endpoint is reachable; this gate is not what is skipping",
)

#: Honesty — the barrier that actually applies today.
PLACEHOLDER_GATE = pytest.mark.skip(reason=PLACEHOLDER_SKIP_REASON)

#: The module-level ``pytestmark`` every layer-3 file uses::
#:
#:     from tests.agentic.gates import LAYER3_MARKS
#:     pytestmark = LAYER3_MARKS
#:
#: Order matters only for legibility: pytest applies ``skipif`` before ``skip``,
#: and either one skipping is enough.
LAYER3_MARKS = [LIVE, ENDPOINT_GATE, PLACEHOLDER_GATE]

#: The contract ``tests/unit/test_agentic_layer_is_placed_and_gated.py`` enforces:
#: which names a layer-3 module may name in its ``pytestmark``, and which of the
#: three mechanisms each one supplies.  A module satisfies the guard by using
#: :data:`LAYER3_MARKS`, or by naming the three constants individually, or by
#: spelling ``pytest.mark.live`` / ``pytest.mark.skipif(...)`` /
#: ``pytest.mark.skip(...)`` inline.
#:
#: Published from here rather than hard-coded in the guard so that renaming a
#: constant cannot leave the guard quietly accepting a name that no longer exists.
MECHANISMS_BY_NAME: dict[str, frozenset[str]] = {
    "LAYER3_MARKS": frozenset({"live", "skipif", "skip"}),
    "LIVE": frozenset({"live"}),
    "ENDPOINT_GATE": frozenset({"skipif"}),
    "PLACEHOLDER_GATE": frozenset({"skip"}),
}


def frame_constraint_numbers() -> dict[str, int]:
    """Parse the slide-frame numbers out of ``_SLIDE_FRAME_CONSTRAINTS`` itself.

    The builder and the reviewer are both shown that block (``assemble_skill_prompt``
    appends it whenever ``design_system_active`` is false), and the ``overflow``
    criterion tells the reviewer to "judge against ``_SLIDE_FRAME_CONSTRAINTS``
    numbers, never reviewer-invented numbers".  A fixture that hard-coded 1280 or
    720 would be judging the model against numbers of the *test's* invention, and
    would go stale silently the day the block changes.

    Raises:
        AssertionError: if the block's shape changed such that a number cannot be
            found.  A fixture builder that quietly fell back to a default would
            produce a slide that does not overflow and a test that cannot fail.
    """
    import re

    from src.services.design_system_compiler import _SLIDE_FRAME_CONSTRAINTS

    frame = re.search(r"(\d+)\s*x\s*(\d+)\s*px", _SLIDE_FRAME_CONSTRAINTS)
    assert frame, (
        "could not find the frame size in _SLIDE_FRAME_CONSTRAINTS. The block's "
        "shape changed; re-read it and update this parser rather than hard-coding "
        "a size here — the whole point is that these numbers have one source."
    )
    horizontal = re.search(r"at least (\d+)px", _SLIDE_FRAME_CONSTRAINTS)
    vertical_floor = re.search(r"NEVER go below (\d+)px", _SLIDE_FRAME_CONSTRAINTS)
    assert horizontal and vertical_floor, (
        "could not find the safe-area numbers in _SLIDE_FRAME_CONSTRAINTS; see above."
    )
    return {
        "width": int(frame.group(1)),
        "height": int(frame.group(2)),
        "horizontal_clearance": int(horizontal.group(1)),
        "vertical_floor": int(vertical_floor.group(1)),
    }
