#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
backfill_text.py -- Repair posts with empty plain_text via the detail API.

The Bilibili feed API sometimes omits the ``module_dynamic.desc`` block for
DRAW (image/text) posts, resulting in empty ``plain_text`` in the database.
The detail API reliably returns this field, so we can backfill the missing
text by querying each affected post individually.

Usage:
    python -X utf8 scripts/backfill_text.py [--dry-run]

Options:
    --dry-run   Show which posts would be updated without modifying the DB.
"""

import json
import sys
import time
from pathlib import Path

# Allow imports from project root
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from automation.bilibili_api import BilibiliClient
from automation.config import DB_PATH
from automation.fetcher import _parse_rich_text

import sqlite3


DELAY = 1.5  # seconds between detail API calls


def main():
    dry_run = "--dry-run" in sys.argv

    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row

    # Find posts with empty plain_text
    rows = conn.execute("""
        SELECT id, uuid, platform_post_id, post_type, published_at
        FROM posts
        WHERE plain_text IS NULL OR plain_text = ''
        ORDER BY published_at DESC
    """).fetchall()

    if not rows:
        print("No posts with empty plain_text found. Database is clean.")
        conn.close()
        return

    print(f"Found {len(rows)} post(s) with empty plain_text.")
    if dry_run:
        print("[DRY RUN] No changes will be made.\n")

    client = BilibiliClient()
    updated = 0
    failed = 0

    for row in rows:
        post_id = row["id"]
        dyn_id = row["platform_post_id"]
        post_type = row["post_type"]
        pub_date = row["published_at"][:10]

        print(f"  {dyn_id}  {pub_date}  type={post_type}  ... ", end="", flush=True)

        try:
            detail = client.fetch_detail(dyn_id)
            item = detail.get("item") or {}

            mod_dyn = item.get("modules", {}).get("module_dynamic", {}) or {}
            desc = mod_dyn.get("desc") or {}
            plain_text, rich_json = _parse_rich_text(desc)

            if plain_text:
                preview = plain_text[:60].replace("\n", " ")
                print(f"OK  ({len(plain_text)} chars) \"{preview}\"")

                if not dry_run:
                    conn.execute(
                        "UPDATE posts SET plain_text = ?, rich_text = ? WHERE id = ?",
                        (plain_text, rich_json, post_id),
                    )
                    updated += 1
            else:
                print("STILL EMPTY (detail API returned no text)")

        except Exception as exc:
            print(f"FAILED: {exc}")
            failed += 1

        time.sleep(DELAY)

    if not dry_run:
        conn.execute("COMMIT")
        print(f"\nDone. Updated {updated} post(s), {failed} failed.")
    else:
        print(f"\n[DRY RUN] Would update {updated} post(s).")

    conn.close()


if __name__ == "__main__":
    main()
