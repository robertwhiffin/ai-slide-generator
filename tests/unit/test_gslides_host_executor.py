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


import pytest

from src.services.html_to_google_slides import (
    HtmlToGoogleSlidesConverter,
    GoogleSlidesConversionError,
)


def _conv():
    return HtmlToGoogleSlidesConverter.__new__(HtmlToGoogleSlidesConverter)


class TestValidateRequests:
    def test_accepts_known_request_types(self):
        reqs = [{"createShape": {"objectId": "a", "shapeType": "TEXT_BOX"}},
                {"insertText": {"objectId": "a", "text": "hi"}}]
        assert _conv()._validate_requests(reqs) == reqs

    def test_rejects_unknown_top_level_key(self):
        with pytest.raises(GoogleSlidesConversionError):
            _conv()._validate_requests([{"exfiltrate": {"url": "http://evil"}}])

    def test_rejects_non_placeholder_non_https_image_url(self):
        with pytest.raises(GoogleSlidesConversionError):
            _conv()._validate_requests(
                [{"createImage": {"objectId": "i", "url": "file:///etc/passwd"}}]
            )

    def test_accepts_placeholder_image_url(self):
        reqs = [{"createImage": {"objectId": "i", "url": "tellr-asset://chart_0.png"}}]
        assert _conv()._validate_requests(reqs) == reqs

    def test_rejects_raw_https_image_url(self):
        # SDR-4437 PR-5 MEDIUM: raw https urls are Google-side SSRF (Google
        # fetches server-side). Every legit image now flows through
        # tellr-asset:// + host upload, so https is no longer accepted.
        with pytest.raises(GoogleSlidesConversionError):
            _conv()._validate_requests(
                [{"createImage": {"objectId": "i", "url": "https://evil.example/x.png"}}]
            )

    def test_rejects_path_traversal_asset_filename(self):
        # SDR-4437 PR-5 CRITICAL: traversal in the tellr-asset:// remainder.
        with pytest.raises(GoogleSlidesConversionError):
            _conv()._validate_requests(
                [{"createImage": {"objectId": "i",
                                  "url": "tellr-asset://../../../../etc/passwd"}}]
            )

    def test_rejects_absolute_path_asset_filename(self):
        # SDR-4437 PR-5 CRITICAL: absolute path — Path(base) / "/abs" discards base.
        with pytest.raises(GoogleSlidesConversionError):
            _conv()._validate_requests(
                [{"createImage": {"objectId": "i",
                                  "url": "tellr-asset:///proc/self/environ"}}]
            )


class TestAssetPathContainment:
    """SDR-4437 PR-5 CRITICAL: the uploader must confine the resolved path to
    assets_dir even if _validate_requests were bypassed (defense in depth)."""

    def test_upload_rejects_traversal_filename(self, tmp_path):
        from unittest.mock import MagicMock
        drive = MagicMock()
        reqs = [{"createImage": {"objectId": "i",
                                 "url": "tellr-asset://../../../../etc/passwd"}}]
        with pytest.raises(GoogleSlidesConversionError):
            _conv()._upload_and_substitute_assets(reqs, drive, str(tmp_path))
        drive.files().create.assert_not_called()

    def test_upload_rejects_absolute_path_filename(self, tmp_path):
        from unittest.mock import MagicMock
        drive = MagicMock()
        reqs = [{"createImage": {"objectId": "i",
                                 "url": "tellr-asset:///etc/passwd"}}]
        with pytest.raises(GoogleSlidesConversionError):
            _conv()._upload_and_substitute_assets(reqs, drive, str(tmp_path))
        drive.files().create.assert_not_called()


class TestUploadAndSubstitute:
    def test_uploads_and_substitutes(self, tmp_path):
        from unittest.mock import MagicMock
        (tmp_path / "chart_0.png").write_bytes(b"\x89PNG\r\n")
        drive = MagicMock()
        drive.files().create().execute.return_value = {"id": "FILEID"}
        drive.permissions().create().execute.return_value = {}
        reqs = [{"createImage": {"objectId": "i", "url": "tellr-asset://chart_0.png"}}]
        out = _conv()._upload_and_substitute_assets(reqs, drive, str(tmp_path))
        assert out[0]["createImage"]["url"] == "https://drive.google.com/uc?id=FILEID"


class TestExecuteThroughChunkedService:
    def test_requests_run_through_chunking_and_retry_429(self, tmp_path, monkeypatch):
        from unittest.mock import MagicMock

        import src.services.html_to_google_slides as g
        monkeypatch.setattr(g.time, "sleep", lambda *_: None)

        conv = _conv()
        # A batchUpdate that 429s once then succeeds, proving retry is wired.
        calls = {"n": 0}

        def _batch(*a, **k):
            m = MagicMock()

            def _execute():
                calls["n"] += 1
                if calls["n"] == 1:
                    raise Exception("429 quota exceeded rate limit")
                return {"ok": True}
            m.execute.side_effect = _execute
            return m

        slides_service = MagicMock()
        slides_service.presentations().batchUpdate.side_effect = _batch
        drive = MagicMock()
        reqs = [{"createShape": {"objectId": "a", "shapeType": "TEXT_BOX",
                                 "elementProperties": {"pageObjectId": "p"}}}]
        err = conv._execute_slide_requests(
            reqs, slides_service, drive, "PRES", "p", str(tmp_path), 1,
        )
        assert err is None
        assert calls["n"] >= 2  # retried after the 429
