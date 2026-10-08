"""Setup API routes for first-time configuration.

These endpoints are used by the frontend to configure the app on first run,
primarily for Homebrew installations where users need to enter their
Databricks workspace URL.
"""

import logging
import os
import re
from typing import Optional
from urllib.parse import urlparse

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, field_validator

from src.core.databricks_client import (
    get_tellr_config,
    is_tellr_configured,
    reset_client,
    save_tellr_config,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/setup", tags=["setup"])

# Workspace hosts we accept on first-run configure. Suffixes are matched against
# the parsed hostname so values like https://x.cloud.databricks.com.attacker.net
# cannot pass an unanchored regex.
_DATABRICKS_HOST_SUFFIXES = (
    ".cloud.databricks.com",
    ".azuredatabricks.net",
    ".gcp.databricks.com",
)
_DATABRICKS_HOST_PATTERNS = (
    r"https://[\w\-]+\.cloud\.databricks\.com",
    r"https://[\w\-\.]+\.azuredatabricks\.net",
    r"https://[\w\-]+\.gcp\.databricks\.com",
)


def _is_allowed_databricks_host(url: str) -> bool:
    """True when *url* is an https Databricks workspace with no extra host suffix."""
    if not any(re.fullmatch(pattern, url) for pattern in _DATABRICKS_HOST_PATTERNS):
        return False

    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.username is not None or parsed.password is not None:
        return False
    if parsed.port is not None:
        return False
    if parsed.path not in ("", "/") or parsed.query or parsed.fragment:
        return False

    hostname = (parsed.hostname or "").lower().rstrip(".")
    if not hostname:
        return False
    return any(
        hostname.endswith(suffix) and len(hostname) > len(suffix)
        for suffix in _DATABRICKS_HOST_SUFFIXES
    )


def _is_already_configured() -> bool:
    """True once a workspace host is set via ~/.tellr/config.yaml or env."""
    return is_tellr_configured() or bool(os.getenv("DATABRICKS_HOST"))


def _refuse_reconfigure() -> None:
    """Block mutating setup once the app already has a workspace host.

    On Databricks Apps, DATABRICKS_HOST is always set, so configure/test-connection
    are unreachable. That is the intended production posture: these routes exist
    only for a true first-run local install.
    """
    if _is_already_configured():
        raise HTTPException(
            status_code=409,
            detail="Workspace is already configured.",
        )


class SetupStatusResponse(BaseModel):
    """Response for setup status check."""
    configured: bool
    host: Optional[str] = None


class ConfigureWorkspaceRequest(BaseModel):
    """Request to configure workspace URL."""
    host: str

    @field_validator("host")
    @classmethod
    def validate_host(cls, v: str) -> str:
        """Validate and normalize the workspace URL."""
        # Remove trailing slashes
        v = v.rstrip("/")

        # Add https:// if not present
        if not v.startswith("http://") and not v.startswith("https://"):
            v = f"https://{v}"

        if not _is_allowed_databricks_host(v):
            raise ValueError(
                "Invalid Databricks workspace URL. "
                "Expected format: https://your-workspace.cloud.databricks.com"
            )

        return v


class ConfigureWorkspaceResponse(BaseModel):
    """Response after configuring workspace."""
    success: bool
    message: str
    host: str


@router.get("/status", response_model=SetupStatusResponse)
async def get_setup_status():
    """
    Check if the app has been configured with a Databricks workspace.

    Returns configured=True if ~/.tellr/config.yaml exists with a valid host,
    or if DATABRICKS_HOST environment variable is set.
    """
    # Check tellr config file first
    if is_tellr_configured():
        config = get_tellr_config()
        host = config.get("databricks", {}).get("host") if config else None
        return SetupStatusResponse(configured=True, host=host)

    # Fall back to environment variable
    env_host = os.getenv("DATABRICKS_HOST")
    if env_host:
        return SetupStatusResponse(configured=True, host=env_host)

    return SetupStatusResponse(configured=False, host=None)


@router.post("/configure", response_model=ConfigureWorkspaceResponse)
async def configure_workspace(request: ConfigureWorkspaceRequest):
    """
    Configure the Databricks workspace URL.

    Saves the workspace URL to ~/.tellr/config.yaml with OAuth browser
    authentication enabled. On the next API call that requires Databricks
    access, the browser will open for SSO login.
    """
    _refuse_reconfigure()
    try:
        # Save the configuration
        save_tellr_config(host=request.host, auth_type="external-browser")

        # Reset the client so it picks up the new config
        reset_client()

        logger.info(f"Workspace configured: {request.host}")

        return ConfigureWorkspaceResponse(
            success=True,
            message="Workspace configured successfully. SSO login will be triggered on first use.",
            host=request.host,
        )

    except Exception as e:
        logger.error(f"Failed to configure workspace: {e}")
        raise HTTPException(
            status_code=500,
            detail="Failed to save configuration"
        )


@router.post("/test-connection")
async def test_connection():
    """
    Test the Databricks connection after configuration.

    This will trigger the OAuth browser flow if using external-browser auth.
    Returns user info on success.
    """
    _refuse_reconfigure()
    try:
        from src.core.databricks_client import get_system_client

        client = get_system_client(force_new=True)
        user = client.current_user.me()

        return {
            "success": True,
            "message": "Connection successful",
            "user": {
                "username": user.user_name,
                "display_name": user.display_name or user.user_name,
            }
        }

    except Exception as e:
        logger.error(f"Connection test failed: {e}")
        raise HTTPException(
            status_code=400,
            detail="Connection failed"
        )
