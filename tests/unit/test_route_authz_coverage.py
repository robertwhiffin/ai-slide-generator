"""Route-table authorization coverage (SDR-4437 PR-2).

Every sensitive route must be gated (permission-helper call in the handler
source, or require_admin in its dependency tree) or carry an explicit
allowlist entry with a rationale. This makes the "forgot the check" class of
bug a CI failure.

NOTE while PR-2 is in flight: this test is committed RED at the end of the
serial gate and turns green as the per-router fan-out tasks land.
"""

import ast
import inspect
import re
import textwrap
from typing import get_args

from fastapi.routing import APIRoute
from pydantic import BaseModel

from src.api.main import app
from src.api.routes import _authz

# Identifier names that mark a route as touching another principal's resource.
# job_id and request_id are load-bearing: their omission from the original
# review's heuristic is exactly how the export poll/download and chat-poll
# IDORs escaped its endpoint list.
TRIGGER_PARAMS = {"session_id", "image_id", "job_id", "request_id"}

# Verified gating-call names. Extend ONLY with a name you have verified
# actually enforces the caller's deck/admin permission (add a comment).
# The trailing [(,] is load-bearing: it matches BOTH call shapes in the
# codebase — the direct call `_gate(session_id, ...)` AND the bare-reference
# form `await asyncio.to_thread(_gate, session_id, level)`, where the helper
# name is followed by a comma, not `(`. Six already-gated sessions.py routes
# (GET .../slides, POST .../export, the three lock endpoints, PUT
# .../lock/heartbeat) and the Task-12 chat-poll gate use the to_thread form;
# a `name\s*\(`-only regex reports all of them as ungated.
_PERMISSION_CALL_RE = re.compile(
    r"\b("
    r"_check_deck_permission_for_session"
    r"|_require_session_access"
    r"|_require_slide_permission"
    r"|_require_export_job_access"
    r"|_check_chat_permission"      # chat.py send/stream/async
    r"|_require_manage"             # deck_contributors.py
    r"|get_deck_permission"         # profiles.py / sessions.py inline checks
    # design_systems.py PUT/DELETE: creator-or-admin (Option C), and ADMIN-ONLY
    # while the row is the ORG DEFAULT. Verified enforcing — raises 403 unless
    # the caller authored the row, else delegates to require_admin; blank/NULL
    # created_by falls back to admin-only; a row with is_default set requires
    # admin regardless of authorship. Behavior is covered per-endpoint by
    # test_authz_design_systems_creator.py, and the exact permission LEVEL of all
    # three mutations — including the is_default condition — is pinned by
    # test_design_system_mutations_have_the_intended_permission_levels below.
    r"|_require_creator_or_admin"
    r")\s*[(,]"
    # images.py PUT/DELETE enforce HIGH-1 owner-scoping with a bespoke inline
    # check rather than a deck-permission helper: `if image.uploaded_by !=
    # <caller>: raise HTTPException(403, ...)`. Verified enforcing (per-endpoint
    # 403 tests: test_update_image_other_owner_403 / test_delete_image_other_owner_403
    # in test_authz_images.py) — the `!=`-then-raise IS the gate. Matched as a
    # verified enforcement token per the Task-4/Task-15 decision procedure.
    r"|image\.uploaded_by\s*!="
)

ADMIN_PATH_PREFIXES = (
    "/api/admin",                     # admin.py + admin_usage.py
    "/api/settings/deck-prompts",     # HIGH-3
    "/api/settings/slide-styles",     # HIGH-3
    "/api/settings/design-systems",   # HIGH-3 (same org-shared library shape)
)

FEEDBACK_READ_PATHS = {
    "/api/feedback/report/stats",
    "/api/feedback/list",
    "/api/feedback/report/summary",
}

IMAGE_READ_ACCEPTED_RISK = (
    "Explicitly accepted cross-user IDOR risk — accepted because images are a "
    "shared library with no per-deck binding to authorize against. Image IDs "
    "are sequential integers, so any authenticated workspace user can "
    "enumerate IDs and retrieve every user's image metadata (uploaded_by, "
    "tags, description) and raw bytes. Reads stay open so a CAN_EDIT "
    "collaborator opening the HTML editor on a shared deck can fetch the "
    "author's images. Revisit if per-deck image binding lands; a cheaper "
    "interim hardening is a random-UUID public identifier."
)

