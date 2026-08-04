"""Column types that carry a stored blob's invariants into the database.

A rule about what a COLUMN may hold belongs on the column. Enforcing it in a
schema, a serializer or a service means it holds only for writers who go through
that code, and every new writer is a fresh chance to bypass it.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Optional

from sqlalchemy import JSON
from sqlalchemy.types import TypeDecorator

logger = logging.getLogger(__name__)


class NormalizedAgentConfig(TypeDecorator):
    """``agent_config`` JSON that cannot store two competing style authorities.

    ``slide_style_id`` and ``design_system_id`` are mutually exclusive: generation
    resolves the design system first (see ``agent_factory._get_prompt_content``), so a
    row carrying both DISAGREES with the deck it produces. The rule was enforced
    successively at a route, then at ``AgentConfig.model_dump()``, then at an
    ``AgentConfig`` ``@model_serializer`` — each time on the theory that the new spot
    was the one chokepoint. A serializer is not one. It governs writers who SERIALIZE
    THE MODEL, and these never do:

    * ``dict(model)`` — iterates the instance, calling no serializer;
    * ``row.agent_config = {...}`` — raw ORM attribute assignment;
    * ``Query.update({"agent_config": ...})`` — a bulk UPDATE, which does not even
      fire mapper-level ``before_update`` events, so an event listener would not have
      closed this either;
    * ``SessionManager.create_session`` — handed a raw dict it never parsed.

    A bind hook is the actual boundary for every writer that goes through a COLUMN
    OBJECT: SQLAlchemy routes those INSERT and UPDATE parameters through it, whatever
    produced the value, so a write path added tomorrow inherits the rule without
    knowing it exists. A cross-vendor review confirmed that covers core
    insert/update/executemany, ORM attribute assignment, ``Query.update``,
    ``bulk_save_objects`` and ``merge``, and found exactly TWO shapes it did not:

    * **an ORM JSON column assigned a ``str``** — the hook ran but returned early on
      ``not isinstance(value, dict)``. A JSON-object string is the same config in
      transport form, so it is now parsed, normalized and re-serialized (see
      :meth:`process_bind_param`). The guard's real subjects — ``None`` and blobs
      that are not configs — still pass through untouched.
    * **raw SQL** — ``conn.execute(text("INSERT ..."))`` never mentions a column
      object, so the statement text goes to the driver as written and NOTHING in
      SQLAlchemy is positioned to intervene. No Python-side hook can close this. The
      only place downstream of every writer is the database, so the rule is ALSO a
      PostgreSQL ``BEFORE INSERT OR UPDATE`` trigger, installed by
      ``src.core.database._migrate_agent_config_precedence_trigger``. The two layers
      state the same rule and agree on precedence; the trigger is the backstop, not
      the primary path.

    DESIGN SYSTEM WINS and the slide style is dropped — deliberately NOT a 422. The
    frontend PUTs the WHOLE config, so rejecting a both-set config would wedge every
    legacy both-set row on every save, failing an unrelated edit; that regression has
    already happened once. Legacy rows therefore HEAL on write, and because the
    normalization happens at the bind, they heal no matter which writer touches them.

    Deliberately SURGICAL. It would be tempting to route each blob through
    ``AgentConfig`` and store the result, but that round trip is LOSSY in both
    directions: the model ignores unknown keys, so a value a newer writer stored would
    be silently destroyed, and it fills in every default, so a lean ``{"tools": []}``
    would inflate into the full field set. So only the one contradiction is repaired
    and every other byte is passed through, on a COPY (a value being persisted must
    not have its caller's dict edited underneath it).

    Emits an ordinary ``JSON`` column, so adopting it needs no migration.
    """

    impl = JSON
    cache_ok = True

    def process_bind_param(self, value: Any, dialect: Any) -> Any:
        """Normalize on the way to the database.

        Handles the config in either of the two forms a writer supplies it: a
        ``dict``, or a JSON-OBJECT STRING. The string form is the same config in
        transport, and the previous ``isinstance(value, dict)`` guard returned it
        untouched, so ``row.agent_config = '{"slide_style_id": 7,
        "design_system_id": 9}'`` stored BOTH authorities on real PostgreSQL. It is
        normalized by parsing, applying precedence, and re-serializing — the caller
        gets back the same encoding it used.

        Everything else passes through EXACTLY as given:

        * ``None`` — "no config at all", which is not an empty config;
        * a non-JSON string, or JSON that is not an object (a scalar, an array) —
          not a config, so not this rule's business;
        * malformed JSON — see below.

        MALFORMED INPUT IS NEVER AN ERROR HERE. A bind hook runs inside somebody
        else's write, so raising turns a save into a 500 on a path that has no idea
        this rule exists. Unparseable bytes are therefore stored as the caller
        supplied them; the column is ``JSON``, so the database still gets its own
        say on whether they are valid.
        """
        if isinstance(value, str):
            return self._normalize_json_object_string(value)
        if not isinstance(value, dict):
            return value
        normalized = self._normalize_mapping(value)
        return value if normalized is None else normalized

    def _normalize_json_object_string(self, value: str) -> str:
        """Apply precedence inside a JSON-object string, preserving the encoding.

        Returns *value* itself unless it parses as a JSON OBJECT that actually
        carries both authorities, so every other string — including one that is not
        JSON at all — is passed through byte-for-byte rather than re-serialized.
        """
        try:
            parsed = json.loads(value)
        except (TypeError, ValueError):
            return value
        if not isinstance(parsed, dict):
            return value
        normalized = self._normalize_mapping(parsed)
        if normalized is None:
            return value
        return json.dumps(normalized)

    @staticmethod
    def _normalize_mapping(value: dict) -> Optional[dict]:
        """The rule itself. ``None`` means "nothing to repair", not "empty config".

        DESIGN SYSTEM WINS and the slide style is dropped. Returns a COPY, so a
        value being persisted never has its caller's dict edited underneath it.
        """
        if value.get("slide_style_id") is None or value.get("design_system_id") is None:
            return None
        logger.warning(
            "agent_config reached the database carrying BOTH slide_style_id=%s and "
            "design_system_id=%s; the design system takes precedence, so the slide "
            "style is dropped to keep ONE style authority in the prompt",
            value["slide_style_id"],
            value["design_system_id"],
        )
        normalized = dict(value)
        normalized["slide_style_id"] = None
        return normalized


def normalize_stored_agent_config(value: Optional[dict]) -> Optional[dict]:
    """The column's rule, callable directly.

    For code that must know what WILL be stored before storing it (a route echoing a
    config back in its own response, say) without depending on a round trip through
    the database.
    """
    return NormalizedAgentConfig().process_bind_param(value, None)
