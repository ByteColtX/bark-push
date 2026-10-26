"""Push parameters mirroring https://bark.day.app/#/params."""

from __future__ import annotations

import json
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, fields
from enum import Enum
from typing import Any
from urllib.parse import quote, urlencode


class Level(str, Enum):
    """Notification interruption level (``level``)."""

    ACTIVE = "active"
    TIME_SENSITIVE = "timeSensitive"
    PASSIVE = "passive"
    CRITICAL = "critical"


class Action(str, Enum):
    """Click behaviour (``action``). Other strings fall back to the default."""

    ALERT = "alert"
    NONE = "none"


#: Python field name -> wire parameter name. Field order is payload order.
_WIRE_NAMES = {
    "title": "title",
    "subtitle": "subtitle",
    "body": "body",
    "markdown": "markdown",
    "device_key": "device_key",
    "device_keys": "device_keys",
    "group": "group",
    "icon": "icon",
    "image": "image",
    "badge": "badge",
    "level": "level",
    "volume": "volume",
    "call": "call",
    "sound": "sound",
    "copy": "copy",
    "url": "url",
    "action": "action",
    "ciphertext": "ciphertext",
    "iv": "iv",
    "is_archive": "isArchive",
    "ttl": "ttl",
    "id": "id",
    "delete": "delete",
}

_TEXT_FIELDS = (
    "title",
    "subtitle",
    "body",
    "markdown",
    "device_key",
    "group",
    "icon",
    "image",
    "sound",
    "copy",
    "url",
    "ciphertext",
    "iv",
)


def _as_int(name: str, value: Any) -> int:
    if isinstance(value, bool):
        raise TypeError(f"{name} must be an integer, not bool")
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value.strip(), 10)
        except ValueError:
            pass
    raise TypeError(f"{name} must be an integer, got {value!r}")


def _as_flag(name: str, value: Any, *, keep_false: bool) -> str | None:
    """Normalise the ``"1"``-style flags. ``None``/false values may be omitted."""
    if value is None:
        return None
    if isinstance(value, bool):
        return "1" if value else ("0" if keep_false else None)
    if isinstance(value, int):
        if value == 1:
            return "1"
        if value == 0:
            return "0" if keep_false else None
    elif isinstance(value, str) and value.strip() in {"0", "1"}:
        if value.strip() == "1":
            return "1"
        return "0" if keep_false else None
    raise ValueError(f"{name} must be a bool, 0/1 or '0'/'1', got {value!r}")


