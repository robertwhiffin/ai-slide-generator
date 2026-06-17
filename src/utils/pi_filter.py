"""Heuristic prompt-injection blocklist (AISEC-248 PR2).

High-precision patterns only: they target attempts to override the agent's
instructions, not ordinary slide-editing phrasing ("ignore the previous layout").
"""

import re
from typing import List

_PATTERNS = [
    ("override-instructions",
     re.compile(r"\bignore\s+(?:all\s+|any\s+)?(?:previous|prior|above|earlier)\s+instructions\b", re.I)),
    ("disregard-rules",
     re.compile(r"\bdisregard\s+(?:your|the|all)\s+(?:rules|instructions|guidelines)\b", re.I)),
    ("role-override",
     re.compile(r"\byou\s+are\s+now\s+(?:a|an|the)\b", re.I)),
    ("system-prefix",
     re.compile(r"(?m)^\s*system\s*:", re.I)),
    ("instruction-header",
     re.compile(r"#{2,3}\s*INSTRUCTION", re.I)),
    ("reveal-system-prompt",
     re.compile(r"\b(?:reveal|print|show|repeat)\s+(?:the\s+)?system\s+prompt\b", re.I)),
]


def scan_for_injection(text: str) -> List[str]:
    """Return labels of matched injection patterns; empty list means clean."""
    if not text:
        return []
    return [label for label, pattern in _PATTERNS if pattern.search(text)]
