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
    monkeypatch.setattr(
        "src.services.graph_configuration.ship_packaged_graph_configuration",
        lambda sf: calls.append(("ship_packaged_graph_configuration", sf))
        or SimpleNamespace(),
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
        ("ship_packaged_graph_configuration", "SESSION_FACTORY"),
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
        "src.services.graph_configuration.ship_packaged_graph_configuration",
        lambda sf: calls.append(("ship_packaged_graph_configuration", sf))
        or SimpleNamespace(),
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
    # Bootstrap failed, so the ship step must never have run.
    assert "ship_packaged_graph_configuration" not in [name for name, _ in calls]


def test_init_database_ship_failure_is_logged_and_startup_continues(
    monkeypatch, caplog
):
    """Shipping is best-effort: a failure is logged, never fatal, and every later
    stage still runs."""
    import logging

    run = _load_run_module()
    calls = []
    monkeypatch.setattr(
        "src.core.database.init_db", lambda: calls.append(("init_db", None))
    )
    monkeypatch.setattr("src.core.database.get_session_local", lambda: "SESSION_FACTORY")
    monkeypatch.setattr(
        "src.services.graph_configuration.bootstrap_graph_configuration",
        lambda sf: calls.append(("bootstrap_graph_configuration", sf))
        or SimpleNamespace(release_id=1, version_number=1, created=False),
    )

    def fail_ship(sf):
        calls.append(("ship_packaged_graph_configuration", sf))
        raise RuntimeError("ship failed")

    monkeypatch.setattr(
        "src.services.graph_configuration.ship_packaged_graph_configuration", fail_ship
    )
    monkeypatch.setattr(
        "src.core.migrate_profiles_to_agent_config.migrate_profiles",
        lambda sf: calls.append(("migrate_profiles", sf)) or 0,
    )
    monkeypatch.setattr(
        "src.core.migrate_profiles_to_agent_config.backfill_sessions",
        lambda sf: calls.append(("backfill_sessions", sf)) or 0,
    )
    monkeypatch.setattr(
        "src.core.backfill_session_slides_startup.backfill_unmigrated_decks",
        lambda sf: calls.append(("backfill_unmigrated_decks", sf)) or 0,
    )
    monkeypatch.setattr(
        "src.core.init_default_profile.seed_defaults",
        lambda include_databricks: calls.append(("seed_defaults", include_databricks)),
    )
    monkeypatch.setattr(
        "src.core.encryption.ensure_encryption_key",
        lambda: calls.append(("ensure_encryption_key", None)),
    )
    monkeypatch.setattr(
        "src.core.strip_retired_prompt_keys.strip_retired_prompt_keys",
        lambda sf: calls.append(("strip_retired_prompt_keys", sf)) or 0,
    )

    with caplog.at_level(logging.INFO):
        run.init_database()  # must not raise SystemExit

    assert calls == [
        ("init_db", None),
        ("bootstrap_graph_configuration", "SESSION_FACTORY"),
        ("ship_packaged_graph_configuration", "SESSION_FACTORY"),
        ("migrate_profiles", "SESSION_FACTORY"),
        ("backfill_sessions", "SESSION_FACTORY"),
        ("backfill_unmigrated_decks", "SESSION_FACTORY"),
        ("seed_defaults", False),
        ("ensure_encryption_key", None),
        ("strip_retired_prompt_keys", "SESSION_FACTORY"),
    ]
    errors = [
        r
        for r in caplog.records
        if r.levelno == logging.ERROR
        and "Failed to ship packaged Graph Configuration" in r.getMessage()
    ]
    assert len(errors) == 1


def test_init_database_logs_an_invalid_ship_as_a_warning_and_a_block_as_info(
    monkeypatch, caplog
):
    """Invalid packaged prompts are a build defect (WARNING); a block is an admin's
    choice (INFO).  Both are non-fatal."""
    import logging

    from src.services.graph_configuration import (
        DraftValidationIssue,
        ShipBlocked,
        ShipInvalid,
    )

    run = _load_run_module()
    monkeypatch.setattr("src.core.database.init_db", lambda: None)
    monkeypatch.setattr("src.core.database.get_session_local", lambda: "SESSION_FACTORY")
    monkeypatch.setattr(
        "src.services.graph_configuration.bootstrap_graph_configuration",
        lambda sf: SimpleNamespace(release_id=1, version_number=1, created=False),
    )
    for target in (
        "src.core.migrate_profiles_to_agent_config.migrate_profiles",
        "src.core.migrate_profiles_to_agent_config.backfill_sessions",
        "src.core.backfill_session_slides_startup.backfill_unmigrated_decks",
        "src.core.strip_retired_prompt_keys.strip_retired_prompt_keys",
    ):
        monkeypatch.setattr(target, lambda sf: 0)
    monkeypatch.setattr(
        "src.core.init_default_profile.seed_defaults", lambda include_databricks: None
    )
    monkeypatch.setattr("src.core.encryption.ensure_encryption_key", lambda: None)

    def _ship_records(outcome):
        monkeypatch.setattr(
            "src.services.graph_configuration.ship_packaged_graph_configuration",
            lambda sf: outcome,
        )
        caplog.clear()
        with caplog.at_level(logging.INFO):
            run.init_database()  # must not raise SystemExit
        return [
            (r.levelno, r.getMessage())
            for r in caplog.records
            if r.getMessage().startswith("Packaged Graph Configuration")
        ]

    invalid = ShipInvalid(
        issues=(DraftValidationIssue("definitions.architect.prompt_text", "blank", "x"),)
    )
    assert _ship_records(invalid) == [
        (logging.WARNING, "Packaged Graph Configuration invalid: ['blank']")
    ]
    blocked = ShipBlocked(reason="hand_edited", hand_edited_agents=("architect",))
    assert _ship_records(blocked) == [
        (logging.INFO, "Packaged Graph Configuration not published: hand_edited")
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
        "src.services.graph_configuration.ship_packaged_graph_configuration",
        lambda sf: SimpleNamespace(),
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


def test_init_database_no_longer_backfills_pins(monkeypatch):
    """Boot pins no conversation (spec 2026-10-22 §5.5: there is no backfill).

    A deck gets a Conversation Pin only when it locks to agent mode, and a
    legacy deck has none.  The row here is the one the old startup backfill
    pinned: an unpinned root whose first message carries the old opt-in text.
    It is ``legacy``, as Task 1's migration made every pre-existing deck.  Every
    boot stage except that one is stubbed, and the session factory is real, so a
    boot that still pins shows up in the row.  V1, the release the backfill
    pinned to, exists.
    """
    from src.database.models.session import SessionMessage, UserSession
    from src.services.graph_configuration import bootstrap_graph_configuration
    from tests.unit.conftest import _make_factory, _make_in_memory_engine

    engine = _make_in_memory_engine()
    try:
        factory = _make_factory(engine)
        v1 = bootstrap_graph_configuration(factory)
        assert v1.version_number == 1, "precondition: V1 is the active release"
        with factory.begin() as db:
            root = UserSession(
                session_id="historical-root",
                created_by="owner@example.com",
                deck_mode="legacy",
            )
            db.add(root)
            db.flush()
            db.add(
                SessionMessage(
                    session_id=root.id,
                    role="user",
                    content="USE AGENT MODE build a deck about puffins",
                    message_type="user_input",
                )
            )

        run = _load_run_module()
        calls = []
        monkeypatch.setattr("src.core.database.init_db", lambda: calls.append("init_db"))
        monkeypatch.setattr("src.core.database.get_session_local", lambda: factory)
        monkeypatch.setattr(
            "src.services.graph_configuration.bootstrap_graph_configuration",
            lambda sf: calls.append("bootstrap_graph_configuration")
            or SimpleNamespace(release_id=v1.release_id, version_number=1, created=False),
        )
        monkeypatch.setattr(
            "src.services.graph_configuration.ship_packaged_graph_configuration",
            lambda sf: calls.append("ship_packaged_graph_configuration")
            or SimpleNamespace(),
        )
        for target in (
            "src.core.migrate_profiles_to_agent_config.migrate_profiles",
            "src.core.migrate_profiles_to_agent_config.backfill_sessions",
            "src.core.backfill_session_slides_startup.backfill_unmigrated_decks",
            "src.core.strip_retired_prompt_keys.strip_retired_prompt_keys",
        ):
            monkeypatch.setattr(
                target, lambda sf, _name=target.rsplit(".", 1)[1]: calls.append(_name) or 0
            )
        monkeypatch.setattr(
            "src.core.init_default_profile.seed_defaults",
            lambda include_databricks: calls.append("seed_defaults"),
        )
        monkeypatch.setattr(
            "src.core.encryption.ensure_encryption_key",
            lambda: calls.append("ensure_encryption_key"),
        )

        run.init_database()

        assert calls == [
            "init_db",
            "bootstrap_graph_configuration",
            "ship_packaged_graph_configuration",
            "migrate_profiles",
            "backfill_sessions",
            "backfill_unmigrated_decks",
            "seed_defaults",
            "ensure_encryption_key",
            "strip_retired_prompt_keys",
        ], "precondition: every other boot stage ran, stubbed"
        with factory() as db:
            pin = (
                db.query(UserSession.graph_release_id)
                .filter(UserSession.session_id == "historical-root")
                .scalar()
            )
        assert pin is None, f"boot pinned a legacy deck to Graph Release {pin}"
    finally:
        engine.dispose()


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