@dataclass(frozen=True, slots=True)
class PushParams:
    """All Bark push parameters.

    ``None`` means "not sent". Values are validated and normalised on creation;
    use :meth:`to_payload` for JSON, :meth:`to_form` for form bodies and
    :meth:`to_query_pairs` for GET query strings.
    """

    # Content
    title: str | None = None
    subtitle: str | None = None
    body: str | None = None
    markdown: str | None = None  # overrides body on the server

    # Device
    device_key: str | None = None
    device_keys: Sequence[str] | None = None  # JSON only (batch)

    # Display and grouping
    group: str | None = None
    icon: str | None = None
    image: str | None = None
    badge: int | str | None = None  # absolute value; 0 clears the badge

    # Alerts and sound
    level: Level | str | None = None
    volume: int | str | None = None  # 0-10, critical only
    call: bool | str | int | None = None  # loop the sound for 30 s
    sound: str | None = None

    # Copy and navigation
    copy: str | None = None
    url: str | None = None
    action: Action | str | None = None

    # Encryption
    ciphertext: str | None = None
    iv: str | None = None

    # Storage and management
    is_archive: bool | str | int | None = None
    ttl: int | str | None = None  # seconds
    id: str | int | None = None  # notification identity (always a string on the wire)
    delete: bool | str | int | None = None

    def __post_init__(self) -> None:
        def set_field(name: str, value: Any) -> None:
            object.__setattr__(self, name, value)

        for name in _TEXT_FIELDS:
            value = getattr(self, name)
            if value is None:
                continue
            if not isinstance(value, str):
                raise TypeError(f"{name} must be a string, got {type(value).__name__}")
        # Empty content fields carry no information; dropping them keeps GET
        # paths free of empty segments (``/key/`` would be a different route).
        for name in ("title", "subtitle", "body"):
            if getattr(self, name) == "":
                set_field(name, None)

        if self.device_key is not None and not self.device_key:
            raise ValueError("device_key must not be empty")

        keys = self.device_keys
        if keys is not None:
            if isinstance(keys, str):
                raise TypeError(
                    "device_keys must be a sequence of strings, not a string"
                )
            keys = tuple(keys)
            if not keys:
                raise ValueError("device_keys must not be empty")
            for key in keys:
                if not isinstance(key, str) or not key:
                    raise ValueError("device_keys must contain non-empty strings")
            set_field("device_keys", keys)
            if self.device_key is not None:
                raise ValueError("use either device_key or device_keys, not both")

        if self.badge is not None:
            badge = _as_int("badge", self.badge)
            if badge < 0:
                raise ValueError("badge must be >= 0")
            set_field("badge", badge)

        if self.level is not None:
            if isinstance(self.level, Level):
                set_field("level", self.level)
            elif isinstance(self.level, str):
                try:
                    set_field("level", Level(self.level))
                except ValueError:
                    values = ", ".join(item.value for item in Level)
                    raise ValueError(f"level must be one of: {values}") from None
            else:
                raise TypeError("level must be a Level or string")

        if self.volume is not None:
            volume = _as_int("volume", self.volume)
            if not 0 <= volume <= 10:
                raise ValueError("volume must be between 0 and 10")
            set_field("volume", volume)

        if self.ttl is not None:
            ttl = _as_int("ttl", self.ttl)
            if ttl <= 0:
                raise ValueError("ttl must be a positive number of seconds")
            set_field("ttl", ttl)

        if self.action is not None:
            if isinstance(self.action, Action):
                set_field("action", self.action.value)
            elif not isinstance(self.action, str):
                raise TypeError("action must be an Action or string")

        if self.id is not None:
            if isinstance(self.id, bool) or not isinstance(self.id, (str, int)):
                raise TypeError("id must be a string (or an integer to convert)")
            notification_id = str(self.id)
            if not notification_id:
                raise ValueError("id must not be empty")
            set_field("id", notification_id)

        set_field("call", _as_flag("call", self.call, keep_false=False))
        set_field("delete", _as_flag("delete", self.delete, keep_false=False))
        archive = _as_flag("is_archive", self.is_archive, keep_false=True)
        set_field("is_archive", archive)

        if self.delete and self.id is None:
            raise ValueError("delete requires id")

    def to_payload(self) -> dict[str, Any]:
        """Return the wire payload; ``None`` values are omitted."""
        payload: dict[str, Any] = {}
        for field in fields(self):
            value = getattr(self, field.name)
            if value is None:
                continue
            if isinstance(value, Enum):
                value = value.value
            elif field.name == "device_keys":
                value = list(value)
            payload[_WIRE_NAMES[field.name]] = value
        return payload

    def to_json(self) -> str:
        """Compact JSON, UTF-8 friendly (used for encrypted pushes)."""
        return json.dumps(self.to_payload(), ensure_ascii=False, separators=(",", ":"))

    def _string_items(self) -> Iterator[tuple[str, str]]:
        for name, value in self.to_payload().items():
            if name == "device_keys":
                raise ValueError("device_keys is only supported in JSON requests")
            yield name, str(value)

    def to_query_pairs(self) -> list[tuple[str, str]]:
        """Query-string pairs, all values stringified. Rejects ``device_keys``."""
        return list(self._string_items())

    def to_query(self) -> str:
        """URL-encoded query string without the leading ``?``."""
        return urlencode(self.to_query_pairs(), quote_via=quote)

    def to_form(self) -> str:
        """URL-encoded form body."""
        return urlencode(self.to_query_pairs(), quote_via=quote)
