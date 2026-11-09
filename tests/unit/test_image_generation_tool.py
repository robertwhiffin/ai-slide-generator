"""The architect's ``generate_image`` tool (chat image generation, Task 2 / Unit G).

Contract: ``docs/superpowers/plans/2026-11-09-chat-image-generation-CORRECTIONS.md``,
"Unit G interface" (it overrides the plan). In short:

* ``ImageGenerationAgentTool(ImageToolContext(...))`` is an ``AgentTool``. One ``run`` makes
  1-3 images IN PARALLEL on a module-level pool, saves each to the Image Library as the
  turn's user (the preset's category; tags ``ai_generated``, the image's model, the preset,
  ``chat``, plus ``chat_option`` when it makes more than one), and returns spotlighted facts:
  ``Option N: {{image:TOKEN}} ...`` per image, fixed text per failure;
* code-enforced caps: calls (``calls_left``), images (``images_left``), a process-wide
  semaphore of ``MAX_CONCURRENT`` slots taken without blocking, and a wall clock
  ``wall = min(remaining_seconds, seconds_left, deadline_at - clock())`` under which no call
  starts when it is below ``MIN_START_SECONDS``;
* a straggler still running at ``wall`` is abandoned: reported as ``FAIL_TIMEOUT``, and it
  never saves when it does finish;
* failure text is fixed (429 busy, 403 forbidden, timeout, other), never ``str(exc)``.

Doubles. The generator is a fake (``generator_factory=``) built from ``threading.Barrier``
and ``Event``\\ s: its calls race on the pool, so its scripted steps run in ARRIVAL order and
no test assumes which option a step serves. Saves are REAL: the default ``save_to_library``
runs ``get_db_session`` + ``save_generated_image`` + ``image_service.upload_image`` against a
file SQLite database (``src.core.database.get_session_local`` is patched onto it, the same
seam as ``test_image_generation_admin_toggle.py``). A file database, not ``:memory:``,
because three saves commit from three pool threads at once. The real Gateway is unreachable
from this file (``get_system_client`` raises), so a tool that ignored ``generator_factory``
fails instead of spending money.

One test seam beyond the interface: the straggler test lowers the module's
``MIN_START_SECONDS`` so a 1-second wall may start. ``run`` must therefore read
``MIN_START_SECONDS`` from the module when it is called (no default argument or class
attribute copy).
"""

from __future__ import annotations

import ast
import dataclasses
import io
import re
import threading
import time
from pathlib import Path
from typing import Any

import pytest
from PIL import Image
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from src.services.agent_tools.image_generation_tool import (
    BUDGET_SECONDS,
    FAIL_BUSY,
    FAIL_FORBIDDEN,
    FAIL_OTHER,
    FAIL_TIMEOUT,
    IMAGE_TOOL_DESCRIPTION,
    IMAGE_TOOL_NAME,
    KIND_TO_PRESET,
    MAX_CALLS_PER_TURN,
    MAX_CONCURRENT,
    MAX_IMAGES_PER_TURN,
    MAX_PER_CALL,
    MIN_START_SECONDS,
    ImageGenerationAgentTool,
    ImageGenerationArgs,
    ImageToolContext,
    save_to_library,
)

import src.database.models  # noqa: F401 - register the complete ORM metadata
from src.core.database import Base, get_db_session
from src.database.models.image import ImageAsset
from src.services import image_generation as image_generation_service
from src.services.agent_runtime import DatabricksModelAdapter
from src.services.agent_tools import image_generation_tool as tool_module
from src.services.agent_tools.toolset import AgentToolset
from src.services.image_generation import (
    MAX_PROMPT_CHARS,
    PRESETS,
    GeneratedImage,
    ImageGenerationError,
    ImageGenerator,
    save_generated_image,
)

REPO = Path(__file__).resolve().parents[2]
MODULE_PATH = REPO / "src" / "services" / "agent_tools" / "image_generation_tool.py"

OWNER = "alice@example.com"
SESSION_ID = "sess-376"
PROMPT = "A calm harbour at dawn, flat style, deep teal palette"
#: Not any preset's default model: the tag must come from the image, not the preset.
FAKE_MODEL = "gpt-image-2.6-sunburst"
#: The tool's ``remaining_seconds`` in most tests (the wall is then 120 s).
REMAINING = 120.0
#: How long a barrier waits: generations that run one at a time break it.
BARRIER_TIMEOUT = 5.0
#: A fixed clock far in the past, so a tool that reads ``time.time()`` instead of
#: ``context.clock`` sees every deadline below as already gone.
NOW = 1_000_000.0

SPOTLIGHT_HEAD = '<untrusted-data source="image_generation">\n'
SPOTLIGHT_TAIL = "\n</untrusted-data>"
REF_RE = re.compile(r"\{\{image:([A-Za-z0-9_-]+)\}\}")
FAILURES = (FAIL_BUSY, FAIL_FORBIDDEN, FAIL_TIMEOUT, FAIL_OTHER)
SECRET = "SECRET-BODY"

SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" width="64" height="64">'
    '<circle cx="32" cy="32" r="20" fill="#1b3139"/></svg>'
)


# ---------------------------------------------------------------------------
# Images the fake "generates" (real bytes: the saves are real)
# ---------------------------------------------------------------------------


def _jpeg() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (48, 32), (30, 90, 200)).save(buf, format="JPEG", quality=90)
    return buf.getvalue()


def _png() -> bytes:
    img = Image.new("RGBA", (32, 32), (0, 0, 0, 0))
    img.paste(Image.new("RGBA", (16, 32), (220, 40, 40, 255)), (16, 0))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _image_for(preset_id: str) -> GeneratedImage:
    if preset_id == "icon_svg":
        data, mime, ext = SVG.encode(), "image/svg+xml", "svg"
    elif preset_id == "icon_png":
        data, mime, ext = _png(), "image/png", "png"
    else:
        data, mime, ext = _jpeg(), "image/jpeg", "jpg"
    return GeneratedImage(
        data=data,
        mime=mime,
        ext=ext,
        model=FAKE_MODEL,
        preset_id=preset_id,
        revised_prompt=None,
        latency_s=0.01,
        usage=None,
    )


# ---------------------------------------------------------------------------
# The fake generator
# ---------------------------------------------------------------------------


class FakeGenerator:
    """The ``generator_factory`` double (``factory`` returns this one shared fake).

    Every ``generate`` call is recorded (prompt, preset, model, quality, ``timeout_s``,
    thread name), then takes the next scripted step in ARRIVAL order:

    * ``"ok"`` (also the default once the script runs out) returns an image at once;
    * ``"block"`` waits for :attr:`release` (at most 10 s), sets :attr:`block_returned`
      and returns an image;
    * an exception instance is raised.

    With a ``barrier``, every call first waits on it (``BARRIER_TIMEOUT``), so calls that
    run one at a time raise ``BrokenBarrierError``.
    """

    def __init__(self, steps: Any = (), *, barrier: threading.Barrier | None = None) -> None:
        self._lock = threading.Lock()
        self._steps = list(steps)
        self._started = threading.Semaphore(0)
        self.barrier = barrier
        self.calls: list[dict[str, Any]] = []
        self.release = threading.Event()
        self.block_returned = threading.Event()
        self.log: list[Any] | None = None

    def factory(self) -> FakeGenerator:
        return self

    def generate(
        self,
        prompt: str,
        preset_id: str,
        model: str | None = None,
        quality: str | None = None,
        *,
        timeout_s: float | None = None,
    ) -> GeneratedImage:
        with self._lock:
            self.calls.append(
                {
                    "prompt": prompt,
                    "preset_id": preset_id,
                    "model": model,
                    "quality": quality,
                    "timeout_s": timeout_s,
                    "thread": threading.current_thread().name,
                }
            )
            step = self._steps.pop(0) if self._steps else "ok"
            if self.log is not None:
                self.log.append("generate")
        self._started.release()
        if self.barrier is not None:
            self.barrier.wait(timeout=BARRIER_TIMEOUT)
        if isinstance(step, BaseException):
            raise step
        if step == "block":
            self.release.wait(timeout=10)
            image = _image_for(preset_id)
            self.block_returned.set()
            return image
        return _image_for(preset_id)

    def wait_started(self, n: int, timeout: float = 5.0) -> bool:
        """True once ``n`` calls have started (since the last wait)."""
        deadline = time.monotonic() + timeout
        for _ in range(n):
            if not self._started.acquire(timeout=max(0.0, deadline - time.monotonic())):
                return False
        return True


# ---------------------------------------------------------------------------
# Harness
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class Library:
    """The test's Image Library database."""

    factory: sessionmaker

    def rows(self) -> list[dict[str, Any]]:
        session = self.factory()
        try:
            return [
                {
                    "token": row.token,
                    "owner": row.uploaded_by,
                    "category": row.category,
                    "tags": list(row.tags or []),
                    "mime": row.mime_type,
                    "description": row.description,
                    "active": row.is_active,
                }
                for row in session.query(ImageAsset).order_by(ImageAsset.id)
            ]
        finally:
            session.close()

    def tokens(self) -> set[str]:
        return {row["token"] for row in self.rows()}


@pytest.fixture
def library(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'library.sqlite'}",
        connect_args={"check_same_thread": False, "timeout": 30},
    )
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    monkeypatch.setattr("src.core.database.get_session_local", lambda: session_factory)
    try:
        yield Library(session_factory)
    finally:
        engine.dispose()


