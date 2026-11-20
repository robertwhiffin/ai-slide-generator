"""A sidecar that runs past its timeout takes every process it started with it.

``build_pptx_huashu`` runs ``node emit_deck.mjs``, which launches Chromium for
each slide through Playwright. When the run passes ``SIDECAR_TIMEOUT_SECONDS``,
killing node alone leaves the browser it launched running with no parent: on
Databricks Apps every timed-out export would keep a Chromium's memory until the
app restarts. So the sidecar runs as the leader of its own process group, and a
timeout kills the whole group.

The sidecar here is a stub in node's place: it starts a sleeping child, as
emit_deck.mjs starts Chromium, writes both process ids where the test reads
them, and then sleeps past a short timeout itself.
"""

from __future__ import annotations

import json
import os
import signal
import time
from pathlib import Path

import pytest

from src.services import pptx_from_html_huashu
from src.services.pptx_from_html_huashu import HuashuExportError
from tests.fixtures.export_snapshot_support import requires_node

# Short enough to keep the test quick, long enough for node to start the stub
# and write its process ids first.
STUB_TIMEOUT_SECONDS = 3
# How long a killed process may take to be gone: reaped by its parent, or by
# launchd/init once its parent is gone too.
GONE_WITHIN_SECONDS = 10

# The stub sidecar. It never reads the payload on stdin and never writes the
# .pptx: it starts a child that sleeps, records both ids, and sleeps itself.
STUB_SIDECAR = """
import { spawn } from 'node:child_process';
import fs from 'node:fs';
const child = spawn('sleep', ['600'], { stdio: 'ignore' });
fs.writeFileSync(%(pids)s, JSON.stringify({ sidecar: process.pid, child: child.pid }));
setInterval(() => {}, 1000);
"""


def _alive(pid: int) -> bool:
    """Whether a process with this id exists (a zombie not yet reaped counts)."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _gone(pids: list[int]) -> list[int]:
    """The ids still alive once ``GONE_WITHIN_SECONDS`` have passed, or [] as soon as none is."""
    deadline = time.monotonic() + GONE_WITHIN_SECONDS
    while True:
        alive = [pid for pid in pids if _alive(pid)]
        if not alive or time.monotonic() > deadline:
            return alive
        time.sleep(0.1)


@requires_node
def test_a_timed_out_sidecar_leaves_no_process_behind(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pids_path = tmp_path / "pids.json"
    stub = tmp_path / "stub_sidecar.mjs"
    stub.write_text(STUB_SIDECAR % {"pids": json.dumps(str(pids_path))}, encoding="utf-8")
    monkeypatch.setattr(pptx_from_html_huashu, "SIDECAR_SCRIPT", stub)
    monkeypatch.setattr(pptx_from_html_huashu, "SIDECAR_TIMEOUT_SECONDS", STUB_TIMEOUT_SECONDS)
    monkeypatch.setattr(pptx_from_html_huashu, "is_available", lambda: True)

    started = time.monotonic()
    with pytest.raises(HuashuExportError, match="timed out"):
        pptx_from_html_huashu.build_pptx_huashu("deck", [{"html": "<p>x</p>"}])
    elapsed = time.monotonic() - started

    pids = json.loads(pids_path.read_text(encoding="utf-8"))
    try:
        alive = _gone([pids["sidecar"], pids["child"]])
        assert alive == [], (
            f"still running {GONE_WITHIN_SECONDS}s after the timeout: {alive} "
            f"(sidecar {pids['sidecar']}, its child {pids['child']})"
        )
        assert elapsed < STUB_TIMEOUT_SECONDS + GONE_WITHIN_SECONDS, (
            f"the timed-out export took {elapsed:.1f}s to return"
        )
    finally:
        for pid in (pids["sidecar"], pids["child"]):
            if _alive(pid):
                os.kill(pid, signal.SIGKILL)
