"""Exceptions raised by :mod:`bark_push`."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover
    from .client import BarkResponse


class BarkError(Exception):
    """Base class for every bark-push error."""


class BarkConnectionError(BarkError):
    """The server could not be reached, or the request timed out."""


class BarkHTTPError(BarkError):
    """HTTP failure without a Bark API error payload."""

    def __init__(self, message: str, *, response: BarkResponse | None = None) -> None:
        super().__init__(message)
        self.response = response
        self.status = response.status if response is not None else None
        self.body = response.raw if response is not None else ""


class BarkAPIError(BarkError):
    """The server answered with a non-200 Bark API ``code``."""

    def __init__(self, message: str, *, response: BarkResponse | None = None) -> None:
        super().__init__(message)
        self.response = response
        self.code = response.code if response is not None else None
        self.status = response.status if response is not None else None
