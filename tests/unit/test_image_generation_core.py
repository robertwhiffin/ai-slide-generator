"""Pure pieces of ``src/services/image_generation.py``.

The contract is the "Unit A interface" and corrections C2-C8 in
``docs/superpowers/plans/2026-11-08-ai-image-generation-CORRECTIONS.md``,
plus the preset table in ``docs/superpowers/plans/2026-11-08-ai-image-generation.md``.
Tool dicts are compared WHOLE: a key that is not listed is a key that must not
be sent (the Gateway rejected ``reasoning`` and silently ignored
``partial_images`` in the Task 0 probe).
"""

from __future__ import annotations

import base64
import dataclasses
import inspect
import io
import random
import re
from datetime import datetime, timedelta, timezone

import pytest
from PIL import Image
from src.services.image_generation import (
    DEFAULT_ORCHESTRATOR_MODEL,
    DEFAULT_PRESET,
    ENV_FLAG,
    IMAGE_MODELS,
    MAX_PROMPT_CHARS,
    ORCHESTRATOR_ENV,
    PRESETS,
    QUALITIES,
    SVG_THUMBNAIL_MAX_BYTES,
    ImageModelSpec,
    Preset,
    build_prompt,
    build_tool,
    check_static_svg,
    fit_to_library,
    generated_filename,
    is_enabled,
    orchestrator_model,
    resolve_request,
    strip_code_fences,
    to_data_url,
)

from src.services import image_service

FLARE_25 = "gpt-image-2.5-flare"
SUNBURST_25 = "gpt-image-2.5-sunburst"
FLARE_26 = "gpt-image-2.6-flare"
SUNBURST_26 = "gpt-image-2.6-sunburst"
ALL_MODELS = (FLARE_25, SUNBURST_25, FLARE_26, SUNBURST_26)
SVG_MODELS = (FLARE_26, SUNBURST_26)
PRESET_IDS = ("background", "illustration", "icon_png", "icon_svg")
ICON_PRESET_IDS = ("icon_png", "icon_svg")

#: The extension the module uses for each library mime (repo convention:
#: ``src/services/agent_tools/gateway_tool.py`` ``_EXTENSIONS``).
EXT_FOR_MIME = {"image/png": "png", "image/jpeg": "jpg", "image/gif": "gif", "image/svg+xml": "svg"}
PIL_FORMAT_FOR_MIME = {"image/png": "PNG", "image/jpeg": "JPEG", "image/gif": "GIF"}

#: The preset table (plan "Design" + C3/C6/C7). ``complexity`` is only set where
#: the probe verified it (S2: svg + complexity low on 2.6-flare); C7 forbids
#: sending unverified tool params, so raster presets carry none.
TABLE = {
    "background": dict(
        size="2048x1152",
        output_format="jpeg",
        transparent=False,
        category="background",
        models=ALL_MODELS,
        default_model=FLARE_26,
        complexity=None,
        timeout_s=180,
    ),
    "illustration": dict(
        size="1536x1024",
        output_format="jpeg",
        transparent=False,
        category="content",
        models=ALL_MODELS,
        default_model=FLARE_26,
        complexity=None,
        timeout_s=180,
    ),
    "icon_png": dict(
        size="1024x1024",
        output_format="png",
        transparent=True,
        category="content",
        models=ALL_MODELS,
        default_model=FLARE_26,
        complexity=None,
        timeout_s=180,
    ),
    # ``transparent`` is n/a for svg (no ``background`` is ever sent), so it is not pinned.
    "icon_svg": dict(
        size=None,
        output_format="svg",
        category="content",
        models=SVG_MODELS,
        default_model=FLARE_26,
        complexity="low",
        timeout_s=240,
    ),
}

