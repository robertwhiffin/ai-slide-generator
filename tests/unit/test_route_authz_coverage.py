"""Route-table authorization coverage (SDR-4437 PR-2).

Every sensitive route must be gated (permission-helper call in the handler
source, or require_admin in its dependency tree) or carry an explicit
allowlist entry with a rationale. This makes the "forgot the check" class of
bug a CI failure.

NOTE while PR-2 is in flight: this test is committed RED at the end of the
serial gate and turns green as the per-router fan-out tasks land.
"""

import inspect
import re
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
