"""
config.py — Centralized configuration for the automation pipeline.

All tunable constants live here. Environment variables override defaults
where noted (e.g. BILIBILI_COOKIE from GitHub Secrets).
"""

import os
from pathlib import Path

# ---------------------------------------------------------------------------
# .env loading — must happen before reading env vars
# ---------------------------------------------------------------------------

_PROJECT_ROOT = Path(__file__).resolve().parent.parent

try:
    from dotenv import load_dotenv
    _env_path = _PROJECT_ROOT / ".env"
    if _env_path.exists():
        load_dotenv(_env_path)
except ImportError:
    pass

# ---------------------------------------------------------------------------
# Project paths (relative to repository root)
# ---------------------------------------------------------------------------

PROJECT_ROOT = _PROJECT_ROOT
DB_PATH = PROJECT_ROOT / "data" / "sui-archive.db"
SCHEMA_PATH = PROJECT_ROOT / "data" / "schema.sql"
IMAGES_DIR = PROJECT_ROOT / "images"
DEPLOY_DIR = PROJECT_ROOT / "deploy"

# ---------------------------------------------------------------------------
# Bilibili
# ---------------------------------------------------------------------------

HOST_MID = "1954091502"  # 岁己SUI 的 B站 UID

FEED_API = "https://api.bilibili.com/x/polymer/web-dynamic/v1/feed/space"
DETAIL_API = "https://api.bilibili.com/x/polymer/web-dynamic/v1/detail"

# Cookie from environment (GitHub Secret or .env).
# Falls back to empty string — API will work for public data but may be
# rate-limited more aggressively without authentication.
BILIBILI_COOKIE = os.environ.get("BILIBILI_COOKIE", "")

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)

# Dynamic types to skip entirely (e.g. video submissions)
SKIP_TYPES = {"DYNAMIC_TYPE_AV"}

# ---------------------------------------------------------------------------
# Network / Retry
# ---------------------------------------------------------------------------

MAX_RETRIES = 3
RETRY_BASE_DELAY = 2.0          # seconds
RETRY_MAX_DELAY = 30.0          # seconds
RATE_LIMIT_WAIT = 60            # seconds when Bilibili returns -352
DELAY_BETWEEN_PAGES = 1.5       # seconds between paginated API calls
DELAY_BETWEEN_IMAGES = 0.15     # seconds between image downloads

# Image download concurrency
IMAGE_WORKERS = 4

# API request timeout (seconds)
REQUEST_TIMEOUT = 30

# Image download timeout (seconds)
IMAGE_TIMEOUT = 60

# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------

PLATFORM_ID = 1  # Bilibili — seeded by schema.sql

# Post-type mapping: Bilibili dynamic type → generic post_type
TYPE_MAP = {
    "DYNAMIC_TYPE_DRAW": None,       # resolved: 'image' or 'text'
    "DYNAMIC_TYPE_WORD": "text",
    "DYNAMIC_TYPE_FORWARD": "repost",
    "DYNAMIC_TYPE_ARTICLE": "article",
    "DYNAMIC_TYPE_LIVE": "live",
    "DYNAMIC_TYPE_MUSIC": "audio",
    "DYNAMIC_TYPE_AV": "video",
}

# ---------------------------------------------------------------------------
# Image naming convention
# ---------------------------------------------------------------------------

# Repost images start indexing from this offset (e.g. 100, 101, ...)
REPOST_INDEX_OFFSET = 100

# ---------------------------------------------------------------------------
# R2 / Cloudflare (loaded from env, used by sync_to_r2.py)
# ---------------------------------------------------------------------------

R2_BUCKET = os.environ.get("R2_BUCKET", "sui-archive-images")
R2_ENDPOINT_URL = os.environ.get("R2_ENDPOINT_URL", "")
R2_ACCESS_KEY_ID = os.environ.get("R2_ACCESS_KEY_ID", "")
R2_SECRET_ACCESS_KEY = os.environ.get("R2_SECRET_ACCESS_KEY", "")

CLOUDFLARE_API_TOKEN = os.environ.get("CLOUDFLARE_API_TOKEN", "")
CLOUDFLARE_ZONE_ID = os.environ.get("CLOUDFLARE_ZONE_ID", "")

# ---------------------------------------------------------------------------
# GitHub
# ---------------------------------------------------------------------------

GITHUB_REPOSITORY = os.environ.get("GITHUB_REPOSITORY", "Tsingyun/sui-archive")
SITE_URL = os.environ.get("SITE_URL", "https://archive.suijisui.uk")
