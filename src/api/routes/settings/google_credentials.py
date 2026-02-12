"""Google OAuth credential management endpoints for profiles.

Allows uploading, checking, and deleting the Google OAuth client credentials
(``credentials.json``) that are stored encrypted in the profile record.
"""

import json
import logging

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from src.core.database import get_db
from src.core.encryption import decrypt_data, encrypt_data
from src.database.models.profile import ConfigProfile

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/profiles", tags=["profiles"])

# Maximum upload size for credentials.json (100 KB is very generous)
_MAX_CREDENTIALS_SIZE = 100 * 1024


def _validate_credentials_json(raw: str) -> dict:
    """Parse and validate the credentials JSON structure.

    Google OAuth credentials must contain either an ``installed`` or ``web`` key.

    Raises:
        ValueError: If the JSON is invalid or missing required keys.
    """
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON: {exc}") from exc

    if not isinstance(data, dict):
        raise ValueError("Credentials must be a JSON object")

    if "installed" not in data and "web" not in data:
        raise ValueError(
            "Invalid Google OAuth credentials: must contain an 'installed' or 'web' key"
        )

    return data


@router.post("/{profile_id}/google-credentials")
async def upload_google_credentials(
    profile_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """Upload a ``credentials.json`` file for Google OAuth.

    The file content is validated, encrypted, and stored on the profile.
    """
    # --- Check profile exists ---
    profile = db.query(ConfigProfile).filter_by(id=profile_id).first()
    if profile is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Profile {profile_id} not found",
        )

    # --- Read & size-check ---
    content = await file.read()
    if len(content) > _MAX_CREDENTIALS_SIZE:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File too large (max 100 KB)",
        )

    raw = content.decode("utf-8")

    # --- Validate structure ---
    try:
        _validate_credentials_json(raw)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )

    # --- Encrypt & persist ---
    profile.google_credentials_encrypted = encrypt_data(raw)
    db.commit()

    logger.info(
        "Google OAuth credentials uploaded for profile",
        extra={"profile_id": profile_id},
    )
    return {"success": True, "has_credentials": True}


@router.get("/{profile_id}/google-credentials/status")
def get_google_credentials_status(
    profile_id: int,
    db: Session = Depends(get_db),
):
    """Check whether Google OAuth credentials have been uploaded for a profile."""
    profile = db.query(ConfigProfile).filter_by(id=profile_id).first()
    if profile is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Profile {profile_id} not found",
        )

    has = False
    if profile.google_credentials_encrypted:
        try:
            decrypt_data(profile.google_credentials_encrypted)
            has = True
        except Exception:
            # Encrypted with a different key — treat as missing
            logger.warning(
                "Stored credentials for profile %s cannot be decrypted (key mismatch); "
                "clearing stale data",
                profile_id,
            )
            profile.google_credentials_encrypted = None
            db.commit()

    return {"has_credentials": has}


@router.delete("/{profile_id}/google-credentials", status_code=status.HTTP_204_NO_CONTENT)
def delete_google_credentials(
    profile_id: int,
    db: Session = Depends(get_db),
):
    """Remove stored Google OAuth credentials from a profile."""
    profile = db.query(ConfigProfile).filter_by(id=profile_id).first()
    if profile is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Profile {profile_id} not found",
        )

    profile.google_credentials_encrypted = None
    db.commit()

    logger.info(
        "Google OAuth credentials deleted for profile",
        extra={"profile_id": profile_id},
    )
