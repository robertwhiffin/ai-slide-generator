"""evals.harness.auth.apply_profile: an explicit profile beats .env / shell DATABRICKS_* vars."""
from __future__ import annotations

import os

import pytest

from evals.harness import auth

STALE_HOST = "https://adb-stale.azuredatabricks.net"
PROFILE_HOST = "https://profile-host.cloud.databricks.com"


class FakeConfig:
    def __init__(self, token):
        self._token = token
        self.seen = []

    def __call__(self, *, profile):
        # Record the auth env visible at resolution time: a stale value here would
        # leak into the real SDK Config (env fills attributes the profile does not pin).
        self.seen.append({k: os.environ.get(k) for k in auth._AUTH_ENV})
        return type("Cfg", (), {"host": PROFILE_HOST, "token": self._token, "profile": profile})()


@pytest.fixture
def stale_env(monkeypatch):
    monkeypatch.setenv("DATABRICKS_HOST", STALE_HOST)
    monkeypatch.setenv("DATABRICKS_TOKEN", "stale-token")
    monkeypatch.setenv("DATABRICKS_CONFIG_PROFILE", "some-other-profile")
    for k in ("DATABRICKS_AUTH_TYPE", "DATABRICKS_CLIENT_ID", "DATABRICKS_CLIENT_SECRET"):
        monkeypatch.delenv(k, raising=False)


def test_pat_profile_sets_host_and_token_over_stale_env(monkeypatch, stale_env):
    fake = FakeConfig(token="profile-pat")
    monkeypatch.setattr(auth, "Config", fake)
    assert auth.apply_profile("tellr-dev") == PROFILE_HOST
    assert os.environ["DATABRICKS_HOST"] == PROFILE_HOST
    assert os.environ["DATABRICKS_TOKEN"] == "profile-pat"
    assert "DATABRICKS_CONFIG_PROFILE" not in os.environ
    # the stale env was cleared BEFORE the profile was resolved
    assert fake.seen == [{k: None for k in auth._AUTH_ENV}]


def test_tokenless_profile_sets_host_and_profile_and_removes_token(monkeypatch, stale_env):
    fake = FakeConfig(token=None)
    monkeypatch.setattr(auth, "Config", fake)
    assert auth.apply_profile("oauth-prof") == PROFILE_HOST
    assert os.environ["DATABRICKS_HOST"] == PROFILE_HOST
    assert os.environ["DATABRICKS_CONFIG_PROFILE"] == "oauth-prof"
    assert "DATABRICKS_TOKEN" not in os.environ
    assert fake.seen == [{k: None for k in auth._AUTH_ENV}]


def test_profile_beats_dotenv_loaded_after(monkeypatch, stale_env, tmp_path):
    """load_dotenv(override=False) -- what src.core.database does -- never undoes the profile."""
    from dotenv import load_dotenv

    monkeypatch.setattr(auth, "Config", FakeConfig(token="profile-pat"))
    auth.apply_profile("tellr-dev")
    env_file = tmp_path / ".env"
    env_file.write_text(f"DATABRICKS_HOST={STALE_HOST}\nDATABRICKS_TOKEN=stale-token\n")
    load_dotenv(env_file)
    assert os.environ["DATABRICKS_HOST"] == PROFILE_HOST
    assert os.environ["DATABRICKS_TOKEN"] == "profile-pat"


def test_unresolvable_profile_exits_naming_it(monkeypatch, stale_env):
    def boom(*, profile):
        raise ValueError("profile not found")

    monkeypatch.setattr(auth, "Config", boom)
    with pytest.raises(SystemExit) as e:
        auth.apply_profile("nope-profile")
    assert "nope-profile" in str(e.value)
