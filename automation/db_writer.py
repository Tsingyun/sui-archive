"""
db_writer.py — Incremental SQLite writer for new posts and images.

Writes ParsedPost and ImageRecord data into the sui-archive.db database
with proper transaction management, conflict handling, and FTS5 sync.

Usage:
    from automation.db_writer import DatabaseWriter
    writer = DatabaseWriter()
    stats = writer.write_all(posts, images)
    # stats → {'posts_added': 3, 'images_added': 5, ...}
"""

import logging
import sqlite3
import uuid
from datetime import datetime, timezone, timedelta
from typing import Optional

from .config import DB_PATH, PLATFORM_ID
from .fetcher import ParsedPost, ImageRecord

logger = logging.getLogger(__name__)

CST = timezone(timedelta(hours=8))


def _now_iso() -> str:
    return datetime.now(tz=CST).strftime("%Y-%m-%dT%H:%M:%S+08:00")


def _new_uuid() -> str:
    return str(uuid.uuid4())


class DatabaseWriter:
    """Writes new posts and images to SQLite atomically."""

    def __init__(self, db_path=None):
        self.db_path = str(db_path or DB_PATH)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=5000")
        conn.execute("PRAGMA cache_size=-65536")  # 64 MB
        return conn

    def post_exists(self, conn: sqlite3.Connection, platform_post_id: str) -> bool:
        """Check if a post already exists in the database."""
        cursor = conn.execute(
            "SELECT 1 FROM posts WHERE platform_id = ? AND platform_post_id = ?",
            (PLATFORM_ID, platform_post_id),
        )
        return cursor.fetchone() is not None

    def image_exists_by_filename(self, conn: sqlite3.Connection, filename: str) -> bool:
        cursor = conn.execute(
            "SELECT 1 FROM images WHERE filename = ?", (filename,),
        )
        return cursor.fetchone() is not None

    def image_exists_by_sha256(self, conn: sqlite3.Connection, sha256: str) -> Optional[str]:
        """Check if an image with the same hash already exists.
        Returns the existing filename if found, None otherwise."""
        cursor = conn.execute(
            "SELECT filename FROM images WHERE sha256 = ?", (sha256,),
        )
        row = cursor.fetchone()
        return row[0] if row else None

    def _ensure_author(self, conn: sqlite3.Connection, mid: str, name: str) -> int:
        """Ensure an author record exists and return its ID."""
        cursor = conn.execute(
            "SELECT id FROM authors WHERE platform_id = ? AND platform_user_id = ?",
            (PLATFORM_ID, mid),
        )
        row = cursor.fetchone()
        if row:
            return row[0]

        conn.execute(
            """INSERT INTO authors (uuid, platform_id, platform_user_id, display_name)
               VALUES (?, ?, ?, ?)""",
            (_new_uuid(), PLATFORM_ID, mid, name or mid),
        )
        return conn.execute("SELECT last_insert_rowid()").fetchone()[0]

    def _insert_post(self, conn: sqlite3.Connection, post: ParsedPost, author_id: Optional[int] = None) -> int:
        """Insert a single post record. Returns the post's internal ID."""
        post_uuid = _new_uuid()

        # Handle repost_of_id — check if the original post exists
        repost_of_internal_id = None
        if post.repost_of_id:
            cursor = conn.execute(
                "SELECT id FROM posts WHERE platform_id = ? AND platform_post_id = ?",
                (PLATFORM_ID, post.repost_of_id),
            )
            row = cursor.fetchone()
            if row:
                repost_of_internal_id = row[0]

        # Build source URL for Bilibili posts
        source_url = f"https://t.bilibili.com/{post.platform_post_id}"

        # Extract raw platform type from metadata JSON if available
        platform_post_type = None
        if post.platform_metadata_json:
            import json
            try:
                meta = json.loads(post.platform_metadata_json)
                platform_post_type = meta.get("dynamic_type")
            except (json.JSONDecodeError, TypeError):
                pass

        conn.execute(
            """
            INSERT INTO posts (
                uuid, platform_id, platform_post_id, post_type,
                platform_post_type, published_at, archived_at, source_url,
                plain_text, rich_text, repost_of_id, repost_snapshot,
                original_author_id, platform_metadata
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                post_uuid,
                PLATFORM_ID,
                post.platform_post_id,
                post.post_type,
                platform_post_type,
                post.published_at,
                _now_iso(),
                source_url,
                post.plain_text,
                post.rich_text_json,
                repost_of_internal_id,
                post.repost_snapshot_json,
                author_id,
                post.platform_metadata_json,
            ),
        )
        return conn.execute("SELECT last_insert_rowid()").fetchone()[0]

    def _insert_image(self, conn: sqlite3.Connection, img: ImageRecord) -> int:
        """Insert an image record. Returns the image's internal ID."""
        img_uuid = _new_uuid()
        conn.execute(
            """
            INSERT OR IGNORE INTO images (
                uuid, filename, storage_path, sha256,
                width, height, quality, source_url, file_size
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                img_uuid,
                img.filename,
                f"images/{img.filename}",
                img.sha256,
                img.width,
                img.height,
                img.quality,
                img.source_url,
                img.file_size,
            ),
        )
        cursor = conn.execute(
            "SELECT id FROM images WHERE filename = ?", (img.filename,)
        )
        row = cursor.fetchone()
        return row[0] if row else -1

    def _link_post_images(self, conn: sqlite3.Connection, post_id: int,
                          image_filenames: list, is_repost_media: bool = False):
        """Create post_media junction records linking a post to its images."""
        for sort_order, fname in enumerate(image_filenames):
            cursor = conn.execute(
                "SELECT id FROM images WHERE filename = ?", (fname,)
            )
            row = cursor.fetchone()
            if not row:
                continue
            image_id = row[0]
            conn.execute(
                """
                INSERT OR IGNORE INTO post_media (post_id, image_id, sort_order, is_repost_media)
                VALUES (?, ?, ?, ?)
                """,
                (post_id, image_id, sort_order, int(is_repost_media)),
            )

    def _insert_stats(self, conn: sqlite3.Connection, post_id: int, stats: dict):
        """Insert a stats snapshot for a post."""
        if not stats:
            return
        conn.execute(
            """
            INSERT INTO post_stats (post_id, views, likes, comments, forwards, snapshot_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                post_id,
                stats.get("views"),
                stats.get("likes", 0),
                stats.get("comments", 0),
                stats.get("forwards", 0),
                _now_iso(),
            ),
        )

    def write_all(self, posts: list, images: list) -> dict:
        """Write all new posts and images to the database in a single transaction.

        Args:
            posts: list of ParsedPost objects
            images: list of ImageRecord objects

        Returns:
            dict with counts: posts_added, posts_skipped, images_added,
            images_skipped_dup, errors
        """
        stats = {
            "posts_added": 0,
            "posts_skipped": 0,
            "images_added": 0,
            "images_skipped_dup": 0,
            "errors": 0,
        }

        if not posts:
            logger.info("No posts to write")
            return stats

        conn = self._connect()

        try:
            conn.execute("BEGIN IMMEDIATE")

            # Phase 1: Insert images first (posts reference them)
            for img in images:
                if self.image_exists_by_filename(conn, img.filename):
                    stats["images_skipped_dup"] += 1
                    continue
                dup = self.image_exists_by_sha256(conn, img.sha256)
                if dup and img.sha256:
                    logger.debug(
                        "Image %s is duplicate of %s (same SHA256)",
                        img.filename, dup,
                    )
                    stats["images_skipped_dup"] += 1
                    continue
                try:
                    self._insert_image(conn, img)
                    stats["images_added"] += 1
                except sqlite3.Error as e:
                    logger.error("Failed to insert image %s: %s", img.filename, e)
                    stats["errors"] += 1

            # Phase 2: Insert posts
            for post in posts:
                if self.post_exists(conn, post.platform_post_id):
                    stats["posts_skipped"] += 1
                    continue

                try:
                    # Ensure author exists for reposts
                    author_id = None
                    if post.original_author_mid:
                        author_id = self._ensure_author(
                            conn, post.original_author_mid,
                            post.original_author_name or "",
                        )

                    post_id = self._insert_post(conn, post, author_id)
                    stats["posts_added"] += 1

                    # Link images
                    self._link_post_images(
                        conn, post_id, post.image_filenames, is_repost_media=False,
                    )
                    self._link_post_images(
                        conn, post_id, post.repost_image_filenames, is_repost_media=True,
                    )

                    # Insert stats
                    self._insert_stats(conn, post_id, post.stats)

                except sqlite3.Error as e:
                    logger.error(
                        "Failed to insert post %s: %s",
                        post.platform_post_id, e,
                    )
                    stats["errors"] += 1

            conn.execute("COMMIT")

            # Checkpoint WAL to merge changes into main db file
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")

        except sqlite3.Error as e:
            logger.error("Transaction failed, rolling back: %s", e)
            try:
                conn.execute("ROLLBACK")
            except sqlite3.Error:
                pass
            stats["errors"] += 1
        finally:
            conn.close()

        logger.info(
            "DB write complete: +%d posts, +%d images, %d skipped, %d errors",
            stats["posts_added"], stats["images_added"],
            stats["posts_skipped"] + stats["images_skipped_dup"],
            stats["errors"],
        )
        return stats