@pytest.fixture(autouse=True)
def _no_real_gateway(monkeypatch: pytest.MonkeyPatch) -> None:
    """A real ``ImageGenerator`` would reach the Gateway with the developer's credentials."""

    def refuse(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("unit tests must never reach the real Gateway")

    monkeypatch.setattr(image_generation_service, "get_system_client", refuse)


def _context(fake: FakeGenerator, **overrides: Any) -> ImageToolContext:
    values: dict[str, Any] = {
        "owner": OWNER,
        "session_id": SESSION_ID,
        "on_call": lambda kind, n: None,
        "calls_left": MAX_CALLS_PER_TURN,
        "images_left": MAX_IMAGES_PER_TURN,
        "seconds_left": BUDGET_SECONDS,
        "deadline_at": None,
        "generator_factory": fake.factory,
    }
    values.update(overrides)
    return ImageToolContext(**values)


def _tool(fake: FakeGenerator, **overrides: Any) -> ImageGenerationAgentTool:
    return ImageGenerationAgentTool(_context(fake, **overrides))


def _run(tool: ImageGenerationAgentTool, *, remaining: float = REMAINING, **args: Any) -> str:
    args.setdefault("prompt", PROMPT)
    args.setdefault("kind", "illustration")
    return tool.run(ImageGenerationArgs(**args), remaining_seconds=remaining)


def _assert_spotlighted(result: Any) -> str:
    """The result is ``spotlight("image_generation", ...)``, once; returns the body."""
    assert isinstance(result, str)
    assert result.startswith(SPOTLIGHT_HEAD), result[:120]
    assert result.endswith(SPOTLIGHT_TAIL), result[-120:]
    assert result.count("<untrusted-data") == 1
    assert "&lt;untrusted-data" not in result, "spotlighted twice"
    return result[len(SPOTLIGHT_HEAD) : -len(SPOTLIGHT_TAIL)]


def _assert_refused(result: str, fake: FakeGenerator, tool: ImageGenerationAgentTool) -> str:
    body = _assert_spotlighted(result)
    assert fake.calls == [], "a refused call starts no generation"
    assert REF_RE.search(result) is None
    assert tool.generated == []
    assert tool.saved_tokens() == []
    return body


def _ref(token: str) -> str:
    return "{{image:" + token + "}}"


def _in_background(tool: ImageGenerationAgentTool, **args: Any):
    box: dict[str, Any] = {}

    def target() -> None:
        try:
            box["result"] = _run(tool, **args)
        except BaseException as exc:  # noqa: BLE001 - reported by the test
            box["error"] = exc

    thread = threading.Thread(target=target, daemon=True)
    thread.start()
    return thread, box


def _imported_modules(path: Path) -> set[str]:
    """Every module a source imports, relative imports resolved (test_gateway_toolset.py)."""
    package = ".".join(path.relative_to(REPO).parent.parts)
    modules: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                parts = package.split(".")
                base = ".".join(parts[: len(parts) - (node.level - 1)])
                module = base + ("." + node.module if node.module else "")
            else:
                module = node.module or ""
            modules.add(module)
            modules.update(module + "." + alias.name for alias in node.names)
    return modules


# ---------------------------------------------------------------------------
# Harness self-test: concurrent real saves land in the test database
# ---------------------------------------------------------------------------


def test_harness_self_test_three_concurrent_real_saves_land_in_the_test_database(library):
    barrier = threading.Barrier(3)
    errors: list[BaseException] = []

    def save() -> None:
        try:
            barrier.wait(timeout=BARRIER_TIMEOUT)
            with get_db_session() as db:
                save_generated_image(
                    db, _image_for("illustration"), owner=OWNER, prompt=PROMPT,
                    category="content", tags=["harness"],
                )
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=save) for _ in range(3)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(15)

    assert errors == []
    assert len(library.rows()) == 3


# ---------------------------------------------------------------------------
# Interface
# ---------------------------------------------------------------------------


def test_the_interface_constants():
    assert IMAGE_TOOL_NAME == "generate_image"
    assert (MAX_CALLS_PER_TURN, MAX_PER_CALL, MAX_IMAGES_PER_TURN) == (2, 3, 6)
    assert (BUDGET_SECONDS, MIN_START_SECONDS, MAX_CONCURRENT) == (240.0, 30.0, 6)
    assert KIND_TO_PRESET == {
        "illustration": "illustration",
        "background": "background",
        "icon": "icon_png",
        "vector_icon": "icon_svg",
    }
    assert all(preset in PRESETS for preset in KIND_TO_PRESET.values())
    assert FAIL_BUSY == "the image model is busy"
    assert FAIL_FORBIDDEN == "the app is not allowed to use the image model"
    assert FAIL_TIMEOUT == "did not finish in time"
    assert FAIL_OTHER == "could not be generated"


def test_the_tool_has_the_agent_tool_shape():
    tool = _tool(FakeGenerator())

    assert tool.name == IMAGE_TOOL_NAME == "generate_image"
    assert tool.description == IMAGE_TOOL_DESCRIPTION
    assert tool.args_schema is ImageGenerationArgs
    assert callable(tool.run)


