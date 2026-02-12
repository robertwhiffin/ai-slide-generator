"""Tests for the Fernet encryption utility."""

import os
from unittest.mock import patch

import pytest

from src.core.encryption import decrypt_data, encrypt_data, get_encryption_key


@pytest.fixture(autouse=True)
def _clear_key_cache():
    """Clear the lru_cache between tests so each test gets a fresh key lookup."""
    get_encryption_key.cache_clear()
    yield
    get_encryption_key.cache_clear()


def test_encrypt_decrypt_roundtrip():
    """Encrypt then decrypt returns original plaintext for various inputs."""
    cases = [
        "hello world",
        '{"installed":{"client_id":"abc"}}',
        "",
        "a" * 10_000,  # large payload
    ]
    for plaintext in cases:
        ciphertext = encrypt_data(plaintext)
        assert ciphertext != plaintext  # must be different
        assert decrypt_data(ciphertext) == plaintext


def test_decrypt_with_wrong_key_raises():
    """Decrypting with a different key raises InvalidToken."""
    from cryptography.fernet import Fernet, InvalidToken

    ciphertext = encrypt_data("secret")

    # Clear cache and set a completely different key
    get_encryption_key.cache_clear()
    new_key = Fernet.generate_key().decode()
    with patch.dict(os.environ, {"GOOGLE_OAUTH_ENCRYPTION_KEY": new_key}):
        with pytest.raises(InvalidToken):
            decrypt_data(ciphertext)


def test_key_from_env_var():
    """get_encryption_key reads from GOOGLE_OAUTH_ENCRYPTION_KEY env var."""
    from cryptography.fernet import Fernet

    expected_key = Fernet.generate_key().decode()
    with patch.dict(os.environ, {"GOOGLE_OAUTH_ENCRYPTION_KEY": expected_key}):
        assert get_encryption_key() == expected_key.encode()


def test_key_auto_generated_when_missing(tmp_path):
    """When env var is absent and no key file, a key is generated and persisted."""
    key_file = tmp_path / ".encryption_key"

    with (
        patch.dict(os.environ, {}, clear=False),
        patch("src.core.encryption._KEY_FILE", key_file),
    ):
        os.environ.pop("GOOGLE_OAUTH_ENCRYPTION_KEY", None)
        key = get_encryption_key()

        assert len(key) > 0
        assert key_file.exists(), "Key file should be created"
        assert key_file.read_text().strip().encode() == key
