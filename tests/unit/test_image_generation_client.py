"""``ImageGenerator`` against the REAL ``DatabricksOpenAI`` Gateway client.

Only the HTTP transport is replaced (``install_mock_gateway_transport``): the
production chain ``gateway_openai_client`` -> ``DatabricksOpenAI`` -> OpenAI SDK
request building, retries, SSE parsing and error mapping all run unmodified
(corrections C3, C5, C11 in
``docs/superpowers/plans/2026-11-08-ai-image-generation-CORRECTIONS.md``).

``MockResponsesWorkspace`` answers the Responses API the way the Gateway did in
the Task 0 probe: a streamed request (``"stream": true``) gets an SSE body whose
``response.output_item.done`` event carries the ``image_generation_call`` item
(base64 ``result``) and whose ``response.completed`` event carries the usage; a
non-streamed request (SVG) gets one JSON ``Response``.

The module under test is imported per test (the ``ig`` fixture) so the fixture
self-tests below run, and pass, before ``src/services/image_generation.py``
exists: they prove the mock is something the real OpenAI SDK parses.
"""

from __future__ import annotations

import base64
import importlib
import io
import json
from typing import Any

import httpx
import openai
import pytest
from PIL import Image

from src.services.gateway_clients import gateway_openai_client
from tests.fixtures.mock_chat_completions import (
    MockChatCompletionsWorkspace,
    install_mock_gateway_transport,
)

GATEWAY_RESPONSES_PATH = "/ai-gateway/mlflow/v1/responses"
TAG_HEADER = "databricks-ai-gateway-request-tags"
ORCHESTRATOR_ENV = "TELLR_IMAGE_GEN_ORCHESTRATOR_MODEL"
DEFAULT_ORCHESTRATOR = "system.ai.gpt-5-4-nano"
FORCED_TOOL_CHOICE = {"type": "image_generation"}
REVISED_PROMPT = "A flat lighthouse icon, centered, generous padding."

#: The usage shape the Gateway reported in the Task 0 probe (every field set).
USAGE: dict[str, Any] = {
    "input_tokens": 2303,
    "input_tokens_details": {"cache_write_tokens": 0, "cached_tokens": 0},
    "output_tokens": 88,
    "output_tokens_details": {"reasoning_tokens": 0},
    "total_tokens": 2391,
}

SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" width="64" height="64">'
    '<circle cx="32" cy="32" r="20" fill="#1b3139"/></svg>'
)

#: The extension the module uses for each library mime (repo convention:
#: ``src/services/agent_tools/gateway_tool.py`` ``_EXTENSIONS``).
EXT_FOR_MIME = {"image/png": "png", "image/jpeg": "jpg", "image/svg+xml": "svg"}


# ---------------------------------------------------------------------------
# Images
# ---------------------------------------------------------------------------