TOOLS_DISCOVERY_RATIONALE = (
    "Discovery endpoint: enumerates Genie spaces / vector endpoints / model "
    "endpoints for the caller's own agent config; results are already scoped "
    "by the caller's OBO client; returns no deck data."
)

IDENTITIES_RATIONALE = (
    "Workspace user/group lookup feeding the sharing picker (plus provider "
    "info); authenticated-user metadata by design; returns no deck data."
)

FEEDBACK_WRITE_RATIONALE = (
    "Feedback write endpoint: how regular users submit feedback; stays open."
)

DESIGN_SYSTEM_READ_RATIONALE = (
    "Read-only library browse; the design-system prefix gates MUTATIONS only "
    "(rename/delete = creator-or-admin, except admin-only while the row is the "
    "org default; set-default = admin-only always), a "
    "contribution-friendly variant of HIGH-3's deck-prompt and slide-style "
    "pattern. Reads must stay open: any user picks "
    "a design system for their own deck, and the generation/preview path reads "
    "its templates, assets and files. Per-design-system scoping (a template or "
    "asset is only served through its OWNING system) is enforced in the "
    "handlers and covered by the cross-design-system disclosure tests."
)

DESIGN_SYSTEM_CONTRIBUTE_RATIONALE = (
    "Deliberate product decision: ANY user may CONTRIBUTE a design system, so "
    "create and import stay open — the same shape as the shared image "
    "library's open upload. Contributing adds a NEW row owned by the caller; "
    "it does not mutate another principal's design system or change what other "
    "users get by default. Managing an EXISTING row is gated: rename/delete are "
    "creator-or-admin (you manage what you uploaded) but become ADMIN-ONLY once "
    "that row is the org default, and set-default — the one mutation with "
    "org-wide blast radius — stays admin-only always."
)

