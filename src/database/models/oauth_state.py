"""OAuth state nonce for the Google OAuth flow (SDR-4437 MEDIUM-3).

Single-use, short-TTL rows binding an OAuth callback to a consent flow the
authenticated user actually started (login-CSRF protection), and carrying
the PKCE ``code_verifier`` server-side so it is never client-visible.

DB-backed by construction: the app runs multiple uvicorn workers and
``/auth/url`` and ``/auth/callback`` routinely land on different workers,
so an in-memory per-worker store fails most callbacks — the same reason
``ExportJob`` lives in the DB. Registered on ``Base`` so ``create_all``
creates the table with zero operator setup on a fresh pip install.
"""

from datetime import datetime

from sqlalchemy import Column, DateTime, String, Text

from src.core.database import Base


class OAuthState(Base):
    """Single-use OAuth state nonce, consumed atomically on callback."""

    __tablename__ = "oauth_states"

    # secrets.token_urlsafe(32) -> 43 chars (256 bits of entropy).
    nonce = Column(String(64), primary_key=True)
    user_identity = Column(String(255), nullable=False, index=True)
    code_verifier = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    def __repr__(self) -> str:  # never include the verifier
        return f"<OAuthState(user='{self.user_identity}')>"
