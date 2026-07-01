"""
bilibili_api.py — Bilibili API client with retry and rate-limit handling.

Provides:
    BilibiliClient.fetch_feed_page(offset)  — one page of dynamics
    BilibiliClient.fetch_detail(dynamic_id)  — single dynamic detail
    BilibiliClient.headers                   — reusable request headers
"""

import time
import logging
from typing import Optional

import requests

from .config import (
    FEED_API,
    DETAIL_API,
    HOST_MID,
    BILIBILI_COOKIE,
    USER_AGENT,
    MAX_RETRIES,
    RETRY_BASE_DELAY,
    RETRY_MAX_DELAY,
    RATE_LIMIT_WAIT,
    REQUEST_TIMEOUT,
)

logger = logging.getLogger(__name__)


class APIError(Exception):
    """Raised when the Bilibili API returns an unrecoverable error."""


class BilibiliClient:
    """Stateless HTTP client for Bilibili dynamic feed APIs."""

    def __init__(self, cookie: Optional[str] = None):
        self.cookie = cookie or BILIBILI_COOKIE
        self.session = requests.Session()
        self.session.headers.update(self.headers)

    @property
    def headers(self) -> dict:
        h = {
            "User-Agent": USER_AGENT,
            "Referer": f"https://space.bilibili.com/{HOST_MID}/dynamic",
            "Origin": "https://space.bilibili.com",
            "Accept": "application/json, text/plain, */*",
        }
        if self.cookie:
            h["Cookie"] = self.cookie
        return h

    # ------------------------------------------------------------------
    # Core request with retry
    # ------------------------------------------------------------------

    def _request(self, url: str, params: dict) -> dict:
        """GET request with exponential-backoff retry.

        Handles:
            - HTTP errors (retry)
            - Network exceptions (retry)
            - Bilibili rate limit code -352 (wait + retry)
            - Other non-zero API codes (raise APIError)

        Returns the `data` field of the JSON response on success.
        """
        last_exc = None

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                resp = self.session.get(
                    url, params=params, timeout=REQUEST_TIMEOUT
                )
                resp.raise_for_status()
                body = resp.json()

                code = body.get("code", -1)

                if code == 0:
                    return body.get("data", {})

                # Rate limited by Bilibili anti-scraping
                if code == -352:
                    wait = min(RATE_LIMIT_WAIT * attempt, RETRY_MAX_DELAY * 4)
                    logger.warning(
                        "Rate limited (-352), waiting %ds (attempt %d/%d)",
                        wait, attempt, MAX_RETRIES,
                    )
                    time.sleep(wait)
                    continue

                # Other API error
                msg = body.get("message", "unknown")
                logger.error(
                    "API error code=%d msg=%s (attempt %d/%d)",
                    code, msg, attempt, MAX_RETRIES,
                )
                if attempt < MAX_RETRIES:
                    time.sleep(min(RETRY_BASE_DELAY * (2 ** (attempt - 1)), RETRY_MAX_DELAY))
                    continue
                raise APIError(f"Bilibili API error: code={code} msg={msg}")

            except requests.exceptions.RequestException as e:
                last_exc = e
                logger.warning(
                    "Request failed: %s (attempt %d/%d)",
                    e, attempt, MAX_RETRIES,
                )
                if attempt < MAX_RETRIES:
                    delay = min(RETRY_BASE_DELAY * (2 ** (attempt - 1)), RETRY_MAX_DELAY)
                    time.sleep(delay)

        if last_exc:
            raise APIError(f"Request failed after {MAX_RETRIES} attempts: {last_exc}")
        raise APIError(f"Request failed after {MAX_RETRIES} attempts")

    # ------------------------------------------------------------------
    # Public API methods
    # ------------------------------------------------------------------

    def fetch_feed_page(self, offset: str = "") -> dict:
        """Fetch one page of the user's dynamic feed.

        Args:
            offset: Pagination cursor. Empty string for the first (latest) page.

        Returns:
            dict with keys: items (list), offset (str), has_more (bool),
            update_num, update_baseline
        """
        params = {"host_mid": HOST_MID}
        if offset:
            params["offset"] = offset

        return self._request(FEED_API, params)

    def fetch_detail(self, dynamic_id: str) -> dict:
        """Fetch a single dynamic by ID (useful for repost resolution).

        Returns:
            dict with the full dynamic item under key 'item'.
        """
        params = {"id": dynamic_id}
        return self._request(DETAIL_API, params)

    def fetch_latest_items(self, count: int = 5) -> list:
        """Quick helper: fetch only the first page and return the items list.

        Used by quick_check for minimal-overhead update detection.
        """
        data = self.fetch_feed_page()
        items = data.get("items", [])
        return items[:count]
