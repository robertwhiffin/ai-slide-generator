"""Startup wiring: all DB migrations run ONCE in the pre-app init step.

The uvicorn workers must never run migration code (the FastAPI lifespan no longer
calls init_db / migrate_profiles / backfill_sessions). Everything that mutates the
schema or data runs once, before the server forks, in run.py::init_database — so
these tests pin that init_database owns the full set.
"""
import importlib.util
from pathlib import Path


def _load_run_module():
    """Load run.py by path: databricks-tellr-app is not installed in the venv
    (its editable install triggers the frontend/sidecar build)."""
    path = (
        Path(__file__).resolve().parents[2]
        / "packages" / "databricks-tellr-app" / "databricks_tellr_app" / "run.py"
    )
    spec = importlib.util.spec_from_file_location("tellr_run", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_init_database_runs_profile_and_session_migrations(monkeypatch):
    """init_database must run the profile->agent_config migration and the session
    backfill pre-fork; the workers no longer do, so these must live here."""
    run = _load_run_module()
    calls = []

    monkeypatch.setattr("src.core.database.init_db", lambda: None)
    monkeypatch.setattr("src.core.database.get_session_local", lambda: "SESSION_FACTORY")
    monkeypatch.setattr(
        "src.core.init_default_profile.seed_defaults", lambda include_databricks: None
    )
    monkeypatch.setattr("src.core.encryption.ensure_encryption_key", lambda: None)
    monkeypatch.setattr(
        "src.core.migrate_profiles_to_agent_config.migrate_profiles",
        lambda sf: calls.append(("migrate_profiles", sf)) or 0,
    )
    monkeypatch.setattr(
        "src.core.migrate_profiles_to_agent_config.backfill_sessions",
        lambda sf: calls.append(("backfill_sessions", sf)) or 0,
    )

    run.init_database()

    assert ("migrate_profiles", "SESSION_FACTORY") in calls
    assert ("backfill_sessions", "SESSION_FACTORY") in calls


def test_init_database_exits_1_when_profile_migration_fails(monkeypatch):
    """A profile-migration failure must abort the boot command (set -e), so a
    broken migration can never leave workers serving against a half-migrated DB."""
    import pytest

    run = _load_run_module()

    monkeypatch.setattr("src.core.database.init_db", lambda: None)
    monkeypatch.setattr("src.core.database.get_session_local", lambda: "SESSION_FACTORY")
    monkeypatch.setattr(
        "src.core.init_default_profile.seed_defaults", lambda include_databricks: None
    )
    monkeypatch.setattr("src.core.encryption.ensure_encryption_key", lambda: None)

    def _boom(sf):
        raise RuntimeError("migration failed")

    monkeypatch.setattr(
        "src.core.migrate_profiles_to_agent_config.migrate_profiles", _boom
    )

    with pytest.raises(SystemExit) as exc:
        run.init_database()
    assert exc.value.code == 1


def test_lifespan_module_does_not_run_migrations_in_workers():
    """The FastAPI app module (run per worker) must not import migration entry
    points — the workers serve requests only; migrations ran pre-fork."""
    import src.api.main as main_module

    # These names were the worker-side migration calls that caused 4 workers to
    # race the migration chain on boot. They must no longer be referenced here.
    assert not hasattr(main_module, "init_db"), (
        "src/api/main.py should not import init_db — workers must not migrate"
    )
    assert not hasattr(main_module, "migrate_profiles")
    assert not hasattr(main_module, "backfill_sessions")