# (method, path) -> rationale. Exemptions must be visible in review, not
# implicit in the heuristic. Entries that do not trip the heuristic are kept
# anyway for review visibility; the liveness test below keeps them honest.
ALLOWLIST = {
    ("GET", "/api/export/pptx/editable/available"):
        "Capability probe: returns a boolean, no deck data.",
    ("GET", "/api/export/google-slides/auth/callback"):
        "OAuth callback (GET, popup flow); state-nonce binding lands in PR-4 "
        "(MEDIUM-3).",
    ("GET", "/api/images/{image_id}"): IMAGE_READ_ACCEPTED_RISK,
    ("GET", "/api/images/{image_id}/data"): IMAGE_READ_ACCEPTED_RISK,
    ("POST", "/api/images/upload"):
        "Shared image library: any authenticated user may upload; writes to "
        "existing images are owner-scoped (SDR-4437 HIGH-1).",
    ("POST", "/api/feedback/chat"): FEEDBACK_WRITE_RATIONALE,
    ("POST", "/api/feedback/submit"): FEEDBACK_WRITE_RATIONALE,
    ("POST", "/api/feedback/survey"): FEEDBACK_WRITE_RATIONALE,
    ("POST", "/api/sessions"):
        "Creates a new session owned by the caller; the optional body "
        "session_id names the NEW session — it does not reference another "
        "principal's resource.",
    # NOT exemptions — these two ARE gated, by an inline creator-only check
    # (session.created_by != get_current_user() -> 403, sessions.py). That is
    # STRICTER than deck CAN_VIEW (conversations are private even to deck
    # contributors) and has no helper name for the detector to match. Listed
    # here for review visibility; tests/unit covers the 403 behavior.
    ("GET", "/api/sessions/{session_id}/messages"):
        "Gated inline: creator-only privacy check (403 for non-creators), "
        "stricter than deck CAN_VIEW; no helper name to detect.",
    ("POST", "/api/sessions/{session_id}/messages"):
        "Gated inline: creator-only privacy check (403 for non-creators), "
        "stricter than deck CAN_VIEW; no helper name to detect.",
    # Duplicate-deck (added by #213, post-dates PR-2's fan-out). Gated in the
    # service layer, not the route facade: the handler calls
    # session_manager.duplicate_session(..., min_permission=CAN_VIEW), which
    # runs _require_deck_permission on the SOURCE deck and raises
    # SessionAccessDeniedError -> 403 before copying. Verified enforcing
    # (session_manager.py:553-554); no route-level helper name to detect.
    ("POST", "/api/sessions/{session_id}/duplicate"):
        "Gated in service layer: duplicate_session(min_permission=CAN_VIEW) "
        "enforces deck CAN_VIEW on the source before copying; no helper name "
        "to detect at the route.",
    # HIGH-3 gates library WRITES only — reads stay open (users browse the
    # prompt/style libraries to pick one); flagged only because the whole
    # settings prefix is marked sensitive.
    ("GET", "/api/settings/deck-prompts"):
        "Read-only library browse; HIGH-3 admin-gates writes only.",
    ("GET", "/api/settings/deck-prompts/{prompt_id}"):
        "Read-only library browse; HIGH-3 admin-gates writes only.",
    ("GET", "/api/settings/slide-styles"):
        "Read-only library browse; HIGH-3 admin-gates writes only.",
    ("GET", "/api/settings/slide-styles/{style_id}"):
        "Read-only library browse; HIGH-3 admin-gates writes only.",
    # Design systems adapt the deck-prompt / slide-style library shape to
    # user-contributed content: rename/delete are creator-or-admin and
    # set-default is admin-only (see DESIGN_SYSTEM_MUTATION_LEVELS), so all
    # three mutations are gated and absent here. Reads stay open — any user
    # browses the library to pick a system, and the generation path needs its
    # assets/templates/files.
    ("GET", "/api/settings/design-systems"): DESIGN_SYSTEM_READ_RATIONALE,
    ("GET", "/api/settings/design-systems/{ds_id}"): DESIGN_SYSTEM_READ_RATIONALE,
    ("GET", "/api/settings/design-systems/{ds_id}/templates"): DESIGN_SYSTEM_READ_RATIONALE,
    ("GET", "/api/settings/design-systems/{ds_id}/templates/{template_id}/thumbnail"):
        DESIGN_SYSTEM_READ_RATIONALE,
    ("GET", "/api/settings/design-systems/{ds_id}/templates/{template_id}/source"):
        DESIGN_SYSTEM_READ_RATIONALE,
    ("GET", "/api/settings/design-systems/{ds_id}/assets/{asset_id}"):
        DESIGN_SYSTEM_READ_RATIONALE,
    ("GET", "/api/settings/design-systems/{ds_id}/assets/{asset_id}/thumbnail"):
        DESIGN_SYSTEM_READ_RATIONALE,
    ("GET", "/api/settings/design-systems/{ds_id}/files"): DESIGN_SYSTEM_READ_RATIONALE,
    # NOTE: APIRoute.path preserves the raw ":path" converter suffix.
    ("GET", "/api/settings/design-systems/{ds_id}/files/{file_path:path}"):
        DESIGN_SYSTEM_READ_RATIONALE,
    ("POST", "/api/settings/design-systems/import"): DESIGN_SYSTEM_CONTRIBUTE_RATIONALE,
    ("POST", "/api/settings/design-systems"): DESIGN_SYSTEM_CONTRIBUTE_RATIONALE,
    ("GET", "/api/tools/available"): TOOLS_DISCOVERY_RATIONALE,
    ("GET", "/api/tools/discover/genie"): TOOLS_DISCOVERY_RATIONALE,
    ("GET", "/api/tools/discover/vector"): TOOLS_DISCOVERY_RATIONALE,
    ("GET", "/api/tools/discover/vector/{endpoint_name}/indexes"): TOOLS_DISCOVERY_RATIONALE,
    # NOTE: APIRoute.path preserves the raw ":path" converter suffix.
    ("GET", "/api/tools/discover/vector/{endpoint_name}/{index_name:path}/columns"): TOOLS_DISCOVERY_RATIONALE,
    ("GET", "/api/tools/discover/mcp"): TOOLS_DISCOVERY_RATIONALE,
    ("GET", "/api/tools/discover/model-endpoints"): TOOLS_DISCOVERY_RATIONALE,
    ("GET", "/api/tools/discover/agent-bricks"): TOOLS_DISCOVERY_RATIONALE,
    ("GET", "/api/settings/identities/provider"): IDENTITIES_RATIONALE,
    ("GET", "/api/settings/identities/users"): IDENTITIES_RATIONALE,
    ("GET", "/api/settings/identities/groups"): IDENTITIES_RATIONALE,
    ("GET", "/api/settings/identities/search"): IDENTITIES_RATIONALE,
}


