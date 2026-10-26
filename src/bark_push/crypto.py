"""Bark payload encryption: AES-CBC + PKCS#7 + base64.

Bark's app stores an ASCII key; the key length selects AES-128/192/256. The
``iv`` request parameter is the ASCII IV string itself, exactly like the
example in https://bark.day.app/#/encryption (openssl hex-decodes it before
use).
"""

from __future__ import annotations

import base64
import json
import os
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from ._aes import decrypt_block, encrypt_block

BLOCK_SIZE = 16
_KEY_SIZES = (16, 24, 32)


@dataclass(frozen=True, slots=True)
class EncryptedPayload:
    """Ciphertext plus the IV that must accompany it."""

    ciphertext: str
    iv: str
    algorithm: str

    def as_params(self) -> dict[str, str]:
        """Keyword arguments for :class:`bark_push.PushParams`."""
        return {"ciphertext": self.ciphertext, "iv": self.iv}


def _key_bytes(key: str | bytes | bytearray | memoryview) -> bytes:
    if isinstance(key, str):
        data = key.encode("utf-8")
    elif isinstance(key, (bytes, bytearray, memoryview)):
        data = bytes(key)
    else:
        raise TypeError("key must be str or bytes")
    if len(data) not in _KEY_SIZES:
        raise ValueError(
            f"key must be 16, 24 or 32 bytes for AES-128/192/256, got {len(data)}"
        )
    return data


def _iv_bytes(iv: str | bytes | bytearray | memoryview) -> tuple[bytes, str]:
    if isinstance(iv, str):
        data = iv.encode("utf-8")
        text = iv
    elif isinstance(iv, (bytes, bytearray, memoryview)):
        data = bytes(iv)
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            raise ValueError(
                "iv bytes must be UTF-8 text because Bark sends iv as a string"
            ) from None
    else:
        raise TypeError("iv must be str or bytes")
    if len(data) != BLOCK_SIZE:
        raise ValueError(f"iv must be 16 bytes, got {len(data)}")
    return data, text


def _new_iv() -> tuple[bytes, str]:
    # 16 hex characters = 16 ASCII bytes; the IV only needs to be unique.
    text = os.urandom(8).hex()
    return text.encode("ascii"), text


def _pad(data: bytes) -> bytes:
    padding = BLOCK_SIZE - len(data) % BLOCK_SIZE
    return data + bytes([padding]) * padding


def _unpad(data: bytes) -> bytes:
    if not data:
        raise ValueError("invalid PKCS#7 padding: empty plaintext")
    padding = data[-1]
    if not 1 <= padding <= BLOCK_SIZE or data[-padding:] != bytes([padding]) * padding:
        raise ValueError("invalid PKCS#7 padding")
    return data[:-padding]


def encrypt_cbc(
    data: bytes,
    key: str | bytes | bytearray | memoryview,
    iv: str | bytes | bytearray | memoryview,
) -> bytes:
    """AES-CBC encrypt ``data`` with PKCS#7 padding."""
    key_data = _key_bytes(key)
    iv_data, _ = _iv_bytes(iv)
    padded = _pad(bytes(data))
    previous = iv_data
    output = bytearray()
    for offset in range(0, len(padded), BLOCK_SIZE):
        block = bytes(
            left ^ right
            for left, right in zip(
                padded[offset : offset + BLOCK_SIZE], previous, strict=True
            )
        )
        previous = encrypt_block(block, key_data)
        output.extend(previous)
    return bytes(output)


def decrypt_cbc(
    data: bytes,
    key: str | bytes | bytearray | memoryview,
    iv: str | bytes | bytearray | memoryview,
) -> bytes:
    """AES-CBC decrypt ``data`` and remove PKCS#7 padding."""
    key_data = _key_bytes(key)
    iv_data, _ = _iv_bytes(iv)
    if not data or len(data) % BLOCK_SIZE:
        raise ValueError("ciphertext length must be a non-zero multiple of 16")
    previous = iv_data
    output = bytearray()
    for offset in range(0, len(data), BLOCK_SIZE):
        block = bytes(data[offset : offset + BLOCK_SIZE])
        decrypted = decrypt_block(block, key_data)
        output.extend(
            left ^ right for left, right in zip(decrypted, previous, strict=True)
        )
        previous = block
    return _unpad(bytes(output))


def encrypt_payload(
    payload: Mapping[str, Any] | str | bytes,
    key: str | bytes | bytearray | memoryview,
    iv: str | bytes | bytearray | memoryview | None = None,
) -> EncryptedPayload:
    """Encrypt a JSON payload (or raw text) for Bark's ``ciphertext`` parameter.

    A mapping is serialised as compact JSON. When ``iv`` is omitted, a random
    16-character hex IV is generated and returned with the ciphertext.
    """
    if isinstance(payload, Mapping):
        plaintext = json.dumps(
            payload, ensure_ascii=False, separators=(",", ":")
        ).encode("utf-8")
    elif isinstance(payload, str):
        plaintext = payload.encode("utf-8")
    elif isinstance(payload, (bytes, bytearray, memoryview)):
        plaintext = bytes(payload)
    else:
        raise TypeError("payload must be a mapping, str or bytes")

    key_data = _key_bytes(key)
    if iv is None:
        iv_data, iv_text = _new_iv()
    else:
        iv_data, iv_text = _iv_bytes(iv)

    ciphertext = encrypt_cbc(plaintext, key_data, iv_data)
    return EncryptedPayload(
        ciphertext=base64.b64encode(ciphertext).decode("ascii"),
        iv=iv_text,
        algorithm=f"aes-{len(key_data) * 8}-cbc",
    )


def decrypt_payload(
    ciphertext: str,
    key: str | bytes | bytearray | memoryview,
    iv: str | bytes | bytearray | memoryview,
) -> bytes:
    """Reverse :func:`encrypt_payload` (useful for tests and tools)."""
    try:
        data = base64.b64decode("".join(ciphertext.split()), validate=True)
    except ValueError:
        raise ValueError("ciphertext is not valid base64") from None
    return decrypt_cbc(data, key, iv)
