"""Fail-closed bearer-token authentication and single-process abuse limits.

Configure RETAILER_API_TOKEN_HASHES as JSON: {sha256(token): retailer_id}.
Only token hashes are stored in environment configuration; raw bearer tokens
are issued to each retailer out of band.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import re
import threading
import time
from collections import defaultdict, deque
from typing import Deque

from app.config import settings

_TOKEN_RE = re.compile(r"^[A-Fa-f0-9]{64}$")
_RETAILER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


class SecurityConfigurationError(Exception):
    pass


def token_hashes() -> list[tuple[str, str]]:
    raw = settings.retailer_api_token_hashes.strip()
    try:
        parsed = json.loads(raw or "{}")
    except json.JSONDecodeError as exc:
        raise SecurityConfigurationError("RETAILER_API_TOKEN_HASHES must be valid JSON") from exc
    if not isinstance(parsed, dict):
        raise SecurityConfigurationError("RETAILER_API_TOKEN_HASHES must be a JSON object")
    entries: list[tuple[str, str]] = []
    for digest, retailer_id in parsed.items():
        if not isinstance(digest, str) or not _TOKEN_RE.fullmatch(digest):
            raise SecurityConfigurationError("Each retailer token key must be a SHA-256 hex digest")
        if not isinstance(retailer_id, str) or not _RETAILER_RE.fullmatch(retailer_id):
            raise SecurityConfigurationError("Each retailer ID must be 1-64 safe characters")
        entries.append((digest.lower(), retailer_id))
    return entries


def authenticate_bearer(authorization: str | None) -> str | None:
    entries = token_hashes()
    if not entries:
        raise SecurityConfigurationError("API authentication is not configured")
    if not authorization or not authorization.startswith("Bearer "):
        return None
    token = authorization[7:].strip()
    if len(token) < 24 or len(token) > 512:
        return None
    digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
    matched: str | None = None
    for configured_digest, retailer_id in entries:
        if hmac.compare_digest(digest, configured_digest):
            matched = retailer_id
    return matched


def make_token_hash(token: str) -> str:
    if len(token) < 24:
        raise ValueError("Bearer tokens must be at least 24 characters")
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class SlidingWindowLimiter:
    """Per-process sliding-window limiter; deploy with one API worker.

    This is a basic abuse guard for the single-instance hackathon demo, not a
    distributed limiter. Use Redis/shared storage before horizontal scaling.
    """
    def __init__(self, window_seconds: int = 60):
        self.window_seconds = window_seconds
        self._events: dict[tuple[str, str], Deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, key: tuple[str, str], limit: int, now: float | None = None) -> bool:
        now = time.monotonic() if now is None else now
        cutoff = now - self.window_seconds
        with self._lock:
            events = self._events[key]
            while events and events[0] <= cutoff:
                events.popleft()
            if len(events) >= max(1, limit):
                return False
            events.append(now)
            if len(self._events) > 10_000:
                for old_key in list(self._events)[:2_000]:
                    old_events = self._events[old_key]
                    while old_events and old_events[0] <= cutoff:
                        old_events.popleft()
                    if not old_events:
                        self._events.pop(old_key, None)
            return True

    def clear(self) -> None:
        with self._lock:
            self._events.clear()


rate_limiter = SlidingWindowLimiter()
