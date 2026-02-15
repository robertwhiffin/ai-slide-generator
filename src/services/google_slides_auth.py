"""Google Slides OAuth2 credential management.

Handles OAuth2 authorization flow, token persistence (DB-backed or file-backed),
and building authenticated Google API service objects.

Supports two modes:
  1. **DB-backed** (production) — credentials JSON and user tokens are stored
     encrypted in PostgreSQL via ``from_profile()``.
  2. **File-backed** (local dev) — reads ``credentials.json`` / ``token.json``
     from disk, same as the legacy behaviour.
"""

import json
import logging
from pathlib import Path
from typing import Optional

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build

logger = logging.getLogger(__name__)

# OAuth scopes required for Google Slides export
SCOPES = [
    "https://www.googleapis.com/auth/presentations",
    "https://www.googleapis.com/auth/drive.file",
]

# Default paths (relative to project root) — used only in file-backed mode
DEFAULT_CREDENTIALS_PATH = "credentials.json"
DEFAULT_TOKEN_PATH = "token.json"


class GoogleSlidesAuthError(Exception):
    """Raised when Google Slides authentication fails."""
    pass


class GoogleSlidesAuth:
    """Manages OAuth2 credentials for Google Slides API.

    Can operate in two modes controlled by the constructor arguments:

    * **DB mode** — pass ``credentials_json`` (and optionally ``token_json``)
      as raw JSON strings.  Persistence is handled externally by the caller
      via the ``on_token_changed`` callback.
    * **File mode** — pass file paths (legacy).
    """

    def __init__(
        self,
        *,
        # --- DB-backed mode ---
        credentials_json: Optional[str] = None,
        token_json: Optional[str] = None,
        on_token_changed: Optional[object] = None,
        # --- File-backed mode (legacy) ---
        credentials_path: Optional[str] = None,
        token_path: Optional[str] = None,
    ):
        self._db_mode = credentials_json is not None

        if self._db_mode:
            # Store raw JSON strings in memory
            self._credentials_json: str = credentials_json  # type: ignore[assignment]
            self._token_json: Optional[str] = token_json
            # Callback: ``fn(token_json_str)`` invoked when the token changes
            self._on_token_changed = on_token_changed
        else:
            # Legacy file-based paths
            self._credentials_path = Path(credentials_path or DEFAULT_CREDENTIALS_PATH)
            self._token_path = Path(token_path or DEFAULT_TOKEN_PATH)
            self._credentials_json = ""
            self._token_json = None
            self._on_token_changed = None

            if not self._credentials_path.exists():
                logger.warning(
                    "Google OAuth credentials file not found",
                    extra={"path": str(self._credentials_path)},
                )

    # ------------------------------------------------------------------
    # Class-level factory for DB-backed instances
    # ------------------------------------------------------------------

    @classmethod
    def from_profile(
        cls,
        profile_id: int,
        user_identity: str,
        db_session,
    ) -> "GoogleSlidesAuth":
        """Build a ``GoogleSlidesAuth`` from encrypted DB records.

        Args:
            profile_id: The config profile whose credentials to use.
            user_identity: The Databricks username (email) of the current user.
            db_session: An active SQLAlchemy ``Session``.

        Returns:
            A fully initialised ``GoogleSlidesAuth`` instance.

        Raises:
            GoogleSlidesAuthError: If the profile has no stored credentials.
        """
        from src.core.encryption import decrypt_data
        from src.database.models.google_oauth_token import GoogleOAuthToken
        from src.database.models.profile import ConfigProfile

        profile = db_session.query(ConfigProfile).filter_by(id=profile_id).first()
        if profile is None:
            raise GoogleSlidesAuthError(f"Profile {profile_id} not found")
        if not profile.google_credentials_encrypted:
            raise GoogleSlidesAuthError(
                f"Profile '{profile.name}' has no Google OAuth credentials uploaded"
            )

        credentials_json = decrypt_data(profile.google_credentials_encrypted)

        # Load existing user token (may be None)
        token_row = (
            db_session.query(GoogleOAuthToken)
            .filter_by(user_identity=user_identity, profile_id=profile_id)
            .first()
        )
        token_json: Optional[str] = None
        if token_row:
            try:
                token_json = decrypt_data(token_row.token_encrypted)
            except Exception:
                # Token encrypted with a stale key — discard it so the
                # user can re-authorize cleanly.
                logger.warning(
                    "Could not decrypt token for user=%s profile=%s; "
                    "deleting stale token row",
                    user_identity,
                    profile_id,
                )
                db_session.delete(token_row)
                db_session.commit()
                token_json = None

        def _persist_token(new_token_json: str) -> None:
            """Encrypt and upsert the token into the DB."""
            from src.core.encryption import encrypt_data

            encrypted = encrypt_data(new_token_json)
            existing = (
                db_session.query(GoogleOAuthToken)
                .filter_by(user_identity=user_identity, profile_id=profile_id)
                .first()
            )
            if existing:
                existing.token_encrypted = encrypted
            else:
                db_session.add(
                    GoogleOAuthToken(
                        user_identity=user_identity,
                        profile_id=profile_id,
                        token_encrypted=encrypted,
                    )
                )
            db_session.commit()

        return cls(
            credentials_json=credentials_json,
            token_json=token_json,
            on_token_changed=_persist_token,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def is_authorized(self) -> bool:
        """Check if a valid (non-expired or refreshable) token exists."""
        creds = self._load_token()
        if creds is None:
            return False
        if creds.valid:
            return True
        if creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
                self._save_token(creds)
                return True
            except Exception:
                logger.warning("Token refresh failed", exc_info=True)
                return False
        return False

    def get_credentials(self) -> Credentials:
        """Return valid credentials, refreshing if necessary.

        Raises:
            GoogleSlidesAuthError: If no valid credentials are available.
        """
        creds = self._load_token()
        if creds is None:
            raise GoogleSlidesAuthError(
                "Not authorized. Complete the OAuth flow first."
            )
        if creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
                self._save_token(creds)
            except Exception as exc:
                raise GoogleSlidesAuthError(
                    f"Token refresh failed: {exc}"
                ) from exc
        if not creds.valid:
            raise GoogleSlidesAuthError(
                "Credentials are invalid. Re-authorize via the OAuth flow."
            )
        return creds

    def get_auth_url(self, redirect_uri: str, state: str | None = None) -> str:
        """Generate the OAuth2 consent URL.

        Args:
            redirect_uri: The registered OAuth callback URI (no query params).
            state: Optional opaque string that Google will return unchanged on
                   the callback.  Used to carry profile_id / user context.
        """
        flow = self._build_flow(redirect_uri)
        kwargs: dict = {
            "access_type": "offline",
            "include_granted_scopes": "true",
            "prompt": "consent",
        }
        if state:
            kwargs["state"] = state
        auth_url, _ = flow.authorization_url(**kwargs)
        logger.info("Generated Google OAuth consent URL")
        return auth_url

    def authorize(self, code: str, redirect_uri: str) -> Credentials:
        """Exchange an authorization code for tokens and persist them."""
        flow = self._build_flow(redirect_uri)
        flow.fetch_token(code=code)
        creds = flow.credentials
        self._save_token(creds)
        logger.info("Google OAuth authorization successful, token saved")
        return creds

    def build_slides_service(self):
        """Return an authenticated Google Slides API service."""
        creds = self.get_credentials()
        return build("slides", "v1", credentials=creds)

    def build_drive_service(self):
        """Return an authenticated Google Drive API service."""
        creds = self.get_credentials()
        return build("drive", "v3", credentials=creds)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_flow(self, redirect_uri: str) -> Flow:
        """Create an OAuth ``Flow`` from either in-memory JSON or a file."""
        if self._db_mode:
            client_config = json.loads(self._credentials_json)
            return Flow.from_client_config(
                client_config, scopes=SCOPES, redirect_uri=redirect_uri
            )
        # File-backed fallback
        if not self._credentials_path.exists():
            raise GoogleSlidesAuthError(
                f"OAuth credentials file not found: {self._credentials_path}"
            )
        return Flow.from_client_secrets_file(
            str(self._credentials_path), scopes=SCOPES, redirect_uri=redirect_uri
        )

    def _load_token(self) -> Optional[Credentials]:
        """Load token from memory (DB mode) or disk (file mode)."""
        if self._db_mode:
            if not self._token_json:
                return None
            try:
                info = json.loads(self._token_json)
                return Credentials.from_authorized_user_info(info, SCOPES)
            except Exception:
                logger.warning("Failed to parse in-memory token JSON", exc_info=True)
                return None

        # File-backed
        if not self._token_path.exists():
            return None
        try:
            return Credentials.from_authorized_user_file(
                str(self._token_path), SCOPES
            )
        except Exception:
            logger.warning("Failed to load token file", exc_info=True)
            return None

    def _save_token(self, creds: Credentials) -> None:
        """Persist token via callback (DB mode) or to disk (file mode)."""
        token_str = creds.to_json()

        if self._db_mode:
            self._token_json = token_str
            if self._on_token_changed and callable(self._on_token_changed):
                self._on_token_changed(token_str)
            return

        # File-backed
        self._token_path.write_text(token_str)
        logger.debug("Token saved", extra={"path": str(self._token_path)})
