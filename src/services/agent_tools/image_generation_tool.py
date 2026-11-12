"""The architect's ``generate_image`` tool: make 1-3 images and save them to the Image Library.

``ImageGenerationAgentTool`` satisfies ``AgentTool``.  One ``run`` generates its images in
parallel on a module-level pool, saves each as the turn's user, and returns spotlighted
facts (a ``{{image:TOKEN}}`` reference per image, fixed text per failure).

Code, not the prompt, enforces the limits: the calls and images left this turn, a
process-wide semaphore of ``MAX_CONCURRENT`` slots taken without blocking, and a wall clock
under which no call starts when it is below ``MIN_START_SECONDS``.

Two races are closed explicitly:

* R6 (abandon race): a job claims its save under a per-run lock after ``generate`` returns;
  a job abandoned at the wall never saves, and a job that has claimed is waited for (briefly)
  so a saved row is never reported as a timeout.
* R7 (straggler slots): a job holds its semaphore slot until it really finishes (released in
  the job's ``finally``), so real concurrency never exceeds ``MAX_CONCURRENT``.

This module must not import ``src.core.skills`` and builds no model client itself: the
generator comes from ``ImageToolContext.generator_factory`` (``ImageGenerator`` by default).
Failure text is the fixed ``FAIL_*`` constants, never an exception's own text.
"""

from __future__ import annotations

import contextvars
import io
import logging
import threading
import time
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor, wait
from dataclasses import dataclass, field
from typing import Any, Final, Literal

from PIL import Image
from pydantic import BaseModel, ConfigDict, Field

from src.core.database import get_db_session
from src.services.generation_fence import TurnFencedError, fence_turn_write
from src.services.image_generation import (
    MAX_PROMPT_CHARS,
    PRESETS,
    GeneratedImage,
    ImageGenerationError,
    ImageGenerator,
    save_generated_image,
)
from src.utils.spotlight import spotlight

logger = logging.getLogger(__name__)

IMAGE_TOOL_NAME: Final = "generate_image"
MAX_CALLS_PER_TURN: Final = 2
MAX_PER_CALL: Final = 3
MAX_IMAGES_PER_TURN: Final = 6
BUDGET_SECONDS: Final = 240.0
MIN_START_SECONDS: Final = 30.0
MAX_CONCURRENT: Final = 6
#: How long ``run`` waits for a job that has already claimed its save to finish saving.
SAVE_GRACE_SECONDS: Final = 10.0

KIND_TO_PRESET: Final = {
    "illustration": "illustration",
    "background": "background",
    "icon": "icon_png",
    "vector_icon": "icon_svg",
}

FAIL_BUSY: Final = "the image model is busy"
FAIL_FORBIDDEN: Final = "the app is not allowed to use the image model"
FAIL_TIMEOUT: Final = "did not finish in time"
FAIL_OTHER: Final = "could not be generated"

_REFUSE_NO_USER: Final = (
    "Image generation is not available: there is no signed-in user to save images for."
)
_REFUSE_CALLS: Final = (
    "No more image generation calls are allowed in this turn. Nothing was generated."
)
_REFUSE_IMAGES: Final = "No more images may be generated in this turn. Nothing was generated."
_REFUSE_TIME: Final = (
    "There is not enough time left in this turn to generate images. Nothing was generated."
)
_REFUSE_BUSY: Final = (
    "The image model is busy right now: no generation slot is free. Nothing was generated."
)

IMAGE_TOOL_DESCRIPTION: Final = (
    "Generate pictures for the deck with the image model and save them to the user's "
    "Image Library. Each image comes back as a {{image:TOKEN}} reference.\n"
    "Call this tool only when the user explicitly asks for a picture, illustration, icon, "
    "visual or background. Never call it for a plain deck build.\n"
    "Open-ended asks are the default: the user wants a picture but has not said exactly what "
    "it shows, for example \"make me a picture to get this message across\", \"an image for "
    "slide 3\" or \"some icon options\". Treat an ask as open-ended even when it says \"a "
    "picture\": call it with count=3, set the intent to discuss, place nothing on a slide, "
    "and ask the user to pick an option.\n"
    "Exact asks only: the user says what the image shows AND that it goes on a slide, for "
    "example \"add a shield icon to slide 2\" or \"add a calm blue background to slide 1\". "
    "Call it with count=1 and place the image in the same answer.\n"
    "Placing an image: put its exact {{image:TOKEN}} reference in that slide's "
    "content_brief, with where it goes and how big. Never write a reference in message.\n"
    "Prompt: describe the subject and match the palette and style from resolved_style / "
    "deck_style; ask for no text in the image.\n"
    "Kinds: illustration (a content picture), background (a full-slide backdrop), icon "
    "(a small raster icon with a transparent background), vector_icon (a small SVG icon).\n"
    "Call this tool at most 2 times in a turn."
)