def test_the_context_defaults_are_the_production_wiring():
    context = ImageToolContext(
        owner=OWNER,
        session_id=SESSION_ID,
        on_call=lambda kind, n: None,
        calls_left=2,
        images_left=6,
        seconds_left=240.0,
        deadline_at=None,
    )

    assert context.generator_factory is ImageGenerator
    assert context.save is save_to_library
    assert context.clock is time.time
    with pytest.raises(dataclasses.FrozenInstanceError):
        context.calls_left = 5  # type: ignore[misc]


def test_a_fresh_tool_has_made_nothing():
    tool = _tool(FakeGenerator())

    assert tool.generated == []
    assert tool.saved_tokens() == []
    assert (tool.calls, tool.images) == (0, 0)
    assert tool.seconds == 0


# ---------------------------------------------------------------------------
# Arguments
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "args",
    [
        {"prompt": "a fox", "kind": "icon", "count": 4},
        {"prompt": "a fox", "kind": "icon", "count": 0},
        {"prompt": "", "kind": "icon"},
        {"prompt": "x" * (MAX_PROMPT_CHARS + 1), "kind": "icon"},
        {"prompt": "a fox", "kind": "photo"},
        {"prompt": "a fox", "kind": "icon_png"},
        {"prompt": "a fox", "kind": "icon", "for_slide": 0},
        {"kind": "icon"},
        {"prompt": "a fox"},
    ],
    ids=[
        "count-4",
        "count-0",
        "empty-prompt",
        "prompt-too-long",
        "unknown-kind",
        "preset-id-is-not-a-kind",
        "for-slide-0",
        "no-prompt",
        "no-kind",
    ],
)
def test_bad_arguments_are_rejected(args):
    with pytest.raises(ValidationError):
        ImageGenerationArgs(**args)


def test_argument_defaults_and_limits():
    args = ImageGenerationArgs(prompt="a fox", kind="vector_icon")
    assert (args.count, args.for_slide) == (1, None)

    longest = ImageGenerationArgs(prompt="x" * MAX_PROMPT_CHARS, kind="icon", count=3, for_slide=1)
    assert (longest.count, longest.for_slide) == (3, 1)


def test_every_argument_is_described_for_the_model():
    properties = ImageGenerationArgs.model_json_schema()["properties"]

    assert set(properties) == {"prompt", "kind", "count", "for_slide"}
    for name, prop in properties.items():
        assert str(prop.get("description", "")).strip(), f"{name} has no description"


def test_the_description_carries_the_usage_rules():
    text = IMAGE_TOOL_DESCRIPTION.lower()

    assert "content_brief" in text
    assert "discuss" in text
    assert re.search(r"count\s*(=|:|to|of)?\s*(3|three)\b", text), "options mean count 3"
    sentences = re.split(r"[.\n]", text)
    assert any(
        "only" in s and "user" in s and "ask" in s for s in sentences
    ), "it must say to call it only when the user asks for an image"
    for kind in ("illustration", "background", "icon", "vector_icon"):
        assert kind in text, f"the {kind} kind is not explained"
    assert "{{image:" in text, "placing an image means putting its reference in content_brief"
    assert re.search(r"at most (2|two)\b|at most twice", text), "at most 2 calls"


def test_the_module_does_not_import_core_skills():
    modules = _imported_modules(MODULE_PATH)

    assert not [m for m in modules if m == "src.core.skills" or m.startswith("src.core.skills.")]


# ---------------------------------------------------------------------------
# Parallel generation and the saved rows
# ---------------------------------------------------------------------------


def test_three_options_are_generated_concurrently_and_saved_as_the_owner(library):
    """A barrier of 3 only opens when the three generations run at the same time."""
    fake = FakeGenerator(barrier=threading.Barrier(3))
    tool = _tool(fake)

    result = _run(tool, kind="background", count=3, for_slide=2)

    assert len(fake.calls) == 3
    assert all(call["thread"].startswith("chat-image-gen") for call in fake.calls), fake.calls
    assert len({call["thread"] for call in fake.calls}) == 3
    rows = library.rows()
    assert len(rows) == 3
    for row in rows:
        assert row["owner"] == OWNER
        assert row["category"] == PRESETS["background"].category == "background"
        assert row["tags"] == ["ai_generated", FAKE_MODEL, "background", "chat", "chat_option"]
        assert row["active"] is True
        assert row["description"] == PROMPT

    body = _assert_spotlighted(result)
    tokens = [row["token"] for row in rows]
    for token in tokens:
        assert result.count(token) == 1, f"{token} must appear exactly once"
    assert sorted(REF_RE.findall(body)) == sorted(tokens)
    assert not any(failure in body for failure in FAILURES)

    assert tool.generated == [
        {"token": ref["token"], "kind": "background", "option": i, "prompt": PROMPT, "for_slide": 2}
        for i, ref in enumerate(tool.generated, start=1)
    ]
    assert {ref["token"] for ref in tool.generated} == set(tokens)
    assert tool.saved_tokens() == [ref["token"] for ref in tool.generated]
    for ref in tool.generated:
        assert f"Option {ref['option']}: {_ref(ref['token'])}" in body


