"""HIGH-6: identity helpers must not swallow OBO-client failures in production.

The helpers read the identity the auth middleware resolved for the request
(``set_current_user``) instead of calling SCIM ``/Me`` again — logfood rate-limits
``/Me``. With no resolved identity they still fail closed.
"""

from unittest.mock import MagicMock

import pytest

from src.core.databricks_client import UserClientRequiredError, reset_user_client, set_user_client
from src.core.user_context import set_current_user


@pytest.fixture(autouse=True)
def _clean_request_context():
    reset_user_client()
    set_current_user(None)
    yield
    reset_user_client()
    set_current_user(None)


def _bind_client_that_must_not_call_me():
    """A bound OBO client whose ``/Me`` call fails the test if made."""
    client = MagicMock()
    client.current_user.me.side_effect = AssertionError("helper made an extra /Me call")
    set_user_client(client)
    return client


# --- google_slides._get_user_identity -------------------------------------


def test_google_identity_dev_early_return(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "test")
    from src.api.routes.google_slides import _get_user_identity

    assert _get_user_identity() == "local_dev"


def test_google_identity_fails_closed_without_request_identity(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    from src.api.routes.google_slides import _get_user_identity

    with pytest.raises(UserClientRequiredError):
        _get_user_identity()


def test_google_identity_returns_request_username_without_me_call(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    client = _bind_client_that_must_not_call_me()
    set_current_user("alice@test.com")
    from src.api.routes.google_slides import _get_user_identity

    assert _get_user_identity() == "alice@test.com"
    client.current_user.me.assert_not_called()


def test_google_identity_empty_username_fails_closed(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    _bind_client_that_must_not_call_me()
    set_current_user("")
    from src.api.routes.google_slides import _get_user_identity

    with pytest.raises(UserClientRequiredError):
        _get_user_identity()


# --- images._get_current_user ----------------------------------------------


def test_images_user_dev_early_return(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "test")
    from src.api.routes.images import _get_current_user

    assert _get_current_user() == "system"


def test_images_user_fails_closed_without_request_identity(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    from src.api.routes.images import _get_current_user

    with pytest.raises(UserClientRequiredError):
        _get_current_user()


def test_images_user_returns_request_username_without_me_call(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    client = _bind_client_that_must_not_call_me()
    set_current_user("bob@test.com")
    from src.api.routes.images import _get_current_user

    assert _get_current_user() == "bob@test.com"
    client.current_user.me.assert_not_called()


# --- design_systems._current_user -------------------------------------------


def test_design_systems_user_returns_request_username_without_me_call(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    client = _bind_client_that_must_not_call_me()
    set_current_user("carol@test.com")
    from src.api.routes.settings.design_systems import _current_user

    assert _current_user() == "carol@test.com"
    client.current_user.me.assert_not_called()


# --- databricks_client.require_request_username (deck_prompts, slide_styles) --


def test_require_request_username_returns_request_username():
    from src.core.databricks_client import require_request_username

    set_current_user("dave@test.com")
    assert require_request_username() == "dave@test.com"


def test_require_request_username_fails_closed_without_identity():
    from src.core.databricks_client import require_request_username

    with pytest.raises(UserClientRequiredError):
        require_request_username()
