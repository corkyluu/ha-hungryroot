"""Small read-only client for Hungryroot's private web API.

This is the same API hungryroot.com uses in the browser. It is not documented
or supported by Hungryroot, so every parser here is defensive: missing fields
become None instead of errors, and the raw responses are kept for diagnostics.
"""

from __future__ import annotations

import logging
from http.cookies import SimpleCookie
from typing import Any

import aiohttp

from .const import API_BASE, CLIENT_KEY, WEB_ORIGIN

_LOGGER = logging.getLogger(__name__)

TIMEOUT = aiohttp.ClientTimeout(total=30)


class HungryrootError(Exception):
    """Any problem talking to Hungryroot."""


class HungryrootAuthError(HungryrootError):
    """The login was refused or the saved session expired."""


class HungryrootCaptchaRequired(HungryrootAuthError):
    """Hungryroot wants a captcha, so email/password login can't be done from HA."""


class HungryrootApiChanged(HungryrootError):
    """Hungryroot answered, but not in the shape we expect."""


def parse_cookie_string(raw: str) -> dict[str, str]:
    """Turn a pasted `Cookie:` header value into a dict."""
    raw = raw.strip()
    if raw.lower().startswith("cookie:"):
        raw = raw[7:].strip()
    jar: SimpleCookie = SimpleCookie()
    try:
        jar.load(raw)
    except Exception:  # noqa: BLE001 - fall back to a manual split
        pass
    cookies = {k: m.value for k, m in jar.items()}
    if not cookies:
        for part in raw.split(";"):
            if "=" in part:
                k, v = part.split("=", 1)
                cookies[k.strip()] = v.strip()
    return cookies


def cookie_string(cookies: dict[str, str]) -> str:
    return "; ".join(f"{k}={v}" for k, v in cookies.items())


class HungryrootClient:
    """Read-only Hungryroot API client. Never sends anything that changes an order."""

    def __init__(self, session: aiohttp.ClientSession, cookie: str | None = None) -> None:
        self._session = session
        self._cookies: dict[str, str] = parse_cookie_string(cookie) if cookie else {}

    @property
    def cookie(self) -> str:
        """Current session cookies, so the config entry can save refreshed ones."""
        return cookie_string(self._cookies)

    def _headers(self, referer: str = "/") -> dict[str, str]:
        headers = {
            "Accept": "application/json",
            "AUTHORIZATION": CLIENT_KEY,
            "Origin": WEB_ORIGIN,
            "Referer": f"{WEB_ORIGIN}{referer}",
            "X-Requested-From": f"{WEB_ORIGIN}{referer}",
            "User-Agent": (
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/130.0 Safari/537.36"
            ),
        }
        if self._cookies:
            headers["Cookie"] = self.cookie
            if "csrftoken" in self._cookies:
                headers["X-CSRFToken"] = self._cookies["csrftoken"]
        return headers

    def _absorb_cookies(self, resp: aiohttp.ClientResponse) -> None:
        for name, morsel in resp.cookies.items():
            if morsel.value:
                self._cookies[name] = morsel.value
            else:
                self._cookies.pop(name, None)

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: Any = None,
        referer: str = "/",
    ) -> tuple[int, Any]:
        headers = self._headers(referer)
        if json is not None:
            headers["Content-Type"] = "application/json"
        try:
            async with self._session.request(
                method,
                f"{API_BASE}{path}",
                params=params,
                json=json,
                headers=headers,
                timeout=TIMEOUT,
                allow_redirects=False,
            ) as resp:
                self._absorb_cookies(resp)
                if "json" in resp.headers.get("Content-Type", ""):
                    body: Any = await resp.json(content_type=None)
                else:
                    body = await resp.text()
                return resp.status, body
        except (aiohttp.ClientError, TimeoutError) as err:
            raise HungryrootError(f"Could not reach Hungryroot: {err}") from err

    async def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        status, body = await self._request("GET", path, params=params, referer="/account/")
        if status in (401, 403):
            raise HungryrootAuthError(f"Hungryroot session not accepted (HTTP {status})")
        if status == 404:
            raise HungryrootApiChanged(f"{path} no longer exists (HTTP 404)")
        if status >= 400:
            raise HungryrootError(f"{path} failed (HTTP {status}): {str(body)[:200]}")
        if not isinstance(body, (dict, list)):
            raise HungryrootApiChanged(f"{path} did not return JSON")
        return body

    # ---- login ---------------------------------------------------------------

    async def login(self, email: str, password: str) -> None:
        """Log in with email + password. Raises HungryrootCaptchaRequired if blocked."""
        self._cookies = {}
        status, body = await self._request(
            "POST",
            "/api/v2/auth/login/",
            json={"email": email, "password": password},
            referer="/login/",
        )
        _LOGGER.debug("Hungryroot login answered HTTP %s", status)
        if status in (200, 201, 202, 204):
            if not self._cookies:
                raise HungryrootApiChanged("Login succeeded but no session cookie came back")
            return
        text = str(body).lower()
        if any(word in text for word in ("captcha", "challenge", "recaptcha", "bot")):
            raise HungryrootCaptchaRequired(text[:200])
        if status in (400, 401, 403):
            raise HungryrootAuthError(text[:200])
        raise HungryrootError(f"Login failed (HTTP {status})")

    # ---- reads ---------------------------------------------------------------

    async def get_customer(self) -> dict[str, Any]:
        return await self._get("/api/v2/customers/self/")

    async def get_orders(self, bucket: str, limit: int) -> dict[str, Any]:
        return await self._get(
            "/api/v2/customers/self/orders/",
            {"time_bucket": bucket, "limit": limit, "sideload": "tags"},
        )

    async def get_order(self, order_id: int | str) -> dict[str, Any]:
        return await self._get(
            f"/api/v2/customers/self/orders/{order_id}/", {"sideload": "tags"}
        )
