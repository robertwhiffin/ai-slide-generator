"""Startup wiring: all DB migrations run ONCE in the pre-app init step.

The uvicorn workers must never run migration code (the FastAPI lifespan no longer
calls init_db / migrate_profiles / backfill_sessions). Everything that mutates the
schema or data runs once, before the server forks, in run.py::init_database — so
these tests pin that init_database owns the full set.
"""
import importlib.util
from pathlib import Path
from types import SimpleNamespace


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

    monkeypatch.setattr(
        "src.core.database.init_db", lambda: calls.append(("init_db", None))
    )
    monkeypatch.setattr("src.core.database.get_session_local", lambda: "SESSION_FACTORY")
    monkeypatch.setattr(
        "src.services.graph_configuration.bootstrap_graph_configuration",
        lambda sf: calls.append(("bootstrap_graph_configuration", sf))
        or SimpleNamespace(release_id=1, version_number=1, created=True),
    )
    # These two record into `calls` as well, so the ORDER assertion at the end is
    # real: with them silent, "the strip ran last" held even when the strip was moved
    # ahead of both — an assertion that could not fail.
    monkeypatch.setattr(
        "src.core.init_default_profile.seed_defaults",
        lambda include_databricks: calls.append(("seed_defaults", include_databricks)),
    )
    monkeypatch.setattr(
        "src.core.encryption.ensure_encryption_key",
        lambda: calls.append(("ensure_encryption_key", None)),
    )
    monkeypatch.setattr(
        "src.core.migrate_profiles_to_agent_config.migrate_profiles",
        lambda sf: calls.append(("migrate_profiles", sf)) or 0,
    )
    monkeypatch.setattr(
        "src.core.migrate_profiles_to_agent_config.backfill_sessions",
        lambda sf: calls.append(("backfill_sessions", sf)) or 0,
    )
    # Row-per-slide (PR1) moved into init_database on the 2026-08-18 main merge:
    # it used to run in the FastAPI lifespan, which no longer runs migrations at
    # all. This test pins "the full set", so the set now includes it.
    monkeypatch.setattr(
        "src.core.backfill_session_slides_startup.backfill_unmigrated_decks",
        lambda sf: calls.append(("backfill_unmigrated_decks", sf)) or 0,
    )
    # B2.5's agent_config blob strip is the LAST step: it removes the retired
    # 'system_prompt' / 'slide_editing_instructions' keys, and last is the position
    # no earlier-finishing step (seed_defaults creates profiles) can undo by writing
    # a fresh blob. This test pins "the full set", so the set now includes it.
    monkeypatch.setattr(
        "src.core.strip_retired_prompt_keys.strip_retired_prompt_keys",
        lambda sf: calls.append(("strip_retired_prompt_keys", sf)) or 0,
    )

    run.init_database()

    assert calls == [
        ("init_db", None),
        ("bootstrap_graph_configuration", "SESSION_FACTORY"),
        ("migrate_profiles", "SESSION_FACTORY"),
        ("backfill_sessions", "SESSION_FACTORY"),
        ("backfill_unmigrated_decks", "SESSION_FACTORY"),
        ("seed_defaults", False),
        ("ensure_encryption_key", None),
        ("strip_retired_prompt_keys", "SESSION_FACTORY"),
    ]


def test_init_database_bootstrap_failure_aborts_before_later_stages(monkeypatch):
    import pytest

    run = _load_run_module()
    calls = []
    monkeypatch.setattr(
        "src.core.database.init_db", lambda: calls.append(("init_db", None))
    )
    monkeypatch.setattr("src.core.database.get_session_local", lambda: "SESSION_FACTORY")

    def fail_bootstrap(sf):
        calls.append(("bootstrap_graph_configuration", sf))
        raise RuntimeError("bootstrap failed")

    monkeypatch.setattr(
        "src.services.graph_configuration.bootstrap_graph_configuration", fail_bootstrap
    )
    monkeypatch.setattr(
        "src.core.migrate_profiles_to_agent_config.migrate_profiles",
        lambda sf: calls.append(("migrate_profiles", sf)),
    )

    with pytest.raises(SystemExit) as exc:
        run.init_database()

    assert exc.value.code == 1
    assert calls == [
        ("init_db", None),
        ("bootstrap_graph_configuration", "SESSION_FACTORY"),
    ]


def test_init_database_exits_1_when_profile_migration_fails(monkeypatch):
    """A profile-migration failure must abort the boot command (set -e), so a
    broken migration can never leave workers serving against a half-migrated DB."""
    import pytest

    run = _load_run_module()

    monkeypatch.setattr("src.core.database.init_db", lambda: None)
    monkeypatch.setattr("src.core.database.get_session_local", lambda: "SESSION_FACTORY")
    monkeypatch.setattr(
        "src.services.graph_configuration.bootstrap_graph_configuration",
        lambda sf: SimpleNamespace(release_id=1, version_number=1, created=False),
    )
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
    assert isinstance(exc.value.__cause__, RuntimeError)
    assert str(exc.value.__cause__) == "migration failed"


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
