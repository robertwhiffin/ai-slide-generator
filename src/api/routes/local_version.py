"""Local version check endpoint.

Checks GitHub releases for newer versions of the ai-slide-generator repo.
This is separate from the PyPI version check (version.py) which serves
Databricks App deployments. This endpoint serves local installations
(both Homebrew and git-clone).
"""

import logging
import time
from pathlib import Path
from typing import Optional

import httpx
from fastapi import APIRouter
from packaging.version import InvalidVersion, Version
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/version", tags=["version"])

# Cache for GitHub releases lookups
_github_cache: dict = {
    "version": None,
    "timestamp": 0,
}
CACHE_TTL_SECONDS = 3600  # 1 hour

GITHUB_REPO = "robertwhiffin/ai-slide-generator"
GITHUB_RELEASES_URL = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"


class LocalVersionCheckResponse(BaseModel):
    """Response model for local version check endpoint."""

    installed_version: str
    latest_version: Optional[str] = None
    update_available: bool = False
    update_command: str = "brew upgrade tellr"  # overridden at runtime
    release_url: Optional[str] = None


def _get_local_version() -> str:
    """Get the locally installed version from package __version__.

    Returns:
        Version string (e.g., "0.1.0") or "unknown"
    """
    try:
        from src import __version__

        return __version__
    except ImportError:
        logger.warning("Could not import __version__ from src")
        return "unknown"


def _get_latest_github_release() -> Optional[dict]:
    """Fetch the latest release from GitHub with caching.

    Returns:
        Dict with 'tag_name' and 'html_url' or None if fetch fails
    """
    global _github_cache

    # Check cache
    now = time.time()
    if _github_cache["version"] and (now - _github_cache["timestamp"]) < CACHE_TTL_SECONDS:
        return _github_cache["version"]

    try:
        with httpx.Client(timeout=10.0) as client:
            response = client.get(
                GITHUB_RELEASES_URL,
                headers={"Accept": "application/vnd.github.v3+json"},
            )
            if response.status_code == 404:
                # No releases yet
                logger.info("No GitHub releases found for %s", GITHUB_REPO)
                return None

            response.raise_for_status()
            data = response.json()
            release_info = {
                "tag_name": data.get("tag_name", ""),
                "html_url": data.get("html_url", ""),
            }

            # Update cache
            _github_cache["version"] = release_info
            _github_cache["timestamp"] = now

            return release_info

    except httpx.HTTPError as e:
        logger.warning(f"Failed to fetch latest release from GitHub: {e}")
        return _github_cache.get("version")  # Return stale cache if available
    except Exception as e:
        logger.warning(f"Unexpected error fetching GitHub release: {e}")
        return _github_cache.get("version")


def _parse_version_tag(tag: str) -> Optional[str]:
    """Extract a clean version string from a git tag.

    Handles tags like 'v1.0.0', '1.0.0', 'v0.2.0-beta', etc.

    Returns:
        Clean version string or None if unparseable
    """
    tag = tag.strip().lstrip("v")
    try:
        Version(tag)
        return tag
    except InvalidVersion:
        return None


def _is_update_available(installed: str, latest: str) -> bool:
    """Check if the latest version is newer than installed."""
    try:
        return Version(latest) > Version(installed)
    except InvalidVersion:
        return False


def _is_homebrew_install() -> bool:
    """Detect whether the app was installed via Homebrew.

    Checks for the Homebrew Cellar path which only exists for
    Homebrew-managed installations.
    """
    homebrew_paths = [
        Path("/opt/homebrew/Cellar/tellr"),   # Apple Silicon
        Path("/usr/local/Cellar/tellr"),       # Intel Mac
    ]
    return any(p.exists() for p in homebrew_paths)


def _get_update_command() -> str:
    """Return the appropriate update command based on install method."""
    if _is_homebrew_install():
        return "brew upgrade tellr"
    return "git pull && ./start_app.sh"


@router.get("/local-check", response_model=LocalVersionCheckResponse)
async def check_local_version() -> LocalVersionCheckResponse:
    """Check for available updates for local installations.

    Compares the locally running version against the latest GitHub release.
    Returns update info with the appropriate upgrade command based on
    whether the app was installed via Homebrew or git clone.
    """
    installed = _get_local_version()
    release = _get_latest_github_release()

    latest_version = None
    update_available = False
    release_url = None
    update_command = _get_update_command()

    if release:
        tag = release.get("tag_name", "")
        latest_version = _parse_version_tag(tag)
        release_url = release.get("html_url")

        if installed != "unknown" and latest_version:
            update_available = _is_update_available(installed, latest_version)

    return LocalVersionCheckResponse(
        installed_version=installed,
        latest_version=latest_version,
        update_available=update_available,
        update_command=update_command,
        release_url=release_url,
    )
