from __future__ import annotations

import base64
import unittest

from bark_push._aes import decrypt_block, encrypt_block
from bark_push.crypto import (
    decrypt_cbc,
    decrypt_payload,
    encrypt_cbc,
    encrypt_payload,
)


class AesTest(unittest.TestCase):
    def test_fips_197_block_vectors(self) -> None:
        plaintext = bytes.fromhex("00112233445566778899aabbccddeeff")
        cases = (
            (
                "000102030405060708090a0b0c0d0e0f",
                "69c4e0d86a7b0430d8cdb78070b4c55a",
            ),
            (
                "000102030405060708090a0b0c0d0e0f1011121314151617",
                "dda97ca4864cdfe06eaf70a0ec0d7191",
            ),
            (
                "000102030405060708090a0b0c0d0e0f101112131415161718191a1b1c1d1e1f",
                "8ea2b7ca516745bfeafc49904b496089",
            ),
        )
        for key_hex, ciphertext_hex in cases:
            key = bytes.fromhex(key_hex)
            ciphertext = bytes.fromhex(ciphertext_hex)
            self.assertEqual(encrypt_block(plaintext, key), ciphertext)
            self.assertEqual(decrypt_block(ciphertext, key), plaintext)

    def test_nist_cbc_vector(self) -> None:
        key = bytes.fromhex("2b7e151628aed2a6abf7158809cf4f3c")
        iv = bytes.fromhex("000102030405060708090a0b0c0d0e0f")
        plaintext = bytes.fromhex(
            "6bc1bee22e409f96e93d7e117393172a"
            "ae2d8a571e03ac9c9eb76fac45af8e51"
            "30c81c46a35ce411e5fbc1191a0a52ef"
            "f69f2445df4f9b17ad2b417be66c3710"
        )
        expected = bytes.fromhex(
            "7649abac8119b246cee98e9b12e9197d"
            "5086cb9b507219ee95db113a917678b2"
            "73bed6b8e3c1743b7116e69e22229516"
            "3ff1caa1681fac09120eca307586e1a7"
        )
        ciphertext = encrypt_cbc(plaintext, key, iv)
        self.assertEqual(ciphertext[: len(expected)], expected)
        self.assertEqual(decrypt_cbc(ciphertext, key, iv), plaintext)

    def test_bark_documentation_vector(self) -> None:
        # https://bark.day.app/#/encryption
        plaintext = b'{"body": "test", "sound": "birdsong"}'
        ciphertext = encrypt_cbc(plaintext, b"1234567890123456", b"1234567890123456")
        self.assertEqual(
            base64.b64encode(ciphertext).decode("ascii"),
            "+aPt5cwN9GbTLLSFri60l3h1X00u/9j1FENfWiTxhNHVLGU+XoJ15JJG5W/d/yf0",
        )

    def test_key_sizes(self) -> None:
        plaintext = "你好,Bark".encode()
        for size in (16, 24, 32):
            key = bytes(range(size))
            iv = b"0123456789abcdef"
            encrypted = encrypt_payload(plaintext, key, iv)
            self.assertEqual(encrypted.algorithm, f"aes-{size * 8}-cbc")
            self.assertEqual(encrypted.iv, "0123456789abcdef")
            self.assertEqual(decrypt_payload(encrypted.ciphertext, key, iv), plaintext)

    def test_payload_mapping_round_trip_and_random_iv(self) -> None:
        payload = {"title": "标题", "body": "hello", "badge": 2}
        encrypted = encrypt_payload(payload, "1234567890123456")
        self.assertEqual(len(encrypted.iv), 16)
        self.assertEqual(encrypted.iv.encode(), encrypted.iv.encode("utf-8"))
        self.assertEqual(
            decrypt_payload(encrypted.ciphertext, "1234567890123456", encrypted.iv),
            b'{"title":"\xe6\xa0\x87\xe9\xa2\x98","body":"hello","badge":2}',
        )

    def test_invalid_key_and_iv(self) -> None:
        with self.assertRaises(ValueError):
            encrypt_payload(b"x", b"short")
        with self.assertRaises(ValueError):
            encrypt_payload(b"x", b"1234567890123456", b"short")
        with self.assertRaises(ValueError):
            encrypt_payload(b"x", b"1234567890123456", b"\xff" * 16)

    def test_wrong_key_fails_to_decrypt(self) -> None:
        encrypted = encrypt_payload(
            b"wrong key test", "1234567890123456", "0123456789abcdef"
        )
        with self.assertRaises(ValueError):
            decrypt_payload(encrypted.ciphertext, "1234567890123457", encrypted.iv)

    def test_invalid_padding_and_base64(self) -> None:
        key = b"1234567890123456"
        iv = b"1234567890123456"
        with self.assertRaises(ValueError):
            decrypt_cbc(b"\x00" * 16, key, iv)
        with self.assertRaises(ValueError):
            decrypt_cbc(b"\x00" * 15, key, iv)
        with self.assertRaises(ValueError):
            decrypt_payload("not base64!", key, iv)

    def test_encrypted_payload_as_params(self) -> None:
        encrypted = encrypt_payload(
            {"body": "b"}, "1234567890123456", "0123456789abcdef"
        )
        self.assertEqual(
            encrypted.as_params(),
            {"ciphertext": encrypted.ciphertext, "iv": "0123456789abcdef"},
        )

    def test_invalid_key_and_iv_types(self) -> None:
        with self.assertRaises(TypeError):
            encrypt_payload(b"x", 123)  # type: ignore[arg-type]
        with self.assertRaises(TypeError):
            encrypt_payload(b"x", b"1234567890123456", 123)  # type: ignore[arg-type]

    def test_string_payload_and_invalid_payload_type(self) -> None:
        encrypted = encrypt_payload("hello", "1234567890123456", "0123456789abcdef")
        self.assertEqual(
            decrypt_payload(encrypted.ciphertext, "1234567890123456", encrypted.iv),
            b"hello",
        )
        with self.assertRaises(TypeError):
            encrypt_payload(123, "1234567890123456")  # type: ignore[arg-type]

    def test_empty_plaintext_padding(self) -> None:
        from bark_push.crypto import _unpad

        with self.assertRaises(ValueError):
            _unpad(b"")

    def test_invalid_block_lengths(self) -> None:
        with self.assertRaises(ValueError):
            encrypt_block(b"\x00" * 15, b"1234567890123456")
        with self.assertRaises(ValueError):
            decrypt_block(b"\x00" * 15, b"1234567890123456")

    def test_invalid_key_length_for_block_cipher(self) -> None:
        with self.assertRaises(ValueError):
            encrypt_block(b"\x00" * 16, b"short")
        with self.assertRaises(ValueError):
            decrypt_block(b"\x00" * 16, b"short")


if __name__ == "__main__":
    unittest.main()
