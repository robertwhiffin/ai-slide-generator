"""Smart session naming via LLM analysis of the initial user prompt.

Generates a concise, descriptive title for a session based on the user's
first message. Called once per session (on first message only).
"""

import logging
import re
from typing import Optional

from langchain_core.messages import HumanMessage, SystemMessage

logger = logging.getLogger(__name__)

TITLE_GENERATION_PROMPT = (
    "Generate a concise 3-8 word title for a presentation session based on "
    "the user's request below. Return ONLY the title text — no quotes, no "
    "punctuation wrapping, no explanation. Do not use Markdown. Keep it short and concise."
    "An example of a good title is 'Q3 Revenue Analysis'."
    "An example of a bad title is 'Detailed revenue analysis for Q3.'."
    ""
)

MAX_TITLE_LENGTH = 100

# Complete reasoning blocks the naming model may prepend despite the prompt.
_THINKING_BLOCK_RE = re.compile(
    r"<\s*(thinking|think|reasoning|reflection)\b[^>]*>.*?<\s*/\s*\1\s*>",
    re.IGNORECASE | re.DOTALL,
)
# An UNCLOSED reasoning tag: the naming call runs with a small max_tokens, so
# an overrunning model gets cut mid-thought and everything from the tag on is
# reasoning junk, never a title.
_UNCLOSED_THINKING_RE = re.compile(
    r"<\s*(thinking|think|reasoning|reflection)\b[^>]*>.*",
    re.IGNORECASE | re.DOTALL,
)
_MARKUP_TAG_RE = re.compile(r"<[^>]*>")


def _sanitize_title(raw: str) -> Optional[str]:
    """Reduce a naming-model response to a clean one-line title, or ``None``.

    Strips complete and truncation-orphaned reasoning blocks, then any other
    markup tags, takes the FIRST non-empty line, and unwraps quote/Markdown
    decoration. A result longer than ``MAX_TITLE_LENGTH`` means the model
    overran the title format entirely — that is junk, not a title, so it is
    REJECTED (the caller keeps the session's default name) rather than
    truncated into garbage.
    """
    text = _THINKING_BLOCK_RE.sub(" ", raw or "")
    text = _UNCLOSED_THINKING_RE.sub(" ", text)
    text = _MARKUP_TAG_RE.sub(" ", text)

    first_line = next(
        (line.strip() for line in text.splitlines() if line.strip()), ""
    )
    title = first_line.strip().strip("\"'").strip("*_#` ").strip()
    if not title:
        return None
    if len(title) > MAX_TITLE_LENGTH:
        return None
    return title


def generate_session_title(
    user_message: str,
    model,
) -> Optional[str]:
    """Generate a descriptive session title from the user's first message.

    Args:
        user_message: The user's first chat message.
        model: A LangChain-compatible chat model (e.g. ChatDatabricks).

    Returns:
        A short title string, or None if generation fails (the caller then
        keeps the session's default name).
    """
    try:
        response = model.invoke([
            SystemMessage(content=TITLE_GENERATION_PROMPT),
            HumanMessage(content=user_message),
        ])

        content = response.content
        if not isinstance(content, str):
            # Some chat models return content blocks; keep only the text ones.
            content = " ".join(
                block.get("text", "") if isinstance(block, dict) else str(block)
                for block in (content or [])
            )
        return _sanitize_title(content)

    except Exception:
        logger.warning(
            "Failed to generate session title",
            extra={"message_preview": user_message[:80]},
            exc_info=True,
        )
        return None
