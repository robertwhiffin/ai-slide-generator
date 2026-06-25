"""Shared spotlighting wrapper for untrusted tool output (AISEC-248).

Every tool's return value flows through ``spotlight`` so the model is told the
content is data, not instructions. It also caps length and neutralizes the
``<untrusted-data>`` delimiters inside the payload so untrusted text cannot
break out of the wrapper (review finding #7).
"""

import logging
import re
from typing import Optional

from src.utils.pi_filter import scan_for_injection
from src.utils.text_caps import cap_tool_output

logger = logging.getLogger(__name__)

_CLOSE = re.compile(r"<\s*/\s*untrusted-data\s*>", re.IGNORECASE)
_OPEN = re.compile(r"<\s*untrusted-data\b", re.IGNORECASE)


def spotlight(
    source: str,
    text: str,
    *,
    scan: bool = True,
    session_id: Optional[str] = None,
) -> str:
    """Wrap untrusted tool output as spotlighted data."""
    capped = cap_tool_output(str(text))

    # Neutralize delimiter injection: a payload must not be able to emit a
    # real <untrusted-data> opener/closer and break out of the wrapper.
    safe = _CLOSE.sub("&lt;/untrusted-data&gt;", capped)
    safe = _OPEN.sub("&lt;untrusted-data", safe)

    if scan:
        hits = scan_for_injection(capped)
        if hits:
            logger.warning(
                "Injection patterns in tool output (flagged, not blocked)",
                extra={"source": source, "patterns": hits, "session_id": session_id},
            )

    return f'<untrusted-data source="{source}">\n{safe}\n</untrusted-data>'
