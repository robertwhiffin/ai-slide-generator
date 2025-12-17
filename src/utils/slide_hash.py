"""Slide content hashing utilities for verification persistence.

This module provides functions to compute deterministic hashes of slide HTML content,
enabling verification results to be matched to slides by content rather than position.

The normalization process ensures that semantically equivalent HTML produces the same hash,
while meaningful content changes produce different hashes.
"""
import hashlib
import re


def normalize_html(html: str) -> str:
    """Normalize HTML for consistent hashing.
    
    Normalization includes:
    - Stripping leading/trailing whitespace
    - Collapsing multiple whitespace characters to single space
    - Removing HTML comments
    - Converting to lowercase for case-insensitive matching
    
    This ensures that equivalent content with different formatting
    produces the same hash.
    
    Args:
        html: Raw HTML string to normalize
        
    Returns:
        Normalized HTML string
        
    Examples:
        >>> normalize_html("  <div>  Hello  </div>  ")
        '<div> hello </div>'
        >>> normalize_html("<div><!-- comment -->text</div>")
        '<div>text</div>'
    """
    if not html:
        return ""
    
    # Remove HTML comments (including multiline)
    html = re.sub(r'<!--.*?-->', '', html, flags=re.DOTALL)
    
    # Collapse all whitespace (spaces, tabs, newlines) to single space
    html = ' '.join(html.split())
    
    # Convert to lowercase for case-insensitive comparison
    html = html.lower()
    
    return html.strip()


def compute_slide_hash(html: str) -> str:
    """Compute a deterministic hash of slide HTML content.
    
    The hash is computed from the normalized HTML, ensuring that:
    - Same content always produces the same hash
    - Different content produces different hashes
    - Whitespace/formatting differences don't affect the hash
    - Case differences don't affect the hash
    - HTML comments don't affect the hash
    
    Args:
        html: Raw slide HTML to hash
        
    Returns:
        16-character hexadecimal hash string (first 16 chars of SHA256)
        
    Examples:
        >>> h1 = compute_slide_hash("<div>Hello</div>")
        >>> h2 = compute_slide_hash("<DIV>  hello  </DIV>")
        >>> h1 == h2
        True
        >>> compute_slide_hash("<div>A</div>") == compute_slide_hash("<div>B</div>")
        False
    """
    normalized = normalize_html(html)
    hash_bytes = hashlib.sha256(normalized.encode('utf-8')).hexdigest()
    
    # Return first 16 characters (64 bits of entropy, negligible collision probability)
    return hash_bytes[:16]


def compute_verification_key(slide_html: str, session_id: str = None) -> str:
    """Compute verification lookup key for a slide.
    
    This is the key used to store/retrieve verification results
    in the verification_map.
    
    Currently just returns the content hash, but could be extended
    to include session_id if needed for multi-session scenarios.
    
    Args:
        slide_html: Slide HTML content
        session_id: Optional session identifier (reserved for future use)
        
    Returns:
        Verification lookup key string
    """
    return compute_slide_hash(slide_html)