def test_one_image_is_not_tagged_as_a_chat_option(library):
    fake = FakeGenerator()
    tool = _tool(fake)

    result = _run(tool, kind="illustration", count=1)

    (row,) = library.rows()
    assert row["tags"] == ["ai_generated", FAKE_MODEL, "illustration", "chat"]
    assert row["owner"] == OWNER
    assert row["category"] == PRESETS["illustration"].category
    assert tool.generated == [
        {"token": row["token"], "kind": "illustration", "option": 1, "prompt": PROMPT,
         "for_slide": None}
    ]
    assert tool.saved_tokens() == [row["token"]]
    body = _assert_spotlighted(result)
    assert result.count(row["token"]) == 1
    assert f"Option 1: {_ref(row['token'])}" in body


@pytest.mark.parametrize(
    "kind, preset, mime",
    [
        ("illustration", "illustration", "image/jpeg"),
        ("background", "background", "image/jpeg"),
        ("icon", "icon_png", "image/png"),
        ("vector_icon", "icon_svg", "image/svg+xml"),
    ],
)
def test_each_kind_generates_with_its_preset(library, kind, preset, mime):
    progress: list[tuple[str, int]] = []
    fake = FakeGenerator()
    tool = _tool(fake, on_call=lambda k, n: progress.append((k, n)))

    result = _run(tool, kind=kind, count=1, for_slide=4)

    assert [call["preset_id"] for call in fake.calls] == [preset]
    (row,) = library.rows()
    assert row["category"] == PRESETS[preset].category
    assert row["tags"] == ["ai_generated", FAKE_MODEL, preset, "chat"]
    assert row["mime"] == mime
    assert tool.generated == [
        {"token": row["token"], "kind": kind, "option": 1, "prompt": PROMPT, "for_slide": 4}
    ]
    assert progress == [(kind, 1)], "the progress line names the kind the model asked for"
    assert result.count(row["token"]) == 1


def test_the_users_prompt_is_sent_and_the_preset_picks_model_and_quality(library):
    """R4: the tool uses the presets' defaults; it chooses no model or quality."""
    fake = FakeGenerator()
    tool = _tool(fake)

    _run(tool, kind="icon", count=2)

    preset = PRESETS["icon_png"]
    assert len(fake.calls) == 2
    for call in fake.calls:
        assert call["prompt"] == PROMPT
        assert call["preset_id"] == "icon_png"
        assert call["model"] in (None, preset.default_model)
        assert call["quality"] in (None, preset.default_quality)


def test_the_usage_counters(library):
    tool = _tool(FakeGenerator())

    _run(tool, kind="icon", count=3)

    assert (tool.calls, tool.images) == (1, 3)
    assert isinstance(tool.seconds, float) and tool.seconds >= 0


def test_save_to_library_stores_the_image_and_returns_its_token(library):
    token = save_to_library(
        _image_for("background"),
        owner=OWNER,
        prompt=PROMPT,
        category="background",
        tags=["ai_generated", FAKE_MODEL, "background", "chat"],
    )

    (row,) = library.rows()
    assert isinstance(token, str) and token == row["token"]
    assert row["owner"] == OWNER
    assert row["category"] == "background"
    assert row["tags"] == ["ai_generated", FAKE_MODEL, "background", "chat"]
    assert row["mime"] == "image/jpeg"


# ---------------------------------------------------------------------------
# Caps: images, calls, time
# ---------------------------------------------------------------------------


def test_images_left_caps_how_many_are_generated(library):
    progress: list[tuple[str, int]] = []
    fake = FakeGenerator()
    tool = _tool(fake, images_left=2, on_call=lambda k, n: progress.append((k, n)))

    result = _run(tool, kind="illustration", count=3)

    assert len(fake.calls) == 2
    rows = library.rows()
    assert len(rows) == 2
    assert all(row["tags"][-1] == "chat_option" for row in rows)
    assert progress == [("illustration", 2)]
    assert [ref["option"] for ref in tool.generated] == [1, 2]
    assert sorted(REF_RE.findall(result)) == sorted(row["token"] for row in rows)


def test_images_left_counts_across_the_calls_of_one_tool(library):
    fake = FakeGenerator()
    tool = _tool(fake, images_left=4, calls_left=2)

    _run(tool, kind="icon", count=3)
    second = _run(tool, kind="icon", count=3)

    assert len(fake.calls) == 4
    assert len(library.rows()) == 4
    assert len(REF_RE.findall(second)) == 1
    assert (tool.calls, tool.images) == (2, 4)
    assert len(tool.generated) == 4
    assert tool.saved_tokens() == [ref["token"] for ref in tool.generated]
    assert set(tool.saved_tokens()) == library.tokens()