def _api_routes():
    for route in app.routes:
        if isinstance(route, APIRoute) and route.path.startswith("/api"):
            yield route


def _model_classes(annotation):
    """Yield Pydantic models in an annotation, unwrapping Optional/Union."""
    if inspect.isclass(annotation) and issubclass(annotation, BaseModel):
        yield annotation
        return
    for arg in get_args(annotation):
        yield from _model_classes(arg)


def _route_param_names(route: APIRoute) -> set:
    """Path params + query/body param names + fields of Pydantic body models.

    The body-model recursion is load-bearing: ExportPPTXRequest.session_id,
    VerifySlideRequest.session_id and ChatRequest.session_id only exist as
    body-model fields — path/query inspection alone would never flag those
    routes, which is the exact regression this test exists to prevent.
    """
    names = set(route.param_convertors.keys())
    try:
        # eval_str resolves string annotations (from __future__ import annotations)
        sig = inspect.signature(route.endpoint, eval_str=True)
    except (NameError, TypeError):
        sig = inspect.signature(route.endpoint)
    for param in sig.parameters.values():
        names.add(param.name)
        for model in _model_classes(param.annotation):
            names.update(model.model_fields.keys())
    return names


def _has_require_admin(route: APIRoute) -> bool:
    return any(
        dep.call is _authz.require_admin for dep in route.dependant.dependencies
    )


def _has_permission_call(route: APIRoute) -> bool:
    """True if the handler source MENTIONS a verified gate name.

    This is a mention test, not an enforcement test: a listed name in a
    comment, docstring, or log line — or a call that resolves a permission
    without raising on it — matches just the same. The coverage test is
    therefore a tripwire for *forgotten* gates only; the per-endpoint 403
    tests each fan-out task writes are the behavioral enforcement
    guarantee. Never satisfy this test by merely naming a helper in
    handler source.
    """
    try:
        source = inspect.getsource(route.endpoint)
    except (OSError, TypeError):
        return False
    return bool(_PERMISSION_CALL_RE.search(source))


def _is_sensitive(route: APIRoute) -> bool:
    if route.path.startswith(ADMIN_PATH_PREFIXES):
        return True
    if route.path in FEEDBACK_READ_PATHS:
        return True
    return bool(TRIGGER_PARAMS & _route_param_names(route))


def test_every_sensitive_route_is_gated():
    failures = []
    for route in _api_routes():
        for method in sorted(route.methods - {"HEAD", "OPTIONS"}):
            if not _is_sensitive(route):
                continue
            if (method, route.path) in ALLOWLIST:
                continue
            if _has_require_admin(route) or _has_permission_call(route):
                continue
            failures.append(f"{method} {route.path} ({route.endpoint.__name__})")
    assert not failures, (
        "Ungated sensitive routes (add a permission gate, or an ALLOWLIST "
        "entry with a written rationale):\n  " + "\n  ".join(failures)
    )


def test_allowlist_entries_are_live_routes():
    """A deleted/renamed route must not leave a stale exemption behind."""
    live = {
        (method, route.path)
        for route in _api_routes()
        for method in route.methods
    }
    stale = [key for key in ALLOWLIST if key not in live]
    assert not stale, f"Stale ALLOWLIST entries: {stale}"


