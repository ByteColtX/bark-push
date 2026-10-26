from __future__ import annotations

import json
import unittest
from dataclasses import FrozenInstanceError

from bark_push import Action, Level, PushParams


class PushParamsTest(unittest.TestCase):
    def test_minimal_payload(self) -> None:
        self.assertEqual(
            PushParams(title="t", body="b").to_payload(),
            {"title": "t", "body": "b"},
        )

    def test_all_wire_names_and_normalisation(self) -> None:
        params = PushParams(
            title="t",
            subtitle="s",
            body="b",
            markdown="**m**",
            device_keys=["k1", "k2"],
            group="g",
            icon="https://example.com/i.png",
            image="https://example.com/big.png",
            badge=3,
            level=Level.CRITICAL,
            volume=10,
            call=True,
            sound="minuet",
            copy="c",
            url="https://example.com",
            action=Action.ALERT,
            ciphertext="ct",
            iv="1234567890123456",
            is_archive=False,
            ttl=60,
            id=123,
            delete=True,
        )
        self.assertEqual(
            params.to_payload(),
            {
                "title": "t",
                "subtitle": "s",
                "body": "b",
                "markdown": "**m**",
                "device_keys": ["k1", "k2"],
                "group": "g",
                "icon": "https://example.com/i.png",
                "image": "https://example.com/big.png",
                "badge": 3,
                "level": "critical",
                "volume": 10,
                "call": "1",
                "sound": "minuet",
                "copy": "c",
                "url": "https://example.com",
                "action": "alert",
                "ciphertext": "ct",
                "iv": "1234567890123456",
                "isArchive": "0",
                "ttl": 60,
                "id": "123",
                "delete": "1",
            },
        )

    def test_device_key_payload(self) -> None:
        self.assertEqual(
            PushParams(device_key="K", body="b").to_payload(),
            {"device_key": "K", "body": "b"},
        )

    def test_markdown_and_body_are_kept(self) -> None:
        payload = PushParams(body="plain", markdown="# md").to_payload()
        self.assertEqual(payload, {"body": "plain", "markdown": "# md"})

    def test_id_is_always_a_string(self) -> None:
        self.assertEqual(PushParams(id=42).to_payload(), {"id": "42"})
        self.assertEqual(PushParams(id="abc").to_payload(), {"id": "abc"})

    def test_level_values(self) -> None:
        for value in ("active", "timeSensitive", "passive", "critical"):
            self.assertEqual(PushParams(level=value).to_payload()["level"], value)
        with self.assertRaises(ValueError):
            PushParams(level="urgent")
        with self.assertRaises(TypeError):
            PushParams(level=1)  # type: ignore[arg-type]

    def test_action_accepts_documented_values_and_unknown_strings(self) -> None:
        self.assertEqual(PushParams(action="alert").to_payload()["action"], "alert")
        self.assertEqual(PushParams(action="none").to_payload()["action"], "none")
        self.assertEqual(PushParams(action="share").to_payload()["action"], "share")

    def test_volume_range(self) -> None:
        for value in (0, 5, 10):
            self.assertEqual(PushParams(volume=value).to_payload()["volume"], value)
        for value in (-1, 11):
            with self.assertRaises(ValueError):
                PushParams(volume=value)

    def test_ttl_must_be_positive(self) -> None:
        self.assertEqual(PushParams(ttl="60").to_payload()["ttl"], 60)
        with self.assertRaises(ValueError):
            PushParams(ttl=0)

    def test_badge(self) -> None:
        self.assertEqual(PushParams(badge="7").to_payload()["badge"], 7)
        with self.assertRaises(ValueError):
            PushParams(badge=-1)
        with self.assertRaises(TypeError):
            PushParams(badge=True)  # type: ignore[arg-type]

    def test_flags(self) -> None:
        self.assertEqual(PushParams(call=True).to_payload(), {"call": "1"})
        self.assertEqual(PushParams(call="1").to_payload(), {"call": "1"})
        self.assertEqual(PushParams(call=False).to_payload(), {})
        self.assertEqual(PushParams(is_archive=False).to_payload(), {"isArchive": "0"})
        self.assertEqual(PushParams(is_archive=True).to_payload(), {"isArchive": "1"})
        self.assertEqual(PushParams(delete=False, id="x").to_payload(), {"id": "x"})
        with self.assertRaises(ValueError):
            PushParams(call="yes")

    def test_delete_requires_id(self) -> None:
        with self.assertRaises(ValueError):
            PushParams(delete=True)

    def test_device_keys_validation(self) -> None:
        with self.assertRaises(TypeError):
            PushParams(device_keys="key1")  # type: ignore[arg-type]
        with self.assertRaises(ValueError):
            PushParams(device_keys=[])
        with self.assertRaises(ValueError):
            PushParams(device_keys=["ok", ""])
        with self.assertRaises(ValueError):
            PushParams(device_key="a", device_keys=["b"])

    def test_empty_title_is_treated_as_unset(self) -> None:
        self.assertEqual(PushParams(title="", body="b").to_payload(), {"body": "b"})

    def test_query_rejects_device_keys(self) -> None:
        params = PushParams(body="b", device_keys=["k1", "k2"])
        with self.assertRaises(ValueError):
            params.to_query_pairs()
        with self.assertRaises(ValueError):
            params.to_form()

    def test_query_encoding(self) -> None:
        params = PushParams(title="标题", body="a/b c", group="g", badge=2)
        self.assertEqual(
            params.to_query_pairs(),
            [
                ("title", "标题"),
                ("body", "a/b c"),
                ("group", "g"),
                ("badge", "2"),
            ],
        )
        self.assertEqual(
            params.to_query(),
            "title=%E6%A0%87%E9%A2%98&body=a%2Fb%20c&group=g&badge=2",
        )

    def test_json_is_compact_and_keeps_unicode(self) -> None:
        self.assertEqual(
            PushParams(body="你好", badge=2).to_json(),
            '{"body":"你好","badge":2}',
        )
        self.assertEqual(json.loads(PushParams(body="你好").to_json())["body"], "你好")

    def test_params_are_immutable(self) -> None:
        params = PushParams(body="b")
        with self.assertRaises(FrozenInstanceError):
            params.body = "other"  # type: ignore[misc]

    def test_sound_image_and_icon_payload(self) -> None:
        params = PushParams(
            sound="minuet",
            image="https://example.com/image.png",
            icon="https://example.com/icon.png",
        )
        self.assertEqual(
            params.to_payload(),
            {
                "icon": "https://example.com/icon.png",
                "image": "https://example.com/image.png",
                "sound": "minuet",
            },
        )

    def test_empty_subtitle_is_treated_as_unset(self) -> None:
        self.assertEqual(PushParams(subtitle="", body="b").to_payload(), {"body": "b"})

    def test_text_fields_reject_non_strings(self) -> None:
        with self.assertRaises(TypeError):
            PushParams(group=1)  # type: ignore[arg-type]
        with self.assertRaises(TypeError):
            PushParams(icon=1)  # type: ignore[arg-type]

    def test_empty_device_key(self) -> None:
        with self.assertRaises(ValueError):
            PushParams(device_key="")

    def test_invalid_integer_values(self) -> None:
        with self.assertRaises(TypeError):
            PushParams(badge="abc")
        with self.assertRaises(TypeError):
            PushParams(volume=1.5)  # type: ignore[arg-type]
        with self.assertRaises(TypeError):
            PushParams(ttl="1.5")

    def test_invalid_integer_flag(self) -> None:
        with self.assertRaises(ValueError):
            PushParams(call=2)

    def test_integer_flags(self) -> None:
        self.assertEqual(PushParams(call=1).to_payload(), {"call": "1"})
        self.assertEqual(PushParams(call=0).to_payload(), {})
        self.assertEqual(PushParams(is_archive=1).to_payload(), {"isArchive": "1"})
        self.assertEqual(PushParams(is_archive=0).to_payload(), {"isArchive": "0"})
        self.assertEqual(
            PushParams(delete=1, id="x").to_payload(), {"id": "x", "delete": "1"}
        )
        self.assertEqual(PushParams(delete=0, id="x").to_payload(), {"id": "x"})

    def test_string_zero_flags(self) -> None:
        self.assertEqual(PushParams(call="0").to_payload(), {})
        self.assertEqual(PushParams(is_archive="0").to_payload(), {"isArchive": "0"})
        self.assertEqual(PushParams(delete="0", id="x").to_payload(), {"id": "x"})

    def test_action_rejects_non_string(self) -> None:
        with self.assertRaises(TypeError):
            PushParams(action=1)  # type: ignore[arg-type]

    def test_id_rejects_bool_float_and_empty(self) -> None:
        with self.assertRaises(TypeError):
            PushParams(id=True)  # type: ignore[arg-type]
        with self.assertRaises(TypeError):
            PushParams(id=1.5)  # type: ignore[arg-type]
        with self.assertRaises(ValueError):
            PushParams(id="")


if __name__ == "__main__":
    unittest.main()
