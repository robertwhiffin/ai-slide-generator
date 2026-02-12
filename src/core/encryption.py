"""Fernet symmetric encryption for sensitive data (OAuth credentials, tokens).

Uses AES-128-CBC with HMAC-SHA256 authentication via the ``cryptography`` library.
The encryption key is read from the ``GOOGLE_OAUTH_ENCRYPTION_KEY`` environment
variable.  If the variable is not set, a key is auto-generated on first access,
persisted to ``.encryption_key`` in the project root, and a warning is logged.
"""

import logging
import os
from functools import lru_cache
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

logger = logging.getLogger(__name__)

_ENV_KEY_NAME = "GOOGLE_OAUTH_ENCRYPTION_KEY"
_KEY_FILE = Path(__file__).resolve().parents[2] / ".encryption_key"


@lru_cache(maxsize=1)
def get_encryption_key() -> bytes:
    """Return the Fernet encryption key.

    Resolution order:
    1. ``GOOGLE_OAUTH_ENCRYPTION_KEY`` env var (production).
    2. ``.encryption_key`` file in project root (persisted across restarts).
    3. Generate a new key → write to the file → set the env var.
    """
    # 1. Env var takes precedence
    key = os.getenv(_ENV_KEY_NAME)
    if key:
        return key.encode()

    # 2. Read from persisted key file
    if _KEY_FILE.exists():
        key = _KEY_FILE.read_text().strip()
        if key:
            os.environ[_ENV_KEY_NAME] = key
            logger.info("Loaded encryption key from %s", _KEY_FILE)
            return key.encode()

    # 3. Generate, persist, and warn
    generated = Fernet.generate_key()
    try:
        _KEY_FILE.write_text(generated.decode())
        _KEY_FILE.chmod(0o600)  # owner-only read/write
        logger.warning(
            "GOOGLE_OAUTH_ENCRYPTION_KEY not set — auto-generated and saved to %s. "
            "Set the env var in production.",
            _KEY_FILE,
        )
    except OSError:
        logger.warning(
            "GOOGLE_OAUTH_ENCRYPTION_KEY not set — auto-generated a key but "
            "could not persist to %s. Key will be lost on restart.",
            _KEY_FILE,
        )

    os.environ[_ENV_KEY_NAME] = generated.decode()
    return generated


def encrypt_data(plaintext: str) -> str:
    """Encrypt *plaintext* and return a base64-encoded ciphertext string."""
    f = Fernet(get_encryption_key())
    return f.encrypt(plaintext.encode()).decode()


def decrypt_data(ciphertext: str) -> str:
    """Decrypt a base64-encoded *ciphertext* string and return the plaintext.

    Raises:
        cryptography.fernet.InvalidToken: If the key does not match or data is corrupt.
    """
    f = Fernet(get_encryption_key())
    return f.decrypt(ciphertext.encode()).decode()
