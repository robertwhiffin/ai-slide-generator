"""Style-source exclusivity must hold at the SERIALIZER, not per route (BLOCKING 3).

``slide_style_id`` and ``design_system_id`` are mutually exclusive: generation
resolves the design system first, so a row carrying both disagrees with the deck it
produces. Five write paths were fixed one at a time (chat-create, chat-client-id,
chat-update, agent-put, mcp-create) by calling
``normalize_style_source_exclusivity`` at the route. Three more were still
bypassing it:

* ``agent-patch-legacy`` — ``agent_config.py`` ``_save_agent_config`` / PATCH /tools
* ``profile-create``     — ``profiles.py`` ``create_profile``
* ``duplicate``          — ``session_manager.duplicate_session``

Per-route calls are the wrong altitude: the rule is a property of a PERSISTED
agent config, so it belongs at the one point every path already funnels through —
``AgentConfig.model_dump()``, the shared persistence serializer. A write path added
tomorrow then inherits it and cannot bypass it.

Semantics unchanged: DESIGN SYSTEM WINS, never a 422 (a 422 wedges legacy both-set
rows on every save — a regression that already happened once), and legacy both-set
rows HEAL on write.

All fixtures SYNTHETIC (invented ids).
"""

from unittest.mock import MagicMock, patch

import pytest

_STYLE_ID = 1
_DS_ID = 1


def _both_set_config():
    """An AgentConfig carrying BOTH style authorities, as a hostile/legacy caller
    would supply it."""
    from src.api.schemas.agent_config import AgentConfig

    return AgentConfig(slide_style_id=_STYLE_ID, design_system_id=_DS_ID)


def _authorities(persisted):
    """Which style authorities survived into *persisted* (a dict)."""
    if persisted is None:
        return []
    return [
        field
        for field in ("slide_style_id", "design_system_id")
        if persisted.get(field) is not None
    ]


def _capturing_db(captured):
    """A stand-in DB session that records the row ``create_session`` adds.

    ``create_session`` reads ``created_at`` back off the row after flushing, so the
    fake populates it the way the real ``server_default`` would; otherwise the
    method fails on a detail unrelated to what these tests measure.
    """
    from datetime import datetime

    class _FakeSession:
        def query(self, *args, **kwargs):
            return self

        def filter(self, *args, **kwargs):
            return self

        def first(self):
            return None  # no existing session -> take the create branch

        def add(self, row):
            captured["agent_config"] = row.agent_config
            captured["row"] = row

        def flush(self):
            row = captured.get("row")
            if row is not None and getattr(row, "created_at", None) is None:
                row.created_at = datetime(2026, 1, 1)

    class _FakeCtx:
        def __enter__(self):
            return _FakeSession()

        def __exit__(self, *exc):
            return False

    return _FakeCtx()


class TestTheSerializerIsTheChokepoint:
    """The rule lives in ``AgentConfig.model_dump()``, so every caller inherits it."""

    def test_model_dump_persists_exactly_one_authority(self):
        """THE structural assertion: the shared serializer itself normalizes, so no
        route needs to remember to."""
        dumped = _both_set_config().model_dump()

        assert _authorities(dumped) == ["design_system_id"], (
            f"the shared serializer persisted {len(_authorities(dumped))} style "
            f"authorities {_authorities(dumped)}; a new write path would inherit "
            f"the defect"
        )
        assert dumped["design_system_id"] == _DS_ID, "the design system must WIN"
        assert dumped["slide_style_id"] is None

    def test_model_dump_json_mode_normalizes_too(self):
        """Some callers dump in JSON mode; the rule cannot depend on the mode."""
        dumped = _both_set_config().model_dump(mode="json")
        assert _authorities(dumped) == ["design_system_id"]

    def test_style_only_and_ds_only_configs_are_untouched(self):
        """The control: only the BOTH-set case is affected. A single authority of
        either kind must survive exactly as supplied."""
        from src.api.schemas.agent_config import AgentConfig

        style_only = AgentConfig(slide_style_id=_STYLE_ID).model_dump()
        assert style_only["slide_style_id"] == _STYLE_ID
        assert style_only["design_system_id"] is None

        ds_only = AgentConfig(design_system_id=_DS_ID).model_dump()
        assert ds_only["design_system_id"] == _DS_ID
        assert ds_only["slide_style_id"] is None

        neither = AgentConfig().model_dump()
        assert _authorities(neither) == []

    def test_normalization_is_not_a_422(self):
        """Semantics: a both-set config must CONSTRUCT and DUMP successfully. A 422
        here would wedge every legacy both-set row on save."""
        config = _both_set_config()  # must not raise
        assert config.model_dump() is not None

    def test_a_legacy_both_set_row_heals_on_write(self):
        """Reading a stored both-set row and dumping it must produce a healed
        config — that is how legacy rows get fixed rather than wedged."""
        from src.api.schemas.agent_config import resolve_agent_config

        legacy_row = {"slide_style_id": _STYLE_ID, "design_system_id": _DS_ID}
        healed = resolve_agent_config(legacy_row).model_dump()

        assert _authorities(healed) == ["design_system_id"]

    def test_the_in_place_helper_still_agrees_with_the_serializer(self):
        """``normalize_style_source_exclusivity`` remains the single statement of
        the rule (routes that call it explicitly, for ordering reasons, must not
        drift from what the serializer does)."""
        from src.api.schemas.agent_config import normalize_style_source_exclusivity

        config = _both_set_config()
        assert normalize_style_source_exclusivity(config) is True
        assert config.model_dump() == _both_set_config().model_dump()


