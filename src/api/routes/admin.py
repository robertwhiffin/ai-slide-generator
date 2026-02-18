"""Admin endpoints for app-wide configuration.

Includes global Google OAuth credentials management.
"""

import logging

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from src.api.utils.validation import validate_credentials_json
from src.core.database import get_db
from src.core.encryption import decrypt_data, encrypt_data
from src.core.user_context import get_current_user
from src.database.models import GoogleGlobalCredentials

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin", tags=["admin"])

_MAX_CREDENTIALS_SIZE = 100 * 1024


@router.post("/google-credentials")
async def upload_google_credentials(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """Upload app-wide Google OAuth credentials.json.

    Validates structure, encrypts, and upserts into GoogleGlobalCredentials.
    Replaces any existing credentials.
    """
    content = await file.read()
    if len(content) > _MAX_CREDENTIALS_SIZE:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File too large (max 100 KB)",
        )

    raw = content.decode("utf-8")
    try:
        validate_credentials_json(raw)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    encrypted = encrypt_data(raw)
    uploaded_by = get_current_user() or "unknown"

    existing = db.query(GoogleGlobalCredentials).first()
    if existing:
        existing.credentials_encrypted = encrypted
        existing.uploaded_by = uploaded_by
    else:
        db.add(
            GoogleGlobalCredentials(
                credentials_encrypted=encrypted,
                uploaded_by=uploaded_by,
            )
        )
    db.commit()

    logger.info(
        "Google OAuth credentials uploaded (admin)",
        extra={"uploaded_by": uploaded_by},
    )
    return {"success": True, "has_credentials": True}


@router.get("/google-credentials/status")
def get_google_credentials_status(db: Session = Depends(get_db)):
    """Check whether app-wide Google OAuth credentials exist and are decryptable."""
    row = db.query(GoogleGlobalCredentials).first()
    has_credentials = False
    if row and row.credentials_encrypted:
        try:
            decrypt_data(row.credentials_encrypted)
            has_credentials = True
        except Exception:
            logger.warning(
                "Stored global credentials cannot be decrypted (key mismatch); "
                "removing stale row"
            )
            db.delete(row)
            db.commit()

    return {"has_credentials": has_credentials}


@router.delete("/google-credentials", status_code=status.HTTP_204_NO_CONTENT)
def delete_google_credentials(db: Session = Depends(get_db)):
    """Remove app-wide Google OAuth credentials."""
    row = db.query(GoogleGlobalCredentials).first()
    if row:
        db.delete(row)
        db.commit()
        logger.info("Google OAuth credentials deleted (admin)")
