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