class TestAgentPatchLegacyPath:
    """``agent_config.py`` ``_save_agent_config`` — reached by PATCH /tools, and by
    the GET stale-pin heal. It dumped the config straight onto the row."""

    def test_save_agent_config_persists_one_authority(self):
        from src.api.routes.agent_config import _save_agent_config

        session_row = MagicMock()
        session_row.agent_config = None
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = session_row

        with patch("src.api.routes.agent_config.get_db_session") as mock_db:
            mock_db.return_value.__enter__ = MagicMock(return_value=db)
            mock_db.return_value.__exit__ = MagicMock(return_value=False)
            returned = _save_agent_config("s-1", _both_set_config())

        assert _authorities(session_row.agent_config) == ["design_system_id"], (
            f"agent-patch-legacy persisted {_authorities(session_row.agent_config)}"
        )
        assert _authorities(returned) == ["design_system_id"], (
            "the RESPONSE must agree with what was stored"
        )


class TestProfileCreatePath:
    """``profiles.py`` ``create_profile`` — dumps via the profile sanitizer."""

    def test_profile_sanitizer_persists_one_authority(self):
        from src.api.routes.profiles import _sanitize_profile_config

        sanitized = _sanitize_profile_config(_both_set_config())

        assert _authorities(sanitized) == ["design_system_id"], (
            f"profile-create persisted {_authorities(sanitized)}"
        )

    def test_profile_sanitizer_normalizes_a_raw_both_set_dict(self):
        """A profile created from a raw client dict must heal too."""
        from src.api.routes.profiles import _sanitize_profile_config

        sanitized = _sanitize_profile_config(
            {"slide_style_id": _STYLE_ID, "design_system_id": _DS_ID}
        )
        assert _authorities(sanitized) == ["design_system_id"]


class TestDuplicateSessionPath:
    """``session_manager.duplicate_session`` — copies the source row's config
    through ``sanitize_agent_config_for_persist``."""

    def test_persist_sanitizer_persists_one_authority(self):
        from src.api.schemas.agent_config import sanitize_agent_config_for_persist

        sanitized = sanitize_agent_config_for_persist(
            {"slide_style_id": _STYLE_ID, "design_system_id": _DS_ID}
        )

        assert _authorities(sanitized) == ["design_system_id"], (
            f"duplicate persisted {_authorities(sanitized)}"
        )

    def test_duplicating_a_legacy_both_set_row_yields_one_authority(self):
        """The realistic case: an OLD session row stored both ids, and duplicating
        it must not propagate the defect into a brand-new row."""
        from src.api.schemas.agent_config import sanitize_agent_config_for_persist

        legacy_source_row = {
            "slide_style_id": _STYLE_ID,
            "design_system_id": _DS_ID,
            "tools": [],
        }
        assert _authorities(
            sanitize_agent_config_for_persist(legacy_source_row)
        ) == ["design_system_id"]

    def test_session_scoped_state_is_still_stripped(self):
        """Regression guard: the persist sanitizer's ORIGINAL job (dropping another
        session's Genie conversation_id) must keep working."""
        from src.api.schemas.agent_config import sanitize_agent_config_for_persist

        sanitized = sanitize_agent_config_for_persist(
            {
                "design_system_id": _DS_ID,
                "tools": [
                    {
                        "type": "genie",
                        "space_id": "space-1",
                        "space_name": "Synthetic Space",
                        "conversation_id": "conv-should-not-copy",
                    }
                ],
            }
        )
        assert sanitized["tools"][0]["conversation_id"] is None


