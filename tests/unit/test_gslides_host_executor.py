# tests/unit/test_gslides_host_executor.py
"""Google Slides jail + host-executor contract tests (SDR-4437 PR-5)."""

import json
from pathlib import Path

from src.services.converter_jail import gslides_runner, protocol


def _write(job, idx, code, page_id, html="<p>x</p>"):
    sdir = job / f"slide_{idx:03d}"
    (sdir / protocol.ASSETS_DIR).mkdir(parents=True)
    (sdir / protocol.HTML_NAME).write_text(html)
    if code is not None:
        (sdir / protocol.CODE_NAME).write_text(code)
    return {"index": idx, "has_code": code is not None,
            "dir": sdir.name, "page_id": page_id}


def test_runner_emits_request_json(tmp_path):
    job = tmp_path / "job"
    job.mkdir()
    good = (
        "def build_slide_requests(html_str, assets_dir, page_id):\n"
        "    import uuid\n"
        "    return [{'createShape': {'objectId': 'txt_' + uuid.uuid4().hex[:8],\n"
        "        'shapeType': 'TEXT_BOX', 'elementProperties': {'pageObjectId': page_id}}}]\n"
    )
    bad = (
        "def build_slide_requests(html_str, assets_dir, page_id):\n"
        "    raise ValueError('boom')\n"
    )
    manifest = {"slides": [
        _write(job, 0, good, "page_a"),
        _write(job, 1, bad, "page_b"),
    ]}
    (job / protocol.MANIFEST_NAME).write_text(json.dumps(manifest))
    out = tmp_path / "requests.json"

    gslides_runner.run(str(job), str(out))
    data = json.loads(out.read_text())

    assert data[0]["requests"][0]["createShape"]["shapeType"] == "TEXT_BOX"
    assert data[0]["error"] is None
    assert data[1]["requests"] is None       # bad slide isolated
    assert "ValueError" in data[1]["error"]
