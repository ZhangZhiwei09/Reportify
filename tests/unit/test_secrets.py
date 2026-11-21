from __future__ import annotations

import pytest
from pydantic import SecretStr

from reportify.modules.security.secrets import SecretError, SecretService


def test_encrypt_decrypt_roundtrip() -> None:
    service = SecretService(SecretStr("test-key"), key_version=1)
    encrypted = service.encrypt("super-secret-password")

    assert encrypted.ciphertext != b"super-secret-password"
    assert encrypted.key_version == 1
    assert service.decrypt(encrypted.ciphertext, encrypted.nonce, 1) == (
        "super-secret-password"
    )


def test_wrong_key_version_is_rejected() -> None:
    service = SecretService(SecretStr("test-key"), key_version=1)
    encrypted = service.encrypt("value")

    with pytest.raises(SecretError):
        service.decrypt(encrypted.ciphertext, encrypted.nonce, 2)


def test_empty_key_is_rejected() -> None:
    with pytest.raises(SecretError):
        SecretService(SecretStr(""))