#: (supports_transparent, supports_svg, supports_complexity) for each image model.
MODEL_CAPABILITIES = {
    FLARE_25: (True, False, False),
    SUNBURST_25: (True, False, False),
    FLARE_26: (True, True, True),
    SUNBURST_26: (True, True, True),
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def flexible_size_ok(size: str) -> bool:
    """The size rule of the flexible-size models (every gpt-image 2.5/2.6 model): multiples of 16, max
    edge 3840, 655,360-8,294,400 pixels, long:short ratio at most 3:1."""
    parts = size.split("x")
    if len(parts) != 2:
        return False
    try:
        w, h = int(parts[0]), int(parts[1])
    except ValueError:
        return False
    return (
        w > 0
        and h > 0
        and w % 16 == 0
        and h % 16 == 0
        and max(w, h) <= 3840
        and 655_360 <= w * h <= 8_294_400
        and max(w, h) / min(w, h) <= 3.0
    )


def _encode(img: Image.Image, fmt: str, **kwargs) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format=fmt, **kwargs)
    return buf.getvalue()


def _half_transparent(size: tuple[int, int], mode: str = "RGBA") -> Image.Image:
    """Left half fully transparent, right half opaque."""
    w, h = size
    img = Image.new("RGBA", size, (0, 0, 0, 0))
    img.paste(Image.new("RGBA", (w - w // 2, h), (220, 40, 40, 255)), (w // 2, 0))
    return img.convert(mode) if mode != "RGBA" else img


def _noise(size: tuple[int, int], mode: str, seed: int = 7) -> Image.Image:
    """Incompressible pixels; RGBA keeps a fully transparent left half."""
    w, h = size
    rgb = Image.frombytes("RGB", size, random.Random(seed).randbytes(w * h * 3))
    if mode == "RGB":
        return rgb
    alpha = Image.new("L", size, 255)
    alpha.paste(0, (0, 0, w // 2, h))
    rgba = rgb.convert("RGBA")
    rgba.putalpha(alpha)
    return rgba


def _decode(data: bytes) -> Image.Image:
    img = Image.open(io.BytesIO(data))
    img.load()
    return img


def _alpha_extrema(img: Image.Image) -> tuple[int, int]:
    assert "A" in img.getbands(), f"no alpha channel in mode {img.mode}"
    return img.getchannel("A").getextrema()


def _decode_data_url(url: str) -> tuple[str, Image.Image]:
    match = re.fullmatch(r"data:(image/[a-z+]+);base64,([A-Za-z0-9+/=]+)", url)
    assert match, url[:80]
    return match.group(1), _decode(base64.b64decode(match.group(2)))


def _assert_library_ready(data: bytes, mime: str, ext: str) -> Image.Image:
    """``fit_to_library`` output: an allowed mime, a matching ext, bytes that ARE that format."""
    assert mime in image_service.ALLOWED_TYPES
    assert ext == EXT_FOR_MIME[mime]
    decoded = _decode(data)
    assert decoded.format == PIL_FORMAT_FOR_MIME[mime]
    return decoded


def _expected_tool(preset_id: str, model: str, quality: str) -> dict:
    """The tool the C3/C6/C7 rules allow, built from the literal table."""
    row = TABLE[preset_id]
    tool = {
        "type": "image_generation",
        "model": model,
        "quality": quality,
        "output_format": row["output_format"],
    }
    if row["output_format"] != "svg":
        tool["size"] = row["size"]
        if row["transparent"]:
            tool["background"] = "transparent"
    if row["complexity"] and MODEL_CAPABILITIES[model][2]:
        tool["complexity"] = row["complexity"]
    return tool


# ---------------------------------------------------------------------------
# Constants, flag, orchestrator
# ---------------------------------------------------------------------------


def test_interface_constants():
    assert ENV_FLAG == "TELLR_IMAGE_GENERATION_ENABLED"
    assert ORCHESTRATOR_ENV == "TELLR_IMAGE_GEN_ORCHESTRATOR_MODEL"
    assert DEFAULT_ORCHESTRATOR_MODEL == "system.ai.gpt-5-4-nano"
    assert MAX_PROMPT_CHARS == 2000
    assert QUALITIES == ("low", "medium", "high")
    assert DEFAULT_PRESET == "icon_png"
    assert SVG_THUMBNAIL_MAX_BYTES == 200 * 1024


# On by default (user decision, 2026-11-09): the env var is a deployment OFF switch.
@pytest.mark.parametrize(
    "value,enabled",
    [("1", True), ("true", True), ("yes", True), ("", True),
     ("0", False), ("false", False), ("FALSE", False), ("no", False), ("off", False),
     (" 0 ", False)],
)
def test_is_enabled_unless_the_deployment_turns_it_off(monkeypatch, value, enabled):
    monkeypatch.setenv("TELLR_IMAGE_GENERATION_ENABLED", value)
    assert is_enabled() is enabled


def test_is_enabled_when_the_flag_is_unset(monkeypatch):
    monkeypatch.delenv("TELLR_IMAGE_GENERATION_ENABLED", raising=False)
    assert is_enabled() is True


def test_orchestrator_defaults_to_gpt_5_4_nano(monkeypatch):
    monkeypatch.delenv("TELLR_IMAGE_GEN_ORCHESTRATOR_MODEL", raising=False)
    assert orchestrator_model() == "system.ai.gpt-5-4-nano"


def test_orchestrator_follows_the_env_override(monkeypatch):
    monkeypatch.setenv("TELLR_IMAGE_GEN_ORCHESTRATOR_MODEL", "system.ai.gpt-5-6-terra")
    assert orchestrator_model() == "system.ai.gpt-5-6-terra"


# ---------------------------------------------------------------------------
# Models and presets
# ---------------------------------------------------------------------------


def test_image_models_are_the_four_gpt_image_2_5_and_2_6_models_with_their_capabilities():
    assert list(IMAGE_MODELS) == list(ALL_MODELS)
    for model_id, spec in IMAGE_MODELS.items():
        assert isinstance(spec, ImageModelSpec)
        assert spec.id == model_id
        assert spec.label.strip() and spec.description.strip()
        assert (
            spec.supports_transparent,
            spec.supports_svg,
            spec.supports_complexity,
        ) == MODEL_CAPABILITIES[model_id]


def test_presets_are_the_plan_table():
    assert list(PRESETS) == list(PRESET_IDS)
    for preset_id, row in TABLE.items():
        preset = PRESETS[preset_id]
        assert isinstance(preset, Preset)
        assert preset.id == preset_id
        assert preset.label.strip() and preset.description.strip() and preset.art_direction.strip()
        assert {field: getattr(preset, field) for field in row} == row, preset_id


def test_presets_are_frozen():
    with pytest.raises(dataclasses.FrozenInstanceError):
        PRESETS["icon_png"].size = "4096x4096"  # type: ignore[misc]
    with pytest.raises(dataclasses.FrozenInstanceError):
        IMAGE_MODELS[FLARE_25].supports_svg = True  # type: ignore[misc]


@pytest.mark.parametrize("preset_id", PRESET_IDS)
def test_every_preset_is_internally_consistent(preset_id):
    preset = PRESETS[preset_id]
    assert preset.models, "a preset offers at least one model"
    assert preset.default_model in preset.models
    assert set(preset.models) <= set(IMAGE_MODELS)
    assert preset.default_quality in QUALITIES
    assert preset.category in ("background", "content")
    assert preset.complexity in (None, "low", "medium", "high")
    assert preset.output_format in ("jpeg", "png", "svg")
    if preset.transparent and preset.output_format != "svg":
        assert preset.output_format == "png", "transparent presets never use jpeg"
        assert all(IMAGE_MODELS[m].supports_transparent for m in preset.models)
    if preset.output_format == "svg":
        assert preset.size is None
        assert all(IMAGE_MODELS[m].supports_svg for m in preset.models)
        assert preset.timeout_s == 240
    else:
        assert preset.size is not None and flexible_size_ok(preset.size), preset.size
        assert preset.timeout_s == 180


def test_default_preset_exists():
    assert DEFAULT_PRESET in PRESETS


@pytest.mark.parametrize(
    "size,ok",
    [
        ("2048x1152", True),
        ("1536x1024", True),
        ("1024x1024", True),
        ("1000x1000", False),
        ("512x512", False),
        ("3840x1280", True),
        ("4096x2048", False),
        ("3072x768", False),
        ("auto", False),
    ],
)
def test_the_flexible_size_rule(size, ok):
    """Guards the helper itself, so the preset check above cannot pass vacuously."""
    assert flexible_size_ok(size) is ok


# ---------------------------------------------------------------------------
# resolve_request
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("preset_id", PRESET_IDS)
def test_resolve_request_applies_the_preset_defaults(preset_id):
    preset = PRESETS[preset_id]
    assert resolve_request(preset_id, None, None) == (
        preset,
        preset.default_model,
        preset.default_quality,
    )


@pytest.mark.parametrize("preset_id", PRESET_IDS)
def test_resolve_request_keeps_an_allowed_model_and_quality(preset_id):
    preset = PRESETS[preset_id]
    model = preset.models[-1]
    assert resolve_request(preset_id, model, "high") == (preset, model, "high")
    assert resolve_request(preset_id, None, "medium") == (preset, preset.default_model, "medium")
    assert resolve_request(preset_id, model, None) == (preset, model, preset.default_quality)


@pytest.mark.parametrize(
    "preset_id,model,quality",
    [
        ("poster", None, None),
        ("", None, None),
        ("icon_svg", FLARE_25, None),
        ("icon_svg", SUNBURST_25, "low"),
        ("background", "dall-e-3", None),
        ("icon_png", "gpt-image-1.5", None),
        ("icon_png", None, "auto"),
        ("icon_png", None, "xhigh"),
        ("background", FLARE_25, "ultra"),
    ],
)
def test_resolve_request_rejects_unknown_presets_disallowed_models_and_bad_qualities(
    preset_id, model, quality
):
    with pytest.raises(ValueError):
        resolve_request(preset_id, model, quality)


# ---------------------------------------------------------------------------
# build_tool (C3/C4/C6/C7)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "preset_id,model,quality,expected",
    [
        (
            "background",
            FLARE_25,
            "low",
            {
                "type": "image_generation",
                "model": FLARE_25,
                "quality": "low",
                "size": "2048x1152",
                "output_format": "jpeg",
            },
        ),
        (
            "background",
            SUNBURST_26,
            "high",
            {
                "type": "image_generation",
                "model": SUNBURST_26,
                "quality": "high",
                "size": "2048x1152",
                "output_format": "jpeg",
            },
        ),
        (
            "illustration",
            SUNBURST_25,
            "medium",
            {
                "type": "image_generation",
                "model": SUNBURST_25,
                "quality": "medium",
                "size": "1536x1024",
                "output_format": "jpeg",
            },
        ),
        (
            "icon_png",
            FLARE_25,
            "low",
            {
                "type": "image_generation",
                "model": FLARE_25,
                "quality": "low",
                "size": "1024x1024",
                "output_format": "png",
                "background": "transparent",
            },
        ),
        (
            "icon_png",
            FLARE_26,
            "high",
            {
                "type": "image_generation",
                "model": FLARE_26,
                "quality": "high",
                "size": "1024x1024",
                "output_format": "png",
                "background": "transparent",
            },
        ),
        (
            "icon_svg",
            FLARE_26,
            "low",
            {
                "type": "image_generation",
                "model": FLARE_26,
                "quality": "low",
                "output_format": "svg",
                "complexity": "low",
            },
        ),
        (
            "icon_svg",
            SUNBURST_26,
            "medium",
            {
                "type": "image_generation",
                "model": SUNBURST_26,
                "quality": "medium",
                "output_format": "svg",
                "complexity": "low",
            },
        ),
    ],
)
def test_build_tool_whole_dicts(preset_id, model, quality, expected):
    assert build_tool(PRESETS[preset_id], model, quality) == expected


@pytest.mark.parametrize("quality", ("low", "medium", "high"))
@pytest.mark.parametrize("preset_id", PRESET_IDS)
def test_build_tool_for_every_offered_model_follows_the_rules(preset_id, quality):
    """Never ``partial_images`` (C4) or ``reasoning`` (C6); ``background`` only
    ``"transparent"`` on transparent rasters; svg has no ``size``/``background`` (C7)."""
    for model in PRESETS[preset_id].models:
        assert build_tool(PRESETS[preset_id], model, quality) == _expected_tool(
            preset_id, model, quality
        ), model


def test_complexity_is_sent_only_to_2_6_models_and_only_when_the_preset_sets_it():
    with_complexity = dataclasses.replace(PRESETS["illustration"], complexity="medium")
    base = {
        "type": "image_generation",
        "quality": "low",
        "size": "1536x1024",
        "output_format": "jpeg",
    }
    assert build_tool(with_complexity, FLARE_25, "low") == {**base, "model": FLARE_25}
    assert build_tool(with_complexity, SUNBURST_25, "low") == {**base, "model": SUNBURST_25}
    assert build_tool(with_complexity, FLARE_26, "low") == {
        **base,
        "model": FLARE_26,
        "complexity": "medium",
    }
    assert build_tool(with_complexity, SUNBURST_26, "low") == {
        **base,
        "model": SUNBURST_26,
        "complexity": "medium",
    }

    without = dataclasses.replace(PRESETS["icon_svg"], complexity=None)
    assert build_tool(without, FLARE_26, "low") == {
        "type": "image_generation",
        "model": FLARE_26,
        "quality": "low",
        "output_format": "svg",
    }


def test_background_follows_the_preset_transparency_and_is_never_opaque():
    opaque_png = dataclasses.replace(PRESETS["icon_png"], transparent=False)
    assert build_tool(opaque_png, FLARE_25, "low") == {
        "type": "image_generation",
        "model": FLARE_25,
        "quality": "low",
        "size": "1024x1024",
        "output_format": "png",
    }

    transparent_svg = dataclasses.replace(PRESETS["icon_svg"], transparent=True)
    assert build_tool(transparent_svg, FLARE_26, "low") == {
        "type": "image_generation",
        "model": FLARE_26,
        "quality": "low",
        "output_format": "svg",
        "complexity": "low",
    }


def test_build_tool_returns_a_fresh_dict_each_call():
    first = build_tool(PRESETS["icon_png"], FLARE_25, "low")
    first["partial_images"] = 3
    first["model"] = "mutated"
    assert build_tool(PRESETS["icon_png"], FLARE_25, "low") == _expected_tool(
        "icon_png", FLARE_25, "low"
    )


# ---------------------------------------------------------------------------
# build_prompt (C8)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("preset_id", PRESET_IDS)
def test_build_prompt_keeps_the_user_prompt_then_appends_the_art_direction(preset_id):
    preset = PRESETS[preset_id]
    user_prompt = "A lighthouse on a rocky coast at dusk"

    prompt = build_prompt(user_prompt, preset)

    assert user_prompt in prompt
    assert preset.art_direction in prompt
    assert prompt.index(user_prompt) < prompt.index(preset.art_direction)


@pytest.mark.parametrize("preset_id", ICON_PRESET_IDS)
def test_icon_art_direction_carries_the_c8_rules(preset_id):
    direction = PRESETS[preset_id].art_direction.lower()
    for phrase in (
        "single",
        "centered",
        "flat",
        "stroke",
        "no text",
        "no glow",
        "no drop shadow",
        "no background tile",
        "padding",
    ):
        assert phrase in direction, phrase


def test_transparent_icon_art_direction_asks_for_transparency():
    assert "transparent" in PRESETS["icon_png"].art_direction.lower()


def test_background_art_direction_keeps_room_for_titles_and_has_no_text_or_logos():
    direction = PRESETS["background"].art_direction.lower()
    for phrase in ("negative space", "no text", "logo"):
        assert phrase in direction, phrase


# ---------------------------------------------------------------------------
# check_static_svg
# ---------------------------------------------------------------------------

_SVG_OK = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">'
    '<circle cx="32" cy="32" r="20" fill="#1b3139"/></svg>'
)


@pytest.mark.parametrize(
    "svg",
    [
        _SVG_OK,
        '<?xml version="1.0" encoding="UTF-8"?>\n' + _SVG_OK,
        '<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink">'
        '<defs><path id="a" d="M0 0h10v10z"/></defs><use href="#a"/><use xlink:href="#a"/></svg>',
        '<svg xmlns="http://www.w3.org/2000/svg"><text x="1" y="1">on time</text></svg>',
    ],
    ids=["plain", "xml-declaration", "internal-href", "text-saying-on"],
)
def test_check_static_svg_accepts_static_markup(svg):
    assert check_static_svg(svg) is None


@pytest.mark.parametrize(
    "svg",
    [
        '<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>',
        '<svg xmlns="http://www.w3.org/2000/svg"><SCRIPT href="x.js"/></svg>',
        '<svg xmlns="http://www.w3.org/2000/svg" onload="alert(1)"></svg>',
        '<svg xmlns="http://www.w3.org/2000/svg">'
        '<rect width="1" height="1" onclick = "x()"/></svg>',
        '<svg xmlns="http://www.w3.org/2000/svg"><foreignObject><div/></foreignObject></svg>',
        '<svg xmlns="http://www.w3.org/2000/svg"><image href="https://evil.example/a.png"/></svg>',
        "<svg xmlns=\"http://www.w3.org/2000/svg\"><image href='http://evil.example/a.png'/></svg>",
        '<svg xmlns="http://www.w3.org/2000/svg">'
        '<use xlink:href="http://evil.example/s.svg#x"/></svg>',
        '<svg xmlns="http://www.w3.org/2000/svg">'
        '<a href="javascript:alert(1)"><text>x</text></a></svg>',
        '<svg xmlns="http://www.w3.org/2000/svg"><image src="data:text/html;base64,PGI+"/></svg>',
    ],
    ids=[
        "script",
        "SCRIPT",
        "onload",
        "spaced-onclick",
        "foreignObject",
        "https-href",
        "single-quoted-http-href",
        "xlink-http-href",
        "javascript-href",
        "data-text-src",
    ],
)
def test_check_static_svg_rejects_scripts_handlers_and_external_references(svg):
    with pytest.raises(ValueError):
        check_static_svg(svg)


@pytest.mark.parametrize(
    "text",
    ["I'm sorry, I can't draw that.", "<html><body>hi</body></html>", ""],
    ids=["prose", "html", "empty"],
)
def test_check_static_svg_rejects_non_svg(text):
    with pytest.raises(ValueError):
        check_static_svg(text)


# ---------------------------------------------------------------------------
# strip_code_fences
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "```svg\n" + _SVG_OK + "\n```",
        "```xml\n" + _SVG_OK + "\n```",
        "```\n" + _SVG_OK + "\n```",
        "\n  ```svg\n" + _SVG_OK + "\n```\n  ",
        _SVG_OK,
    ],
    ids=["svg", "xml", "bare", "padded", "unfenced"],
)
def test_strip_code_fences_returns_the_inner_markup(text):
    assert strip_code_fences(text) == _SVG_OK


def test_strip_code_fences_keeps_multiline_content():
    inner = '<svg xmlns="http://www.w3.org/2000/svg">\n  <rect width="1" height="1"/>\n</svg>'
    assert strip_code_fences(f"```svg\n{inner}\n```") == inner


# ---------------------------------------------------------------------------
# to_data_url
# ---------------------------------------------------------------------------


def _palette_with_transparency() -> bytes:
    img = Image.new("P", (32, 32), 0)
    img.putpalette([255, 255, 255, 200, 30, 30] + [0, 0, 0] * 254)
    img.paste(1, (16, 0, 32, 32))
    return _encode(img, "PNG", transparency=0)


@pytest.mark.parametrize(
    "source",
    [
        _encode(_half_transparent((40, 24)), "PNG"),
        _encode(_half_transparent((40, 24), mode="LA"), "PNG"),
        _palette_with_transparency(),
    ],
    ids=["RGBA", "LA", "P+transparency"],
)
def test_to_data_url_keeps_alpha_sources_as_png_with_alpha(source):
    mime, decoded = _decode_data_url(to_data_url(source))
    assert mime == "image/png"
    assert decoded.format == "PNG"
    assert decoded.size == _decode(source).size
    assert _alpha_extrema(decoded.convert("RGBA")) == (0, 255)


@pytest.mark.parametrize("fmt", ["PNG", "JPEG"])
def test_to_data_url_sends_opaque_sources_as_jpeg(fmt):
    source = _encode(Image.new("RGB", (40, 24), (30, 90, 200)), fmt)
    mime, decoded = _decode_data_url(to_data_url(source))
    assert mime == "image/jpeg"
    assert decoded.format == "JPEG"
    assert decoded.size == (40, 24)


def test_to_data_url_bounds_the_longest_side():
    rgb = _encode(Image.new("RGB", (256, 128), (30, 90, 200)), "PNG")
    rgba = _encode(_half_transparent((128, 256)), "PNG")
    assert _decode_data_url(to_data_url(rgb, max_side=64))[1].size == (64, 32)
    assert _decode_data_url(to_data_url(rgba, max_side=64))[1].size == (32, 64)


def test_to_data_url_never_upscales_and_defaults_to_1536():
    small = _encode(Image.new("RGB", (40, 20), (1, 2, 3)), "PNG")
    wide = _encode(Image.new("RGB", (3072, 96), (1, 2, 3)), "PNG")
    assert _decode_data_url(to_data_url(small, max_side=64))[1].size == (40, 20)
    assert _decode_data_url(to_data_url(wide))[1].size == (1536, 48)


# ---------------------------------------------------------------------------
# fit_to_library
# ---------------------------------------------------------------------------


def test_fit_to_library_defaults_to_the_library_cap():
    assert (
        inspect.signature(fit_to_library).parameters["max_bytes"].default
        == image_service.MAX_FILE_SIZE
    )


def test_a_small_png_passes_through_untouched():
    raw = _encode(_half_transparent((40, 24)), "PNG")
    assert fit_to_library(raw) == (raw, "image/png", "png")


def test_a_small_jpeg_passes_through_untouched():
    raw = _encode(Image.new("RGB", (40, 24), (200, 180, 40)), "JPEG", quality=90)
    assert fit_to_library(raw) == (raw, "image/jpeg", "jpg")


def test_jpeg_bytes_are_labelled_jpeg_whatever_was_asked_for():
    raw = _encode(_noise((64, 48), "RGB"), "JPEG", quality=90)
    data, mime, ext = fit_to_library(raw)
    assert (mime, ext) == ("image/jpeg", "jpg")
    assert _decode(data).format == "JPEG"


def _assert_shrunk_to_fit(raw: bytes, max_bytes: int, size: tuple[int, int]) -> Image.Image:
    assert len(raw) > max_bytes, "precondition: the input is over the cap"
    data, mime, ext = fit_to_library(raw, max_bytes=max_bytes)
    assert len(data) <= max_bytes
    decoded = _assert_library_ready(data, mime, ext)
    w, h = decoded.size
    assert w >= size[0] // 4, f"shrunk far more than needed: {decoded.size}"
    assert abs(w / h - size[0] / size[1]) < 0.05, f"aspect ratio changed: {decoded.size}"
    return decoded


def test_an_over_cap_opaque_png_is_shrunk_under_the_cap():
    size = (240, 160)
    _assert_shrunk_to_fit(_encode(_noise(size, "RGB"), "PNG"), 30_000, size)


def test_an_over_cap_transparent_png_is_shrunk_under_the_cap_and_keeps_alpha():
    size = (240, 160)
    decoded = _assert_shrunk_to_fit(_encode(_noise(size, "RGBA"), "PNG"), 30_000, size)
    assert decoded.format == "PNG"
    assert _alpha_extrema(decoded) == (0, 255)


def test_an_over_cap_jpeg_stays_jpeg_under_the_cap():
    size = (320, 240)
    decoded = _assert_shrunk_to_fit(_encode(_noise(size, "RGB"), "JPEG", quality=95), 30_000, size)
    assert decoded.format == "JPEG"


def test_webp_with_alpha_becomes_png_with_alpha():
    raw = _encode(_half_transparent((40, 24)), "WEBP", lossless=True)
    data, mime, ext = fit_to_library(raw)
    decoded = _assert_library_ready(data, mime, ext)
    assert (mime, ext) == ("image/png", "png")
    assert decoded.size == (40, 24)
    assert _alpha_extrema(decoded) == (0, 255)


def test_webp_without_alpha_becomes_jpeg():
    raw = _encode(Image.new("RGB", (40, 24), (30, 90, 200)), "WEBP", quality=90)
    data, mime, ext = fit_to_library(raw)
    decoded = _assert_library_ready(data, mime, ext)
    assert (mime, ext) == ("image/jpeg", "jpg")
    assert decoded.size == (40, 24)


# ---------------------------------------------------------------------------
# generated_filename
# ---------------------------------------------------------------------------

_FILENAME = re.compile(
    r"(?P<prefix>[a-z0-9-]+?)-(?P<slug>[a-z0-9_-]{1,40})-(?P<stamp>\d{8}T\d{6}Z)-(?P<hex>[0-9a-f]{8})\.(?P<ext>[a-z]+)"
)


def _parts(name: str) -> dict[str, str]:
    match = _FILENAME.fullmatch(name)
    assert match, name
    return match.groupdict()


def test_generated_filename_format():
    before = datetime.now(timezone.utc).replace(microsecond=0)
    name = generated_filename("A Red Fox, jumping!", "png")
    after = datetime.now(timezone.utc)

    assert name.startswith("ai-a-red-fox-jumping-")
    parts = _parts(name)
    assert (parts["prefix"], parts["slug"], parts["ext"]) == ("ai", "a-red-fox-jumping", "png")
    stamp = datetime.strptime(parts["stamp"], "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
    assert before - timedelta(seconds=1) <= stamp <= after


def test_generated_filename_custom_prefix_and_ext():
    name = generated_filename("Make it blue", "jpg", prefix="ai-edit")
    assert name.startswith("ai-edit-make-it-blue-")
    assert name.endswith(".jpg")
    assert _FILENAME.fullmatch(name)


@pytest.mark.parametrize(
    "prompt",
    ["word " * 40, "../../etc/passwd", "Café ☕ résumé", "!!!", "UPPER_case and-dashes"],
)
def test_generated_filename_is_a_safe_bounded_slug(prompt):
    name = generated_filename(prompt, "svg")
    parts = _parts(name)
    assert parts["prefix"] == "ai"
    assert 1 <= len(parts["slug"]) <= 40
    assert "/" not in name and "\\" not in name and name.count(".") == 1
    assert name.endswith(".svg")


def test_generated_filenames_do_not_collide():
    names = {generated_filename("same prompt", "png") for _ in range(200)}
    assert len(names) == 200


# ---------------------------------------------------------------------------
# Defaults and explainers (user request, 2026-11-08: "let's not default to Low")
# ---------------------------------------------------------------------------


def test_every_preset_defaults_to_the_recommended_model_at_medium():
    # measured live: 2.6 Flare is the fastest (8-14 s) with clean slide output; medium adds
    # detail at about the same speed as low
    for preset in PRESETS.values():
        assert (preset.default_model, preset.default_quality) == (FLARE_26, "medium"), preset.id


def test_the_recommended_model_says_so_and_every_model_explains_when_to_choose_it():
    assert "recommended" in IMAGE_MODELS[FLARE_26].label.lower()
    for spec in IMAGE_MODELS.values():
        # a "when to choose this" explainer, not a capability tag line
        assert len(spec.description) >= 60, (spec.id, spec.description)
    labels = [spec.label for spec in IMAGE_MODELS.values()]
    assert sum("recommended" in label.lower() for label in labels) == 1


def test_every_quality_has_an_explainer():
    from src.services.image_generation import QUALITY_DESCRIPTIONS

    assert list(QUALITY_DESCRIPTIONS) == list(QUALITIES)
    assert all(len(text) >= 20 for text in QUALITY_DESCRIPTIONS.values())
    assert "recommended" in QUALITY_DESCRIPTIONS["medium"].lower()