def test_trigger_detection_recurses_into_body_models():
    """Self-test for the load-bearing body-model recursion."""
    route = next(
        r for r in _api_routes()
        if r.path == "/api/export/pptx" and "POST" in r.methods
    )
    # session_id exists ONLY as an ExportPPTXRequest body field here.
    assert "session_id" in _route_param_names(route)


def _handler_source(route: APIRoute) -> str:
    try:
        return inspect.getsource(route.endpoint)
    except (OSError, TypeError):
        return ""


def _has_creator_or_admin(route: APIRoute) -> bool:
    """True if the handler invokes the creator-or-admin gate on its own row."""
    return bool(re.search(r"_require_creator_or_admin\s*\(", _handler_source(route)))


def _freezes_the_org_default(gate) -> bool:
    """True if *gate* makes the org default admin-only, in the right ORDER.

    Verified structurally (AST), not by grep: an ``if`` whose test reads
    ``is_default`` must exist in the gate, must call ``require_admin`` on that
    branch, and must appear BEFORE the authorship comparison. Ordering is part
    of the requirement — an is_default branch placed after the creator branch
    returns is dead code for exactly the caller the freeze exists to stop (the
    row's author), so "the condition is present somewhere" is not sufficient.
    """
    if gate is None:
        return False
    try:
        tree = ast.parse(textwrap.dedent(inspect.getsource(gate)))
    except (OSError, TypeError, SyntaxError):
        return False

    def _reads_is_default(node) -> bool:
        return any(
            isinstance(sub, ast.Attribute) and sub.attr == "is_default"
            for sub in ast.walk(node)
        )

    def _calls_require_admin(node) -> bool:
        return any(
            isinstance(sub, ast.Call)
            and isinstance(sub.func, ast.Name)
            and sub.func.id == "require_admin"
            for sub in ast.walk(node)
        )

    freeze_lines = [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.If)
        and _reads_is_default(node.test)
        and _calls_require_admin(node)
    ]
    if not freeze_lines:
        return False

    # The authorship comparison the freeze must precede. Located by the
    # attribute read of ``created_by`` off the row, which is the gate's only
    # authorship input.
    authorship_lines = [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute) and node.attr == "created_by"
    ]
    if not authorship_lines:
        # No authorship branch left at all — not the creator-or-admin gate this
        # level describes; fail rather than pass by absence.
        return False
    return min(freeze_lines) < min(authorship_lines)


def _gate_freezes_the_org_default(route: APIRoute) -> bool:
    """True if the gate THIS route calls freezes the org default.

    The gate is resolved from the route's OWN module rather than imported
    directly, so rewiring one handler to a different helper that does not carry
    the condition fails for that route specifically — per-route, not global.
    """
    module = inspect.getmodule(route.endpoint)
    return _freezes_the_org_default(getattr(module, "_require_creator_or_admin", None))


# The design-system mutation permission model (Option C + org-default freeze).
# Design systems are org-shared, user-CONTRIBUTED content, so the intended level
# differs per route and this table is the single place that says which is which:
#
#   "admin"            set-default — ORG-WIDE blast radius (changes what every
#                      user gets by default), so authorship must not buy it.
#                      ALWAYS admin, unconditionally.
#   "creator_or_admin_except_org_default"
#                      rename/delete — manage what YOU uploaded, EXCEPT while
#                      that row is the org default, when it is ADMIN-ONLY.
#                      Both halves are required: the creator-or-admin gate must
#                      be called, AND its verdict must be conditioned on the
#                      row's ``is_default``. Plain "creator_or_admin" is no
#                      longer an accepted level for these two routes — a
#                      non-admin CREATOR deleting the ACTIVE ORG DEFAULT
#                      answered 204 and broke other users' sessions, so dropping
#                      the condition is a REGRESSION, not a simplification.
#   "open"             create/import — any user may CONTRIBUTE a new row.
#
# Asserting the exact LEVEL (not merely "is gated") is what makes this a real
# tripwire: silently promoting rename/delete back to blanket admin-only,
# demoting set-default to creator-or-admin, dropping either gate entirely, or
# removing the is_default condition all fail here. Adding an ALLOWLIST entry
# cannot silence it.
DESIGN_SYSTEM_MUTATION_LEVELS = {
    ("PUT", "/api/settings/design-systems/{ds_id}"):
        "creator_or_admin_except_org_default",
    ("DELETE", "/api/settings/design-systems/{ds_id}"):
        "creator_or_admin_except_org_default",
    ("POST", "/api/settings/design-systems/{ds_id}/set-default"): "admin",
    ("POST", "/api/settings/design-systems/import"): "open",
    ("POST", "/api/settings/design-systems"): "open",
}

