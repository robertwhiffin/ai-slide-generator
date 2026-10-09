"""C1: render-dependent self-tests skip honestly when no Playwright chromium can be launched."""
import pytest

from evals.harness import render


class _Boom:
    def __enter__(self):
        raise RuntimeError("Executable doesn't exist at ~/.cache/ms-playwright/chromium")

    def __exit__(self, *a):
        return False


def test_chromium_available_is_false_when_launch_fails(monkeypatch):
    monkeypatch.delenv("EVALS_FORCE_NO_CHROMIUM", raising=False)
    import playwright.sync_api as sync_api

    monkeypatch.setattr(sync_api, "sync_playwright", lambda: _Boom())
    assert render.chromium_available.__wrapped__() is False


def test_chromium_available_is_cached():
    assert hasattr(render.chromium_available, "cache_info")


def test_requires_chromium_skips_with_the_explicit_reason(monkeypatch, request):
    monkeypatch.setattr(render, "chromium_available", lambda: False)
    with pytest.raises(pytest.skip.Exception, match="Playwright chromium not installed"):
        request.getfixturevalue("requires_chromium")


def test_force_env_makes_chromium_unavailable(monkeypatch):
    monkeypatch.setenv("EVALS_FORCE_NO_CHROMIUM", "1")
    assert render.chromium_available.__wrapped__() is False
