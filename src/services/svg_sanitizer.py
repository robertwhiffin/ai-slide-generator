"""Server-side sanitization for SVG images before they are stored."""

from __future__ import annotations

import re
from urllib.parse import urlsplit

from lxml import etree  # type: ignore[import-untyped]

SVG_NAMESPACE = "http://www.w3.org/2000/svg"

_ALLOWED_ELEMENTS = frozenset(
    {
        "svg",
        "g",
        "defs",
        "symbol",
        "use",
        "title",
        "desc",
        "switch",
        "view",
        "path",
        "rect",
        "circle",
        "ellipse",
        "line",
        "polyline",
        "polygon",
        "text",
        "tspan",
        "textPath",
        "a",
        "image",
        "style",
        "linearGradient",
        "radialGradient",
        "stop",
        "pattern",
        "marker",
        "mask",
        "clipPath",
        "filter",
        "feBlend",
        "feColorMatrix",
        "feComponentTransfer",
        "feComposite",
        "feConvolveMatrix",
        "feDiffuseLighting",
        "feDisplacementMap",
        "feDistantLight",
        "feDropShadow",
        "feFlood",
        "feFuncA",
        "feFuncB",
        "feFuncG",
        "feFuncR",
        "feGaussianBlur",
        "feImage",
        "feMerge",
        "feMergeNode",
        "feMorphology",
        "feOffset",
        "fePointLight",
        "feSpecularLighting",
        "feSpotLight",
        "feTile",
        "feTurbulence",
        "animate",
        "animateMotion",
        "animateTransform",
        "set",
        "mpath",
    }
)

_ALLOWED_ATTRIBUTES = frozenset(
    {
        "id",
        "class",
        "style",
        "transform",
        "transform-origin",
        "clip-path",
        "clip-rule",
        "mask",
        "filter",
        "opacity",
        "fill",
        "fill-opacity",
        "fill-rule",
        "stroke",
        "stroke-dasharray",
        "stroke-dashoffset",
        "stroke-linecap",
        "stroke-linejoin",
        "stroke-miterlimit",
        "stroke-opacity",
        "stroke-width",
        "paint-order",
        "color",
        "color-interpolation",
        "color-interpolation-filters",
        "display",
        "visibility",
        "systemLanguage",
        "requiredFeatures",
        "requiredExtensions",
        "lang",
        "space",
        "role",
        "tabindex",
        "version",
        "baseProfile",
        "width",
        "height",
        "viewBox",
        "preserveAspectRatio",
        "x",
        "y",
        "dx",
        "dy",
        "zoomAndPan",
        "d",
        "points",
        "rx",
        "ry",
        "cx",
        "cy",
        "r",
        "x1",
        "x2",
        "y1",
        "y2",
        "rotate",
        "textLength",
        "lengthAdjust",
        "font-family",
        "font-size",
        "font-style",
        "font-variant",
        "font-weight",
        "letter-spacing",
        "word-spacing",
        "text-decoration",
        "text-anchor",
        "dominant-baseline",
        "alignment-baseline",
        "baseline-shift",
        "writing-mode",
        "gradientUnits",
        "gradientTransform",
        "spreadMethod",
        "href",
        "offset",
        "stop-color",
        "stop-opacity",
        "patternUnits",
        "patternContentUnits",
        "patternTransform",
        "markerWidth",
        "markerHeight",
        "markerUnits",
        "refX",
        "refY",
        "orient",
        "clipPathUnits",
        "maskUnits",
        "maskContentUnits",
        "filterUnits",
        "primitiveUnits",
        "in",
        "in2",
        "result",
        "mode",
        "values",
        "type",
        "tableValues",
        "slope",
        "intercept",
        "amplitude",
        "exponent",
        "k1",
        "k2",
        "k3",
        "k4",
        "operator",
        "radius",
        "stdDeviation",
        "xChannelSelector",
        "yChannelSelector",
        "scale",
        "flood-color",
        "flood-opacity",
        "kernelMatrix",
        "divisor",
        "bias",
        "targetX",
        "targetY",
        "edgeMode",
        "kernelUnitLength",
        "preserveAlpha",
        "lighting-color",
        "surfaceScale",
        "diffuseConstant",
        "specularConstant",
        "specularExponent",
        "pointsAtX",
        "pointsAtY",
        "pointsAtZ",
        "limitingConeAngle",
        "azimuth",
        "elevation",
        "seed",
        "numOctaves",
        "baseFrequency",
        "stitchTiles",
        "attributeName",
        "attributeType",
        "begin",
        "end",
        "dur",
        "repeatCount",
        "repeatDur",
        "from",
        "to",
        "by",
        "keyTimes",
        "keySplines",
        "keyPoints",
        "calcMode",
        "additive",
        "accumulate",
        "path",
        "startOffset",
        "method",
        "spacing",
        "crossorigin",
        "decoding",
        "loading",
        "target",
        "download",
        "rel",
    }
)

_URL_ATTRIBUTES = frozenset({"href"})
_ANIMATION_ELEMENTS = frozenset({"animate", "animateMotion", "animateTransform", "set"})
_ANIMATION_FORBIDDEN_TARGETS = frozenset({"href", "style"})
_SAFE_DATA_IMAGE_TYPES = frozenset({"png", "jpeg", "jpg", "gif", "webp"})
_UNSAFE_URL_PATTERN = re.compile(
    r"(?:javascript|vbscript|livescript|mocha):|data:image/svg\+xml",
    re.IGNORECASE,
)