def test_no_images_left_is_refused(library):
    fake = FakeGenerator()
    progress: list = []
    tool = _tool(fake, images_left=0, on_call=lambda k, n: progress.append((k, n)))

    result = _run(tool, kind="icon", count=1)

    _assert_refused(result, fake, tool)
    assert progress == []
    assert library.rows() == []


def test_a_call_beyond_calls_left_is_refused(library):
    progress: list = []
    fake = FakeGenerator()
    tool = _tool(fake, calls_left=1, on_call=lambda k, n: progress.append((k, n)))

    first = _run(tool, kind="icon", count=1)
    assert len(fake.calls) == 1
    assert len(REF_RE.findall(first)) == 1

    second = _run(tool, kind="icon", count=1)

    body = _assert_spotlighted(second)
    assert REF_RE.search(body) is None
    assert len(fake.calls) == 1, "the refused call made no generation"
    assert len(library.rows()) == 1
    assert progress == [("icon", 1)], "no progress line for a refused call"
    assert len(tool.generated) == 1


def test_no_calls_left_refuses_the_first_call(library):
    fake = FakeGenerator()
    tool = _tool(fake, calls_left=0)

    _assert_refused(_run(tool, kind="icon", count=3), fake, tool)
    assert library.rows() == []


@pytest.mark.parametrize(
    "overrides, remaining",
    [
        ({"deadline_at": NOW - 1.0, "clock": lambda: NOW}, REMAINING),
        ({"deadline_at": NOW + MIN_START_SECONDS - 1.0, "clock": lambda: NOW}, REMAINING),
        ({}, MIN_START_SECONDS - 0.1),
        ({"seconds_left": MIN_START_SECONDS - 1.0}, REMAINING),
        ({"seconds_left": 0.0}, REMAINING),
    ],
    ids=[
        "deadline-passed",
        "deadline-within-min-start",
        "remaining-below-min-start",
        "seconds-left-below-min-start",
        "seconds-left-spent",
    ],
)
def test_too_little_time_starts_nothing(library, overrides, remaining):
    progress: list = []
    fake = FakeGenerator()
    tool = _tool(fake, on_call=lambda k, n: progress.append((k, n)), **overrides)

    result = _run(tool, kind="illustration", count=3, remaining=remaining)

    _assert_refused(result, fake, tool)
    assert progress == []
    assert library.rows() == []


def test_a_past_deadline_on_the_real_clock_starts_nothing(library):
    fake = FakeGenerator()
    tool = _tool(fake, deadline_at=time.time() - 5.0)

    _assert_refused(_run(tool, kind="icon", count=1), fake, tool)


def test_just_enough_time_starts(library):
    """The positive control for the refusals: every limit just above MIN_START_SECONDS."""
    fake = FakeGenerator()
    tool = _tool(
        fake,
        deadline_at=NOW + MIN_START_SECONDS + 5.0,
        clock=lambda: NOW,
        seconds_left=MIN_START_SECONDS + 5.0,
    )

    result = _run(tool, kind="icon", count=1, remaining=MIN_START_SECONDS + 5.0)

    assert len(fake.calls) == 1
    assert len(REF_RE.findall(result)) == 1
    assert len(library.rows()) == 1


@pytest.mark.parametrize(
    "overrides, remaining, wall",
    [
        ({}, 45.0, 45.0),
        ({"seconds_left": 50.0}, REMAINING, 50.0),
        ({"deadline_at": NOW + 40.0, "clock": lambda: NOW}, REMAINING, 40.0),
    ],
    ids=["remaining-binds", "seconds-left-binds", "deadline-binds"],
)
def test_each_generation_gets_a_timeout_within_the_wall(library, overrides, remaining, wall):
    fake = FakeGenerator()
    tool = _tool(fake, **overrides)

    _run(tool, kind="illustration", count=2, remaining=remaining)

    assert len(fake.calls) == 2
    for call in fake.calls:
        assert call["timeout_s"] is not None, "the wall must reach generate(timeout_s=...)"
        assert 0 < call["timeout_s"] <= wall + 1e-6, call


# ---------------------------------------------------------------------------
# Stragglers
# ---------------------------------------------------------------------------


