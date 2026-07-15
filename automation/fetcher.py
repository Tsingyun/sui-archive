"""
fetcher.py — Incremental dynamic fetcher + image downloader.

Fetches new posts from Bilibili since the last known post in SQLite,
downloads associated images, and returns structured data ready for
database insertion.

Usage:
    from automation.fetcher import IncrementalFetcher
    fetcher = IncrementalFetcher()
    result = fetcher.fetch_new_posts(stop_at_id="123456")
    # result.posts   → list of parsed post dicts
    # result.images  → list of downloaded image records
"""

import hashlib
import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

from .config import (
    IMAGES_DIR,
    HOST_MID,
    SKIP_TYPES,
    DELAY_BETWEEN_PAGES,
    DELAY_BETWEEN_IMAGES,
    IMAGE_WORKERS,
    IMAGE_TIMEOUT,
    REPOST_INDEX_OFFSET,
    PLATFORM_ID,
    TYPE_MAP,
)
from .bilibili_api import BilibiliClient, APIError

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class ImageRecord:
    filename: str
    local_path: str
    sha256: str
    source_url: str
    width: Optional[int] = None
    height: Optional[int] = None
    quality: str = "original"   # 'original' | 'repost'
    file_size: int = 0


@dataclass
class ParsedPost:
    platform_post_id: str
    post_type: str
    published_at: str          # ISO 8601
    published_ts: int          # Unix timestamp
    plain_text: str
    rich_text_json: str        # JSON string
    is_repost: bool
    repost_of_id: Optional[str] = None
    repost_snapshot_json: Optional[str] = None
    original_author_mid: Optional[str] = None
    original_author_name: Optional[str] = None
    platform_metadata_json: str = "{}"
    image_filenames: list = field(default_factory=list)
    repost_image_filenames: list = field(default_factory=list)
    stats: dict = field(default_factory=dict)


@dataclass
class FetchResult:
    posts: list = field(default_factory=list)         # list[ParsedPost]
    images: list = field(default_factory=list)         # list[ImageRecord]
    total_pages: int = 0
    total_new_posts: int = 0
    total_new_images: int = 0
    total_downloaded_images: int = 0
    skipped_images: int = 0
    failed_images: int = 0
    elapsed_seconds: float = 0


# ---------------------------------------------------------------------------
# Parsing helpers (adapted from legacy archive_dynamics.py)
# ---------------------------------------------------------------------------

def _clean_img_url(url: str) -> str:
    if not url:
        return ""
    url = url.split("?")[0]
    if url.startswith("//"):
        url = "https:" + url
    return url


def _parse_rich_text(desc_obj: dict) -> tuple:
    """Returns (plain_text, rich_text_json_str)."""
    import json
    if not desc_obj:
        return "", "{}"

    # Primary: extract from rich_text_nodes array
    nodes = desc_obj.get("rich_text_nodes") or []
    parts = []
    for n in nodes:
        nt = n.get("type", "")
        if nt == "RICH_TEXT_NODE_TYPE_EMOJI":
            parts.append(n.get("orig_text", ""))
        else:
            parts.append(n.get("text", ""))
    plain = "".join(parts)

    # Fallback: some feed responses (especially DRAW posts) omit
    # rich_text_nodes but include a plain "text" field in desc.
    if not plain:
        plain = desc_obj.get("text", "") or ""

    return plain, json.dumps(desc_obj, ensure_ascii=False)


def _extract_images(major: dict) -> list:
    """Extract image info dicts from a major content block."""
    if not major:
        return []
    mtype = major.get("type", "")
    images = []

    if mtype in ("MAJOR_TYPE_DRAW", "MAJOR_TYPE_OPUS"):
        draw = major.get("draw", {}) or {}
        for item in draw.get("items") or []:
            # Defensive: item might be a string URL instead of a dict
            if isinstance(item, str):
                src = _clean_img_url(item) if item else ""
                if src:
                    images.append({"url": src, "width": None, "height": None, "size_kb": None})
                continue
            src = item.get("src") or ""
            if not src:
                continue
            images.append({
                "url": _clean_img_url(src),
                "width": item.get("width"),
                "height": item.get("height"),
                "size_kb": item.get("size"),
            })

    elif mtype == "MAJOR_TYPE_ARTICLE":
        for cover in (major.get("article") or {}).get("covers") or []:
            # Defensive: cover might be a string URL instead of a dict
            if isinstance(cover, str):
                src = _clean_img_url(cover) if cover else ""
            else:
                src = cover.get("url") or cover.get("src") or ""
                if src:
                    src = _clean_img_url(src)
            if src:
                images.append({
                    "url": src,
                    "width": None,
                    "height": None,
                    "size_kb": None,
                })

    return images


