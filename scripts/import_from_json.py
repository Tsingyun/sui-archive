#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
import_from_json.py — Import dynamics.json into sui-archive.db

Reads dynamics.json from the project directory, creates the SQLite database
schema (if not exists), and imports all dynamics atomically in a single
transaction. Idempotent: running twice does not create duplicates.

Usage:
    python -X utf8 import_from_json.py
"""

import json
import os
import re
import sqlite3
import sys
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

PROJECT_DIR = Path(r"F:\文件库\岁己\dynamics_archive_QoderWork")
DYNAMICS_JSON = PROJECT_DIR / "dynamics.json"
SCHEMA_SQL = PROJECT_DIR / "data" / "schema.sql"
DB_PATH = PROJECT_DIR / "data" / "sui-archive.db"
IMAGES_DIR = PROJECT_DIR / "images"

PLATFORM_ID = 1  # bilibili, seeded by schema.sql

# Timezone: UTC+8 (China Standard Time)
CST = timezone(timedelta(hours=8))

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Post-type mapping from B站 dynamic type to generic post_type
TYPE_MAP = {
    "DYNAMIC_TYPE_DRAW": None,       # resolved at runtime: 'image' or 'text'
    "DYNAMIC_TYPE_WORD": "text",
    "DYNAMIC_TYPE_FORWARD": "repost",
    "DYNAMIC_TYPE_ARTICLE": "article",
    "DYNAMIC_TYPE_LIVE": "live",
    "DYNAMIC_TYPE_MUSIC": "audio",
    "DYNAMIC_TYPE_AV": "video",
}

MIME_MAP = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".bmp": "image/bmp",
}


def ts_to_iso(ts: int) -> str:
    """Convert Unix timestamp to ISO 8601 with +08:00."""
    dt = datetime.fromtimestamp(ts, tz=CST)
    return dt.strftime("%Y-%m-%dT%H:%M:%S+08:00")


def now_iso() -> str:
    """Current time as ISO 8601 with +08:00."""
    return datetime.now(tz=CST).strftime("%Y-%m-%dT%H:%M:%S+08:00")


def determine_post_type(dynamic: dict) -> str:
    """Determine the generic post_type for a dynamic."""
    if dynamic.get("is_repost"):
        return "repost"

    raw_type = dynamic.get("type", "")
    mapped = TYPE_MAP.get(raw_type)

    if mapped is not None:
        return mapped

    # DYNAMIC_TYPE_DRAW: 'image' if has images, else 'text'
    if raw_type == "DYNAMIC_TYPE_DRAW":
        images = dynamic.get("content", {}).get("images", [])
        return "image" if images else "text"

    # Fallback
    return "mixed"


def url_to_ext(url: str) -> str:
    """Extract file extension from a URL. Returns '.jpg' as default."""
    if not url:
        return ""
    # Strip query string
    clean = url.split("?")[0].split("#")[0]
    _, ext = os.path.splitext(clean)
    return ext.lower() if ext else ".jpg"


def ext_to_mime(ext: str) -> str:
    """Map file extension to MIME type."""
    return MIME_MAP.get(ext.lower(), "image/jpeg")


def safe_int(val, default=None):
    """Convert a value to int safely."""
    if val is None:
        return default
    try:
        return int(val)
    except (ValueError, TypeError):
        return default


def get_image_dimensions_from_file(filepath: Path):
    """Get image dimensions using Pillow. Returns (width, height) or (None, None)."""
    try:
        from PIL import Image
        with Image.open(filepath) as img:
            return img.size  # (width, height)
    except Exception:
        return None, None


def build_existing_files_map(images_dir: Path) -> dict:
    """
    Scan images/ directory and build a map of existing files.
    Key: (dynamic_id, index_str, quality) -> full filename
    """
    file_map = {}
    if not images_dir.exists():
        return file_map

    pattern = re.compile(r"^(\d+)_(\d+)@(\w+)\.\w+$")
    for fname in images_dir.iterdir():
        if not fname.is_file():
            continue
        m = pattern.match(fname.name)
        if m:
            dyn_id, idx_str, quality = m.group(1), m.group(2), m.group(3)
            file_map[(dyn_id, idx_str, quality)] = fname.name

    return file_map


# ---------------------------------------------------------------------------
# Main import logic
# ---------------------------------------------------------------------------

def main():
    print("=" * 60)
    print("SUI Archive — JSON to SQLite Importer")
    print("=" * 60)

    # 1. Read dynamics.json
    print(f"\n[1/5] Reading {DYNAMICS_JSON}...")
    if not DYNAMICS_JSON.exists():
        print(f"ERROR: {DYNAMICS_JSON} not found!")
        sys.exit(1)

    with open(DYNAMICS_JSON, "r", encoding="utf-8") as f:
        data = json.load(f)

    dynamics = data["dynamics"]
    total = len(dynamics)
    print(f"  Found {total} dynamics.")

    # 2. Ensure data/ directory exists
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    # 3. Create/open database and execute schema
    print(f"\n[2/5] Initializing database {DB_PATH}...")
    if not SCHEMA_SQL.exists():
        print(f"ERROR: {SCHEMA_SQL} not found!")
        sys.exit(1)

    with open(SCHEMA_SQL, "r", encoding="utf-8") as f:
        schema_sql = f.read()

    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    conn.execute("PRAGMA synchronous = NORMAL")
    conn.execute("PRAGMA cache_size = -64000")
    conn.execute("PRAGMA temp_store = MEMORY")

    # Execute schema (all CREATE TABLE IF NOT EXISTS — idempotent)
    conn.executescript(schema_sql)

    # Re-enable foreign keys after executescript (it issues implicit COMMIT)
    conn.execute("PRAGMA foreign_keys = ON")

    print("  Schema applied successfully.")

    # 4. Pre-scan images/ directory for extension fallback
    print(f"\n[3/5] Scanning images directory...")
    existing_files = build_existing_files_map(IMAGES_DIR)
    print(f"  Found {len(existing_files)} existing image files.")

    # 5. Import all dynamics in a single transaction
    print(f"\n[4/5] Importing {total} dynamics...")
    archived_at = now_iso()

    # Counters
    counts = {
        "posts_inserted": 0,
        "posts_skipped": 0,
        "images_inserted": 0,
        "images_skipped": 0,
        "post_media_inserted": 0,
        "post_media_skipped": 0,
        "authors_created": 0,
        "authors_found": 0,
        "stats_inserted": 0,
        "stats_skipped": 0,
        "reposts_resolved": 0,
    }

    # Track author cache: (platform_id, platform_user_id) -> author_id
    author_cache = {}
    # Pre-load existing authors
    cursor = conn.execute("SELECT id, platform_id, platform_user_id FROM authors")
    for row in cursor:
        author_cache[(row[1], row[2])] = row[0]

    # Track which platform_post_ids are being inserted (for repost resolution)
    all_platform_post_ids = set()

    # Use a single transaction
    conn.execute("BEGIN TRANSACTION")

    try:
        for i, dyn in enumerate(dynamics):
            dynamic_id = str(dyn["dynamic_id"])
            all_platform_post_ids.add(dynamic_id)

            # --- Determine post_type ---
            post_type = determine_post_type(dyn)
            platform_post_type = dyn.get("type", "")

            # --- Published time ---
            publish_ts = dyn.get("publish_timestamp", 0)
            published_at = ts_to_iso(publish_ts) if publish_ts else archived_at

            # --- Content ---
            content = dyn.get("content", {})
            plain_text = content.get("text") or None
            major_type = content.get("major_type") or None

            # --- Source URL ---
            source_url = f"https://t.bilibili.com/{dynamic_id}"

            # --- Platform metadata ---
            metadata = {}
            if major_type:
                metadata["major_type"] = major_type
            platform_metadata = json.dumps(metadata, ensure_ascii=False) if metadata else None

            # --- Repost handling ---
            is_repost = dyn.get("is_repost", False)
            repost_content = dyn.get("repost_content")
            repost_of_id = None       # resolved in pass 2
            repost_snapshot = None
            original_author_id = None

            if is_repost and repost_content:
                # Build repost snapshot (will be cleared if original is in archive)
                rc_id = str(repost_content.get("id", "")) if repost_content.get("id") else None
                rc_type = repost_content.get("type", "")
                rc_text = repost_content.get("text", "")
                rc_deleted = repost_content.get("deleted", False)
                rc_author_name = repost_content.get("author_name")
                rc_author_mid = repost_content.get("author_mid")

                # Find or create author
                if rc_author_mid is not None and rc_author_name:
                    mid_str = str(rc_author_mid)
                    cache_key = (PLATFORM_ID, mid_str)
                    if cache_key in author_cache:
                        original_author_id = author_cache[cache_key]
                        counts["authors_found"] += 1
                    else:
                        profile_url = f"https://space.bilibili.com/{mid_str}"
                        conn.execute(
                            """INSERT OR IGNORE INTO authors
                               (platform_id, platform_user_id, display_name, profile_url)
                               VALUES (?, ?, ?, ?)""",
                            (PLATFORM_ID, mid_str, rc_author_name, profile_url),
                        )
                        # Retrieve the id (whether newly inserted or existing)
                        row = conn.execute(
                            """SELECT id FROM authors
                               WHERE platform_id = ? AND platform_user_id = ?""",
                            (PLATFORM_ID, mid_str),
                        ).fetchone()
                        if row:
                            original_author_id = row[0]
                            author_cache[cache_key] = row[0]
                            counts["authors_created"] += 1

                # Build snapshot JSON (tentative — cleared later if original in archive)
                snapshot = {
                    "platform_post_id": rc_id,
                    "type": rc_type,
                    "text": rc_text,
                    "deleted": rc_deleted,
                    "author_name": rc_author_name,
                    "author_mid": str(rc_author_mid) if rc_author_mid is not None else None,
                }
                repost_snapshot = json.dumps(snapshot, ensure_ascii=False)

            # --- Insert post ---
            post_uuid = str(uuid.uuid4())
            try:
                cur = conn.execute(
                    """INSERT OR IGNORE INTO posts
                       (uuid, platform_id, platform_post_id, post_type,
                        platform_post_type, published_at, archived_at,
                        source_url, plain_text, language,
                        repost_of_id, repost_snapshot, original_author_id,
                        platform_metadata, is_pinned, is_deleted, schema_version)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0, 1)""",
                    (
                        post_uuid, PLATFORM_ID, dynamic_id, post_type,
                        platform_post_type, published_at, archived_at,
                        source_url, plain_text, "zh-CN",
                        repost_of_id, repost_snapshot, original_author_id,
                        platform_metadata,
                    ),
                )
                if cur.rowcount > 0:
                    counts["posts_inserted"] += 1
                else:
                    counts["posts_skipped"] += 1
            except sqlite3.IntegrityError:
                counts["posts_skipped"] += 1

            # Get the post's row id (whether newly inserted or existing)
            row = conn.execute(
                "SELECT id FROM posts WHERE platform_id = ? AND platform_post_id = ?",
                (PLATFORM_ID, dynamic_id),
            ).fetchone()
            post_id = row[0] if row else None

            if post_id is None:
                # Should not happen, but safety
                continue

            # --- Insert images for original content ---
            images_list = content.get("images", [])
            for img_idx, img in enumerate(images_list):
                _insert_image(
                    conn, counts, existing_files,
                    dynamic_id=dynamic_id,
                    post_id=post_id,
                    img=img,
                    img_index=img_idx,
                    quality="original",
                    is_repost_media=False,
                )

            # --- Insert images for repost content ---
            if is_repost and repost_content:
                repost_images = repost_content.get("images", [])
                for img_idx, img in enumerate(repost_images):
                    _insert_image(
                        conn, counts, existing_files,
                        dynamic_id=dynamic_id,
                        post_id=post_id,
                        img=img,
                        img_index=100 + img_idx,
                        quality="repost",
                        is_repost_media=True,
                    )

            # --- Insert stats ---
            stats = dyn.get("stats", {})
            stat_views = stats.get("views")  # usually None
            stat_likes = stats.get("likes", 0) or 0
            stat_comments = stats.get("comments", 0) or 0
            stat_forwards = stats.get("forwards", 0) or 0

            # Only insert if no stats exist for this post yet (idempotent)
            cur = conn.execute(
                """INSERT INTO post_stats (post_id, views, likes, comments, forwards, snapshot_at)
                   SELECT ?, ?, ?, ?, ?, ?
                   WHERE NOT EXISTS (SELECT 1 FROM post_stats WHERE post_id = ?)""",
                (post_id, stat_views, stat_likes, stat_comments, stat_forwards,
                 archived_at, post_id),
            )
            if cur.rowcount > 0:
                counts["stats_inserted"] += 1
            else:
                counts["stats_skipped"] += 1

            # --- Progress ---
            if (i + 1) % 500 == 0:
                print(f"  Progress: {i + 1}/{total} ({(i + 1) * 100 // total}%)")

        # -------------------------------------------------------------------
        # Pass 2: Resolve repost_of_id for reposts where original is in archive
        # -------------------------------------------------------------------
        print(f"\n[5/5] Resolving repost references...")

        # Build platform_post_id → posts.id mapping for all posts in DB
        pid_map = {}
        cursor = conn.execute(
            "SELECT id, platform_post_id FROM posts WHERE platform_id = ?",
            (PLATFORM_ID,),
        )
        for row in cursor:
            pid_map[row[1]] = row[0]

        # For each repost, resolve the reference
        for dyn in dynamics:
            if not dyn.get("is_repost"):
                continue
            rc = dyn.get("repost_content")
            if not rc:
                continue

            rc_id = str(rc.get("id", "")) if rc.get("id") else None
            if not rc_id or rc_id == "0":
                continue

            dynamic_id = str(dyn["dynamic_id"])
            post_row = conn.execute(
                "SELECT id FROM posts WHERE platform_id = ? AND platform_post_id = ?",
                (PLATFORM_ID, dynamic_id),
            ).fetchone()
            if not post_row:
                continue
            post_id = post_row[0]

            if rc_id in pid_map:
                # Original is in archive — set repost_of_id, clear snapshot
                original_post_id = pid_map[rc_id]
                conn.execute(
                    """UPDATE posts
                       SET repost_of_id = ?, repost_snapshot = NULL
                       WHERE id = ?""",
                    (original_post_id, post_id),
                )
                counts["reposts_resolved"] += 1
            # else: repost_snapshot was already set during insert, repost_of_id stays NULL

        # Commit the transaction
        conn.execute("COMMIT")
        print("  Transaction committed successfully.")

    except Exception as e:
        conn.execute("ROLLBACK")
        print(f"\nERROR: Import failed, transaction rolled back.")
        print(f"  {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        conn.close()
        sys.exit(1)

    # -------------------------------------------------------------------
    # Summary
    # -------------------------------------------------------------------
    print("\n" + "=" * 60)
    print("IMPORT SUMMARY")
    print("=" * 60)

    # Actual row counts from database
    tables = ["platforms", "authors", "posts", "images", "post_media",
              "post_stats", "post_tags", "tags", "media"]
    print("\nDatabase row counts:")
    for table in tables:
        try:
            row = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
            print(f"  {table:20s}: {row[0]:>6d}")
        except Exception:
            pass

    print(f"\nImport statistics:")
    print(f"  Posts inserted     : {counts['posts_inserted']}")
    print(f"  Posts skipped      : {counts['posts_skipped']}")
    print(f"  Images inserted    : {counts['images_inserted']}")
    print(f"  Images skipped     : {counts['images_skipped']}")
    print(f"  Post-media inserted: {counts['post_media_inserted']}")
    print(f"  Post-media skipped : {counts['post_media_skipped']}")
    print(f"  Authors created    : {counts['authors_created']}")
    print(f"  Authors found      : {counts['authors_found']}")
    print(f"  Stats inserted     : {counts['stats_inserted']}")
    print(f"  Stats skipped      : {counts['stats_skipped']}")
    print(f"  Reposts resolved   : {counts['reposts_resolved']}")

    # Post-type breakdown
    print(f"\nPosts by type:")
    cursor = conn.execute(
        "SELECT post_type, COUNT(*) FROM posts GROUP BY post_type ORDER BY COUNT(*) DESC"
    )
    for row in cursor:
        print(f"  {row[0]:20s}: {row[1]:>6d}")

    conn.close()
    print(f"\nDone. Database: {DB_PATH}")
    print("=" * 60)


def _insert_image(conn, counts, existing_files, dynamic_id, post_id,
                    img, img_index, quality, is_repost_media):
    """Insert a single image and its post_media association."""
    url = img.get("url", "") or ""
    source_url = url if url else None

    # Determine extension
    ext = url_to_ext(url) if url else ""

    # Fallback: check existing file on disk
    idx_str = f"{img_index:02d}"
    lookup_key = (dynamic_id, idx_str, quality)

    if not ext:
        # Try to find the file in the existing files map
        existing_name = existing_files.get(lookup_key)
        if existing_name:
            _, ext = os.path.splitext(existing_name)
            ext = ext.lower()
        else:
            # Also try scanning by prefix
            prefix = f"{dynamic_id}_{idx_str}@{quality}"
            for key, fname in existing_files.items():
                if fname.startswith(prefix):
                    _, ext = os.path.splitext(fname)
                    ext = ext.lower()
                    break
            if not ext:
                ext = ".jpg"  # default fallback

    # Build filename
    filename = f"{dynamic_id}_{idx_str}@{quality}{ext}"
    storage_path = f"images/{filename}"

    # Determine file properties from disk if file exists
    filepath = IMAGES_DIR / filename
    file_size = None
    width = safe_int(img.get("width"))
    height = safe_int(img.get("height"))
    mime_type = ext_to_mime(ext)

    if filepath.exists():
        file_size = os.path.getsize(filepath)
        pw, ph = get_image_dimensions_from_file(filepath)
        if pw is not None:
            width = pw
            height = ph
    else:
        # Use size_kb from JSON as fallback
        size_kb = safe_int(img.get("size_kb"))
        if size_kb is not None:
            file_size = size_kb * 1024

    # Insert image (idempotent via UNIQUE filename)
    img_uuid = str(uuid.uuid4())
    cur = conn.execute(
        """INSERT OR IGNORE INTO images
           (uuid, filename, storage_path, file_size, width, height,
            mime_type, quality, source_url, is_cover, is_deleted, archived_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?)""",
        (img_uuid, filename, storage_path, file_size, width, height,
         mime_type, quality, source_url,
         1 if img_index == 0 else 0,
         now_iso()),
    )

    if cur.rowcount > 0:
        counts["images_inserted"] += 1
    else:
        counts["images_skipped"] += 1

    # Get the image_id regardless (whether newly inserted or existing)
    img_row = conn.execute(
        "SELECT id FROM images WHERE filename = ?", (filename,)
    ).fetchone()

    if img_row is None:
        return

    image_id = img_row[0]

    # Insert post_media association (idempotent via UNIQUE index)
    try:
        cur = conn.execute(
            """INSERT OR IGNORE INTO post_media
               (post_id, image_id, sort_order, is_repost_media)
               VALUES (?, ?, ?, ?)""",
            (post_id, image_id, img_index, 1 if is_repost_media else 0),
        )
        if cur.rowcount > 0:
            counts["post_media_inserted"] += 1
        else:
            counts["post_media_skipped"] += 1
    except sqlite3.IntegrityError:
        counts["post_media_skipped"] += 1


if __name__ == "__main__":
    main()