def _rgba_png(size: tuple[int, int] = (48, 32)) -> bytes:
    """An RGBA PNG whose left half is fully transparent and right half opaque."""
    w, h = size
    img = Image.new("RGBA", size, (0, 0, 0, 0))
    img.paste(Image.new("RGBA", (w - w // 2, h), (220, 40, 40, 255)), (w // 2, 0))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _opaque_rgba_png(size: tuple[int, int] = (48, 32)) -> bytes:
    """An RGBA PNG in which every pixel is fully opaque (screenshots, design-tool exports)."""
    img = Image.new("RGBA", size, (30, 90, 200, 255))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _rgb_png(size: tuple[int, int] = (48, 32)) -> bytes:
    img = Image.new("RGB", size, (30, 90, 200))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _jpeg(size: tuple[int, int] = (64, 36)) -> bytes:
    img = Image.new("RGB", size, (200, 180, 40))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=90)
    return buf.getvalue()


def _webp_rgba(size: tuple[int, int] = (40, 40)) -> bytes:
    w, h = size
    img = Image.new("RGBA", size, (0, 0, 0, 0))
    img.paste(Image.new("RGBA", (w - w // 2, h), (10, 200, 90, 255)), (w // 2, 0))
    buf = io.BytesIO()
    img.save(buf, format="WEBP", lossless=True)
    return buf.getvalue()


def _decode(data: bytes) -> Image.Image:
    img = Image.open(io.BytesIO(data))
    img.load()
    return img


def _alpha_min(img: Image.Image) -> int:
    assert "A" in img.getbands(), f"no alpha channel in mode {img.mode}"
    return img.getchannel("A").getextrema()[0]


def _decode_data_url(url: str) -> tuple[str, Image.Image]:
    header, b64 = url.split(",", 1)
    assert header.startswith("data:") and header.endswith(";base64"), header
    return header[len("data:") : -len(";base64")], _decode(base64.b64decode(b64))


# ---------------------------------------------------------------------------
# The mock Gateway
# ---------------------------------------------------------------------------


def _image_item(result_b64: str | None) -> dict[str, Any]:
    return {
        "id": "ig_mock",
        "type": "image_generation_call",
        "status": "completed",
        "result": result_b64,
        "revised_prompt": REVISED_PROMPT,
    }


_MESSAGE_ITEM: dict[str, Any] = {
    "id": "msg_mock",
    "type": "message",
    "role": "assistant",
    "status": "completed",
    "content": [{"type": "output_text", "text": "Here is your image.", "annotations": []}],
}


def _response(
    body: dict[str, Any],
    output: list[dict[str, Any]],
    *,
    status: str = "completed",
    usage: dict[str, Any] | None = None,
    error: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "id": "resp_mock",
        "object": "response",
        "created_at": 0,
        "model": body.get("model", "mock"),
        "status": status,
        "error": error,
        "output": output,
        "parallel_tool_calls": True,
        "tool_choice": body.get("tool_choice", "auto"),
        "tools": body.get("tools", []),
        "usage": usage,
    }


def _sse(events: list[dict[str, Any]]) -> bytes:
    frames = []
    for seq, event in enumerate(events):
        event = {**event, "sequence_number": seq}
        frames.append(f"event: {event['type']}\ndata: {json.dumps(event)}\n\n")
    return "".join(frames).encode()


class MockResponsesWorkspace(MockChatCompletionsWorkspace):
    """A mock workspace whose transport answers ``POST .../responses``.

    ``result``: the bytes the image model "generated" (``None``: the model
    answers in prose and makes no ``image_generation_call``).
    ``status``: a non-200 status answers every request with that HTTP error.
    ``failure``: ``"response_failed"`` streams a ``response.failed`` event;
    ``"stream_error"`` streams an ``{"error": ...}`` frame the SDK raises on;
    ``"timeout"`` raises ``httpx.ReadTimeout`` from the transport.
    """

    def __init__(
        self, result: bytes | None = None, *, status: int = 200, failure: str | None = None
    ) -> None:
        super().__init__({}, usage=None)
        self.result = result
        self.status = status
        self.failure = failure

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.failure == "timeout":
            raise httpx.ReadTimeout("mock read timeout", request=request)
        if self.status != 200:
            # ``retry-after-ms`` keeps any SDK retry instant, so a missing
            # ``max_retries=0`` shows up as extra requests, not a slow test.
            return httpx.Response(
                self.status,
                headers={"retry-after-ms": "1"},
                json={"error_code": "MOCK_ERROR", "message": f"mock HTTP {self.status}"},
            )
        body = json.loads(request.content)
        if body.get("stream"):
            return httpx.Response(
                200,
                headers={"content-type": "text/event-stream"},
                content=_sse(self._events(body)),
            )
        output = (
            [_MESSAGE_ITEM] if self.result is None else [_image_item(self._b64()), _MESSAGE_ITEM]
        )
        return httpx.Response(200, json=_response(body, output, usage=USAGE))

    def _b64(self) -> str:
        assert self.result is not None
        return base64.b64encode(self.result).decode()

    def _events(self, body: dict[str, Any]) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = [
            {"type": "response.created", "response": _response(body, [], status="in_progress")},
        ]
        if self.failure == "response_failed":
            error = {
                "code": "moderation_blocked",
                "message": "Your request was rejected by the safety system.",
            }
            events.append(
                {
                    "type": "response.failed",
                    "response": _response(body, [], status="failed", usage=USAGE, error=error),
                }
            )
            return events
        if self.failure == "stream_error":
            events.append({"type": "error", "error": {"message": "upstream overloaded"}})
            return events
        done_items = (
            [_MESSAGE_ITEM] if self.result is None else [_image_item(self._b64()), _MESSAGE_ITEM]
        )
        for index, item in enumerate(done_items):
            events.append(
                {"type": "response.output_item.done", "output_index": index, "item": item}
            )
        # The completed response does NOT repeat the base64 image: the final
        # image must come from ``response.output_item.done`` (C3).
        completed_output = [
            {**item, "result": None} if item["type"] == "image_generation_call" else item
            for item in done_items
        ]
        events.append(
            {
                "type": "response.completed",
                "response": _response(body, completed_output, usage=USAGE),
            }
        )
        return events

    def bodies(self) -> list[dict[str, Any]]:
        return [json.loads(r.content) for r in self.requests]


@pytest.fixture
def mock_ws(monkeypatch):
    """Install the mock transport; return a factory for configured workspaces."""
    install_mock_gateway_transport(monkeypatch)

    def make(result: bytes | None = None, **kwargs: Any) -> MockResponsesWorkspace:
        return MockResponsesWorkspace(result, **kwargs)

    return make


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv(ORCHESTRATOR_ENV, raising=False)
    monkeypatch.delenv("TELLR_IMAGE_GENERATION_ENABLED", raising=False)


@pytest.fixture
def ig():
    """The module under test, imported per test (see the module docstring)."""
    return importlib.import_module("src.services.image_generation")


def _generator(ig, ws: MockResponsesWorkspace, **kwargs: Any):
    return ig.ImageGenerator(
        client_factory=lambda: gateway_openai_client(ws, max_retries=0), **kwargs
    )


def _read_timeout(request: httpx.Request) -> float:
    return request.extensions["timeout"]["read"]


# ---------------------------------------------------------------------------
# Fixture self-tests: the mock is valid for the real SDK (no production code)
# ---------------------------------------------------------------------------


def test_fixture_self_test_the_real_sdk_parses_the_streamed_image(mock_ws):
    ws = mock_ws(_rgba_png())
    stream = gateway_openai_client(ws).responses.create(
        model="system.ai.gpt-5-4-nano",
        input="a lighthouse",
        tools=[
            {"type": "image_generation", "model": "gpt-image-2.5-flare", "output_format": "png"}
        ],
        tool_choice=FORCED_TOOL_CHOICE,
        stream=True,
    )
    events = list(stream)

    assert [e.type for e in events] == [
        "response.created",
        "response.output_item.done",
        "response.output_item.done",
        "response.completed",
    ]
    done = [e.item for e in events if e.type == "response.output_item.done"]
    assert [item.type for item in done] == ["image_generation_call", "message"]
    assert base64.b64decode(done[0].result) == _rgba_png()
    assert done[0].revised_prompt == REVISED_PROMPT
    completed = events[-1].response
    assert completed.usage.model_dump() == USAGE
    assert [item.type for item in completed.output] == ["image_generation_call", "message"]
    assert completed.output[0].result is None

    (request,) = ws.requests
    assert request.url.path == GATEWAY_RESPONSES_PATH
    assert request.headers.get_list(TAG_HEADER) == ['{"source": "tellr"}']
    assert json.loads(request.content)["stream"] is True


def test_fixture_self_test_the_real_sdk_parses_the_non_streamed_svg(mock_ws):
    ws = mock_ws(SVG.encode())
    response = gateway_openai_client(ws).responses.create(
        model="system.ai.gpt-5-4-nano",
        input="an icon",
        tools=[
            {"type": "image_generation", "model": "gpt-image-2.6-flare", "output_format": "svg"}
        ],
    )

    assert [item.type for item in response.output] == ["image_generation_call", "message"]
    assert base64.b64decode(response.output[0].result).decode() == SVG
    assert response.usage.model_dump() == USAGE
    assert "stream" not in json.loads(ws.requests[0].content)


@pytest.mark.parametrize("failure", ["response_failed", None])
def test_fixture_self_test_failure_and_no_image_streams_parse(mock_ws, failure):
    ws = mock_ws(None, failure=failure)
    events = list(gateway_openai_client(ws).responses.create(model="m", input="x", stream=True))
    assert not any(
        e.type == "response.output_item.done" and e.item.type == "image_generation_call"
        for e in events
    )
    assert events[-1].type == ("response.failed" if failure else "response.completed")


def test_fixture_self_test_a_stream_error_frame_raises_an_sdk_api_error(mock_ws):
    ws = mock_ws(_rgba_png(), failure="stream_error")
    with pytest.raises(openai.APIError):
        list(gateway_openai_client(ws).responses.create(model="m", input="x", stream=True))


def test_fixture_self_test_status_errors_and_retries_are_observable(mock_ws):
    """403 maps to the SDK's status error; a 500 is retried by the SDK default
    (``max_retries=2``) so "exactly one request" really proves ``max_retries=0``."""
    forbidden = mock_ws(status=403)
    with pytest.raises(openai.APIStatusError) as exc:
        gateway_openai_client(forbidden).responses.create(model="m", input="x", stream=True)
    assert exc.value.status_code == 403

    failing = mock_ws(status=500)
    with pytest.raises(openai.APIStatusError):
        gateway_openai_client(failing).responses.create(model="m", input="x", stream=True)
    assert len(failing.requests) == 3


def test_fixture_self_test_per_call_timeout_is_observable_on_the_request(mock_ws):
    ws = mock_ws(SVG.encode())
    gateway_openai_client(ws).responses.create(model="m", input="x", timeout=33)
    assert _read_timeout(ws.requests[0]) == 33


def test_fixture_self_test_transport_timeout_raises_an_sdk_timeout(mock_ws):
    ws = mock_ws(failure="timeout")
    client = gateway_openai_client(ws)
    client.max_retries = 0  # the SDK default would retry the timeout twice
    with pytest.raises(openai.APITimeoutError):
        client.responses.create(model="m", input="x", stream=True, timeout=1)
    assert len(ws.requests) == 1


# ---------------------------------------------------------------------------
# generate(): the request
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "preset_id,model,quality,result",
    [
        ("background", "gpt-image-2.6-sunburst", "medium", _jpeg()),
        ("illustration", None, None, _jpeg()),
        ("icon_png", "gpt-image-2.6-flare", "high", _rgba_png()),
        ("icon_png", None, None, _rgba_png()),
    ],
    ids=["background-explicit", "illustration-defaults", "icon_png-explicit", "icon_png-defaults"],
)
def test_raster_generate_sends_one_streamed_forced_tool_request(
    ig, mock_ws, preset_id, model, quality, result
):
    ws = mock_ws(result)
    prompt = "A lighthouse on a rocky coast"

    _generator(ig, ws).generate(prompt, preset_id, model=model, quality=quality)

    preset, resolved_model, resolved_quality = ig.resolve_request(preset_id, model, quality)
    (request,) = ws.requests
    assert request.method == "POST"
    assert request.url.path == GATEWAY_RESPONSES_PATH
    assert request.headers.get_list(TAG_HEADER) == ['{"source": "tellr"}']
    assert json.loads(request.content) == {
        "model": DEFAULT_ORCHESTRATOR,
        "input": ig.build_prompt(prompt, preset),
        "tools": [ig.build_tool(preset, resolved_model, resolved_quality)],
        "tool_choice": FORCED_TOOL_CHOICE,
        "stream": True,
    }
    assert _read_timeout(request) == preset.timeout_s == 180


def test_icon_png_request_carries_the_literal_transparent_png_tool(ig, mock_ws):
    """The tool the Gateway accepted in the probe, byte for byte (C6/C7)."""
    ws = mock_ws(_rgba_png())
    _generator(ig, ws).generate(
        "a lighthouse", "icon_png", model="gpt-image-2.5-flare", quality="low"
    )

    assert ws.bodies()[0]["tools"] == [
        {
            "type": "image_generation",
            "model": "gpt-image-2.5-flare",
            "quality": "low",
            "size": "1024x1024",
            "output_format": "png",
            "background": "transparent",
        }
    ]


def test_svg_generate_sends_one_non_streamed_forced_tool_request(ig, mock_ws):
    ws = mock_ws(SVG.encode())
    prompt = "A lighthouse"

    _generator(ig, ws).generate(prompt, "icon_svg", model="gpt-image-2.6-flare", quality="low")

    preset = ig.PRESETS["icon_svg"]
    (request,) = ws.requests
    assert request.url.path == GATEWAY_RESPONSES_PATH
    assert request.headers.get_list(TAG_HEADER) == ['{"source": "tellr"}']
    sent = json.loads(request.content)
    assert sent.pop("stream", False) is False
    assert sent == {
        "model": DEFAULT_ORCHESTRATOR,
        "input": ig.build_prompt(prompt, preset),
        "tools": [ig.build_tool(preset, "gpt-image-2.6-flare", "low")],
        "tool_choice": FORCED_TOOL_CHOICE,
    }
    assert sent["tools"] == [
        {
            "type": "image_generation",
            "model": "gpt-image-2.6-flare",
            "quality": "low",
            "output_format": "svg",
            "complexity": "low",
        }
    ]
    assert _read_timeout(request) == preset.timeout_s == 240


# ---------------------------------------------------------------------------
# generate(): the caller's per-call timeout (chat image generation, Unit G)
#
# Contract (docs/superpowers/plans/2026-11-09-chat-image-generation-CORRECTIONS.md,
# "Unit G interface"): ``generate(..., *, timeout_s=None)``. The read timeout on the
# REAL request is ``preset.timeout_s`` when ``timeout_s`` is None, otherwise
# ``min(preset.timeout_s, max(5.0, timeout_s))``: a caller may only shorten it.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "preset_id,result,timeout_s,expected",
    [
        ("illustration", _jpeg(), 30, 30),
        ("illustration", _jpeg(), 30.5, 30.5),
        ("illustration", _jpeg(), None, 180),
        ("illustration", _jpeg(), 999, 180),
        ("illustration", _jpeg(), 180, 180),
        ("illustration", _jpeg(), 1, 5),
        ("illustration", _jpeg(), 0, 5),
        ("background", _jpeg(), 42, 42),
        ("icon_png", _rgba_png(), 30, 30),
        ("icon_png", _rgba_png(), 999, 180),
        ("icon_svg", SVG.encode(), None, 240),
        ("icon_svg", SVG.encode(), 30, 30),
        ("icon_svg", SVG.encode(), 200, 200),
        ("icon_svg", SVG.encode(), 999, 240),
    ],
    ids=[
        "raster-30",
        "raster-30.5",
        "raster-none-is-preset",
        "raster-999-capped-at-preset",
        "raster-equal-to-preset",
        "raster-1-floored-at-5",
        "raster-0-floored-at-5",
        "background-42",
        "icon_png-30",
        "icon_png-999-capped",
        "svg-none-is-240",
        "svg-30",
        "svg-200-under-its-240",
        "svg-999-capped-at-240",
    ],
)
def test_the_callers_timeout_reaches_the_request_capped_by_the_preset(
    ig, mock_ws, preset_id, result, timeout_s, expected
):
    ws = mock_ws(result)

    _generator(ig, ws).generate("a lighthouse", preset_id, timeout_s=timeout_s)

    (request,) = ws.requests
    assert _read_timeout(request) == expected


def test_timeout_s_is_keyword_only_and_defaults_to_none(ig):
    import inspect

    param = inspect.signature(ig.ImageGenerator.generate).parameters["timeout_s"]
    assert param.kind is inspect.Parameter.KEYWORD_ONLY
    assert param.default is None


def test_a_timeout_override_changes_nothing_else_in_the_request(ig, mock_ws):
    """The override is the read timeout only: the body is the same request as without it."""
    plain = mock_ws(_jpeg())
    _generator(ig, plain).generate("a lighthouse", "illustration")
    short = mock_ws(_jpeg())
    _generator(ig, short).generate("a lighthouse", "illustration", timeout_s=30)

    assert short.bodies() == plain.bodies()
    assert len(short.requests) == 1


def test_orchestrator_defaults_to_gpt_5_4_nano_and_follows_the_env_override(
    ig, mock_ws, monkeypatch
):
    ws = mock_ws(_rgba_png())
    _generator(ig, ws).generate("a fox", "icon_png")
    monkeypatch.setenv(ORCHESTRATOR_ENV, "system.ai.gpt-5-6-terra")
    _generator(ig, ws).generate("a fox", "icon_png")

    assert [b["model"] for b in ws.bodies()] == [DEFAULT_ORCHESTRATOR, "system.ai.gpt-5-6-terra"]


def test_an_explicit_orchestrator_wins(ig, mock_ws, monkeypatch):
    monkeypatch.setenv(ORCHESTRATOR_ENV, "system.ai.gpt-5-6-terra")
    ws = mock_ws(_rgba_png())
    _generator(ig, ws, orchestrator="system.ai.gpt-5-4-mini").generate("a fox", "icon_png")

    assert ws.bodies()[0]["model"] == "system.ai.gpt-5-4-mini"


@pytest.mark.parametrize(
    "preset_id,model,quality",
    [("poster", None, None), ("icon_svg", "gpt-image-2.5-flare", None), ("icon_png", None, "auto")],
)
def test_invalid_requests_raise_value_error_before_any_call(ig, mock_ws, preset_id, model, quality):
    ws = mock_ws(_rgba_png())
    with pytest.raises(ValueError):
        _generator(ig, ws).generate("a fox", preset_id, model=model, quality=quality)
    assert ws.requests == []


# ---------------------------------------------------------------------------
# generate(): the result
# ---------------------------------------------------------------------------


def test_transparent_png_result_keeps_alpha_and_carries_the_call_metadata(ig, mock_ws):
    source = _rgba_png((64, 40))
    ws = mock_ws(source)

    img = _generator(ig, ws).generate(
        "a lighthouse", "icon_png", model="gpt-image-2.6-flare", quality="low"
    )

    assert isinstance(img, ig.GeneratedImage)
    assert (img.mime, img.ext) == ("image/png", "png")
    decoded = _decode(img.data)
    assert decoded.format == "PNG"
    assert decoded.size == (64, 40)
    assert _alpha_min(decoded) == 0
    assert img.model == "gpt-image-2.6-flare"
    assert img.preset_id == "icon_png"
    assert img.revised_prompt == REVISED_PROMPT
    assert img.usage == USAGE
    assert isinstance(img.latency_s, float) and img.latency_s >= 0


def test_jpeg_result_for_a_background_is_a_library_jpeg(ig, mock_ws):
    ws = mock_ws(_jpeg((64, 36)))

    img = _generator(ig, ws).generate("calm gradient", "background")

    assert (img.mime, img.ext) == ("image/jpeg", "jpg")
    decoded = _decode(img.data)
    assert decoded.format == "JPEG" and decoded.size == (64, 36)
    assert img.preset_id == "background"
    assert img.model == ig.PRESETS["background"].default_model
    assert img.usage == USAGE


def test_the_real_bytes_decide_the_mime_not_the_requested_format(ig, mock_ws):
    """The model returned JPEG for a PNG preset: label what the bytes are."""
    ws = mock_ws(_jpeg())

    img = _generator(ig, ws).generate("a lighthouse", "icon_png")

    assert (img.mime, img.ext) == ("image/jpeg", "jpg")
    assert _decode(img.data).format == "JPEG"


def test_a_webp_result_is_converted_into_a_library_type(ig, mock_ws):
    """WebP is not in ``image_service.ALLOWED_TYPES``: output goes through ``fit_to_library``."""
    ws = mock_ws(_webp_rgba())

    img = _generator(ig, ws).generate("a lighthouse", "icon_png")

    assert (img.mime, img.ext) == ("image/png", "png")
    decoded = _decode(img.data)
    assert decoded.format == "PNG" and _alpha_min(decoded) == 0


def test_svg_result_is_the_markup_with_svg_mime(ig, mock_ws):
    ws = mock_ws(SVG.encode())

    img = _generator(ig, ws).generate("a lighthouse", "icon_svg")

    assert img.data == SVG.encode()
    assert (img.mime, img.ext) == ("image/svg+xml", "svg")
    assert img.model == ig.PRESETS["icon_svg"].default_model
    assert img.preset_id == "icon_svg"
    assert img.revised_prompt == REVISED_PROMPT
    assert img.usage == USAGE


@pytest.mark.parametrize(
    "fence",
    ["```svg\n{}\n```", "```xml\n{}\n```", "```\n{}\n```", "\n```svg\n{}\n```\n"],
    ids=["svg", "xml", "bare", "padded"],
)
def test_a_fenced_svg_result_is_unwrapped(ig, mock_ws, fence):
    ws = mock_ws(fence.format(SVG).encode())

    img = _generator(ig, ws).generate("a lighthouse", "icon_svg")

    assert img.data == SVG.encode()


@pytest.mark.parametrize(
    "markup",
    [
        '<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>',
        '<svg xmlns="http://www.w3.org/2000/svg" onload="alert(1)">'
        '<rect width="1" height="1"/></svg>',
        '<svg xmlns="http://www.w3.org/2000/svg"><image href="https://evil.example/x.png"/></svg>',
        '```svg\n<svg xmlns="http://www.w3.org/2000/svg"><foreignObject/></svg>\n```',
        "I'm sorry, I can't draw that.",
    ],
    ids=["script", "onload", "external-href", "fenced-foreignObject", "prose"],
)
def test_unsafe_or_non_svg_output_is_rejected(ig, mock_ws, markup):
    ws = mock_ws(markup.encode())
    with pytest.raises(ig.ImageGenerationError):
        _generator(ig, ws).generate("a lighthouse", "icon_svg")


def test_a_raster_result_that_is_not_an_image_is_an_error(ig, mock_ws):
    ws = mock_ws(b"definitely not an image")
    with pytest.raises(ig.ImageGenerationError):
        _generator(ig, ws).generate("a lighthouse", "icon_png")


@pytest.mark.parametrize("preset_id", ["icon_png", "icon_svg"])
def test_no_image_item_is_an_image_generation_error(ig, mock_ws, preset_id):
    ws = mock_ws(None)
    with pytest.raises(ig.ImageGenerationError):
        _generator(ig, ws).generate("a lighthouse", preset_id)
    assert len(ws.requests) == 1


def test_a_failed_response_stream_is_an_image_generation_error(ig, mock_ws):
    ws = mock_ws(None, failure="response_failed")
    with pytest.raises(ig.ImageGenerationError):
        _generator(ig, ws).generate("a lighthouse", "background")


def test_an_error_frame_mid_stream_is_an_image_generation_error(ig, mock_ws):
    ws = mock_ws(_rgba_png(), failure="stream_error")
    with pytest.raises(ig.ImageGenerationError) as exc:
        _generator(ig, ws).generate("a lighthouse", "icon_png")
    assert exc.value.status_code is None


def test_a_transport_timeout_is_an_image_generation_error(ig, mock_ws):
    ws = mock_ws(failure="timeout")
    with pytest.raises(ig.ImageGenerationError) as exc:
        _generator(ig, ws).generate("a lighthouse", "icon_png")
    assert exc.value.status_code is None


def test_http_403_is_an_image_generation_error_with_the_status(ig, mock_ws):
    ws = mock_ws(status=403)
    with pytest.raises(ig.ImageGenerationError) as exc:
        _generator(ig, ws).generate("a lighthouse", "icon_png")
    assert exc.value.status_code == 403
    assert isinstance(exc.value, RuntimeError)
    assert len(ws.requests) == 1


def test_image_generation_error_carries_an_optional_status_code(ig):
    assert ig.ImageGenerationError("boom").status_code is None
    err = ig.ImageGenerationError("denied", status_code=403)
    assert (str(err), err.status_code) == ("denied", 403)


# ---------------------------------------------------------------------------
# default_client(): no silent paid retries
# ---------------------------------------------------------------------------


def test_default_client_is_the_tagged_gateway_client_with_no_retries(ig, mock_ws, monkeypatch):
    ws = mock_ws(_rgba_png())
    monkeypatch.setattr(ig, "get_system_client", lambda *a, **k: ws)

    client = ig.default_client()

    assert client.max_retries == 0
    assert str(client.base_url).rstrip("/") == "https://chat.invalid/ai-gateway/mlflow/v1"


@pytest.mark.parametrize("preset_id", ["icon_png", "icon_svg"])
def test_a_500_through_the_default_client_is_sent_exactly_once(ig, mock_ws, monkeypatch, preset_id):
    ws = mock_ws(status=500)
    monkeypatch.setattr(ig, "get_system_client", lambda *a, **k: ws)

    with pytest.raises(ig.ImageGenerationError) as exc:
        ig.ImageGenerator().generate("a lighthouse", preset_id)

    assert exc.value.status_code == 500
    assert len(ws.requests) == 1
    assert ws.requests[0].url.path == GATEWAY_RESPONSES_PATH
    assert ws.requests[0].headers.get_list(TAG_HEADER) == ['{"source": "tellr"}']


# ---------------------------------------------------------------------------
# edit()
# ---------------------------------------------------------------------------


def test_edit_of_a_transparent_png_sends_it_flattened_on_white_and_asks_for_transparency(
    ig, mock_ws
):
    # Finding (2026-11-08, live Gateway): sent with its alpha, a transparent icon is read
    # as if on black and comes back as a dark "neon" edit whose alpha never drops below ~60.
    # Flattened onto white first, the same request returns a clean transparent edit. So the
    # model sees an opaque white-backed image while the tool still asks for transparency.
    source = _rgba_png((80, 50))
    ws = mock_ws(_rgba_png())
    prompt = "Make the lighthouse blue"

    img = _generator(ig, ws).edit(
        prompt, source, "image/png", model="gpt-image-2.6-flare", quality="medium"
    )

    (request,) = ws.requests
    assert request.url.path == GATEWAY_RESPONSES_PATH
    assert request.headers.get_list(TAG_HEADER) == ['{"source": "tellr"}']
    sent = json.loads(request.content)
    (message,) = sent.pop("input")
    assert sent == {
        "model": DEFAULT_ORCHESTRATOR,
        "tools": [
            {
                "type": "image_generation",
                "model": "gpt-image-2.6-flare",
                "quality": "medium",
                "size": "auto",
                "output_format": "png",
                "background": "transparent",
            }
        ],
        "tool_choice": FORCED_TOOL_CHOICE,
        "stream": True,
    }
    assert message["role"] == "user"
    text_part, image_part = message["content"]
    assert set(text_part) == {"type", "text"} and text_part["type"] == "input_text"
    assert prompt in text_part["text"]
    assert set(image_part) == {"type", "image_url"} and image_part["type"] == "input_image"
    mime, decoded = _decode_data_url(image_part["image_url"])
    assert mime == "image/jpeg"
    assert decoded.size == (80, 50) and decoded.mode == "RGB"
    # left half of the source is fully transparent -> white; right half opaque red survives
    left = decoded.getpixel((10, 25))
    right = decoded.getpixel((70, 25))
    assert all(c >= 245 for c in left), left
    assert right[0] >= 180 and right[1] <= 90 and right[2] <= 90, right
    assert _read_timeout(request) == 180

    assert (img.mime, img.ext) == ("image/png", "png")
    assert _alpha_min(_decode(img.data)) == 0
    assert img.model == "gpt-image-2.6-flare"
    assert img.preset_id is None
    assert img.usage == USAGE


@pytest.mark.parametrize(
    "source,source_mime",
    [
        (_jpeg((80, 50)), "image/jpeg"),
        (_rgb_png((80, 50)), "image/png"),
        # whole-branch review: an alpha CHANNEL is not transparency; an opaque RGBA source
        # must be edited as opaque, or the model is told to cut out a background to keep
        (_opaque_rgba_png((80, 50)), "image/png"),
    ],
    ids=["jpeg", "opaque-png", "opaque-rgba-png"],
)
def test_edit_of_an_opaque_image_sends_a_jpeg_image_and_an_opaque_jpeg_tool(
    ig, mock_ws, source, source_mime
):
    ws = mock_ws(_jpeg())

    img = _generator(ig, ws).edit(
        "Add a sunset", source, source_mime, model="gpt-image-2.5-sunburst", quality="low"
    )

    sent = ws.bodies()[0]
    assert sent["tools"] == [
        {
            "type": "image_generation",
            "model": "gpt-image-2.5-sunburst",
            "quality": "low",
            "size": "auto",
            "output_format": "jpeg",
        }
    ]
    assert sent["tool_choice"] == FORCED_TOOL_CHOICE
    assert sent["stream"] is True
    image_part = sent["input"][0]["content"][1]
    assert image_part == {"type": "input_image", "image_url": ig.to_data_url(source)}
    mime, decoded = _decode_data_url(image_part["image_url"])
    assert mime == "image/jpeg" and decoded.format == "JPEG" and decoded.size == (80, 50)
    assert (img.mime, img.ext) == ("image/jpeg", "jpg")


def test_edit_defaults_pick_an_offered_model_and_quality(ig, mock_ws):
    ws = mock_ws(_jpeg())
    _generator(ig, ws).edit("Add a sunset", _jpeg(), "image/jpeg")

    (tool,) = ws.bodies()[0]["tools"]
    assert tool["model"] in ig.IMAGE_MODELS
    assert tool["quality"] in ig.QUALITIES


def test_edit_of_an_svg_source_raises_value_error_before_any_request(ig, mock_ws):
    ws = mock_ws(_rgba_png())
    with pytest.raises(ValueError):
        _generator(ig, ws).edit("Make it blue", SVG.encode(), "image/svg+xml")
    assert ws.requests == []


@pytest.mark.parametrize("model,quality", [("dall-e-3", None), (None, "ultra")])
def test_edit_with_an_unknown_model_or_quality_raises_value_error_before_any_request(
    ig, mock_ws, model, quality
):
    ws = mock_ws(_jpeg())
    with pytest.raises(ValueError):
        _generator(ig, ws).edit("Make it blue", _jpeg(), "image/jpeg", model=model, quality=quality)
    assert ws.requests == []


def test_edit_maps_http_errors_and_missing_images_to_image_generation_errors(ig, mock_ws):
    forbidden = mock_ws(status=403)
    with pytest.raises(ig.ImageGenerationError) as exc:
        _generator(ig, forbidden).edit("Make it blue", _jpeg(), "image/jpeg")
    assert exc.value.status_code == 403

    prose = mock_ws(None)
    with pytest.raises(ig.ImageGenerationError):
        _generator(ig, prose).edit("Make it blue", _jpeg(), "image/jpeg")
