"""Shared async fetching via scrapling sessions. Optionally carries a Goodreads cookie."""

import asyncio
import logging
import email.utils
import random
from datetime import datetime, timezone
from typing import Any

from scrapling.fetchers import AsyncDynamicSession, AsyncStealthySession
from scrapling.parser import Selector

MAX_RETRIES = 4
BACKOFF_BASE = 1.0  # seconds
MAX_BACKOFF = 30.0  # cap per sleep, also caps a server-sent Retry-After

_GOODREADS_DOMAIN = ".goodreads.com"

_http_session: AsyncDynamicSession | None = None
_LOG_FILE = "scrapling_fetch.log"


def _redirect_scrapling_logging() -> None:
    """Send scrapling's verbose output to a file instead of stderr."""
    logger = logging.getLogger("scrapling")
    for handler in list(logger.handlers):
        if isinstance(handler, logging.StreamHandler) and not isinstance(
            handler, logging.FileHandler
        ):
            logger.removeHandler(handler)
    logger.addHandler(logging.FileHandler(_LOG_FILE))
    logger.setLevel(logging.DEBUG)


_stealthy_session: AsyncStealthySession | None = None
_has_cookie: bool = False


def _parse_cookie_string(cookie: str) -> list[dict[str, str]]:
    """Convert a raw Cookie header value into Playwright cookie dicts.

    Playwright's ``browserContext.add_cookies()`` requires a list of
    dicts with ``name``, ``value``, ``domain`` and ``path`` keys.
    """
    cookies: list[dict[str, str]] = []
    for pair in cookie.split(";"):
        pair = pair.strip()
        if "=" not in pair:
            continue
        name, _, value = pair.partition("=")
        cookies.append({
            "name": name.strip(),
            "value": value.strip(),
            "domain": _GOODREADS_DOMAIN,
            "path": "/",
        })
    return cookies


async def init_session(cookie: str | None) -> None:
    """Launch the two Playwright browser sessions."""
    global _http_session, _stealthy_session, _has_cookie
    _has_cookie = bool(cookie)
    pw_cookies = _parse_cookie_string(cookie) if cookie else None

    session_kwargs: dict[str, Any] = dict(
        headless=True, network_idle=True, google_search=False,
    )
    if pw_cookies is not None:
        session_kwargs["cookies"] = pw_cookies

    _redirect_scrapling_logging()

    # Shelves don't appear to need bot protection — use a standard session.
    _http_session = AsyncDynamicSession(**session_kwargs)
    await _http_session.__aenter__()

    # Individual book/author pages do have bot protection.
    _stealthy_session = AsyncStealthySession(**session_kwargs)
    await _stealthy_session.__aenter__()


async def close_session() -> None:
    """Shut down both browser sessions."""
    global _http_session, _stealthy_session
    if _http_session is not None:
        await _http_session.__aexit__(None, None, None)
        _http_session = None
    if _stealthy_session is not None:
        await _stealthy_session.__aexit__(None, None, None)
        _stealthy_session = None


def has_cookie() -> bool:
    return _has_cookie


# ---------------------------------------------------------------------------
# Auth / error detection
# ---------------------------------------------------------------------------


def _detect_auth_failure(response: Selector, body: str) -> bool:
    if response.css("div#third_party_sign_in, div.third_party_sign_in").first:
        return True
    if "wrong with your Goodreads cookie" in body:
        return True
    return False


class AuthError(Exception):
    # Plain Exception, not sys.exit: a SystemExit escaping a gathered task
    # prints a traceback.
    def __init__(self) -> None:
        super().__init__(
            "Cookie appears invalid or expired. "
            "Re-grab the Cookie header value from your browser DevTools and "
            "try again."
        )


class FetchError(Exception):
    def __init__(self, url: str):
        super().__init__(
            f"Failed to fetch {url} after {MAX_RETRIES} retries — "
            "Goodreads may be rate-limiting; try again later."
        )


# ---------------------------------------------------------------------------
# Retry / back-off helpers
# ---------------------------------------------------------------------------


def _is_transient_status(status: int) -> bool:
    return status == 202 or status == 429 or 500 <= status < 600


def _parse_retry_after(header: str | None) -> float | None:
    if not header:
        return None
    if header.isdecimal():  # isdigit() accepts chars (e.g. '²') that int() rejects
        return int(header)
    try:  # Retry-After may instead be an HTTP-date
        retry_at = email.utils.parsedate_to_datetime(header)
    except (TypeError, ValueError):
        return None
    if retry_at.tzinfo is None:
        retry_at = retry_at.replace(tzinfo=timezone.utc)
    return max(0.0, (retry_at - datetime.now(timezone.utc)).total_seconds())


def _backoff(attempt: int) -> float:
    return random.uniform(0, min(MAX_BACKOFF, BACKOFF_BASE * 2**attempt))


# ---------------------------------------------------------------------------
# Fetching
# ---------------------------------------------------------------------------


async def get_soup(url: str, *, stealthy: bool = False) -> Selector:
    """Fetch *url* and return a parsed :class:`Selector`.

    When *stealthy* is ``True`` the request goes through the anti-bot
    session; otherwise the lighter-weight dynamic session is used.
    """
    assert (
        _http_session is not None and _stealthy_session is not None
    ), "init_session() must be called first"
    session = _stealthy_session if stealthy else _http_session

    for attempt in range(MAX_RETRIES + 1):
        try:
            response = await session.fetch(url)
            if not _is_transient_status(response.status):
                if response.status >= 400:
                    raise FetchError(url)
                body = response.html_content
                if _has_cookie and _detect_auth_failure(response, body):
                    raise AuthError()
                return response
            delay = _parse_retry_after(response.headers.get("Retry-After"))
        except (TimeoutError, ConnectionError, OSError):
            delay = None
        if attempt == MAX_RETRIES:
            break
        await asyncio.sleep(
            min(delay, MAX_BACKOFF) if delay is not None else _backoff(attempt)
        )
    raise FetchError(url)
