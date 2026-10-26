"""HTTP client for the Bark push API."""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass, replace
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from ._version import __version__
from .crypto import encrypt_payload
from .errors import BarkAPIError, BarkConnectionError, BarkHTTPError
from .params import PushParams

DEFAULT_SERVER = "https://api.day.app"
_USER_AGENT = f"bark-push/{__version__}"

#: Fields that are encrypted; server-side controls stay in the clear.
ENCRYPTED_WIRE_FIELDS = frozenset(
    {
        "title",
        "subtitle",
        "body",
        "markdown",
        "group",
        "icon",
        "image",
        "badge",
        "level",
        "volume",
        "call",
        "sound",
        "copy",
        "url",
        "action",
    }
)

_METHODS = frozenset({"json", "form", "get"})


@dataclass(frozen=True, slots=True)
class BarkResponse:
    """Parsed Bark server response."""

    status: int
    raw: str
    code: int | None = None
    message: str | None = None
    data: Any = None
    payload: Any = None

    @property
    def ok(self) -> bool:
        return 200 <= self.status < 300 and (self.code is None or self.code == 200)


class BarkClient:
    """Send Bark pushes over HTTP using only :mod:`urllib`.

    ``key`` is the device key shown in the Bark app. Pass ``server`` to use a
    self-hosted bark-server.
    """

    __slots__ = ("key", "server", "timeout")

    def __init__(
        self,
        key: str | None = None,
        *,
        server: str = DEFAULT_SERVER,
        timeout: float = 10.0,
    ) -> None:
        if key is not None and (not isinstance(key, str) or not key):
            raise ValueError("key must be a non-empty string")
        if not isinstance(server, str) or not server:
            raise ValueError("server must be a non-empty URL")
        if timeout <= 0:
            raise ValueError("timeout must be positive")
        self.key = key
        self.server = server.rstrip("/")
        self.timeout = timeout

    def __repr__(self) -> str:
        key = "<set>" if self.key else None
        return f"BarkClient(key={key!r}, server={self.server!r})"

    # ------------------------------------------------------------------ API

    def send(
        self,
        params: PushParams | None = None,
        *,
        method: str = "json",
        key: str | None = None,
        body_key: bool = False,
        **fields: Any,
    ) -> BarkResponse:
        """Send one push.

        ``method`` is ``"json"`` (default), ``"form"`` or ``"get"``. With
        ``body_key=True`` the request goes to ``POST /push`` and the device key
        must be inside ``params`` (``device_key`` or ``device_keys``).
        Keyword arguments are shorthand for ``PushParams(**fields)``.
        """
        params = self._make_params(params, fields)
        method = self._check_method(method)

        if body_key and key is not None:
            raise ValueError(
                "key= cannot be used with body_key=True; put the key in params"
            )
        if body_key:
            if method == "get":
                raise ValueError("POST /push does not support GET")
            if params.device_key is None and params.device_keys is None:
                raise ValueError(
                    "body_key=True requires device_key or device_keys in params"
                )
            if params.device_keys is not None and method != "json":
                raise ValueError("device_keys is only supported in JSON requests")
            url = f"{self.server}/push"
        else:
            if params.device_key is not None:
                raise ValueError(
                    "params.device_key requires body_key=True; "
                    "use key=... or the client key for /{key} requests"
                )
            if params.device_keys is not None:
                raise ValueError("device_keys requires body_key=True (POST /push)")
            device_key = key or self.key
            if not device_key:
                raise ValueError("device key required (client key or key=...)")
            url = f"{self.server}/{quote(device_key, safe='')}"

        headers = {"Accept": "application/json", "User-Agent": _USER_AGENT}
        data: bytes | None
        if method == "get":
            url = self._get_url(url, params)
            data = None
        elif method == "json":
            data = json.dumps(
                params.to_payload(), ensure_ascii=False, separators=(",", ":")
            ).encode("utf-8")
            headers["Content-Type"] = "application/json; charset=utf-8"
        else:
            data = params.to_form().encode("utf-8")
            headers["Content-Type"] = "application/x-www-form-urlencoded; charset=utf-8"
        return self._request(url, data, headers)

    def send_many(
        self,
        device_keys: Iterable[str],
        params: PushParams | None = None,
        **fields: Any,
    ) -> BarkResponse:
        """Batch push to several devices via ``POST /push`` (JSON only)."""
        base = self._make_params(params, fields)
        if isinstance(device_keys, str):
            raise TypeError("device_keys must be an iterable of strings, not a string")
        keys = tuple(device_keys)
        if not keys:
            raise ValueError("device_keys must not be empty")
        for device_key in keys:
            if not isinstance(device_key, str) or not device_key:
                raise ValueError("device_keys must contain non-empty strings")
        batch = replace(base, device_key=None, device_keys=keys)
        return self.send(batch, method="json", body_key=True)

    def delete(
        self,
        notification_id: str,
        *,
        key: str | None = None,
        method: str = "json",
    ) -> BarkResponse:
        """Delete a notification by ``id``.

        Silent push; requires Background App Refresh on the device.
        """
        return self.send(
            PushParams(id=notification_id, delete=True), method=method, key=key
        )

    def send_encrypted(
        self,
        params: PushParams,
        secret_key: str | bytes,
        *,
        iv: str | bytes | None = None,
        key: str | None = None,
        method: str = "json",
        body_key: bool = False,
    ) -> BarkResponse:
        """Encrypt the content fields and send only ``ciphertext`` + ``iv``.

        ``secret_key`` is the ASCII key configured in the Bark app (16/24/32
        bytes). A random 16-character hex IV is used when ``iv`` is omitted.
        Server-side controls (``isArchive``, ``ttl``, ``id``, ``delete`` and the
        device key) are sent in the clear so the server can act on them.
        """
        if not isinstance(params, PushParams):
            raise TypeError("params must be a PushParams")
        if params.ciphertext is not None or params.iv is not None:
            raise ValueError("params already contains ciphertext/iv")
        if params.device_keys is not None:
            raise ValueError(
                "encrypted batch push is not supported: each device would need "
                "its own ciphertext"
            )

        content = {
            name: value
            for name, value in params.to_payload().items()
            if name in ENCRYPTED_WIRE_FIELDS
        }
        encrypted = encrypt_payload(content, secret_key, iv)
        wrapper = PushParams(
            ciphertext=encrypted.ciphertext,
            iv=encrypted.iv,
            device_key=params.device_key,
            is_archive=params.is_archive,
            ttl=params.ttl,
            id=params.id,
            delete=params.delete,
        )
        return self.send(wrapper, method=method, key=key, body_key=body_key)

    # -------------------------------------------------------------- helpers

    @staticmethod
    def _make_params(params: PushParams | None, fields: dict[str, Any]) -> PushParams:
        if params is None:
            if not fields:
                raise TypeError("send() requires params or keyword fields")
            return PushParams(**fields)
        if fields:
            raise TypeError("pass either params or keyword fields, not both")
        if not isinstance(params, PushParams):
            raise TypeError("params must be a PushParams")
        return params

    @staticmethod
    def _check_method(method: str) -> str:
        if not isinstance(method, str) or method.lower() not in _METHODS:
            raise ValueError("method must be 'json', 'form' or 'get'")
        return method.lower()

    @staticmethod
    def _get_url(url: str, params: PushParams) -> str:
        segments: list[str] = []
        path_fields: set[str] = set()
        if params.body is not None:
            if params.title is not None:
                segments.append(params.title)
                path_fields.add("title")
            if params.subtitle is not None and params.title is not None:
                segments.append(params.subtitle)
                path_fields.add("subtitle")
            segments.append(params.body)
            path_fields.add("body")
        if segments:
            url += "/" + "/".join(quote(segment, safe="") for segment in segments)
        pairs = [
            (name, value)
            for name, value in params.to_query_pairs()
            if name not in path_fields
        ]
        if pairs:
            url += "?" + urlencode(pairs, quote_via=quote)
        return url

    def _request(
        self, url: str, data: bytes | None, headers: dict[str, str]
    ) -> BarkResponse:
        request = Request(
            url,
            data=data,
            headers=headers,
            method="POST" if data is not None else "GET",
        )
        try:
            with urlopen(request, timeout=self.timeout) as response:
                raw = response.read()
                parsed = self._parse(
                    response.status, raw, response.headers.get_content_charset()
                )
        except HTTPError as exc:
            raw = exc.read()
            charset = exc.headers.get_content_charset() if exc.headers else None
            parsed = self._parse(exc.code, raw, charset)
            raise self._make_error(parsed) from None
        except (URLError, TimeoutError, OSError) as exc:
            raise BarkConnectionError(
                f"request to {self.server} failed: {exc}"
            ) from exc

        if not parsed.ok:
            raise self._make_error(parsed)
        return parsed

    @staticmethod
    def _parse(status: int, raw: bytes, charset: str | None) -> BarkResponse:
        text = raw.decode(charset or "utf-8", errors="replace")
        payload: Any = None
        try:
            payload = json.loads(text)
        except ValueError:
            payload = None

        code: int | None = None
        message: str | None = None
        data: Any = None
        if isinstance(payload, dict):
            raw_code = payload.get("code")
            if isinstance(raw_code, bool):
                raw_code = None
            if isinstance(raw_code, str) and raw_code.strip().isdigit():
                raw_code = int(raw_code.strip())
            if isinstance(raw_code, int):
                code = raw_code
            raw_message = payload.get("message")
            if isinstance(raw_message, str):
                message = raw_message
            data = payload.get("data")

        return BarkResponse(
            status=status,
            raw=text,
            code=code,
            message=message,
            data=data,
            payload=payload,
        )

    @staticmethod
    def _make_error(response: BarkResponse) -> Exception:
        if response.code is not None and response.code != 200:
            return BarkAPIError(
                response.message or f"Bark API error (code {response.code})",
                response=response,
            )
        detail = response.message or f"HTTP {response.status}"
        return BarkHTTPError(detail, response=response)