class TestNoFourthPerRouteCall:
    """codex's constraint: do NOT add a fourth per-route call. The three paths must
    be covered by the SERIALIZER, which is provable by patching the in-place helper
    away — the paths must still persist exactly one authority without it."""

    @pytest.mark.parametrize(
        "path",
        ["profile-create", "duplicate", "agent-patch-legacy"],
    )
    def test_paths_are_exclusive_without_any_route_level_call(self, path):
        from src.api.schemas import agent_config as schema_module

        # Neuter the in-place helper. If a path depended on a route-level call to
        # it, that path would now persist BOTH ids.
        with patch.object(
            schema_module, "normalize_style_source_exclusivity", lambda *a, **k: False
        ):
            if path == "profile-create":
                from src.api.routes.profiles import _sanitize_profile_config

                persisted = _sanitize_profile_config(_both_set_config())
            elif path == "duplicate":
                from src.api.schemas.agent_config import (
                    sanitize_agent_config_for_persist,
                )

                persisted = sanitize_agent_config_for_persist(_both_set_config())
            else:
                persisted = _both_set_config().model_dump()

        assert _authorities(persisted) == ["design_system_id"], (
            f"{path}: exclusivity depended on a route-level call, so a NEW write "
            f"path would not inherit it"
        )


class TestModelDumpIsNotTheChokepoint:
    """B3, round 7: overriding ``model_dump`` is not a chokepoint — it is one of
    several ways to serialize, so the invariant held only for callers who happened
    to choose that one.

    codex's probe found five ways to persist a both-set config with BOTH authorities
    intact. Four are choices of serializer, which an override on a single method
    cannot cover:

    * ``model_dump_json()`` — pydantic v2 serializes via the Rust core and does NOT
      route through a python ``model_dump`` override;
    * ``dict(model)`` — iterates ``__dict__``, never calling any dump;
    * raw ORM assignment / a SQLAlchemy bulk update — persists the attributes
      themselves.

    And one is a real, reachable APPLICATION path:
    ``SessionManager.create_session`` accepts an ``agent_config`` RAW DICT and
    assigns it straight to the ORM without normalising it.

    Plus a contract violation in the override itself: it ASSIGNED ``None`` to
    ``slide_style_id`` instead of removing the key, so ``model_dump(exclude_none=True)``
    emitted ``"slide_style_id": None`` — an explicit null from the one option whose
    entire purpose is to omit nulls.

    The fix moves the invariant to a ``@model_serializer``, which ``model_dump``,
    ``model_dump_json`` and nested serialization all funnel through, and normalises
    ``create_session``'s raw dict. Semantics are unchanged: DESIGN SYSTEM WINS,
    never a 422, and legacy both-set rows still HEAL rather than wedge.

    ``dict(model)`` is deliberately NOT covered, and the boundary is asserted below
    rather than papered over. It iterates the instance's attributes and invokes no
    serializer at all, so it is the same act as reading ``config.slide_style_id``
    directly — which the PUT ordering REQUIRES to keep working (reference validation
    must see the dangling design system before exclusivity is applied, or a user
    holding a dead pin plus a real style is left with neither). The reachable
    attribute-level writers are handled where they PERSIST instead:
    ``create_session`` normalises its raw dict, and every route-level writer
    serializes. A future attribute-level persister must do the same.

    All fixtures SYNTHETIC (invented ids).
    """

    def test_model_dump_json_carries_one_authority(self):
        """codex row 4: the json serializer bypassed the python override."""
        import json

        persisted = json.loads(_both_set_config().model_dump_json())

        assert _authorities(persisted) == ["design_system_id"], (
            "model_dump_json() persisted BOTH style authorities — pydantic's json "
            "serializer does not call a model_dump override"
        )

    def test_dict_of_model_is_raw_attribute_access_and_is_not_a_persist_path(self):
        """codex row 5, resolved by stating the boundary instead of hiding it.

        ``dict(model)`` invokes NO serializer — it is attribute iteration, identical
        to reading ``config.slide_style_id``, which the PUT ordering depends on. So it
        still shows both ids, and that is correct: the model is allowed to hold both
        transiently. What must be true is that no PERSISTING path uses it; the
        reachable attribute-level writer (``create_session``) is normalised, and every
        route-level writer serializes.
        """
        raw = dict(_both_set_config())

        # Documented, deliberate: raw attribute access is not a persistence boundary.
        assert _authorities(raw) == ["slide_style_id", "design_system_id"]
        # And the same object, serialized, carries exactly one authority.
        assert _authorities(_both_set_config().model_dump()) == ["design_system_id"]

    def test_exclude_none_does_not_reintroduce_an_explicit_null(self):
        """The regression: ``exclude_none=True`` must not emit ``slide_style_id: None``."""
        persisted = _both_set_config().model_dump(exclude_none=True)

        assert "slide_style_id" not in persisted, (
            "model_dump(exclude_none=True) emitted an explicit slide_style_id: None, "
            "violating that option's contract"
        )
        assert persisted.get("design_system_id") == _DS_ID

    def test_create_session_normalizes_a_raw_both_set_dict(self):
        """codex's REAL existing bypass: ``SessionManager.create_session``.

        It accepts an ``agent_config`` raw dict from its caller and assigns it to the
        ORM unnormalised, so a both-set config is persisted verbatim.
        """
        from src.api.services.session_manager import SessionManager

        captured = {}

        raw_both_set = {"slide_style_id": _STYLE_ID, "design_system_id": _DS_ID}

        with patch(
            "src.api.services.session_manager.get_db_session",
            lambda: _capturing_db(captured),
        ):
            SessionManager().create_session(
                created_by="synthetic-user", agent_config=raw_both_set
            )

        assert _authorities(captured["agent_config"]) == ["design_system_id"], (
            "SessionManager.create_session persisted a RAW both-set dict without "
            "normalising it — a reachable bypass, not a theoretical one"
        )

    def test_create_session_still_stores_a_single_authority_config_unchanged(self):
        """Normalising must not disturb a config that already has one authority."""
        from src.api.services.session_manager import SessionManager

        captured = {}

        with patch(
            "src.api.services.session_manager.get_db_session",
            lambda: _capturing_db(captured),
        ):
            SessionManager().create_session(
                created_by="synthetic-user",
                agent_config={"slide_style_id": _STYLE_ID},
            )

        assert _authorities(captured["agent_config"]) == ["slide_style_id"], (
            "a style-only config must be persisted untouched"
        )

    def test_create_session_still_accepts_no_agent_config(self):
        """The common case: no config at all stays None, not {}."""
        from src.api.services.session_manager import SessionManager

        captured = {}

        with patch(
            "src.api.services.session_manager.get_db_session",
            lambda: _capturing_db(captured),
        ):
            SessionManager().create_session(created_by="synthetic-user")

        assert captured["agent_config"] is None

    def test_the_object_may_still_hold_both_transiently(self):
        """Load-bearing: normalisation is at SERIALIZATION, not construction.

        ``put_agent_config`` validates DB references BEFORE making the sources
        exclusive, because a DANGLING design system can only be detected with a
        lookup. If the model refused to hold both at construction, that ordering
        would be impossible and a user holding a dead pin plus a real slide style
        would end up with NEITHER.
        """
        from src.api.schemas.agent_config import AgentConfig

        config = AgentConfig(slide_style_id=_STYLE_ID, design_system_id=_DS_ID)

        assert config.slide_style_id == _STYLE_ID
        assert config.design_system_id == _DS_ID

    def test_a_dangling_design_system_still_leaves_the_slide_style_intact(self):
        """The ordering this protects, end to end through the in-place helper."""
        from src.api.schemas.agent_config import (
            AgentConfig,
            normalize_style_source_exclusivity,
        )

        config = AgentConfig(slide_style_id=_STYLE_ID, design_system_id=_DS_ID)
        # Reference validation clears the dead design system first...
        config.design_system_id = None
        # ...so making the sources exclusive must keep the user's real style.
        normalize_style_source_exclusivity(config)

        assert config.slide_style_id == _STYLE_ID
        assert _authorities(config.model_dump()) == ["slide_style_id"]
