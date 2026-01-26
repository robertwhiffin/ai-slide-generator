"""Version check endpoint for update notifications.

Checks PyPI for newer versions of databricks-tellr-app and classifies
update type (patch vs major) to provide appropriate user messaging.
"""

import logging
import time
from importlib import metadata
from typing import Optional

import httpx
from fastapi import APIRouter
from packaging.version import Version, InvalidVersion
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/version", tags=["version"])

# Cache for PyPI lookups (avoid rate limiting)
_pypi_cache: dict = {
    "version": None,
    "timestamp": 0,
}
CACHE_TTL_SECONDS = 3600  # 1 hour

PACKAGE_NAME = "databricks-tellr-app"
PYPI_URL = f"https://pypi.org/pypi/{PACKAGE_NAME}/json"


class VersionCheckResponse(BaseModel):
    """Response model for version check endpoint."""

    installed_version: str
    latest_version: Optional[str]
    update_available: bool
    update_type: Optional[str]  # "patch" or "major"
    package_name: str


def _get_installed_version() -> str:
    """Get the installed version of databricks-tellr-app.

    Returns:
        Version string or "unknown" if not installed
    """
    try:
        return metadata.version(PACKAGE_NAME)
    except metadata.PackageNotFoundError:
        logger.warning(f"Package {PACKAGE_NAME} not found in installed packages")
        return "unknown"


def _get_latest_version_from_pypi() -> Optional[str]:
    """Fetch the latest version from PyPI with caching.

    Returns:
        Latest version string or None if fetch fails
    """
    global _pypi_cache

    # Check cache
    now = time.time()
    if _pypi_cache["version"] and (now - _pypi_cache["timestamp"]) < CACHE_TTL_SECONDS:
        return _pypi_cache["version"]

    try:
        with httpx.Client(timeout=10.0) as client:
            response = client.get(PYPI_URL)
            response.raise_for_status()
            data = response.json()
            latest_version = data.get("info", {}).get("version")

            # Update cache
            _pypi_cache["version"] = latest_version
            _pypi_cache["timestamp"] = now

            return latest_version

    except httpx.HTTPError as e:
        logger.warning(f"Failed to fetch version from PyPI: {e}")
        return _pypi_cache.get("version")  # Return stale cache if available
    except Exception as e:
        logger.warning(f"Unexpected error fetching PyPI version: {e}")
        return _pypi_cache.get("version")


def _classify_update_type(installed: str, latest: str) -> Optional[str]:
    """Classify the update type based on version comparison.

    Args:
        installed: Currently installed version
        latest: Latest available version

    Returns:
        "patch" if only patch version changed
        "major" if minor or major version changed
        None if versions are equal or can't be parsed
    """
    try:
        installed_v = Version(installed)
        latest_v = Version(latest)

        if latest_v <= installed_v:
            return None

        # Compare major and minor versions
        # If either major or minor changed, it's a "major" update (requires tellr.update())
        if installed_v.major != latest_v.major or installed_v.minor != latest_v.minor:
            return "major"

        # Only patch changed
        return "patch"

    except InvalidVersion as e:
        logger.warning(f"Could not parse versions for comparison: {e}")
        return None


@router.get("", response_model=VersionCheckResponse)
@router.get("/check", response_model=VersionCheckResponse)
async def check_version() -> VersionCheckResponse:
    """Check for available updates.

    Returns version comparison info including:
    - installed_version: Currently running version
    - latest_version: Latest version on PyPI
    - update_available: Whether an update is available
    - update_type: "patch" (redeploy) or "major" (run tellr.update())
    """
    installed = _get_installed_version()
    latest = _get_latest_version_from_pypi()

    update_available = False
    update_type = None

    if installed != "unknown" and latest:
        update_type = _classify_update_type(installed, latest)
        update_available = update_type is not None

    return VersionCheckResponse(
        installed_version=installed,
        latest_version=latest,
        update_available=update_available,
        update_type=update_type,
        package_name=PACKAGE_NAME,
    )
