"""Unit B: image-generation routes (``src/api/routes/image_generation.py``).

Contract: ``docs/superpowers/plans/2026-11-08-ai-image-generation-CORRECTIONS.md``,
section "Unit B interface".

Harness (match this when implementing)
--------------------------------------
* One FILE-backed SQLite database per test (``tmp_path``), default pool (each
  session has its own connection, like Postgres).
* ``src.core.database.get_session_local`` is patched to that database's
  sessionmaker. ``get_db_session`` and ``get_db`` both look it up at CALL time,
  so every path lands there: the job store's default ``session_factory``
  (whatever name it was bound under), ``save_generated_image``'s session (the
  job runner's), the export poll's ``_require_export_job_access`` and the
  session manager. ``app.dependency_overrides[get_db]`` is also set to a session
  on the same database, as the other route tests do.
* ``src.api.routes.images._get_current_user`` is patched to a switchable caller.
  The route must read the owner through that module at request time.
* ``image_generation_jobs._submit`` is patched to run the work INLINE with a fake
  ``ImageGenerator`` injected as ``generator=``, so a POST has finished its job
  before the response returns. While the work runs, the patched caller is
  switched to a different identity: a runner that asks "who am I?" from the
  worker thread instead of using the owner captured by the route would file
  the image under the wrong user, and the tests catch that.
  In capture mode the seam queues the work instead (used for the 429 test) and
  replays it at teardown, so the module's in-flight count returns to zero.
* CSRF: ``CSRFProtectionMiddleware`` is inactive outside
  ``ENVIRONMENT=production`` (tests run with ``ENVIRONMENT=test``) and allows
  requests with no Origin/Referer, so POSTs need no extra headers. This matches
  ``test_authz_images.py``.
* The flag is toggled per test with ``monkeypatch`` on
  ``TELLR_IMAGE_GENERATION_ENABLED`` and read per request, so the router must be
  registered unconditionally and gated by a dependency.
* Unit D: the feature is effective only when the env flag AND the admin setting
  (``workspace_settings`` row ``image_generation_enabled``, value ``True``) are on.
  The fixture turns BOTH on, so every "feature on" case below runs with the admin
  setting enabled; ``Env.admin()`` writes the row straight into the test database
  (``None`` deletes it, the never-set default). The gate must read it per request
  (no cache, no restart), through ``get_db`` or ``get_db_session``: both land on the
  test database.
"""

from __future__ import annotations

import base64
import importlib
import io
import logging
from concurrent.futures import Future
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Optional

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import src.database.models  # noqa: F401  (register every table before create_all)
from src.api.services import image_generation_jobs as jobs
from src.core.database import Base, get_db
from src.database.models.image import ImageAsset
from src.database.models.session import ExportJob
from src.database.models.workspace_setting import WorkspaceSetting
from src.services.image_generation import (
    DEFAULT_PRESET,
    IMAGE_MODELS,
    MAX_PROMPT_CHARS,
    PRESETS,
    QUALITIES,
    GeneratedImage,
    ImageGenerationError,
)

FLAG = "TELLR_IMAGE_GENERATION_ENABLED"
#: ``workspace_settings.IMAGE_GENERATION_KEY`` (Unit D); pinned in
#: ``test_image_generation_admin_toggle.py``.
ADMIN_SETTING_KEY = "image_generation_enabled"
ADMIN_SETTING_URL = "/api/admin/image-generation"
ALICE = "alice@test.com"
BOB = "bob@test.com"
#: The identity the worker would see if it asked; it must never own anything.
WORKER_IDENTITY = "worker-thread@must-not-own-anything.example"
PROMPT = "A calm navy gradient with soft light and room for a title"
JOB_PREFIX = "image-generation:"
MSG_403_PREFIX = "The app identity cannot use the image model (403)."

SVG_BYTES = (
    b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">'
    b'<circle cx="12" cy="12" r="10" fill="#1f77b4"/></svg>'
)