def _local_name(value: str) -> str:
    return value.rsplit("}", 1)[-1].rsplit(":", 1)[-1]


def _element_local_name(element: etree._Element) -> str:
    return etree.QName(element).localname


def _is_allowed_element(element: etree._Element) -> bool:
    return _element_local_name(element) in _ALLOWED_ELEMENTS


def _normalized_url(value: str) -> str:
    characters = (character for character in value if character not in "\t\n\r\f\v")
    return "".join(characters).strip()


def _is_safe_url(value: str) -> bool:
    normalized = _normalized_url(value)
    if not normalized or normalized.startswith("#"):
        return True

    parsed = urlsplit(normalized)
    scheme = parsed.scheme.lower()
    if not scheme or scheme in {"http", "https", "mailto"}:
        return True
    if scheme != "data":
        return False

    media_type = parsed.path.split(";", 1)[0].lower()
    image_type = media_type.removeprefix("image/")
    return image_type in _SAFE_DATA_IMAGE_TYPES


def _has_external_use_reference(element: etree._Element) -> bool:
    return any(
        _local_name(name) == "href" and not _normalized_url(value).startswith("#")
        for name, value in element.attrib.items()
    )


def _animation_targets_forbidden_attribute(element: etree._Element) -> bool:
    target = element.get("attributeName")
    if target is None:
        return False
    local_target = _local_name(target)
    return local_target.startswith("on") or local_target in _ANIMATION_FORBIDDEN_TARGETS


def _contains_unsafe_url(value: str) -> bool:
    return _UNSAFE_URL_PATTERN.search(_normalized_url(value)) is not None


def _sanitize_attributes(root: etree._Element) -> None:
    for element in root.iter():
        for name, value in list(element.attrib.items()):
            local_name = _local_name(name)
            if local_name not in _ALLOWED_ATTRIBUTES:
                del element.attrib[name]
                continue
            if local_name in _URL_ATTRIBUTES and not _is_safe_url(value):
                del element.attrib[name]
            elif local_name == "style" and _contains_unsafe_url(value):
                del element.attrib[name]

        if _element_local_name(element) == "style" and _contains_unsafe_url(
            element.text or ""
        ):
            element.text = None


_RASTER_MAGICS = (
    b"\x89PNG\r\n\x1a\n",
    b"\xff\xd8\xff",
    b"GIF87a",
    b"GIF89a",
)
_SNIFF_WINDOW = 4096
# An SVG document: optional BOM/whitespace, any XML prolog (declaration, comments,
# PIs, DOCTYPE with optional internal subset), then ``<svg`` as the ROOT element.
# Anchoring on the root (not a substring) keeps CSS/HTML/text that merely mentions
# ``<svg`` (e.g. a ``data:image/svg+xml,<svg ...>`` URI) from being treated as SVG.
_SVG_ROOT_RE = re.compile(
    r"\A\ufeff?\s*"
    r"(?:<\?.*?\?>\s*|<!--.*?-->\s*|<!DOCTYPE(?:[^>\[]|\[.*?\])*>\s*)*"
    r"<(?:[\w.-]+:)?svg[\s/>]",
    re.IGNORECASE | re.DOTALL,
)


def looks_like_svg(content: bytes) -> bool:
    """Content sniff: True if the bytes look like an SVG document.

    Used so a client-declared MIME type (e.g. ``image/png``) is never trusted
    to decide whether sanitization is needed. Content that starts with a known
    raster magic number is not SVG; otherwise it is SVG only if ``<svg`` is the
    root element (after any XML prolog) within the first few KB (UTF-8/ASCII or
    BOM-marked UTF-16).
    """
    head = content[:_SNIFF_WINDOW]
    if head.startswith(_RASTER_MAGICS):
        return False
    if head.startswith((b"\xff\xfe", b"\xfe\xff")):
        text = head.decode("utf-16", errors="ignore")
    else:
        text = head.decode("utf-8", errors="ignore")
    return _SVG_ROOT_RE.match(text) is not None


def sanitize_svg(content: bytes) -> bytes:
    """Return a sanitized SVG, rejecting malformed or non-SVG XML input."""
    parser = etree.XMLParser(
        resolve_entities=False,
        no_network=True,
        load_dtd=False,
        huge_tree=False,
        remove_comments=True,
        remove_pis=True,
    )

    try:
        root = etree.fromstring(content, parser=parser)
    except etree.XMLSyntaxError as exc:
        raise ValueError("SVG must be well-formed XML") from exc

    if root is None:
        raise ValueError("SVG document is empty")

    root_qname = etree.QName(root)
    if root_qname.localname != "svg" or root_qname.namespace not in {None, SVG_NAMESPACE}:
        raise ValueError("SVG root element is required")

    if root.getroottree().docinfo.doctype:
        raise ValueError("SVG DOCTYPE declarations are not allowed")

    elements_to_remove = []
    for element in root.iter():
        if element is root:
            continue

        local_name = _element_local_name(element)
        if not _is_allowed_element(element):
            elements_to_remove.append(element)
        elif local_name == "use" and _has_external_use_reference(element):
            elements_to_remove.append(element)
        elif local_name in _ANIMATION_ELEMENTS and _animation_targets_forbidden_attribute(
            element
        ):
            elements_to_remove.append(element)

    for element in elements_to_remove:
        parent = element.getparent()
        if parent is not None:
            parent.remove(element)

    _sanitize_attributes(root)

    return etree.tostring(root, encoding="utf-8", xml_declaration=True)