def _determine_post_type(raw_type: str, has_images: bool, is_repost: bool) -> str:
    if is_repost:
        return "repost"
    mapped = TYPE_MAP.get(raw_type)
    if mapped is not None:
        return mapped
    if raw_type == "DYNAMIC_TYPE_DRAW":
        return "image" if has_images else "text"
    return "mixed"


def _ts_to_iso(ts: int) -> str:
    from datetime import datetime, timezone, timedelta
    cst = timezone(timedelta(hours=8))
    if not ts:
        return ""
    dt = datetime.fromtimestamp(ts, tz=cst)
    return dt.strftime("%Y-%m-%dT%H:%M:%S+08:00")


def _url_to_ext(url: str) -> str:
    if not url:
        return ".jpg"
    clean = url.split("?")[0].split("#")[0]
    _, ext = os.path.splitext(clean)
    ext = ext.lower()
    return ext if ext in (".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp") else ".jpg"


def _make_image_filename(dyn_id: str, idx: int, url: str, is_repost: bool) -> str:
    """Generate the canonical local filename for an image.

    Convention: {dyn_id}_{idx:02d}@{quality}.{ext}
    Repost images start indexing at offset (100+).
    """
    ext = _url_to_ext(url)
    quality = "@repost" if is_repost else "@original"
    actual_idx = (REPOST_INDEX_OFFSET + idx) if is_repost else idx
    return f"{dyn_id}_{actual_idx:02d}{quality}{ext}"


# ---------------------------------------------------------------------------
# Item parser
# ---------------------------------------------------------------------------

def _parse_item(item: dict) -> Optional[ParsedPost]:
    """Parse a raw Bilibili feed item into a ParsedPost."""
    import json

    dyn_id = str(item.get("id_str", ""))
    dyn_type = item.get("type", "")

    if dyn_type in SKIP_TYPES:
        return None

    # Timestamp
    ts = 0
    try:
        ts = int(item.get("modules", {}).get("module_author", {}).get("pub_ts", 0))
    except (ValueError, TypeError):
        pass

    # Content
    mod_dyn = item.get("modules", {}).get("module_dynamic", {}) or {}
    desc = mod_dyn.get("desc") or {}
    major = mod_dyn.get("major") or {}
    plain_text, rich_json = _parse_rich_text(desc)
    images = _extract_images(major)

    # Stats
    stats_mod = item.get("modules", {}).get("module_stat", {}) or {}
    stats = {
        "likes": (stats_mod.get("like") or {}).get("count", 0),
        "comments": (stats_mod.get("comment") or {}).get("count", 0),
        "forwards": (stats_mod.get("forward") or {}).get("count", 0),
    }

    # Platform metadata (preserve useful fields)
    meta = {
        "dynamic_type": dyn_type,
        "major_type": major.get("type", ""),
    }
    if major.get("type") == "MAJOR_TYPE_ARTICLE":
        art = major.get("article") or {}
        meta["article_title"] = art.get("title", "")
        meta["article_id"] = art.get("id")
    elif major.get("type") == "MAJOR_TYPE_LIVE":
        live = major.get("live") or {}
        meta["live_title"] = live.get("title", "")
        meta["live_id"] = live.get("id")

    # Repost handling
    orig = item.get("orig")
    is_repost = orig is not None
    repost_of_id = None
    repost_snapshot = None
    orig_author_mid = None
    orig_author_name = None
    repost_image_filenames = []

    if orig:
        orig_id = str(orig.get("id_str", ""))
        orig_state = orig.get("state", "")

        if orig_state == "DYNAMIC_STATE_DELETED" or orig_id == "0":
            repost_snapshot = json.dumps({
                "deleted": True, "id": orig_id,
                "text": "[原动态已删除]",
            }, ensure_ascii=False)
        else:
            repost_of_id = orig_id if orig_id else None
            orig_mod_dyn = orig.get("modules", {}).get("module_dynamic", {}) or {}
            orig_desc = orig_mod_dyn.get("desc") or {}
            orig_major = orig_mod_dyn.get("major") or {}
            orig_text, _ = _parse_rich_text(orig_desc)
            orig_images = _extract_images(orig_major)

            orig_author = orig.get("modules", {}).get("module_author", {}) or {}
            orig_author_mid = str(orig_author.get("mid", "")) or None
            orig_author_name = orig_author.get("name")

            repost_snapshot = json.dumps({
                "deleted": False,
                "text": orig_text,
                "major_type": orig_major.get("type", ""),
                "image_count": len(orig_images),
            }, ensure_ascii=False)

            # Generate repost image filenames
            for idx, img in enumerate(orig_images):
                fname = _make_image_filename(orig_id, idx, img["url"], is_repost=True)
                repost_image_filenames.append(fname)

    post = ParsedPost(
        platform_post_id=dyn_id,
        post_type=_determine_post_type(dyn_type, bool(images), is_repost),
        published_at=_ts_to_iso(ts),
        published_ts=ts,
        plain_text=plain_text,
        rich_text_json=rich_json,
        is_repost=is_repost,
        repost_of_id=repost_of_id,
        repost_snapshot_json=repost_snapshot,
        original_author_mid=orig_author_mid,
        original_author_name=orig_author_name,
        platform_metadata_json=json.dumps(meta, ensure_ascii=False),
        stats=stats,
    )

    # Original image filenames
    for idx, img in enumerate(images):
        fname = _make_image_filename(dyn_id, idx, img["url"], is_repost=False)
        post.image_filenames.append(fname)

    return post