class ImageGenerationArgs(BaseModel):
    # A prompt of whitespace would be a paid call with no subject.
    model_config = ConfigDict(str_strip_whitespace=True)

    prompt: str = Field(
        min_length=1,
        max_length=MAX_PROMPT_CHARS,
        description="What to draw: the subject, style and palette. Ask for no text in the image.",
    )
    kind: Literal["illustration", "background", "icon", "vector_icon"] = Field(
        description="illustration, background, icon (raster) or vector_icon (SVG).",
    )
    count: int = Field(
        1,
        ge=1,
        le=MAX_PER_CALL,
        description="How many options to make, 1 to 3: 3 for open-ended asks, 1 for an exact ask.",
    )
    for_slide: int | None = Field(
        None,
        ge=1,
        description="The 1-based slide number the image is for, if the user named one.",
    )


def save_to_library(
    img: GeneratedImage, *, owner: str, prompt: str, category: str, tags: list[str]
) -> str:
    """Store a generated image in the Image Library as *owner*; return its token.

    Refused (``TurnFencedError``) when the turn it runs for was stopped.
    """
    with get_db_session() as db:
        fence_turn_write(db)
        asset = save_generated_image(
            db, img, owner=owner, prompt=prompt, category=category, tags=tags
        )
        return asset.token


@dataclass(frozen=True)
class ImageToolContext:
    owner: str | None
    session_id: str | None
    on_call: Callable[[str, int], None]
    calls_left: int
    images_left: int
    seconds_left: float
    deadline_at: float | None
    generator_factory: Callable[[], Any] = ImageGenerator
    save: Callable[..., str] = save_to_library
    clock: Callable[[], float] = time.time
    #: The number of this tool's first option; the graph node sets it so options are numbered
    #: per turn, across the turn's calls.
    first_option: int = 1


#: Process-wide: one slot per generation in flight (including abandoned stragglers, R7).
_SLOTS = threading.BoundedSemaphore(MAX_CONCURRENT)
_POOL = ThreadPoolExecutor(max_workers=MAX_CONCURRENT, thread_name_prefix="chat-image-gen")


def _take_slots(want: int) -> int:
    """Take up to *want* slots without blocking; return how many were taken."""
    taken = 0
    for _ in range(want):
        if not _SLOTS.acquire(blocking=False):
            break
        taken += 1
    return taken


@dataclass
class _Job:
    option: int
    abandoned: bool = False
    claimed: bool = False
    future: Future | None = field(default=None, repr=False)


def _failure_text(exc: BaseException) -> str:
    status = exc.status_code if isinstance(exc, ImageGenerationError) else None
    if status == 429:
        return FAIL_BUSY
    if status == 403:
        return FAIL_FORBIDDEN
    return FAIL_OTHER


def _describe(img: GeneratedImage) -> str:
    try:
        if img.mime != "image/svg+xml":
            with Image.open(io.BytesIO(img.data)) as opened:
                return f"{img.mime}, {opened.width}x{opened.height}"
    except Exception:  # noqa: BLE001 - the size is a nicety
        pass
    return img.mime


