"""A streamed image call has a wall-clock deadline, and its stream is always closed.

httpx's ``timeout`` caps each read, not the whole call: a stream that keeps sending events
never ends, holding a Library job's in-flight entry or a chat generation slot (and its
worker thread) until the process restarts. So the stream reader stops at the call's own
deadline (its start plus the effective timeout) and closes the stream however it ends.
"""

from __future__ import annotations

import base64
import io
from types import SimpleNamespace
from typing import Any

import pytest
from PIL import Image

from src.services import image_generation as ig
from src.services.image_generation import ImageGenerationError, ImageGenerator


def _png_b64() -> str:
    buf = io.BytesIO()
    Image.new("RGB", (8, 8), (10, 20, 30)).save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()


class _Stream:
    """An event stream: *events* first, then ``response.in_progress`` forever if *endless*."""

    def __init__(self, events: list[Any], *, endless: bool = False) -> None:
        self._events = list(events)
        self._endless = endless
        self.closed = False
        self.yielded = 0

    def __iter__(self):
        while self._events or self._endless:
            self.yielded += 1
            if self._events:
                yield self._events.pop(0)
            else:
                yield SimpleNamespace(type="response.in_progress")
            if self.yielded > 10_000:
                raise AssertionError("the reader never stopped")

    def close(self) -> None:
        self.closed = True


def _done(b64: str) -> list[Any]:
    item = SimpleNamespace(type="image_generation_call", result=b64, revised_prompt=None)
    return [
        SimpleNamespace(type="response.output_item.done", item=item),
        SimpleNamespace(type="response.completed", response=SimpleNamespace(usage=None)),
    ]


def test_the_reader_stops_at_its_deadline():
    stream = _Stream([], endless=True)
    clock = iter([0.0, 1.0, 2.0, 50.0, 100.0] + [200.0] * 100)

    with pytest.raises(ImageGenerationError) as raised:
        ImageGenerator._read_stream(stream, deadline=10.0, clock=lambda: next(clock))

    assert "too long" in str(raised.value)
    assert stream.yielded <= 4
    assert stream.closed


def test_the_reader_closes_a_stream_that_completes():
    stream = _Stream(_done(_png_b64()))

    b64, _revised, _usage = ImageGenerator._read_stream(stream, deadline=None)

    assert b64
    assert stream.closed


def test_the_reader_closes_a_stream_that_fails():
    failed = SimpleNamespace(
        type="response.failed",
        response=SimpleNamespace(error=SimpleNamespace(message="nope")),
    )
    stream = _Stream([failed])

    with pytest.raises(ImageGenerationError):
        ImageGenerator._read_stream(stream, deadline=None)

    assert stream.closed


def test_generate_hands_the_reader_its_start_plus_the_effective_timeout(monkeypatch):
    """An endless stream through ``generate``: it fails with the deadline error once the
    clock passes start + the effective timeout (30 s here), and the stream is closed."""
    stream = _Stream([], endless=True)
    client = SimpleNamespace(responses=SimpleNamespace(create=lambda **kwargs: stream))
    ticks = {"now": 1000.0}

    def clock() -> float:
        ticks["now"] += 7.0  # every read of the clock moves 7 s on
        return ticks["now"]

    monkeypatch.setattr(ig.time, "monotonic", clock)

    with pytest.raises(ImageGenerationError) as raised:
        ImageGenerator(client_factory=lambda: client).generate(
            "a shield", "icon_png", timeout_s=30.0
        )

    assert "too long" in str(raised.value)
    assert 3 <= stream.yielded <= 6, stream.yielded
    assert stream.closed
