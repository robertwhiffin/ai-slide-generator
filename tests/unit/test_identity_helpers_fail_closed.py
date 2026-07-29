"""HIGH-6: identity helpers must not swallow OBO-client failures in production."""

from unittest.mock import MagicMock

import pytest

from src.core.databricks_client import UserClientRequiredError


def _raise_user_client_required():
    raise UserClientRequiredError("no OBO client bound")


# --- google_slides._get_user_identity -------------------------------------


def test_google_identity_dev_early_return(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "test")
    from src.api.routes.google_slides import _get_user_identity

    assert _get_user_identity() == "local_dev"


def test_google_identity_propagates_failure_in_production(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setattr(
        "src.core.databricks_client.get_user_client", _raise_user_client_required
    )
    from src.api.routes.google_slides import _get_user_identity

    with pytest.raises(UserClientRequiredError):
        _get_user_identity()


def test_google_identity_returns_username_in_production(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    client = MagicMock()
    client.current_user.me.return_value.user_name = "alice@test.com"
    monkeypatch.setattr(
        "src.core.databricks_client.get_user_client", lambda: client
    )
    from src.api.routes.google_slides import _get_user_identity

    assert _get_user_identity() == "alice@test.com"


def test_google_identity_empty_username_fails_closed(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    client = MagicMock()
    client.current_user.me.return_value.user_name = None
    monkeypatch.setattr(
        "src.core.databricks_client.get_user_client", lambda: client
    )
    from src.api.routes.google_slides import _get_user_identity

    with pytest.raises(UserClientRequiredError):
        _get_user_identity()


# --- images._get_current_user ----------------------------------------------


def test_images_user_dev_early_return(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "test")
    from src.api.routes.images import _get_current_user

    assert _get_current_user() == "system"


def test_images_user_propagates_failure_in_production(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setattr(
        "src.core.databricks_client.get_user_client", _raise_user_client_required
    )
    from src.api.routes.images import _get_current_user

    with pytest.raises(UserClientRequiredError):
        _get_current_user()


def test_images_user_returns_username_in_production(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    client = MagicMock()
    client.current_user.me.return_value.user_name = "bob@test.com"
    monkeypatch.setattr(
        "src.core.databricks_client.get_user_client", lambda: client
    )
    from src.api.routes.images import _get_current_user

    assert _get_current_user() == "bob@test.com"