# Levels the assertion below knows how to check. A typo'd or newly-invented
# level must not silently fall through to the permissive "open" branch.
_KNOWN_MUTATION_LEVELS = frozenset(
    {"admin", "creator_or_admin_except_org_default", "open"}
)


def test_design_system_mutations_have_the_intended_permission_levels():
    """Self-test for the design-system prefix (the gap that let the missing
    set-default gate through review), now level-aware.

    The prefix's presence in ADMIN_PATH_PREFIXES only makes those routes
    SENSITIVE — an ALLOWLIST entry would still silence them. This pins each
    mutation to its INTENDED permission level, so no future entry can exempt one
    and no refactor can quietly change which level a route enforces.
    """
    seen = set()
    failures = []
    for route in _api_routes():
        for method in route.methods:
            expected = DESIGN_SYSTEM_MUTATION_LEVELS.get((method, route.path))
            if expected is None:
                continue
            seen.add((method, route.path))
            admin = _has_require_admin(route)
            creator = _has_creator_or_admin(route)
            where = f"{method} {route.path}"
            if expected == "admin":
                # Must be admin-only: require_admin in the dependency tree, and
                # NOT softened to the creator-or-admin gate.
                if not admin:
                    failures.append(
                        f"{where} has ORG-WIDE blast radius and must carry "
                        "Depends(require_admin)"
                    )
                if creator:
                    failures.append(
                        f"{where} must stay ADMIN-ONLY — it changes what every "
                        "user gets by default; authorship must not grant it"
                    )
            elif expected == "creator_or_admin_except_org_default":
                # Must be gated, but by the creator-or-admin gate specifically:
                # neither wide open nor promoted back to blanket admin-only...
                if not creator:
                    failures.append(
                        f"{where} mutates another principal's design system and "
                        "must call _require_creator_or_admin(ds)"
                    )
                if admin:
                    failures.append(
                        f"{where} must be CREATOR-OR-ADMIN, not admin-only — a "
                        "user must be able to manage the system they uploaded"
                    )
                # ...AND that gate's verdict must be conditioned on the row being
                # the org default, checked BEFORE the authorship comparison.
                # Without this half, a non-admin CREATOR deletes the ACTIVE ORG
                # DEFAULT (204) and other users' sessions keep pointing at the
                # dead id — the exact hole a cross-vendor review exploited.
                if not _gate_freezes_the_org_default(route):
                    failures.append(
                        f"{where} must be ADMIN-ONLY while the row is the ORG "
                        "DEFAULT: the gate it calls must branch on the loaded "
                        "row's is_default to require_admin, BEFORE the "
                        "authorship comparison"
                    )
            elif expected == "open":  # contributing is a deliberate decision
                if admin or creator:
                    failures.append(
                        f"{where} must stay OPEN: any authenticated user may "
                        "CONTRIBUTE a design system"
                    )
            else:
                # An unrecognised level must never fall through to the most
                # PERMISSIVE branch: a typo ("creator_or_admin", say, now that
                # the level is conditional) would otherwise silently assert
                # "open" and pass on a gated route.
                failures.append(
                    f"{where} declares unknown permission level {expected!r} — "
                    f"expected one of {sorted(_KNOWN_MUTATION_LEVELS)}"
                )
    assert not failures, "Design-system permission model drift:\n  " + "\n  ".join(failures)
    missing = set(DESIGN_SYSTEM_MUTATION_LEVELS) - seen
    assert not missing, f"design-system mutation routes missing: {missing}"


