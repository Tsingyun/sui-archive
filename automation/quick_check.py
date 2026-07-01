"""
quick_check.py — Lightweight update detection (<3 seconds).

Compares the latest dynamic from Bilibili's API against the most recent
post stored in SQLite. If they match, no further work is needed.

Usage:
    from automation.quick_check import QuickChecker
    checker = QuickChecker()
    result = checker.check()
    # result.has_updates  → bool
    # result.latest_id    → str
    # result.new_count    → int (estimated)
"""

import logging
import sqlite3
import time
from dataclasses import dataclass
from typing import Optional

from .config import DB_PATH, PLATFORM_ID, SKIP_TYPES
from .bilibili_api import BilibiliClient, APIError

logger = logging.getLogger(__name__)


@dataclass
class QuickCheckResult:
    has_updates: bool
    latest_id: str = ""
    latest_timestamp: int = 0
    db_latest_id: str = ""
    db_latest_ts: int = 0
    new_count: int = 0
    elapsed_ms: float = 0
    error: Optional[str] = None


def _iso_to_ts(iso_str: str) -> int:
    """Parse ISO 8601 timestamp (e.g. 2026-06-27T00:50:58+08:00) to Unix ts."""
    if not iso_str:
        return 0
    try:
        from datetime import datetime, timezone, timedelta
        # Handle +08:00 timezone offset
        if "+" in iso_str or iso_str.endswith("Z"):
            dt = datetime.fromisoformat(iso_str)
        else:
            # Assume CST if no timezone
            cst = timezone(timedelta(hours=8))
            dt = datetime.fromisoformat(iso_str).replace(tzinfo=cst)
        return int(dt.timestamp())
    except (ValueError, TypeError):
        return 0


class QuickChecker:
    """Performs a minimal-overhead comparison between remote and local state."""

    def __init__(self, db_path=None, client=None):
        self.db_path = db_path or DB_PATH
        self.client = client or BilibiliClient()

    def _get_db_latest(self) -> tuple:
        """Get the latest post from SQLite.

        Returns (platform_post_id, published_at_iso, published_ts) or ("", "", 0).
        """
        try:
            conn = sqlite3.connect(str(self.db_path))
            conn.execute("PRAGMA journal_mode=WAL")
            cursor = conn.execute(
                """
                SELECT platform_post_id, published_at
                FROM posts
                WHERE platform_id = ?
                ORDER BY published_at DESC
                LIMIT 1
                """,
                (PLATFORM_ID,),
            )
            row = cursor.fetchone()
            conn.close()
            if row:
                pub_id = str(row[0])
                pub_iso = row[1] or ""
                pub_ts = _iso_to_ts(pub_iso)
                return pub_id, pub_iso, pub_ts
        except sqlite3.Error as e:
            logger.warning("Could not read latest post from DB: %s", e)
        return "", "", 0

    def _extract_item_ts(self, item: dict) -> int:
        """Extract Unix timestamp from a Bilibili feed item."""
        try:
            return int(
                item.get("modules", {})
                .get("module_author", {})
                .get("pub_ts", 0)
            )
        except (ValueError, TypeError):
            return 0

    def check(self) -> QuickCheckResult:
        """Run the quick check. Target: < 3 seconds.

        Detection strategy (robust against non-chronological API ordering):

        1. Read the latest post timestamp from SQLite.
        2. Fetch first page of Bilibili feed (1 HTTP request, ~1-2s).
        3. Compare timestamps: only flag updates if the API has posts
           with a publish time NEWER than the DB's latest.
        4. Count how many items on page 1 are actually newer.
        """
        t0 = time.monotonic()
        result = QuickCheckResult(has_updates=False)

        try:
            # Step 1: Local state
            db_latest_id, db_latest_iso, db_latest_ts = self._get_db_latest()
            result.db_latest_id = db_latest_id
            result.db_latest_ts = db_latest_ts
            logger.info(
                "DB latest: id=%s ts=%d (%s)",
                db_latest_id, db_latest_ts, db_latest_iso,
            )

            if not db_latest_id:
                # Empty database — everything is new
                result.has_updates = True
                result.error = "No posts in database"
                result.elapsed_ms = (time.monotonic() - t0) * 1000
                return result

            # Step 2: Fetch first page (lightweight — single API call)
            feed_data = self.client.fetch_feed_page(offset="")
            items = feed_data.get("items", [])

            if not items:
                logger.info("No items returned from API")
                result.elapsed_ms = (time.monotonic() - t0) * 1000
                return result

            # Step 3: Extract API's latest timestamp
            latest_item = items[0]
            latest_id = str(latest_item.get("id_str", ""))
            latest_ts = self._extract_item_ts(latest_item)

            result.latest_id = latest_id
            result.latest_timestamp = latest_ts
            logger.info("API latest: id=%s ts=%d", latest_id, latest_ts)

            # Step 4: Find the maximum timestamp across all items on page 1
            # (the API may not return items in strict chronological order)
            max_api_ts = 0
            all_item_ids = set()
            for item in items:
                ts = self._extract_item_ts(item)
                if ts > max_api_ts:
                    max_api_ts = ts
                all_item_ids.add(str(item.get("id_str", "")))

            # Step 5: Decision logic
            # Case A: DB's latest ID is in the API response → no new posts above it
            if db_latest_id in all_item_ids:
                # Count items that appear BEFORE the DB latest in the API list
                # AND have a newer timestamp
                new_count = 0
                for item in items:
                    item_id = str(item.get("id_str", ""))
                    item_type = item.get("type", "")
                    if item_type in SKIP_TYPES:
                        continue
                    if item_id == db_latest_id:
                        break
                    item_ts = self._extract_item_ts(item)
                    if item_ts > db_latest_ts:
                        new_count += 1

                if new_count == 0:
                    logger.info("No new posts (DB latest found in API feed, no newer items)")
                    result.elapsed_ms = (time.monotonic() - t0) * 1000
                    return result

                result.has_updates = True
                result.new_count = new_count
                logger.info("Detected %d newer post(s) before DB boundary in API feed", new_count)

            # Case B: DB's latest ID is NOT in the API response
            # Check if any item has a timestamp newer than the DB's latest
            elif max_api_ts > db_latest_ts:
                new_count = sum(
                    1 for item in items
                    if item.get("type", "") not in SKIP_TYPES
                    and self._extract_item_ts(item) > db_latest_ts
                )
                result.has_updates = True
                result.new_count = new_count
                logger.info(
                    "Detected %d post(s) newer than DB (DB latest not on page 1)",
                    new_count,
                )

            else:
                # API's newest is older than or same as DB's newest → no updates
                logger.info(
                    "No updates: API max_ts (%d) <= DB latest_ts (%d)",
                    max_api_ts, db_latest_ts,
                )
                result.elapsed_ms = (time.monotonic() - t0) * 1000
                return result

        except APIError as e:
            result.error = str(e)
            logger.error("Quick check API error: %s", e)
        except Exception as e:
            result.error = f"{type(e).__name__}: {e}"
            logger.error("Quick check failed: %s", e)

        result.elapsed_ms = (time.monotonic() - t0) * 1000
        return result
