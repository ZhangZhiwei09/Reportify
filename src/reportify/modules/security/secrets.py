"""AES-GCM encryption for stored credentials."""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from pydantic import SecretStr

_NONCE_BYTES = 12


class SecretError(RuntimeError):
    """A secret could not be encrypted or decrypted."""


@dataclass(frozen=True)
class EncryptedSecret:
    ciphertext: bytes
    nonce: bytes
    key_version: int


class SecretService:
    def __init__(self, secret_key: SecretStr, key_version: int = 1) -> None:
        raw = secret_key.get_secret_value().encode("utf-8")
        if not raw:
            raise SecretError("secret key must not be empty")
        self._key = hashlib.sha256(raw).digest()
        self._key_version = key_version

    @property
    def key_version(self) -> int:
        return self._key_version

    def encrypt(self, plaintext: str) -> EncryptedSecret:
        nonce = os.urandom(_NONCE_BYTES)
        ciphertext = AESGCM(self._key).encrypt(nonce, plaintext.encode("utf-8"), None)
        return EncryptedSecret(
            ciphertext=ciphertext,
            nonce=nonce,
            key_version=self._key_version,
        )

    def decrypt(self, ciphertext: bytes, nonce: bytes, key_version: int) -> str:
        if key_version != self._key_version:
            raise SecretError(f"unsupported secret key version: {key_version}")
        try:
            plaintext = AESGCM(self._key).decrypt(nonce, ciphertext, None)
        except Exception as exc:
            raise SecretError("failed to decrypt secret") from exc
        return plaintext.decode("utf-8")
