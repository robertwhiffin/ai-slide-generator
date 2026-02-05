"""JavaScript syntax validation utilities.

RC5: Validates and attempts to fix JavaScript syntax errors in slide scripts.
"""

import logging
from typing import Tuple

logger = logging.getLogger(__name__)


def validate_javascript(script: str) -> Tuple[bool, str]:
    """Validate JavaScript syntax using esprima.
    
    Args:
        script: JavaScript code to validate
        
    Returns:
        Tuple of (is_valid, error_message)
    """
    if not script or not script.strip():
        return True, ""  # Empty script is valid
    
    try:
        import esprima
    except ImportError:
        logger.warning("esprima not installed, skipping JS validation")
        return True, ""  # Be permissive if esprima not available
    
    try:
        esprima.parseScript(script, tolerant=True)
        return True, ""
    except esprima.Error as e:
        return False, f"JavaScript syntax error: {e}"
    except Exception as e:
        logger.warning(f"JS validation failed with unexpected error: {e}")
        # Be permissive on unexpected errors - don't block
        return True, ""


def try_fix_common_js_errors(script: str) -> str:
    """Attempt to fix common JavaScript syntax errors.
    
    Args:
        script: JavaScript code that may have errors
        
    Returns:
        Fixed script (or original if no fixes applied)
    """
    if not script:
        return script
    
    fixed = script
    
    # Fix unclosed braces (simple heuristic)
    open_braces = fixed.count('{')
    close_braces = fixed.count('}')
    if open_braces > close_braces:
        fixed += '\n}' * (open_braces - close_braces)
    
    # Fix unclosed parentheses
    open_parens = fixed.count('(')
    close_parens = fixed.count(')')
    if open_parens > close_parens:
        fixed += ')' * (open_parens - close_parens)
    
    # Fix unclosed brackets
    open_brackets = fixed.count('[')
    close_brackets = fixed.count(']')
    if open_brackets > close_brackets:
        fixed += ']' * (open_brackets - close_brackets)
    
    return fixed


def validate_and_fix_javascript(script: str) -> Tuple[str, bool, str]:
    """Validate JavaScript and attempt to fix if invalid.
    
    Args:
        script: JavaScript code to validate
        
    Returns:
        Tuple of (fixed_script, was_fixed, error_message)
        - fixed_script: The script (possibly fixed)
        - was_fixed: True if fixes were applied
        - error_message: Error message if validation failed and couldn't be fixed
    """
    if not script or not script.strip():
        return script, False, ""
    
    # First, check if script is already valid
    is_valid, error = validate_javascript(script)
    if is_valid:
        return script, False, ""
    
    # Try to fix common errors
    fixed_script = try_fix_common_js_errors(script)
    
    # Re-validate after fix attempt
    is_valid_after_fix, _ = validate_javascript(fixed_script)
    if is_valid_after_fix:
        logger.info("Successfully fixed JavaScript syntax errors")
        return fixed_script, True, ""
    
    # Could not fix - return original with error
    return script, False, error
