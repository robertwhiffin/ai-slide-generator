"""Setup API routes for first-time configuration.

These endpoints are used by the frontend to configure the app on first run,
primarily for Homebrew installations where users need to enter their
Databricks workspace URL.
"""

import logging
import os
import re
from typing import Optional
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, field_validator

from src.api.routes._authz import _is_production, require_admin
from src.core.databricks_client import (
    get_tellr_config,
    is_tellr_configured,
    reset_client,
    save_tellr_config,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/setup", tags=["setup"])

# F-CR-24: permitted workspace domains. A host is accepted only if it is a
# subdomain of one at a label boundary. "databricks.com" covers the AWS
# (*.cloud.databricks.com) and GCP (*.gcp.databricks.com) workspace domains.
_ALLOWED_HOST_SUFFIXES = (
    "databricks.com",
    "azuredatabricks.net",  # Azure: adb-123456.18.azuredatabricks.net
)

_HOSTNAME_RE = re.compile(r"[a-z0-9-]+(\.[a-z0-9-]+)+")


def _is_allowed_databricks_host(hostname: str) -> bool:
    """Return True if ``hostname`` is a boundary subdomain of a permitted domain."""
    if not _HOSTNAME_RE.fullmatch(hostname):
        return False
    return any(hostname.endswith("." + suffix) for suffix in _ALLOWED_HOST_SUFFIXES)


def require_setup_access() -> None:
    """FastAPI dependency gating the mutating setup endpoints (F-CR-24).

    Delegates to ``require_admin``: behind the Databricks Apps proxy the caller
    must be a workspace admin; in local (Homebrew/dev) mode the app is
    single-user and ``require_admin`` bypasses, so first-run setup still works.
    """
    require_admin()


def _is_already_configured() -> bool:
    """True once a workspace host is set via ~/.tellr/config.yaml or env."""
    return is_tellr_configured() or bool(os.getenv("DATABRICKS_HOST"))


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
        v = v.strip().rstrip("/")

        # Add https:// if not present
        if not v.startswith("http://") and not v.startswith("https://"):
            v = f"https://{v}"

        error = ValueError(
            "Invalid Databricks workspace URL. "
            "Expected format: https://your-workspace.cloud.databricks.com"
        )

        # F-CR-24: validate the *parsed* hostname, not the raw string. Reject
        # userinfo ("x.cloud.databricks.com@attacker.example"), ports, paths,
        # queries and fragments; the host must be a boundary subdomain of a
        # permitted domain (so "x.cloud.databricks.com.attacker.example" fails).
        try:
            parts = urlsplit(v)
            port = parts.port
        except ValueError:
            raise error
        hostname = parts.hostname or ""
        if (
            parts.scheme != "https"
            or "@" in parts.netloc
            or port is not None
            or parts.path
            or parts.query
            or parts.fragment
            or parts.netloc.lower() != hostname
            or not _is_allowed_databricks_host(hostname)
        ):
            raise error

        return f"https://{hostname}"


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
    import os

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


@router.post(
    "/configure",
    response_model=ConfigureWorkspaceResponse,
    dependencies=[Depends(require_setup_access)],
)
async def configure_workspace(request: ConfigureWorkspaceRequest):
    """
    Configure the Databricks workspace URL.

    Saves the workspace URL to ~/.tellr/config.yaml with OAuth browser
    authentication enabled. On the next API call that requires Databricks
    access, the browser will open for SSO login.

    F-CR-24: once the app is configured, re-configuration requires a verified
    admin. ``require_setup_access`` already enforced admin in production; in
    local mode there is no verified identity (``require_admin`` bypasses), so
    overwriting an existing config over the API is refused outright.
    """
    if _is_already_configured() and not _is_production():
        raise HTTPException(
            status_code=409,
            detail="Workspace is already configured. Edit ~/.tellr/config.yaml to change it.",
        )

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


@router.post("/test-connection", dependencies=[Depends(require_setup_access)])
async def test_connection():
    """
    Test the Databricks connection after configuration.

    This will trigger the OAuth browser flow if using external-browser auth.
    Returns user info on success.
    """
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