def test_a_straggler_is_abandoned_at_the_wall_and_never_saved(library, monkeypatch):
    monkeypatch.setattr(tool_module, "MIN_START_SECONDS", 0.1)
    wall = 1.0
    fake = FakeGenerator(["ok", "block"])
    tool = _tool(fake, seconds_left=wall)

    try:
        started = time.monotonic()
        result = _run(tool, kind="illustration", count=2)
        elapsed = time.monotonic() - started

        assert len(fake.calls) == 2, (
            "both generations start (run must read MIN_START_SECONDS from the module at "
            "call time)"
        )
        assert elapsed < wall + 1.0, f"run took {elapsed:.2f}s with a {wall}s wall"
        assert elapsed >= wall * 0.8, "run waits for the wall before giving up on a job"
        body = _assert_spotlighted(result)
        assert FAIL_TIMEOUT in body
        assert body.count(FAIL_TIMEOUT) == 1
        (row,) = library.rows()
        assert REF_RE.findall(body) == [row["token"]]
        assert tool.saved_tokens() == [row["token"]]
        assert len(tool.generated) == 1
    finally:
        fake.release.set()

    assert fake.block_returned.wait(5), "the straggler's generate returned"
    time.sleep(0.5)  # the straggler's job has long passed the point where it would save
    assert len(library.rows()) == 1, "an abandoned straggler must never save"
    assert len(tool.generated) == 1
    assert len(tool.saved_tokens()) == 1


# ---------------------------------------------------------------------------
# Failures: fixed text, never the exception's
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "error, expected",
    [
        (ImageGenerationError(SECRET, status_code=429), FAIL_BUSY),
        (ImageGenerationError(SECRET, status_code=403), FAIL_FORBIDDEN),
        (ImageGenerationError(SECRET, status_code=500), FAIL_OTHER),
        (ImageGenerationError(SECRET, status_code=401), FAIL_OTHER),
        (ImageGenerationError(SECRET), FAIL_OTHER),
        (RuntimeError(SECRET), FAIL_OTHER),
        (ValueError(SECRET), FAIL_OTHER),
    ],
    ids=["429", "403", "500", "401", "no-status", "runtime-error", "value-error"],
)
def test_a_failure_is_fixed_text_never_the_exception(library, error, expected):
    fake = FakeGenerator([error])
    tool = _tool(fake)

    result = _run(tool, kind="icon", count=1)

    body = _assert_spotlighted(result)
    assert SECRET not in result
    assert expected in body
    assert [f for f in FAILURES if f in body] == [expected]
    assert REF_RE.search(body) is None
    assert tool.generated == []
    assert tool.saved_tokens() == []
    assert library.rows() == []


def test_one_failed_option_keeps_the_others(library):
    fake = FakeGenerator(["ok", ImageGenerationError(SECRET, status_code=429), "ok"])
    tool = _tool(fake)

    result = _run(tool, kind="illustration", count=3)

    body = _assert_spotlighted(result)
    assert SECRET not in result
    assert body.count(FAIL_BUSY) == 1
    rows = library.rows()
    assert len(rows) == 2
    assert sorted(REF_RE.findall(body)) == sorted(row["token"] for row in rows)
    options = [ref["option"] for ref in tool.generated]
    assert len(options) == 2
    assert options == sorted(options) and len(set(options)) == 2
    assert set(options) <= {1, 2, 3}
    for ref in tool.generated:
        assert f"Option {ref['option']}: {_ref(ref['token'])}" in body
    assert tool.saved_tokens() == [ref["token"] for ref in tool.generated]


def test_a_failed_save_is_fixed_text_never_the_exception(library):
    def broken_save(img: Any, **kwargs: Any) -> str:
        raise RuntimeError(SECRET)

    fake = FakeGenerator()
    tool = _tool(fake, save=broken_save)

    result = _run(tool, kind="icon", count=1)

    body = _assert_spotlighted(result)
    assert SECRET not in result
    assert FAIL_OTHER in body
    assert tool.generated == []
    assert tool.saved_tokens() == []


def test_a_custom_save_gets_the_owner_prompt_category_and_tags(library):
    """``save=`` is called as ``save(img, owner=, prompt=, category=, tags=)``."""
    saved: list[dict[str, Any]] = []

    def save(img: GeneratedImage, **kwargs: Any) -> str:
        saved.append(kwargs)
        with get_db_session() as db:
            return save_generated_image(db, img, **kwargs).token

    tool = _tool(FakeGenerator(), save=save)

    result = _run(tool, kind="vector_icon", count=2)

    assert sorted(saved, key=repr) == [
        {
            "owner": OWNER,
            "prompt": PROMPT,
            "category": PRESETS["icon_svg"].category,
            "tags": ["ai_generated", FAKE_MODEL, "icon_svg", "chat", "chat_option"],
        }
    ] * 2
    assert sorted(REF_RE.findall(result)) == sorted(library.tokens())


# ---------------------------------------------------------------------------
# Through the runtime loop's own dispatcher
# ---------------------------------------------------------------------------


def _answer(tool: ImageGenerationAgentTool, args: dict[str, Any]) -> str:
    toolset = AgentToolset(tools=(tool,), max_calls=MAX_CALLS_PER_TURN, budget_seconds=240.0)
    return DatabricksModelAdapter._answer_tool_call(
        {"name": IMAGE_TOOL_NAME, "args": dict(args), "id": "c1", "type": "tool_call"},
        {tool.name: tool},
        toolset,
        budget_text="Tool budget exhausted.",
    )