# ---------------------------------------------------------------------------
# Incremental Fetcher
# ---------------------------------------------------------------------------

class IncrementalFetcher:
    """Fetches new dynamics and downloads images incrementally."""

    def __init__(self, client=None):
        self.client = client or BilibiliClient()
        IMAGES_DIR.mkdir(parents=True, exist_ok=True)

    def fetch_new_posts(self, stop_at_id: str) -> FetchResult:
        """Fetch all new posts since stop_at_id.

        Paginates backward through the feed until it finds a post whose
        ID matches stop_at_id (the latest post already in the database).

        Returns a FetchResult with parsed posts and image records.
        """
        t0 = time.monotonic()
        result = FetchResult()

        all_items = []
        offset = ""
        found_boundary = False

        logger.info("Starting incremental fetch (stop_at_id=%s)", stop_at_id)

        while not found_boundary:
            page_data = self.client.fetch_feed_page(offset=offset)
            items = page_data.get("items", [])
            result.total_pages += 1

            if not items:
                logger.info("No more items returned")
                break

            for item in items:
                dyn_id = str(item.get("id_str", ""))
                dyn_type = item.get("type", "")

                if dyn_type in SKIP_TYPES:
                    continue

                if dyn_id == stop_at_id:
                    found_boundary = True
                    break

                all_items.append(item)

            if not page_data.get("has_more", False):
                break

            offset = page_data.get("offset", "")
            if not offset:
                break

            time.sleep(DELAY_BETWEEN_PAGES)

        logger.info("Fetched %d new items across %d pages", len(all_items), result.total_pages)

        # Parse items
        for item in all_items:
            post = _parse_item(item)
            if post:
                result.posts.append(post)

        # Backfill empty text via detail API.
        # The feed API sometimes omits desc for DRAW posts; the detail
        # API reliably includes it.  Fetch each affected post individually.
        self._backfill_empty_text(result.posts)

        result.total_new_posts = len(result.posts)

        # Download images
        self._download_all_images(result)

        result.elapsed_seconds = time.monotonic() - t0
        return result

    def _backfill_empty_text(self, posts: list):
        """Use the detail API to fill in text for posts where the feed API
        returned an empty or missing ``desc`` block.

        This primarily affects DYNAMIC_TYPE_DRAW posts: the feed endpoint
        sometimes omits the ``module_dynamic.desc`` object, while the detail
        endpoint reliably includes it.
        """
        import json as _json

        empty_posts = [
            p for p in posts
            if not p.plain_text and p.post_type in ("text", "image", "mixed", "repost")
        ]
        if not empty_posts:
            return

        logger.info(
            "Backfilling text for %d post(s) via detail API", len(empty_posts)
        )

        for post in empty_posts:
            try:
                detail = self.client.fetch_detail(post.platform_post_id)
                item = detail.get("item") or {}

                mod_dyn = item.get("modules", {}).get("module_dynamic", {}) or {}
                desc = mod_dyn.get("desc") or {}
                plain_text, rich_json = _parse_rich_text(desc)

                if plain_text:
                    post.plain_text = plain_text
                    post.rich_text_json = rich_json
                    logger.debug(
                        "Backfilled text for %s (%d chars)",
                        post.platform_post_id, len(plain_text),
                    )

                # Also backfill images if the feed response had none
                if not post.image_filenames:
                    major = mod_dyn.get("major") or {}
                    for idx, img in enumerate(_extract_images(major)):
                        fname = _make_image_filename(
                            post.platform_post_id, idx, img["url"], is_repost=False
                        )
                        post.image_filenames.append(fname)

                # Small delay to avoid rate-limiting
                time.sleep(DELAY_BETWEEN_PAGES)

            except Exception as exc:
                logger.warning(
                    "Detail API backfill failed for %s: %s",
                    post.platform_post_id, exc,
                )

    def _download_all_images(self, result: FetchResult):
        """Download images for all fetched posts."""
        # Collect all download tasks
        tasks = []

        for post in result.posts:
            # Original images
            for idx, fname in enumerate(post.image_filenames):
                local_path = IMAGES_DIR / fname
                if local_path.exists():
                    result.skipped_images += 1
                    # Still record the image for DB insertion
                    result.images.append(ImageRecord(
                        filename=fname,
                        local_path=str(local_path),
                        sha256=_file_sha256(str(local_path)),
                        source_url="",  # will be filled from post data
                        quality="original",
                        file_size=local_path.stat().st_size if local_path.exists() else 0,
                    ))
                    continue
                # Need the URL — re-extract from the parsed data
                # (We'll pass URLs through the post metadata)
                tasks.append((fname, str(local_path), "original"))

            # Repost images
            for idx, fname in enumerate(post.repost_image_filenames):
                local_path = IMAGES_DIR / fname
                if local_path.exists():
                    result.skipped_images += 1
                    result.images.append(ImageRecord(
                        filename=fname,
                        local_path=str(local_path),
                        sha256=_file_sha256(str(local_path)),
                        source_url="",
                        quality="repost",
                        file_size=local_path.stat().st_size if local_path.exists() else 0,
                    ))
                    continue
                tasks.append((fname, str(local_path), "repost"))

        # We need to re-extract URLs from the raw items for download.
        # This is handled by storing URL→filename mapping during parse.
        # For now, the orchestrator should pass the raw items along.
        # TODO: refactor to pass URL mapping through the pipeline.

        if not tasks:
            logger.info("No new images to download (%d skipped)", result.skipped_images)
            return

        logger.info("Downloading %d images (%d skipped)", len(tasks), result.skipped_images)

        with ThreadPoolExecutor(max_workers=IMAGE_WORKERS) as pool:
            futures = {}
            for fname, path, quality in tasks:
                # URL should have been stored — this is a simplified version
                # The orchestrator provides URL mapping
                futures[pool.submit(
                    self._download_one, fname, path
                )] = (fname, path, quality)

            for fut in as_completed(futures):
                fname, path, quality = futures[fut]
                try:
                    record = fut.result()
                    if record:
                        result.images.append(record)
                        result.total_downloaded_images += 1
                        result.total_new_images += 1
                    else:
                        result.failed_images += 1
                except Exception as e:
                    logger.error("Image download failed: %s — %s", fname, e)
                    result.failed_images += 1
                time.sleep(DELAY_BETWEEN_IMAGES)

    def _download_one(self, filename: str, save_path: str, url: str = "") -> Optional[ImageRecord]:
        """Download a single image file with retry on transient errors.

        Retries up to 3 attempts with exponential backoff (2s, 4s, 8s)
        on transient failures: timeouts, 503 Service Unavailable, and
        connection errors.  Does NOT retry on 404 or 403.
        """
        import requests as _requests

        if not url:
            logger.warning("No URL for %s, skipping", filename)
            return None

        max_attempts = 3
        last_error = None

        for attempt in range(1, max_attempts + 1):
            try:
                resp = self.client.session.get(url, timeout=IMAGE_TIMEOUT, stream=True)

                # Do not retry on permanent client errors
                if resp.status_code in (403, 404):
                    logger.error(
                        "Permanent error %d for %s, not retrying", resp.status_code, filename,
                    )
                    return None

                # Retry on 503 Service Unavailable
                if resp.status_code == 503 and attempt < max_attempts:
                    delay = 2 ** attempt  # 2, 4, 8
                    logger.warning(
                        "503 for %s (attempt %d/%d), retrying in %ds",
                        filename, attempt, max_attempts, delay,
                    )
                    time.sleep(delay)
                    continue

                resp.raise_for_status()

                hasher = hashlib.sha256()
                with open(save_path, "wb") as f:
                    for chunk in resp.iter_content(8192):
                        f.write(chunk)
                        hasher.update(chunk)

                sha = hasher.hexdigest()
                size = os.path.getsize(save_path)

                if attempt > 1:
                    logger.info("Downloaded %s on attempt %d", filename, attempt)

                return ImageRecord(
                    filename=filename,
                    local_path=save_path,
                    sha256=sha,
                    source_url=url,
                    quality="repost" if "@repost" in filename else "original",
                    file_size=size,
                )

            except (_requests.exceptions.Timeout,
                    _requests.exceptions.ConnectionError) as e:
                last_error = e
                if attempt < max_attempts:
                    delay = 2 ** attempt  # 2, 4, 8
                    logger.warning(
                        "Transient error for %s (attempt %d/%d): %s — retrying in %ds",
                        filename, attempt, max_attempts, type(e).__name__, delay,
                    )
                    time.sleep(delay)
                else:
                    logger.error(
                        "Failed to download %s after %d attempts: %s",
                        filename, max_attempts, e,
                    )
            except Exception as e:
                last_error = e
                logger.error("Failed to download %s: %s", filename, e)
                break  # non-transient, don't retry

            # Clean up partial file between retries
            if os.path.exists(save_path):
                os.remove(save_path)

        return None

    def download_images_with_urls(self, result: FetchResult, url_map: dict):
        """Download images using an explicit URL→filename mapping.

        Called by the orchestrator which has access to raw API items.

        Args:
            result: FetchResult to populate
            url_map: dict mapping filename → source URL
        """
        tasks = []
        for fname, url in url_map.items():
            local_path = IMAGES_DIR / fname
            if local_path.exists():
                result.skipped_images += 1
                result.images.append(ImageRecord(
                    filename=fname,
                    local_path=str(local_path),
                    sha256=_file_sha256(str(local_path)),
                    source_url=url,
                    quality="repost" if "@repost" in fname else "original",
                    file_size=local_path.stat().st_size,
                ))
                continue
            tasks.append((fname, str(local_path), url))

        if not tasks:
            return

        logger.info("Downloading %d new images (%d skipped)", len(tasks), result.skipped_images)

        with ThreadPoolExecutor(max_workers=IMAGE_WORKERS) as pool:
            futures = {}
            for fname, path, url in tasks:
                futures[pool.submit(self._download_one, fname, path, url)] = (fname, path)

            for fut in as_completed(futures):
                fname, path = futures[fut]
                try:
                    record = fut.result()
                    if record:
                        result.images.append(record)
                        result.total_downloaded_images += 1
                        result.total_new_images += 1
                    else:
                        result.failed_images += 1
                except Exception as e:
                    logger.error("Download error: %s — %s", fname, e)
                    result.failed_images += 1
                time.sleep(DELAY_BETWEEN_IMAGES)


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------

def _file_sha256(path: str) -> str:
    h = hashlib.sha256()
    try:
        with open(path, "rb") as f:
            while True:
                chunk = f.read(65536)
                if not chunk:
                    break
                h.update(chunk)
    except OSError:
        return ""
    return h.hexdigest()
