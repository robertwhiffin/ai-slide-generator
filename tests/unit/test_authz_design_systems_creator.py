"""Design-system rename/delete are CREATOR-OR-ADMIN gated (Option C).

Supersedes the admin-only half of ``test_authz_design_systems_admin.py`` for
PUT/DELETE. The product model design systems actually implement:

    all GETs              OPEN
    POST /import          OPEN  — any user may CONTRIBUTE
    POST ""    (create)   OPEN  — any user may CONTRIBUTE
    PUT    /{ds_id}       CREATOR OR ADMIN, except ADMIN-ONLY while is_default
    DELETE /{ds_id}       CREATOR OR ADMIN, except ADMIN-ONLY while is_default
    POST /{ds_id}/set-default   ADMIN ONLY  — org-wide blast radius (always)

Design systems are org-shared, user-contributed content: any user may add one
AND manage the ones they uploaded, nobody may touch someone else's, and admins
may manage anything.

ORG-DEFAULT FREEZE (product owner's decision: "only admin when it's org
default"). Creator-or-admin was not sufficient on its own: a non-admin CREATOR
could delete the ACTIVE ORG DEFAULT design system and get 204, leaving the row
inactive/non-default while OTHER users' sessions still pointed at it. So an
admin's act of promoting a system to org default could be undone by its author.
The moment a row becomes the org default, rename/delete on THAT row require
admin; creators keep full control of every NON-default system they uploaded.
The verdict reads ``is_default`` off the LOADED ROW inside the handler's
transaction — never from client input.

IDENTITY (why these tests are honest): the caller is resolved server-side from
``get_permission_context().user_name``, which the OBO middleware
(``src/api/main.py``) populates from the authenticated token — in production
from ``user_client.current_user.me()``, and in dev/test from ``DEV_USER_ID``.
These tests therefore steer identity by setting ``DEV_USER_ID`` and letting the
REAL middleware build the permission context, rather than monkeypatching the
guard or the getter. Nothing the client sends (body, query, header) can change
the verdict, so there is no spoofable seam for a test to accidentally bless.

Every case runs against a REAL seeded design system, so a missing gate answers
200/204 rather than 403 — a 403 proves the gate fired and cannot be a
404-by-accident on an absent row. All fixtures are SYNTHETIC.

Fixture idiom (in-memory SQLite ``get_db`` override + the
``production``/``non_admin``/``admin`` monkeypatch triple) copied from
``tests/unit/test_authz_design_systems_admin.py``.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.api.main import app
from src.core.database import Base, get_db
from src.database.models.design_system import DesignSystem
from tests.unit.conftest_design_system import make_bundle_zip

BASE = "/api/settings/design-systems"

CREATOR = "creator@test.com"
OTHER = "someone-else@test.com"


@pytest.fixture(scope="function")
def db_engine():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    yield engine
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


@pytest.fixture(scope="function")
def db_session(db_engine):
    session_local = sessionmaker(autocommit=False, autoflush=False, bind=db_engine)
    session = session_local()
    yield session
    session.close()


@pytest.fixture(scope="function")
def client(db_session):
    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c
    app.dependency_overrides.clear()


def _seed(db_session, created_by, name="Acme Synthetic DS", is_default=False):
    """Seed a real, active design system authored by ``created_by``.

    ``is_default`` seeds the row as the ORG DEFAULT, which is what the freeze
    tests below toggle. It is written to the DB row, never sent by the client —
    the guard must read it from the row it loaded.
    """
    ds = DesignSystem(
        name=name,
        description="synthetic fixture",
        created_by=created_by,
        updated_by=created_by,
        version=1,
        published=False,
        is_default=is_default,
        is_active=True,
    )
    db_session.add(ds)
    db_session.commit()
    db_session.refresh(ds)
    return ds


@pytest.fixture
def production(monkeypatch):
    """Turn OFF the dev-mode admin bypass so the admin verdict is real."""
    from src.api.routes import _authz

    monkeypatch.setattr(_authz, "_is_production", lambda: True)
    monkeypatch.setattr(_authz, "get_current_user", lambda: "user@test.com")
    _authz.reset_admin_cache()
    yield _authz
    _authz.reset_admin_cache()


@pytest.fixture
def non_admin(production, monkeypatch):
    monkeypatch.setattr(production, "_admin_acl_probe", lambda user: False)


@pytest.fixture
def admin(production, monkeypatch):
    monkeypatch.setattr(production, "_admin_acl_probe", lambda user: True)


@pytest.fixture
def as_creator(monkeypatch):
    """Authenticate the request AS the seeded design system's author."""
    monkeypatch.setenv("DEV_USER_ID", CREATOR)