def _png(color=(0, 128, 255, 255), size=(32, 32)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGBA", size, color).save(buf, format="PNG")
    return buf.getvalue()


def _jpeg(color=(10, 40, 90), size=(48, 27)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, format="JPEG")
    return buf.getvalue()


_BY_FORMAT = {
    "jpeg": (_jpeg, "image/jpeg", "jpg", "JPEG"),
    "png": (_png, "image/png", "png", "PNG"),
    "svg": (lambda: SVG_BYTES, "image/svg+xml", "svg", None),
}

#: Models usable for raster output: those any non-SVG preset offers.
RASTER_MODELS = {
    m for p in PRESETS.values() if p.output_format != "svg" for m in p.models
}


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class FakeGenerator:
    """The ``ImageGenerator`` surface. Returns preset-appropriate real bytes, or raises."""

    def __init__(self) -> None:
        self.raises: Optional[BaseException] = None
        self.calls: list[tuple[str, dict]] = []

    def generate(self, prompt, preset_id, model=None, quality=None):
        self.calls.append(
            ("generate", dict(prompt=prompt, preset_id=preset_id, model=model, quality=quality))
        )
        if self.raises is not None:
            raise self.raises
        preset = PRESETS[preset_id]
        make, mime, ext, _ = _BY_FORMAT[preset.output_format]
        return GeneratedImage(
            data=make(), mime=mime, ext=ext, model=model or preset.default_model,
            preset_id=preset_id, revised_prompt=None, latency_s=0.01, usage=None,
        )

    def edit(self, prompt, source, source_mime, model=None, quality=None):
        self.calls.append(
            ("edit", dict(prompt=prompt, source=source, source_mime=source_mime,
                          model=model, quality=quality))
        )
        if self.raises is not None:
            raise self.raises
        return GeneratedImage(
            data=_png(color=(200, 30, 30, 255)), mime="image/png", ext="png",
            model=model or sorted(RASTER_MODELS)[0], preset_id=None,
            revised_prompt=None, latency_s=0.01, usage=None,
        )


class SubmitSeam:
    """Stands in for ``image_generation_jobs._submit``."""

    def __init__(self, generator: FakeGenerator, caller: dict) -> None:
        self.generator = generator
        self.caller = caller
        self.capture = False
        self.calls = 0
        self.pending: list[tuple[Callable, tuple, dict, Future]] = []
        self.errors: list[BaseException] = []

    def __call__(self, fn, /, *args, **kwargs):
        self.calls += 1
        future: Future = Future()
        if self.capture:
            self.pending.append((fn, args, kwargs, future))
        else:
            self._run(fn, args, kwargs, future)
        return future

    def _run(self, fn, args, kwargs, future) -> None:
        kwargs = {**kwargs, "generator": self.generator}
        requester = self.caller["name"]
        self.caller["name"] = WORKER_IDENTITY  # the worker thread is not the requester
        try:
            future.set_result(fn(*args, **kwargs))
        except BaseException as exc:  # run_job must never raise; recorded for teardown
            self.errors.append(exc)
            future.set_exception(exc)
        finally:
            self.caller["name"] = requester

    def drain(self) -> None:
        self.capture = False
        while self.pending:
            fn, args, kwargs, future = self.pending.pop(0)
            self._run(fn, args, kwargs, future)


# ---------------------------------------------------------------------------
# Harness
# ---------------------------------------------------------------------------


@dataclass
class Env:
    client: TestClient
    factory: Any
    caller: dict
    generator: FakeGenerator
    seam: SubmitSeam
    monkeypatch: Any
    snapshots: dict = field(default_factory=dict)

    # -- switches --
    def flag(self, on: bool) -> None:
        # on by default: "off" is the deployment explicitly opting out
        if on:
            self.monkeypatch.setenv(FLAG, "1")
        else:
            self.monkeypatch.setenv(FLAG, "0")

    def admin(self, on: Optional[bool]) -> None:
        """Set the admin setting row directly; ``None`` removes it (never set)."""
        db = self.factory()
        try:
            row = db.get(WorkspaceSetting, ADMIN_SETTING_KEY)
            if on is None:
                if row is not None:
                    db.delete(row)
            elif row is None:
                db.add(WorkspaceSetting(key=ADMIN_SETTING_KEY, value=on,
                                        updated_by="test-admin@test.example"))
            else:
                row.value = on
            db.commit()
        finally:
            db.close()

    def as_user(self, name: str) -> None:
        self.caller["name"] = name

    # -- requests --
    def generate(self, **body):
        body.setdefault("prompt", PROMPT)
        return self.client.post("/api/images/generate", json=body)

    def edit(self, token: str, **body):
        body.setdefault("prompt", "make the background navy")
        return self.client.post(f"/api/images/{token}/edit", json=body)

    def poll(self, job_id: str):
        return self.client.get(f"/api/images/generate/jobs/{job_id}")

    def available(self):
        return self.client.get("/api/images/generate/available")

    def completed(self, response) -> dict:
        """Assert a 202 start, then poll it and assert completion; return the poll body."""
        assert response.status_code == 202, response.text
        job_id = response.json()["job_id"]
        polled = self.poll(job_id)
        assert polled.status_code == 200, polled.text
        body = polled.json()
        assert body["status"] == "completed", body
        assert body["job_id"] == job_id
        assert body["image"] is not None
        return body

    # -- database --
    def jobs(self) -> list[dict]:
        db = self.factory()
        try:
            return [
                {"job_id": r.job_id, "session_id": r.session_id, "status": r.status,
                 "status_message": r.status_message, "error_message": r.error_message,
                 "completed_at": r.completed_at}
                for r in db.query(ExportJob).order_by(ExportJob.id).all()
            ]
        finally:
            db.close()

    def images(self) -> list[dict]:
        db = self.factory()
        try:
            return [_image_snapshot(r) for r in db.query(ImageAsset).order_by(ImageAsset.id).all()]
        finally:
            db.close()

    def image(self, token: str) -> dict:
        db = self.factory()
        try:
            return _image_snapshot(db.query(ImageAsset).filter(ImageAsset.token == token).one())
        finally:
            db.close()

    def seed_image(
        self, *, owner: str, category: str = "content", mime: str = "image/png",
        data: Optional[bytes] = None, original_filename: str = "team-logo.png",
        is_active: bool = True,
    ) -> str:
        stamp = datetime(2026, 1, 2, 3, 4, 5)
        db = self.factory()
        try:
            # updated_by is deliberately NOT any caller, so a route that writes
            # ``updated_by = caller`` onto the source shows up as a change.
            row = ImageAsset(
                filename=f"seed-{original_filename}", original_filename=original_filename,
                mime_type=mime, size_bytes=0, image_data=data or _png(),
                thumbnail_base64=None, tags=["seeded"], description="seeded source",
                category=category, uploaded_by=owner, is_active=is_active,
                created_by=owner, updated_by="seeder@test.example",
                created_at=stamp, updated_at=stamp,
            )
            row.size_bytes = len(row.image_data)
            db.add(row)
            db.commit()
            return row.token
        finally:
            db.close()


def _image_snapshot(r: ImageAsset) -> dict:
    return {
        "token": r.token, "image_data": r.image_data, "mime_type": r.mime_type,
        "tags": list(r.tags or []), "category": r.category, "description": r.description,
        "uploaded_by": r.uploaded_by, "is_active": r.is_active, "updated_at": r.updated_at,
        "updated_by": r.updated_by, "original_filename": r.original_filename,
    }


@pytest.fixture
def env(tmp_path, monkeypatch):
    from src.api.main import app

    engine = create_engine(
        f"sqlite:///{tmp_path / 'image-routes.sqlite'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    monkeypatch.setattr("src.core.database.get_session_local", lambda: factory)

    def _override_get_db():
        db = factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _override_get_db

    caller = {"name": ALICE}
    monkeypatch.setattr("src.api.routes.images._get_current_user", lambda: caller["name"])

    generator = FakeGenerator()
    seam = SubmitSeam(generator, caller)
    monkeypatch.setattr(jobs, "_submit", seam)
    monkeypatch.setenv(FLAG, "1")

    harness = Env(
        client=TestClient(app), factory=factory, caller=caller, generator=generator,
        seam=seam, monkeypatch=monkeypatch,
    )
    harness.admin(True)  # Unit D: "feature on" = env flag AND admin setting
    try:
        yield harness
    finally:
        seam.drain()  # free any captured in-flight slots
        app.dependency_overrides.pop(get_db, None)
        engine.dispose()
    assert not seam.errors, f"run_job raised (it must never raise): {seam.errors!r}"


# ---------------------------------------------------------------------------
# Feature flag
# ---------------------------------------------------------------------------


class TestFlag:
    @pytest.mark.parametrize("value", ["0", "false"])
    def test_available_reports_unavailable_when_off(self, env, value):
        env.monkeypatch.setenv(FLAG, value)

        resp = env.available()

        assert resp.status_code == 200, "the probe itself is never flag-gated"
        body = resp.json()
        assert body["available"] is False
        assert not body.get("presets")
        assert not body.get("edit")

    def test_generate_is_404_when_off(self, env):
        env.flag(False)
        assert env.generate().status_code == 404
        assert env.jobs() == [] and env.seam.calls == 0

        env.flag(True)
        assert env.generate().status_code == 202

    def test_edit_is_404_when_off(self, env):
        token = env.seed_image(owner=ALICE)
        env.flag(False)
        assert env.edit(token).status_code == 404
        assert env.jobs() == [] and env.seam.calls == 0
        assert len(env.images()) == 1

        env.flag(True)
        assert env.edit(token).status_code == 202

    def test_poll_is_404_when_off(self, env):
        job_id = env.generate().json()["job_id"]

        env.flag(False)
        assert env.poll(job_id).status_code == 404
        assert env.poll("x").status_code == 404

        env.flag(True)
        assert env.poll(job_id).status_code == 200


# ---------------------------------------------------------------------------
# Admin setting (Unit D): effective = env flag AND admin setting, per request
# ---------------------------------------------------------------------------

#: (env flag on?, admin setting) combinations in which the feature must be OFF.
#: ``None`` = no workspace_settings row at all, the out-of-the-box default.
OFF_COMBOS = [
    pytest.param(True, False, id="env-on-admin-off"),
    pytest.param(False, True, id="env-off-admin-on"),
    pytest.param(False, None, id="env-off-admin-never-set"),
]


class TestOnByDefault:
    """Out of the box (no env var, no admin row) the feature is ON (user decision, 2026-11-09)."""

    def test_unset_env_and_never_set_admin_is_available(self, env):
        env.monkeypatch.delenv(FLAG, raising=False)
        env.admin(None)

        body = env.available().json()

        assert body["available"] is True
        assert body["presets"]

    def test_unset_env_and_never_set_admin_generates(self, env):
        env.monkeypatch.delenv(FLAG, raising=False)
        env.admin(None)

        assert env.generate().status_code == 202


class TestAdminSetting:
    @staticmethod
    def _switch(env, env_on: bool, admin: Optional[bool]) -> None:
        env.flag(env_on)
        env.admin(admin)

    @pytest.mark.parametrize("env_on, admin", OFF_COMBOS)
    def test_available_reports_unavailable(self, env, env_on, admin):
        self._switch(env, env_on, admin)

        resp = env.available()

        assert resp.status_code == 200, "the probe itself is never gated"
        body = resp.json()
        assert body["available"] is False
        assert not body.get("presets")
        assert not body.get("edit")

    @pytest.mark.parametrize("env_on, admin", OFF_COMBOS)
    def test_generate_is_404(self, env, env_on, admin):
        self._switch(env, env_on, admin)

        assert env.generate().status_code == 404
        assert env.jobs() == [] and env.seam.calls == 0

        self._switch(env, True, True)
        assert env.generate().status_code == 202

    @pytest.mark.parametrize("env_on, admin", OFF_COMBOS)
    def test_edit_is_404(self, env, env_on, admin):
        token = env.seed_image(owner=ALICE)
        self._switch(env, env_on, admin)

        assert env.edit(token).status_code == 404
        assert env.jobs() == [] and env.seam.calls == 0
        assert len(env.images()) == 1

        self._switch(env, True, True)
        assert env.edit(token).status_code == 202

    @pytest.mark.parametrize("env_on, admin", OFF_COMBOS)
    def test_poll_is_404(self, env, env_on, admin):
        job_id = env.completed(env.generate())["job_id"]
        self._switch(env, env_on, admin)

        assert env.poll(job_id).status_code == 404

        self._switch(env, True, True)
        assert env.poll(job_id).status_code == 200

    def test_turning_the_setting_off_takes_effect_on_the_next_request(self, env):
        token = env.seed_image(owner=ALICE)
        job_id = env.completed(env.generate())["job_id"]
        assert env.available().json()["available"] is True

        env.admin(False)  # no restart, same client, same process
        assert env.available().json()["available"] is False
        assert env.generate().status_code == 404
        assert env.edit(token).status_code == 404
        assert env.poll(job_id).status_code == 404
        assert len(env.jobs()) == 1 and env.seam.calls == 1

        env.admin(True)
        assert env.available().json()["available"] is True
        assert env.poll(job_id).status_code == 200
        env.completed(env.generate())

    def test_the_admin_route_drives_the_gate(self, env):
        """The real admin PUT writes what the gate reads (``require_admin`` is
        bypassed outside production, as for every route in this file)."""
        off = env.client.put(ADMIN_SETTING_URL, json={"enabled": False})
        assert off.status_code == 200, off.text
        assert env.generate().status_code == 404
        assert env.available().json()["available"] is False

        on = env.client.put(ADMIN_SETTING_URL, json={"enabled": True})
        assert on.status_code == 200, on.text
        assert env.available().json()["available"] is True
        env.completed(env.generate())


# ---------------------------------------------------------------------------
# GET /generate/available (flag on)
# ---------------------------------------------------------------------------


class TestAvailable:
    def test_reports_available_with_limits(self, env):
        body = env.available().json()
        assert body["available"] is True
        assert body["max_prompt_chars"] == MAX_PROMPT_CHARS
        assert body["default_preset"] == DEFAULT_PRESET

    def test_presets_mirror_the_server_presets(self, env):
        presets = env.available().json()["presets"]

        assert [p["id"] for p in presets] == list(PRESETS)
        for option in presets:
            preset = PRESETS[option["id"]]
            assert option["label"] == preset.label
            assert option["description"] == preset.description
            assert option["output_format"] == preset.output_format
            assert option["category"] == preset.category
            assert option["transparent"] is preset.transparent
            assert [m["id"] for m in option["models"]] == list(preset.models)
            for model in option["models"]:
                assert model["label"] == IMAGE_MODELS[model["id"]].label
                assert model["description"] == IMAGE_MODELS[model["id"]].description
            assert option["default_model"] == preset.default_model
            assert option["qualities"] == list(QUALITIES)
            assert option["default_quality"] == preset.default_quality

    def test_edit_lists_only_raster_capable_models(self, env):
        edit = env.available().json()["edit"]

        ids = [m["id"] for m in edit["models"]]
        assert ids, "edit must offer at least one model"
        assert set(ids) <= RASTER_MODELS
        assert edit["default_model"] in ids
        assert edit["qualities"] == list(QUALITIES)
        assert edit["default_quality"] in QUALITIES

    def test_available_carries_the_quality_explainers(self, env):
        from src.services.image_generation import QUALITY_DESCRIPTIONS

        assert env.available().json()["quality_descriptions"] == QUALITY_DESCRIPTIONS

    def test_every_advertised_preset_and_model_is_accepted(self, env):
        for option in env.available().json()["presets"]:
            for model in option["models"]:
                body = env.completed(
                    env.generate(preset=option["id"], model=model["id"],
                                 quality=option["default_quality"])
                )
                assert body["image"]["tags"] == ["ai_generated", model["id"], option["id"]]

    def test_the_advertised_edit_defaults_are_accepted(self, env):
        edit = env.available().json()["edit"]
        token = env.seed_image(owner=ALICE)

        env.completed(env.edit(token, model=edit["default_model"], quality=edit["default_quality"]))


# ---------------------------------------------------------------------------
# POST /generate: happy path
# ---------------------------------------------------------------------------


class TestGenerate:
    def test_generate_poll_list_and_fetch(self, env):
        resp = env.generate(preset="background")
        assert resp.status_code == 202, resp.text
        job_id = resp.json()["job_id"]
        assert job_id

        polled = env.poll(job_id)
        assert polled.status_code == 200
        body = polled.json()
        assert body["status"] == "completed"
        assert body["status_message"] == "Done"
        assert body["error"] is None
        assert isinstance(body["progress"], int)
        assert isinstance(body["total_slides"], int)
        image = body["image"]
        token = image["id"]
        assert image["mime_type"] == "image/jpeg"
        assert image["category"] == "background"
        assert image["uploaded_by"] == ALICE
        assert image["tags"] == ["ai_generated", PRESETS["background"].default_model, "background"]
        assert image["description"] == PROMPT
        assert env.image(token)["uploaded_by"] == ALICE

        listed = env.client.get("/api/images")
        assert listed.status_code == 200
        assert token in [i["id"] for i in listed.json()["images"]]

        data = env.client.get(f"/api/images/{token}/data")
        assert data.status_code == 200
        uri = data.json()["data_uri"]
        assert uri.startswith("data:image/jpeg;base64,")
        decoded = base64.b64decode(uri.split(",", 1)[1])
        assert Image.open(io.BytesIO(decoded)).format == "JPEG"

    def test_the_job_is_an_image_generation_job_of_the_caller(self, env):
        job_id = env.generate().json()["job_id"]

        [row] = env.jobs()
        assert row["job_id"] == job_id
        assert row["session_id"] == JOB_PREFIX + ALICE

    def test_owner_is_the_requester_not_the_worker_identity(self, env):
        env.as_user(BOB)
        body = env.completed(env.generate())

        assert body["image"]["uploaded_by"] == BOB
        assert [i["uploaded_by"] for i in env.images()] == [BOB]
        assert env.jobs()[0]["session_id"] == JOB_PREFIX + BOB

    def test_default_preset_is_used_when_omitted(self, env):
        preset = PRESETS[DEFAULT_PRESET]
        body = env.completed(env.generate())

        assert body["image"]["tags"] == ["ai_generated", preset.default_model, DEFAULT_PRESET]
        assert body["image"]["mime_type"] == _BY_FORMAT[preset.output_format][1]
        assert body["image"]["category"] == preset.category

    def test_svg_round_trip(self, env):
        body = env.completed(env.generate(preset="icon_svg"))
        token = body["image"]["id"]

        assert body["image"]["mime_type"] == "image/svg+xml"
        uri = env.client.get(f"/api/images/{token}/data").json()["data_uri"]
        assert uri.startswith("data:image/svg+xml;base64,")
        assert b"<svg" in base64.b64decode(uri.split(",", 1)[1])

    def test_generation_error_is_reported_on_the_poll(self, env):
        env.generator.raises = ImageGenerationError("PERMISSION_DENIED", status_code=403)

        resp = env.generate()
        assert resp.status_code == 202
        body = env.poll(resp.json()["job_id"]).json()

        assert body["status"] == "error"
        assert body["status_message"] == "Failed"
        assert body["error"].startswith(MSG_403_PREFIX)
        assert body["image"] is None
        assert env.images() == []

    def test_prompt_at_the_limit_is_accepted_whole(self, env):
        prompt = "a" * MAX_PROMPT_CHARS
        env.completed(env.generate(prompt=prompt))

        assert env.generator.calls[0][1]["prompt"] == prompt


# ---------------------------------------------------------------------------
# POST /generate: validation and capacity
# ---------------------------------------------------------------------------


def _model_not_allowed_for(preset_id: str) -> str:
    return next(m for m in IMAGE_MODELS if m not in PRESETS[preset_id].models)


class TestGenerateValidation:
    @pytest.mark.parametrize(
        "body",
        [
            pytest.param({"preset": "poster"}, id="unknown-preset"),
            pytest.param(
                {"preset": "icon_svg", "model": "__not_for_svg__"},
                id="model-not-allowed-for-preset",
            ),
            pytest.param(
                {"preset": "background", "model": "gpt-image-9-imaginary"}, id="unknown-model"
            ),
            pytest.param({"preset": "background", "quality": "ultra"}, id="bad-quality"),
        ],
    )
    def test_bad_choices_are_400_and_start_nothing(self, env, body):
        if body.get("model") == "__not_for_svg__":
            body = {**body, "model": _model_not_allowed_for("icon_svg")}

        resp = env.generate(**body)

        assert resp.status_code == 400, resp.text
        assert env.jobs() == []
        assert env.seam.calls == 0

    @pytest.mark.parametrize(
        "prompt",
        [
            pytest.param("", id="empty"),
            pytest.param("   \n\t ", id="whitespace"),
            pytest.param("a" * (MAX_PROMPT_CHARS + 1), id="too-long"),
        ],
    )
    def test_prompt_bounds_are_422(self, env, prompt):
        resp = env.client.post("/api/images/generate", json={"prompt": prompt})

        assert resp.status_code == 422
        assert env.jobs() == [] and env.seam.calls == 0

    def test_missing_prompt_is_422(self, env):
        assert env.client.post("/api/images/generate", json={}).status_code == 422

    def test_429_when_capacity_is_exhausted_and_that_job_reads_as_error(self, env):
        env.seam.capture = True
        accepted = []
        for _ in range(jobs.MAX_INFLIGHT):
            resp = env.generate()
            assert resp.status_code == 202, resp.text
            accepted.append(resp.json()["job_id"])

        refused = env.generate()

        assert refused.status_code == 429, refused.text
        assert env.seam.calls == jobs.MAX_INFLIGHT
        rows = env.jobs()
        assert len(rows) == jobs.MAX_INFLIGHT + 1, "the refused request's job row exists"
        [refused_row] = [r for r in rows if r["job_id"] not in accepted]
        assert refused_row["status"] == "error", "a refused job must not sit pending forever"
        assert refused_row["error_message"]
        assert refused_row["status_message"], "status_message is never null"
        assert refused_row["completed_at"] is not None, "a refused job is finished, like W6"
        polled = env.poll(refused_row["job_id"]).json()
        assert polled["status"] == "error"
        assert polled["error"]
        for job_id in accepted:
            waiting = env.poll(job_id).json()
            assert waiting["status"] == "pending"
            assert waiting["status_message"] == "Queued"

        env.seam.drain()  # the four finish; capacity returns
        assert all(env.poll(j).json()["status"] == "completed" for j in accepted)
        assert env.generate().status_code == 202


# ---------------------------------------------------------------------------
# POST /{token}/edit
# ---------------------------------------------------------------------------


class TestEdit:
    def test_another_users_ephemeral_image_is_404(self, env):
        token = env.seed_image(owner=BOB, category="ephemeral")

        assert env.edit(token).status_code == 404
        assert env.jobs() == [] and env.seam.calls == 0
        assert len(env.images()) == 1

    def test_own_ephemeral_image_is_editable_and_lands_in_the_library(self, env):
        token = env.seed_image(owner=ALICE, category="ephemeral")

        body = env.completed(env.edit(token))

        assert body["image"]["category"] == "content"
        assert body["image"]["uploaded_by"] == ALICE

    def test_unknown_token_is_404(self, env):
        assert env.edit("no-such-token").status_code == 404
        assert env.jobs() == [] and env.seam.calls == 0

    def test_inactive_image_is_404(self, env):
        token = env.seed_image(owner=ALICE, is_active=False)

        assert env.edit(token).status_code == 404
        assert env.jobs() == [] and env.seam.calls == 0

    def test_svg_source_is_400(self, env):
        token = env.seed_image(owner=ALICE, mime="image/svg+xml", data=SVG_BYTES,
                               original_filename="icon.svg")

        assert env.edit(token).status_code == 400
        assert env.jobs() == [] and env.seam.calls == 0

    @pytest.mark.parametrize(
        "body",
        [pytest.param({"model": "gpt-image-9-imaginary"}, id="bad-model"),
         pytest.param({"quality": "ultra"}, id="bad-quality")],
    )
    def test_bad_model_or_quality_is_400(self, env, body):
        token = env.seed_image(owner=ALICE)

        assert env.edit(token, **body).status_code == 400
        assert env.jobs() == [] and env.seam.calls == 0

    @pytest.mark.parametrize(
        "prompt",
        [
            pytest.param("", id="empty"),
            pytest.param("   \n\t ", id="whitespace"),
            pytest.param("a" * (MAX_PROMPT_CHARS + 1), id="too-long"),
        ],
    )
    def test_prompt_bounds_are_422(self, env, prompt):
        token = env.seed_image(owner=ALICE)

        assert env.edit(token, prompt=prompt).status_code == 422
        assert env.jobs() == [] and env.seam.calls == 0

    def test_success_adds_one_row_and_leaves_the_source_untouched(self, env):
        source_bytes = _jpeg(color=(0, 200, 0))
        token = env.seed_image(owner=ALICE, mime="image/jpeg", data=source_bytes,
                               original_filename="quarterly-hero.jpg", category="background")
        before = env.image(token)

        body = env.completed(env.edit(token, prompt="add soft morning light"))

        images = env.images()
        assert len(images) == 2, "an edit creates exactly one new row"
        new = body["image"]
        assert new["id"] != token
        assert env.image(token) == before, "source bytes, metadata and updated_at unchanged"
        assert env.image(token)["image_data"] == source_bytes
        assert new["uploaded_by"] == ALICE
        assert new["category"] == "background"
        assert new["tags"][:2] == ["ai_generated", "ai_edit"] and len(new["tags"]) == 3
        assert new["description"] == "Edit of quarterly-hero.jpg: add soft morning light"

        [(kind, call)] = env.generator.calls
        assert kind == "edit"
        assert call["prompt"] == "add soft morning light"
        assert call["source"] == source_bytes
        assert call["source_mime"] == "image/jpeg"

    def test_explicit_model_is_recorded_in_the_tags(self, env):
        model = sorted(RASTER_MODELS)[-1]
        token = env.seed_image(owner=ALICE)

        body = env.completed(env.edit(token, model=model, quality="high"))

        assert body["image"]["tags"] == ["ai_generated", "ai_edit", model]
        assert env.generator.calls[0][1]["quality"] == "high"

    def test_editing_someone_elses_library_image_yields_my_own_copy(self, env):
        token = env.seed_image(owner=BOB, category="content")
        before = env.image(token)

        body = env.completed(env.edit(token))

        new_token = body["image"]["id"]
        assert env.image(new_token)["uploaded_by"] == ALICE
        assert env.image(token) == before
        assert env.image(token)["uploaded_by"] == BOB
        listed = [i["id"] for i in env.client.get("/api/images").json()["images"]]
        assert new_token in listed and token not in listed


# ---------------------------------------------------------------------------
# GET /generate/jobs/{job_id}: who may poll
# ---------------------------------------------------------------------------


class TestPollAuthz:
    def test_another_user_gets_404(self, env):
        job_id = env.generate().json()["job_id"]

        env.as_user(BOB)
        assert env.poll(job_id).status_code == 404

        env.as_user(ALICE)
        assert env.poll(job_id).status_code == 200

    def test_unknown_job_is_404(self, env):
        assert env.poll("no-such-job").status_code == 404

    def test_a_real_export_job_is_404(self, env):
        db = env.factory()
        try:
            db.add(ExportJob(job_id="pptx-job-1", session_id="deck-123", status="completed",
                             output_path="/tmp/deck-123.pptx"))
            db.commit()
        finally:
            db.close()

        assert env.poll("pptx-job-1").status_code == 404

    @pytest.mark.parametrize(
        "path",
        [
            "/api/export/pptx/poll/{job_id}",
            "/api/export/pptx/download/{job_id}",
            "/api/export/google-slides/poll/{job_id}",
        ],
    )
    def test_export_poll_routes_fail_closed_on_an_image_job(self, env, path):
        job_id = env.completed(env.generate())["job_id"]

        resp = env.client.get(path.format(job_id=job_id))

        assert resp.status_code in (403, 404), resp.text


# ---------------------------------------------------------------------------
# Startup log line (the deploy overlay check greps for it)
# ---------------------------------------------------------------------------


class TestStartupLog:
    def _reload(self, monkeypatch, caplog, flag: Optional[str]):
        import src.api.routes.image_generation as module

        if flag is None:
            monkeypatch.delenv(FLAG, raising=False)
        else:
            monkeypatch.setenv(FLAG, flag)
        caplog.clear()
        with caplog.at_level(logging.INFO):
            importlib.reload(module)
        return module

    def test_enabled_import_logs_that_the_deployment_offers_it(self, monkeypatch, caplog):
        self._reload(monkeypatch, caplog, "1")

        expected = "AI image generation is offered on this deployment"
        hits = [r for r in caplog.records if expected in r.getMessage()]
        assert hits, [r.getMessage() for r in caplog.records]
        assert hits[0].levelno == logging.INFO

    def test_disabled_import_is_silent(self, monkeypatch, caplog):
        self._reload(monkeypatch, caplog, "0")

        assert not [
            r for r in caplog.records
            if "AI image generation is offered" in r.getMessage()
        ]
