"""CSS parsing and merging utilities for slide deck editing."""
from __future__ import annotations

from typing import Dict, Optional

import tinycss2


def parse_css_rules(css_text: Optional[str]) -> Dict[str, str]:
    """Parse CSS into a dict of {selector: declarations}.
    
    Args:
        css_text: Raw CSS string
        
    Returns:
        Dictionary mapping selectors to their declaration blocks
        
    Example:
        >>> parse_css_rules(".box { color: red; }")
        {'.box': 'color: red;'}
    """
    rules: Dict[str, str] = {}
    if not css_text:
        return rules
    
    try:
        parsed = tinycss2.parse_stylesheet(css_text, skip_whitespace=True)
        for rule in parsed:
            if rule.type == 'qualified-rule':
                selector = tinycss2.serialize(rule.prelude).strip()
                declarations = tinycss2.serialize(rule.content).strip()
                rules[selector] = declarations
    except Exception:
        # If parsing fails, return empty dict rather than crashing
        # The original CSS will be preserved
        pass
    
    return rules


def merge_css(existing_css: str, replacement_css: str) -> str:
    """Merge replacement CSS rules into existing CSS.
    
    Merge behavior:
        - Rules in replacement_css override matching selectors in existing_css
        - New selectors from replacement_css are appended
        - Existing selectors not in replacement_css are preserved
    
    Args:
        existing_css: Current deck CSS
        replacement_css: CSS from LLM edit response
        
    Returns:
        Merged CSS string
        
    Example:
        >>> existing = ".box { color: red; } .card { padding: 10px; }"
        >>> replacement = ".box { color: blue; }"
        >>> merge_css(existing, replacement)
        '.box { color: blue; }\\n\\n.card { padding: 10px; }'
    """
    existing_rules = parse_css_rules(existing_css)
    replacement_rules = parse_css_rules(replacement_css)
    
    if not replacement_rules:
        # Parsing failed or empty, return original unchanged
        return existing_css
    
    # Update existing with replacement (override matching, add new)
    existing_rules.update(replacement_rules)
    
    # Reconstruct CSS with consistent formatting
    css_parts = []
    for selector, declarations in existing_rules.items():
        css_parts.append(f"{selector} {{\n{declarations}\n}}")
    
    return '\n\n'.join(css_parts)