class ImageGenerationAgentTool:
    name = IMAGE_TOOL_NAME
    description = IMAGE_TOOL_DESCRIPTION
    args_schema = ImageGenerationArgs

    def __init__(self, context: ImageToolContext) -> None:
        self._context = context
        self.generated: list[dict] = []
        self.calls = 0
        self.images = 0
        self.seconds = 0.0

    def saved_tokens(self) -> list[str]:
        return [ref["token"] for ref in self.generated]

    # -- run ------------------------------------------------------------

    def _reply(self, text: str) -> str:
        return spotlight("image_generation", text, session_id=self._context.session_id)

    def run(self, args: ImageGenerationArgs, *, remaining_seconds: float) -> str:  # type: ignore[override]
        ctx = self._context
        if not ctx.owner:
            return self._reply(_REFUSE_NO_USER)
        if self.calls >= ctx.calls_left:
            return self._reply(_REFUSE_CALLS)
        room = ctx.images_left - self.images
        if room <= 0:
            return self._reply(_REFUSE_IMAGES)
        # seconds_left is this tool's budget for ALL its calls: on a toolset whose own clock
        # runs longer (beside Gateway tools), remaining_seconds alone would hand a second
        # call the whole budget again.
        wall = min(remaining_seconds, ctx.seconds_left - self.seconds)
        if ctx.deadline_at is not None:
            wall = min(wall, ctx.deadline_at - ctx.clock())
        if wall < MIN_START_SECONDS:
            return self._reply(_REFUSE_TIME)
        n = _take_slots(min(args.count, MAX_PER_CALL, room))
        if n == 0:
            return self._reply(_REFUSE_BUSY)

        started = time.monotonic()
        first_option = ctx.first_option + self.images
        self.calls += 1
        self.images += n
        try:
            return self._generate(args, n, wall, first_option)
        finally:
            self.seconds += time.monotonic() - started

    def _generate(self, args: ImageGenerationArgs, n: int, wall: float, first_option: int) -> str:
        ctx = self._context
        preset_id = KIND_TO_PRESET[args.kind]
        category = PRESETS[preset_id].category
        lock = threading.Lock()
        jobs = [_Job(option=first_option + i) for i in range(n)]
        submit_errors: dict[int, str] = {}

        try:
            ctx.on_call(args.kind, n)
        except TurnFencedError:
            # The turn was stopped before any job started: give back the n slots
            # ``run`` took (process-wide), and generate nothing.
            for _ in range(n):
                _SLOTS.release()
            raise
        except Exception:  # noqa: BLE001 - the progress line must never break a generation
            logger.debug("image tool on_call failed", exc_info=True)

        def job_body(job: _Job) -> tuple[str, GeneratedImage] | None:
            try:
                img = ctx.generator_factory().generate(args.prompt, preset_id, timeout_s=wall)
                with lock:
                    if job.abandoned:
                        return None
                    job.claimed = True
                tags = ["ai_generated", img.model, preset_id, "chat"]
                if n > 1:
                    tags.append("chat_option")
                token = ctx.save(
                    img, owner=ctx.owner, prompt=args.prompt, category=category, tags=tags
                )
                return token, img
            finally:
                _SLOTS.release()

        for index, job in enumerate(jobs):
            try:
                # A pool thread starts with an empty context: each job runs in a
                # copy of this one, so the save is fenced on the turn's request id.
                job.future = _POOL.submit(contextvars.copy_context().run, job_body, job)
            except Exception:  # noqa: BLE001 - the pool is gone: give the slot back
                _SLOTS.release()
                submit_errors[index] = FAIL_OTHER

        futures = [job.future for job in jobs if job.future is not None]
        wait(futures, timeout=max(wall, 0.0))
        with lock:  # R6: whatever has not finished and has not claimed its save is abandoned
            for job in jobs:
                if job.future is not None and not job.future.done() and not job.claimed:
                    job.abandoned = True
            claimed = [
                j.future
                for j in jobs
                if j.future is not None and j.claimed and not j.future.done()
            ]
        if claimed:
            wait(claimed, timeout=SAVE_GRACE_SECONDS)

        # A refused save means the turn was stopped: the refusal ends the tool loop
        # (nothing is recorded or reported), rather than becoming "not generated".
        for job in jobs:
            if job.future is not None and job.future.done():
                refused = job.future.exception()
                if isinstance(refused, TurnFencedError):
                    raise refused

        lines: list[str] = []
        made = 0
        for index, job in enumerate(jobs):
            future = job.future
            if future is None:
                lines.append(f"Option {job.option}: not generated ({submit_errors[index]}).")
                continue
            if not future.done():
                lines.append(f"Option {job.option}: not generated ({FAIL_TIMEOUT}).")
                continue
            exc = future.exception()
            if exc is not None:
                logger.warning(
                    "image generation failed",
                    extra={"kind": args.kind, "error_type": type(exc).__name__},
                )
                lines.append(f"Option {job.option}: not generated ({_failure_text(exc)}).")
                continue
            outcome = future.result()
            if outcome is None:
                lines.append(f"Option {job.option}: not generated ({FAIL_TIMEOUT}).")
                continue
            token, img = outcome
            made += 1
            self.generated.append(
                {
                    "token": token,
                    "kind": args.kind,
                    "option": job.option,
                    "prompt": args.prompt,
                    "for_slide": args.for_slide,
                }
            )
            lines.append(f"Option {job.option}: {{{{image:{token}}}}} ({_describe(img)})")

        if made:
            head = f"Generated {made} of {n} {args.kind} images, saved to the user's Image Library:"
            tail = "Nothing is on a slide yet. The user sees these images under your reply."
        else:
            head = f"No {args.kind} images were produced:"
            tail = "Nothing was saved and nothing is on a slide."
        return self._reply("\n".join([head, *lines, tail]))