def test_the_loop_runs_the_tool_from_the_models_arguments(library):
    fake = FakeGenerator()
    tool = _tool(fake)

    answer = _answer(tool, {"prompt": PROMPT, "kind": "icon", "count": 2, "for_slide": 3})

    _assert_spotlighted(answer)
    assert len(fake.calls) == 2
    assert sorted(REF_RE.findall(answer)) == sorted(library.tokens())
    assert [ref["for_slide"] for ref in tool.generated] == [3, 3]


def test_the_loop_rejects_four_images_without_generating(library):
    fake = FakeGenerator()
    tool = _tool(fake)

    answer = _answer(tool, {"prompt": PROMPT, "kind": "icon", "count": 4})

    assert answer.startswith("Tool error")
    assert fake.calls == []
    assert library.rows() == []


def test_the_loop_never_sees_the_exception_text(library):
    tool = _tool(FakeGenerator([ImageGenerationError(SECRET, status_code=429)]))

    answer = _answer(tool, {"prompt": PROMPT, "kind": "icon"})

    assert SECRET not in answer
    assert FAIL_BUSY in answer
    assert not answer.startswith("Tool error"), "a failed generation is not a tool crash"


# ---------------------------------------------------------------------------
# The process-wide semaphore (MAX_CONCURRENT slots, taken without blocking)
# ---------------------------------------------------------------------------


def test_no_free_slot_is_refused_as_busy_without_generating(library):
    """Two other runs hold all six slots: a third run is refused at once."""
    holder = FakeGenerator(["block"] * 6)
    background = [
        _in_background(_tool(holder), kind="icon", count=3),
        _in_background(_tool(holder), kind="icon", count=3),
    ]
    try:
        assert holder.wait_started(6), "the two holding runs started their six generations"
        progress: list = []
        fake = FakeGenerator()
        tool = _tool(fake, on_call=lambda k, n: progress.append((k, n)))

        started = time.monotonic()
        result = _run(tool, kind="illustration", count=1)

        assert time.monotonic() - started < 2.0, "the slot is taken without blocking"
        body = _assert_refused(result, fake, tool)
        assert "busy" in body.lower()
        assert progress == []
    finally:
        holder.release.set()
        for thread, _ in background:
            thread.join(15)

    for _, box in background:
        assert "error" not in box, box.get("error")
        assert len(REF_RE.findall(box["result"])) == 3
    assert len(library.rows()) == 6

    # The slots are given back once the runs finish (a moment's grace for a slot that is
    # released by a done-callback, which can run just after ``wait`` returns).
    time.sleep(0.2)
    after = FakeGenerator()
    result = _run(_tool(after), kind="icon", count=3)
    assert len(after.calls) == 3
    assert len(REF_RE.findall(result)) == 3


def test_free_slots_clamp_the_count(library):
    """Four of six slots are held: a run asking for three makes two."""
    holder = FakeGenerator(["block"] * 4)
    background = [
        _in_background(_tool(holder), kind="icon", count=3),
        _in_background(_tool(holder), kind="icon", count=1),
    ]
    try:
        assert holder.wait_started(4), "the holding runs started their four generations"
        progress: list = []
        fake = FakeGenerator()
        tool = _tool(fake, on_call=lambda k, n: progress.append((k, n)))

        result = _run(tool, kind="background", count=3)

        assert len(fake.calls) == 2
        assert progress == [("background", 2)]
        assert len(REF_RE.findall(result)) == 2
    finally:
        holder.release.set()
        for thread, _ in background:
            thread.join(15)

    for _, box in background:
        assert "error" not in box, box.get("error")


# ---------------------------------------------------------------------------
# The progress callback
# ---------------------------------------------------------------------------


def test_on_call_runs_once_before_generating_with_the_clamped_count(library):
    log: list[Any] = []
    fake = FakeGenerator()
    fake.log = log
    tool = _tool(
        fake, images_left=2, on_call=lambda kind, n: log.append(("on_call", kind, n))
    )

    _run(tool, kind="vector_icon", count=3)

    assert log[0] == ("on_call", "vector_icon", 2)
    assert [entry for entry in log if entry != "generate"] == [("on_call", "vector_icon", 2)]
    assert log[1:] == ["generate", "generate"]


def test_an_on_call_error_is_swallowed(library):
    def broken(kind: str, n: int) -> None:
        raise RuntimeError("the progress line failed")

    fake = FakeGenerator()
    tool = _tool(fake, on_call=broken)

    result = _run(tool, kind="icon", count=1)

    assert len(fake.calls) == 1
    (row,) = library.rows()
    assert REF_RE.findall(result) == [row["token"]]
    assert tool.saved_tokens() == [row["token"]]
