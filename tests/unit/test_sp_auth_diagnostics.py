"""SDR-4437 F-CR-18: the SP auth probe must report presence only, never credentials."""

from types import SimpleNamespace

from src.core.databricks_client import sp_auth_diagnostics


def _client(auth_type="pat"):
    return SimpleNamespace(config=SimpleNamespace(auth_type=auth_type))


def test_reports_presence_of_m2m_credentials(monkeypatch):
    monkeypatch.setenv("DATABRICKS_CLIENT_ID", "some-client-id")
    monkeypatch.setenv("DATABRICKS_CLIENT_SECRET", "some-client-secret")
    monkeypatch.delenv("DATABRICKS_TOKEN", raising=False)

    diag = sp_auth_diagnostics(_client("oauth-m2m"))

    assert diag == {
        "has_client_id": True,
        "has_client_secret": True,
        "has_token": False,
        "resolved_auth_type": "oauth-m2m",
    }


def test_reports_token_winning_over_m2m(monkeypatch):
    """The finding's mechanism: a token in the env makes the SDK pick pat over oauth-m2m."""
    monkeypatch.setenv("DATABRICKS_CLIENT_ID", "some-client-id")
    monkeypatch.setenv("DATABRICKS_CLIENT_SECRET", "some-client-secret")
    monkeypatch.setenv("DATABRICKS_TOKEN", "some-token")

    diag = sp_auth_diagnostics(_client("pat"))

    assert diag["has_token"] is True
    assert diag["resolved_auth_type"] == "pat"


def test_never_leaks_credential_values(monkeypatch):
    monkeypatch.setenv("DATABRICKS_CLIENT_ID", "id-sentinel")
    monkeypatch.setenv("DATABRICKS_CLIENT_SECRET", "secret-sentinel")
    monkeypatch.setenv("DATABRICKS_TOKEN", "token-sentinel")

    rendered = repr(sp_auth_diagnostics(_client()))

    for sentinel in ("id-sentinel", "secret-sentinel", "token-sentinel"):
        assert sentinel not in rendered


def test_missing_secret_is_reported_absent(monkeypatch):
    """The question the probe exists to answer: is a usable client_secret injected?"""
    monkeypatch.setenv("DATABRICKS_CLIENT_ID", "some-client-id")
    monkeypatch.delenv("DATABRICKS_CLIENT_SECRET", raising=False)

    assert sp_auth_diagnostics(_client())["has_client_secret"] is False


def test_survives_unreadable_config():
    class Exploding:
        @property
        def auth_type(self):
            raise RuntimeError("boom")

    diag = sp_auth_diagnostics(SimpleNamespace(config=Exploding()))

    assert diag["resolved_auth_type"] == "unavailable: RuntimeError"