@pytest.fixture
def as_other_user(monkeypatch):
    """Authenticate the request as a DIFFERENT user than the author."""
    monkeypatch.setenv("DEV_USER_ID", OTHER)


# --- (a)/(b) the creator may manage their OWN NON-DEFAULT design system -----
#
# ``_seed`` defaults to ``is_default=False``, which is now load-bearing: these
# two cases are the NON-default half of the org-default freeze, and they must
# stay green (creators keep full control of what they uploaded).


def test_creator_non_admin_can_rename_own_non_default_design_system(
    client, db_session, non_admin, as_creator
):
    """(a) A plain user renames the NON-DEFAULT design system they uploaded."""
    ds = _seed(db_session, CREATOR)
    resp = client.put(f"{BASE}/{ds.id}", json={"name": "Acme DS renamed by its author"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["name"] == "Acme DS renamed by its author"


def test_creator_non_admin_can_delete_own_non_default_design_system(
    client, db_session, non_admin, as_creator
):
    """(b) A plain user deletes the NON-DEFAULT design system they uploaded."""
    ds = _seed(db_session, CREATOR)
    resp = client.delete(f"{BASE}/{ds.id}")
    assert resp.status_code == 204, resp.text


# --- (c)/(d) nobody may touch someone else's -------------------------------


def test_non_creator_non_admin_cannot_rename_other_users_design_system(
    client, db_session, non_admin, as_other_user
):
    """(c) A plain user may NOT rename a design system they did not upload."""
    ds = _seed(db_session, CREATOR)
    resp = client.put(f"{BASE}/{ds.id}", json={"name": "Hijacked by a stranger"})
    assert resp.status_code == 403, resp.text
    db_session.refresh(ds)
    assert ds.name == "Acme Synthetic DS", "denied rename must not mutate the row"


def test_non_creator_non_admin_cannot_delete_other_users_design_system(
    client, db_session, non_admin, as_other_user
):
    """(d) A plain user may NOT delete a design system they did not upload."""
    ds = _seed(db_session, CREATOR)
    resp = client.delete(f"{BASE}/{ds.id}")
    assert resp.status_code == 403, resp.text
    db_session.refresh(ds)
    assert ds.is_active is True, "denied delete must not deactivate the row"


# --- (e) admins may manage ANY design system, including others' ------------


def test_admin_can_rename_design_system_they_did_not_create(
    client, db_session, admin, as_other_user
):
    """(e) Admin overrides authorship on rename."""
    ds = _seed(db_session, CREATOR)
    resp = client.put(f"{BASE}/{ds.id}", json={"name": "Renamed by an admin"})
    assert resp.status_code == 200, resp.text


def test_admin_can_delete_design_system_they_did_not_create(
    client, db_session, admin, as_other_user
):
    """(e) Admin overrides authorship on delete."""
    ds = _seed(db_session, CREATOR)
    resp = client.delete(f"{BASE}/{ds.id}")
    assert resp.status_code == 204, resp.text


# --- (f) set-default stays ADMIN-ONLY (org-wide blast radius) --------------


def test_creator_non_admin_cannot_set_default_on_own_design_system(
    client, db_session, non_admin, as_creator
):
    """(f) Authorship does NOT buy set-default — it changes what EVERYONE gets."""
    ds = _seed(db_session, CREATOR)
    resp = client.post(f"{BASE}/{ds.id}/set-default")
    assert resp.status_code == 403, resp.text
    db_session.refresh(ds)
    assert ds.is_default is False, "denied set-default must not flip the org default"


def test_admin_can_set_default(client, db_session, admin, as_other_user):
    """(f) Behavior preserved for the admin half of set-default."""
    ds = _seed(db_session, CREATOR)
    resp = client.post(f"{BASE}/{ds.id}/set-default")
    assert resp.status_code == 200, resp.text


# --- (g) the core user story: contributing stays OPEN ----------------------


def test_non_admin_can_still_import_bundle(client, non_admin, as_other_user):
    """(g) Any authenticated user may CONTRIBUTE a design system by upload."""
    resp = client.post(
        f"{BASE}/import",
        files={"file": ("synthetic.zip", make_bundle_zip(), "application/zip")},
    )
    assert resp.status_code == 201, resp.text


def test_non_admin_can_still_create(client, non_admin, as_other_user):
    """(g) Any authenticated user may CONTRIBUTE a design system via create."""
    resp = client.post(BASE, json={"name": "Contributed by a regular user"})
    assert resp.status_code == 201, resp.text


# --- (h) blank authorship falls back to ADMIN-ONLY (security requirement) --
#
# ``design_system.created_by`` is nullable and legacy rows may carry NULL or a
# blank string. A blank author must NEVER resolve to "anyone may manage this":
# an unauthenticated/blank CALLER must not match a blank OWNER either, so the
# comparison can never be satisfied by two empty values.


@pytest.mark.parametrize(
    "blank", [None, "", "   "], ids=["null", "empty", "whitespace"]
)
def test_creatorless_design_system_is_admin_only_for_non_admin(
    client, db_session, non_admin, as_creator, blank
):
    """(h) NULL/blank ``created_by`` -> admin-only, so a non-admin gets 403."""
    ds = _seed(db_session, blank)
    put = client.put(f"{BASE}/{ds.id}", json={"name": "Claimed via blank authorship"})
    assert put.status_code == 403, f"PUT on blank-author DS -> {put.status_code} {put.text}"
    delete = client.delete(f"{BASE}/{ds.id}")
    assert delete.status_code == 403, (
        f"DELETE on blank-author DS -> {delete.status_code} {delete.text}"
    )
    db_session.refresh(ds)
    assert ds.name == "Acme Synthetic DS"
    assert ds.is_active is True


@pytest.mark.parametrize(
    "blank", [None, "", "   "], ids=["null", "empty", "whitespace"]
)
def test_creatorless_design_system_is_still_manageable_by_admin(
    client, db_session, admin, as_creator, blank
):
    """(h) The admin-only fallback still lets an ADMIN clean up legacy rows."""
    ds = _seed(db_session, blank)
    resp = client.put(f"{BASE}/{ds.id}", json={"name": "Adopted by an admin"})
    assert resp.status_code == 200, resp.text


def test_blank_caller_cannot_match_blank_creator(client, db_session, non_admin, monkeypatch):
    """(h) A blank CALLER must not match a blank OWNER — the both-empty trap.

    Belt-and-braces on the fallback: even if identity resolution yields an
    empty username, `"" == ""` must not be read as "the caller is the author".
    """
    monkeypatch.setenv("DEV_USER_ID", "")
    ds = _seed(db_session, "")
    resp = client.delete(f"{BASE}/{ds.id}")
    assert resp.status_code == 403, resp.text
    db_session.refresh(ds)
    assert ds.is_active is True


# --- (i) VISUALLY EMPTY authorship is blank too -----------------------------
#
# ``str.strip()`` removes ASCII and Unicode WHITESPACE (Zs/Zl/Zp), but a
# zero-width character is category Cf — ``isspace()`` is False and ``strip()``
# leaves it untouched. So a ``created_by`` of ZERO WIDTH SPACE passed the
# non-blank test on BOTH sides and satisfied the creator branch, handing
# "anyone may manage this" to an author-less row.
#
# The fix normalizes (NFKC) and strips format/separator characters before the
# non-blank test, so any value that is semantically empty is BLANK -> admin-only.
# Case sensitivity is deliberately NOT relaxed: differing case still fails
# closed, which the existing suite pins.

# Cf format characters (zero-width and friends), plus combinations with real
# whitespace. Each must read as BLANK.
_INVISIBLE_BLANKS = [
    ("zwsp", "​"),          # ZERO WIDTH SPACE
    ("zwnj", "‌"),          # ZERO WIDTH NON-JOINER
    ("zwj", "‍"),           # ZERO WIDTH JOINER
    ("bom", "﻿"),           # ZERO WIDTH NO-BREAK SPACE / BOM
    ("word_joiner", "⁠"),   # WORD JOINER
    ("soft_hyphen", "­"),   # SOFT HYPHEN (Cf)
    ("lrm", "‎"),           # LEFT-TO-RIGHT MARK
    ("mixed_zw_and_spaces", "  ​ ﻿\t‌  "),
    ("zw_with_nbsp", " ​ "),
    ("ideographic_space_zw", "　‍"),
]


@pytest.mark.parametrize(
    ("label", "blank"), _INVISIBLE_BLANKS, ids=[label for label, _ in _INVISIBLE_BLANKS]
)
def test_zero_width_authorship_is_admin_only_for_non_admin(
    client, db_session, non_admin, monkeypatch, label, blank
):
    """(i) A visually empty ``created_by`` is admin-only, even when the CALLER
    presents the very same invisible string."""
    monkeypatch.setenv("DEV_USER_ID", blank)
    ds = _seed(db_session, blank)

    put = client.put(f"{BASE}/{ds.id}", json={"name": "Claimed via invisible authorship"})
    assert put.status_code == 403, (
        f"PUT with {label} caller+owner -> {put.status_code} {put.text}"
    )
    delete = client.delete(f"{BASE}/{ds.id}")
    assert delete.status_code == 403, (
        f"DELETE with {label} caller+owner -> {delete.status_code} {delete.text}"
    )
    db_session.refresh(ds)
    assert ds.name == "Acme Synthetic DS"
    assert ds.is_active is True


@pytest.mark.parametrize(
    ("label", "blank"), _INVISIBLE_BLANKS, ids=[label for label, _ in _INVISIBLE_BLANKS]
)
def test_zero_width_authorship_still_manageable_by_admin(
    client, db_session, admin, monkeypatch, label, blank
):
    """(i) The admin fallback still applies, so these rows stay cleanable."""
    monkeypatch.setenv("DEV_USER_ID", blank)
    ds = _seed(db_session, blank)

    resp = client.put(f"{BASE}/{ds.id}", json={"name": "Adopted by an admin"})
    assert resp.status_code == 200, resp.text


# Owner and caller that differ ONLY by invisible characters. These are not
# "blank vs blank" — they are a REAL name against a decorated variant, which
# must not be treated as the same principal.
_INVISIBLE_DIFFERENCES = [
    ("owner_has_zwsp", f"{CREATOR}​", CREATOR),
    ("caller_has_zwsp", CREATOR, f"{CREATOR}​"),
    ("owner_has_bom_prefix", f"﻿{CREATOR}", CREATOR),
    ("caller_has_soft_hyphen", CREATOR, "cre­ator@test.com"),
    ("owner_zwj_inside", "cre‍ator@test.com", CREATOR),
]


@pytest.mark.parametrize(
    ("label", "owner", "caller"),
    _INVISIBLE_DIFFERENCES,
    ids=[label for label, _, _ in _INVISIBLE_DIFFERENCES],
)
def test_owner_and_caller_differing_by_invisibles_are_not_the_same_principal(
    client, db_session, non_admin, monkeypatch, label, owner, caller
):
    """(i) Stripping invisibles must not become a LOOSER comparison: a caller
    whose name merely resembles the owner's is still denied."""
    monkeypatch.setenv("DEV_USER_ID", caller)
    ds = _seed(db_session, owner)

    delete = client.delete(f"{BASE}/{ds.id}")
    assert delete.status_code == 403, (
        f"DELETE with {label} -> {delete.status_code} {delete.text}"
    )
    db_session.refresh(ds)
    assert ds.is_active is True


# --- (j) ORG-DEFAULT FREEZE: admin-only while the row IS the org default ----
#
# The hole an independent cross-vendor review PROVED by running it: a non-admin
# CREATOR deleted the ACTIVE ORG DEFAULT design system and got 204. The row went
# inactive/non-default while ANOTHER user's session still pointed at the
# now-broken id, so an admin's promotion could be undone by the row's author.
#
# Product owner's decision, verbatim: "only admin when it's org default".
#
# These cases seed the SAME author and call as the SAME caller as the (a)/(b)
# cases above — the ONLY difference is ``is_default``. That is what makes the
# new condition load-bearing rather than incidental: identical setups must give
# OPPOSITE verdicts, which the flip test below asserts inside a single test body.


def test_creator_non_admin_cannot_rename_own_design_system_while_org_default(
    client, db_session, non_admin, as_creator
):
    """(j1) The author may NOT rename their own system while it IS the org default."""
    ds = _seed(db_session, CREATOR, is_default=True)
    resp = client.put(f"{BASE}/{ds.id}", json={"name": "Renamed under the admin's feet"})
    assert resp.status_code == 403, resp.text
    db_session.refresh(ds)
    assert ds.name == "Acme Synthetic DS", "denied rename must not mutate the row"
    assert ds.is_default is True, "denied rename must leave the org default intact"
    assert ds.version == 1, "denied rename must not bump the version"


def test_creator_non_admin_cannot_delete_own_design_system_while_org_default(
    client, db_session, non_admin, as_creator
):
    """(j2) The author may NOT delete their own system while it IS the org default.

    This is the reviewer's exact reproduction: it answered 204 before the freeze.
    """
    ds = _seed(db_session, CREATOR, is_default=True)
    resp = client.delete(f"{BASE}/{ds.id}")
    assert resp.status_code == 403, resp.text
    db_session.refresh(ds)
    assert ds.is_active is True, "denied delete must not deactivate the org default"
    assert ds.is_default is True, "denied delete must not clear the org default"


def test_admin_can_rename_design_system_that_is_org_default(
    client, db_session, admin, as_other_user
):
    """(j3) An ADMIN may still rename the org default (the freeze is admin-ONLY,
    not nobody-may)."""
    ds = _seed(db_session, CREATOR, is_default=True)
    resp = client.put(f"{BASE}/{ds.id}", json={"name": "Org default renamed by an admin"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["name"] == "Org default renamed by an admin"


def test_admin_can_delete_design_system_that_is_org_default(
    client, db_session, admin, as_other_user
):
    """(j3) An ADMIN may still delete the org default."""
    ds = _seed(db_session, CREATOR, is_default=True)
    resp = client.delete(f"{BASE}/{ds.id}")
    assert resp.status_code == 204, resp.text
    db_session.refresh(ds)
    assert ds.is_active is False
    assert ds.is_default is False, "deleting the default must not leave it flagged default"


def test_org_default_flag_alone_flips_the_verdict_for_the_same_creator(
    client, db_session, non_admin, as_creator
):
    """(j4) THE FLIP TEST — one row, one author, one caller, opposite verdicts.

    Everything is held constant: the SAME design system row, authored by the
    SAME principal, called by the SAME non-admin caller, over the SAME route.
    The ONLY thing that changes between the two halves is ``is_default`` on the
    row. If the guard ignored ``is_default``, both halves would return the same
    status and this test fails — which is what makes the new condition provably
    load-bearing rather than incidentally satisfied by some other difference.
    """
    ds = _seed(db_session, CREATOR)
    ds_id = ds.id

    # --- is_default OFF -> the creator branch applies -> ALLOWED -------------
    assert ds.is_default is False
    allowed = client.put(f"{BASE}/{ds_id}", json={"name": "Allowed while not default"})
    assert allowed.status_code == 200, (
        f"creator must manage their own NON-default system: {allowed.status_code} {allowed.text}"
    )

    # --- flip the SAME row to the org default (server-side, not client input) -
    db_session.refresh(ds)
    ds.is_default = True
    db_session.commit()
    db_session.refresh(ds)
    assert ds.is_default is True
    name_while_default = ds.name

    # --- is_default ON -> admin-only -> DENIED -------------------------------
    denied = client.put(f"{BASE}/{ds_id}", json={"name": "Denied while default"})
    assert denied.status_code == 403, (
        f"same row+author+caller, is_default=True must be DENIED: "
        f"{denied.status_code} {denied.text}"
    )
    db_session.refresh(ds)
    assert ds.name == name_while_default, "denied rename must not mutate the row"

    # --- and flip it BACK OFF -> allowed again (the condition is the ONLY gate)
    ds.is_default = False
    db_session.commit()
    reallowed = client.put(f"{BASE}/{ds_id}", json={"name": "Allowed again once not default"})
    assert reallowed.status_code == 200, (
        f"clearing is_default must restore creator control: "
        f"{reallowed.status_code} {reallowed.text}"
    )


def test_org_default_flag_alone_flips_the_delete_verdict_for_the_same_creator(
    client, db_session, non_admin, as_creator
):
    """(j5) The flip test for DELETE — the route the reviewer actually exploited.

    DELETE is destructive, so the two halves cannot reuse one row (the allowed
    half consumes it). Two rows with the SAME author, called by the SAME
    non-admin caller, differing ONLY in ``is_default``, must give opposite
    verdicts.
    """
    non_default = _seed(db_session, CREATOR, name="Acme Non-Default")
    default = _seed(db_session, CREATOR, name="Acme Org Default", is_default=True)

    allowed = client.delete(f"{BASE}/{non_default.id}")
    assert allowed.status_code == 204, (
        f"creator must delete their own NON-default system: "
        f"{allowed.status_code} {allowed.text}"
    )

    denied = client.delete(f"{BASE}/{default.id}")
    assert denied.status_code == 403, (
        f"same author+caller, is_default=True must be DENIED: "
        f"{denied.status_code} {denied.text}"
    )
    db_session.refresh(default)
    assert default.is_active is True
    assert default.is_default is True


def test_frozen_org_default_is_denied_before_any_mutation_or_recompute(
    client, db_session, non_admin, as_creator, monkeypatch
):
    """(j6) ORDERING: the freeze must deny BEFORE the handler does any work.

    A gate that runs after the mutation (or after the expensive compile) would
    still answer 403 while having already changed the row or burned the work, so
    a status-code-only assertion cannot tell a correctly-ordered gate from a
    late one. This installs a landmine in ``recompute_compiled_style_content``
    — the PUT path's expensive step — and asserts the denied request never
    reaches it, then asserts the row is byte-for-byte untouched.
    """
    from src.api.routes.settings import design_systems as ds_routes

    ds = _seed(db_session, CREATOR, is_default=True)
    before = (ds.name, ds.description, ds.version, ds.is_default, ds.is_active)

    def _landmine(*args, **kwargs):
        raise AssertionError(
            "recompute_compiled_style_content ran on a DENIED request: the "
            "org-default gate is ordered AFTER the handler's expensive work"
        )

    monkeypatch.setattr(ds_routes, "recompute_compiled_style_content", _landmine)

    resp = client.put(
        f"{BASE}/{ds.id}",
        json={"name": "Renamed past the gate", "description": "and re-described"},
    )
    assert resp.status_code == 403, resp.text

    db_session.refresh(ds)
    assert (ds.name, ds.description, ds.version, ds.is_default, ds.is_active) == before, (
        "a denied request must leave the row completely unmodified"
    )


def test_frozen_org_default_denial_explains_why_without_leaking_the_row(
    client, db_session, non_admin, as_creator
):
    """(j7) The 403 detail must be debuggable — it names the org-default REASON,
    so this is distinguishable from the not-the-author denial — while disclosing
    nothing about the row (no name, no author, no id) beyond what the OPEN read
    endpoints already return to any authenticated caller."""
    ds = _seed(db_session, CREATOR, name="Acme Confidential Fixture", is_default=True)

    resp = client.delete(f"{BASE}/{ds.id}")
    assert resp.status_code == 403, resp.text
    detail = resp.json()["detail"]

    assert "default" in detail.lower(), f"denial must name the reason: {detail!r}"
    assert detail != "Admin access required", (
        "the freeze denial must be distinguishable from a plain admin denial"
    )
    for leak in ("Acme Confidential Fixture", CREATOR):
        assert leak not in detail, f"denial leaked {leak!r}: {detail!r}"
