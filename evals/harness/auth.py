"""Pin the eval harness to one Databricks CLI profile.

``src.core.database`` calls ``load_dotenv()`` on import, which injects the repo
``.env``'s ``DATABRICKS_HOST`` / ``DATABRICKS_TOKEN`` (possibly a stale workspace).
Every live call in the harness (endpoint probe, agent model calls, judge) reads
those env vars, so an explicit profile must be written INTO the env, overwriting
whatever is there. ``load_dotenv(override=False)`` never overrides a set var, so
the profile wins regardless of import order.
"""
from __future__ import annotations

import os

from databricks.sdk.core import Config

DEFAULT_PROFILE = "tellr-dev"

# Auth-bearing env vars that would otherwise leak into (or conflict with) the
# profile's resolution. The SDK fills any attribute not set explicitly from the
# env, so a stale DATABRICKS_HOST would beat the profile's host if left in place.
_AUTH_ENV = (
    "DATABRICKS_HOST",
    "DATABRICKS_TOKEN",
    "DATABRICKS_CONFIG_PROFILE",
    "DATABRICKS_AUTH_TYPE",
    "DATABRICKS_CLIENT_ID",
    "DATABRICKS_CLIENT_SECRET",
    "DATABRICKS_USERNAME",
    "DATABRICKS_PASSWORD",
)


def apply_profile(profile: str) -> str:
    """Resolve ``profile`` from ~/.databrickscfg and make it the env's only auth.

    PAT profile: sets DATABRICKS_HOST + DATABRICKS_TOKEN.
    Token-less (OAuth/CLI) profile: sets DATABRICKS_HOST + DATABRICKS_CONFIG_PROFILE
    and removes DATABRICKS_TOKEN. Returns the resolved host. Never logs the token.
    """
    for k in _AUTH_ENV:
        os.environ.pop(k, None)
    try:
        cfg = Config(profile=profile)
    except Exception as e:  # noqa: BLE001 - surface any resolution failure as a clean exit
        raise SystemExit(f"cannot resolve Databricks profile {profile!r}: {e}") from e
    host = cfg.host
    if not host:
        raise SystemExit(f"Databricks profile {profile!r} resolved no host")
    os.environ["DATABRICKS_HOST"] = host
    if cfg.token:
        os.environ["DATABRICKS_TOKEN"] = cfg.token
    else:
        os.environ["DATABRICKS_CONFIG_PROFILE"] = profile
        os.environ.pop("DATABRICKS_TOKEN", None)
    return host