def test_permission_call_detection_matches_to_thread_form():
    """Self-test: gates invoked as `asyncio.to_thread(_gate, ...)` must count.

    GET /api/sessions/{session_id}/slides is already gated via
    `await asyncio.to_thread(_check_deck_permission_for_session, session_id,
    PermissionLevel.CAN_VIEW)` (sessions.py) — the helper name is followed by
    a comma there, not `(`. If the detector regresses to a direct-call-only
    regex, this test fails before the six to_thread-gated sessions.py routes
    (and the Task-12 chat-poll gate) show up as false red.
    """
    route = next(
        r for r in _api_routes()
        if r.path == "/api/sessions/{session_id}/slides" and "GET" in r.methods
    )
    assert _has_permission_call(route)


# The prefix every design-system route lives under. Derived from the entry the
# ADMIN_PATH_PREFIXES list already carries, so the two cannot drift apart.
_DESIGN_SYSTEM_PREFIX = "/api/settings/design-systems"


def _design_system_mutation_routes() -> set[tuple[str, str]]:
    """Every NON-GET design-system route currently mounted on the app.

    HEAD/OPTIONS are framework-generated rather than product surface, so they are
    not mutations and are excluded.
    """
    return {
        (method, route.path)
        for route in _api_routes()
        if route.path == _DESIGN_SYSTEM_PREFIX
        or route.path.startswith(f"{_DESIGN_SYSTEM_PREFIX}/")
        for method in route.methods
        if method not in ("GET", "HEAD", "OPTIONS")
    }


def test_every_design_system_mutation_route_is_explicitly_classified():
    """The level table must be EXHAUSTIVE, not merely consistent.

    ``test_design_system_mutations_have_the_intended_permission_levels`` iterates
    the mapping and skips routes absent from it, so a NEW mutation route — say a
    creator-gated PATCH — would sail through review while unclassified: nothing
    forced anyone to state its intended level. Asserting set EQUALITY makes
    classification mandatory, so adding any non-GET design-system route fails
    here until its permission level is written down.
    """
    live = _design_system_mutation_routes()
    mapped = set(DESIGN_SYSTEM_MUTATION_LEVELS)

    unclassified = sorted(live - mapped)
    assert not unclassified, (
        "New design-system mutation route(s) are not classified in "
        "DESIGN_SYSTEM_MUTATION_LEVELS — add each with its intended permission "
        f"level ('admin', 'creator_or_admin' or 'open'): {unclassified}"
    )
    stale = sorted(mapped - live)
    assert not stale, (
        f"DESIGN_SYSTEM_MUTATION_LEVELS names route(s) that no longer exist: {stale}"
    )


def test_org_default_freeze_detection_requires_the_condition_before_authorship():
    """Self-test for the freeze detector, including its ORDERING half.

    The detector must not be satisfied by an is_default branch that sits AFTER
    the creator branch has already returned — that placement is dead code for
    the row's author, who is exactly the principal the freeze exists to stop. A
    positive-only self-test would pass against a detector that ignored order, so
    this drives the real gate AND two deliberately-wrong stand-ins through the
    same AST predicate.
    """
    from src.api.routes.settings import design_systems as ds_routes

    # The real gate, correctly ordered, reached the way the route check reaches it.
    route = next(
        r for r in _api_routes()
        if r.path == "/api/settings/design-systems/{ds_id}" and "DELETE" in r.methods
    )
    assert _gate_freezes_the_org_default(route)
    assert _freezes_the_org_default(ds_routes._require_creator_or_admin)

    def _late_gate(ds):
        created_by = ds.created_by  # authorship compared FIRST
        if created_by == "someone":
            return
        if ds.is_default:  # ...freeze checked too late to bind the author
            require_admin()  # noqa: F821 - stand-in source, never executed

    def _no_condition_gate(ds):
        if ds.created_by == "someone":
            return
        require_admin()  # noqa: F821 - stand-in source, never executed

    assert not _freezes_the_org_default(_late_gate), (
        "detector accepted a gate whose is_default condition comes too LATE"
    )
    assert not _freezes_the_org_default(_no_condition_gate), (
        "detector accepted a gate with NO is_default condition"
    )
    assert not _freezes_the_org_default(None)
