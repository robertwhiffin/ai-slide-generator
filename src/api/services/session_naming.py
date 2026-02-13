"""Smart session naming via LLM analysis of the initial user prompt.

Generates a concise, descriptive title for a session based on the user's
first message. Called once per session (on first message only).
"""

import logging
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


def generate_session_title(
    user_message: str,
    model,
) -> Optional[str]:
    """Generate a descriptive session title from the user's first message.

    Args:
        user_message: The user's first chat message.
        model: A LangChain-compatible chat model (e.g. ChatDatabricks).

    Returns:
        A short title string, or None if generation fails.
    """
    try:
        response = model.invoke([
            SystemMessage(content=TITLE_GENERATION_PROMPT),
            HumanMessage(content=user_message),
        ])

        title = response.content.strip().strip('"\'')

        if not title:
            return None

        if len(title) > MAX_TITLE_LENGTH:
            title = title[:MAX_TITLE_LENGTH]

        return title

    except Exception:
        logger.warning(
            "Failed to generate session title",
            extra={"message_preview": user_message[:80]},
            exc_info=True,
        )
        return None
