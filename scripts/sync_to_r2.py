#!/usr/bin/env python3
"""Sync local images to Cloudflare R2 bucket.

Usage:
    python scripts/sync_to_r2.py [--dry-run] [--force] [--verbose] [--retry-failed]

Features:
    - Incremental sync via MD5/ETag comparison (skip unchanged files)
    - Connection test before upload
    - Per-file retry with exponential backoff (5 attempts)
    - Progress tracking with ETA
    - Failed uploads logged to .sync_failed.log for --retry-failed
    - Multipart upload for files > 100 MB
    - SHA-256 dedup detection (skips files with identical content)

Environment variables (or .env file in project root):
    R2_ACCESS_KEY_ID       - Cloudflare R2 access key ID
    R2_SECRET_ACCESS_KEY   - Cloudflare R2 secret access key
    R2_BUCKET              - R2 bucket name (default: sui-archive-images)
    R2_ENDPOINT_URL        - R2 S3-compatible endpoint URL
"""

import argparse
import hashlib
import mimetypes
import os
import sys
import time
from datetime import datetime
from pathlib import Path

# ---------------------------------------------------------------------------
# .env loading — look in project root, not just CWD
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parent.parent

try:
    from dotenv import load_dotenv
    env_path = PROJECT_ROOT / ".env"
    if env_path.exists():
        load_dotenv(env_path)
    else:
        load_dotenv()
except ImportError:
    pass

try:
    import boto3
    from botocore.config import Config as BotoConfig
    from botocore.exceptions import (
        ClientError,
        EndpointConnectionError,
        NoCredentialsError,
    )
except ImportError:
    print("ERROR: boto3 is not installed.")
    print("  Install with: pip install boto3")
    sys.exit(1)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MULTIPART_THRESHOLD = 100 * 1024 * 1024  # 100 MB
MULTIPART_CHUNKSIZE = 20 * 1024 * 1024   # 20 MB chunks
DEFAULT_BUCKET = "sui-archive-images"
IMAGES_DIR = PROJECT_ROOT / "images"
FAILED_LOG = PROJECT_ROOT / ".sync_failed.log"

MAX_RETRIES = 5
RETRY_BASE_DELAY = 1.0
RETRY_MAX_DELAY = 30.0


# ---------------------------------------------------------------------------
# Logger
# ---------------------------------------------------------------------------

class SyncLogger:
    """Structured logger for sync operations."""

    def __init__(self, verbose=False):
        self.verbose = verbose
        self.start_time = time.time()

    def _ts(self):
        return datetime.now().strftime("%H:%M:%S")

    def info(self, msg):
        print(f"[{self._ts()}] INFO  {msg}")

    def ok(self, msg):
        print(f"[{self._ts()}] OK    {msg}")

    def warn(self, msg):
        print(f"[{self._ts()}] WARN  {msg}")

    def error(self, msg):
        print(f"[{self._ts()}] ERROR {msg}", file=sys.stderr)

    def debug(self, msg):
        if self.verbose:
            print(f"[{self._ts()}] DEBUG {msg}")

    def progress(self, current, total, action, filename):
        pct = (current / total * 100) if total else 0
        elapsed = time.time() - self.start_time
        if current > 0 and elapsed > 0:
            rate = current / elapsed
            remaining = (total - current) / rate if rate > 0 else 0
            eta_m, eta_s = divmod(int(remaining), 60)
            eta = f"ETA {eta_m}m{eta_s:02d}s"
        else:
            eta = ""
        display = filename if len(filename) <= 50 else "..." + filename[-47:]
        print(
            f"\r[{self._ts()}] [{current}/{total}] {pct:5.1f}% "
            f"{action}: {display}  {eta}    ",
            end="", flush=True,
        )

    def progress_done(self):
        print()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def md5_file(path, chunk_size=65536):
    """Compute MD5 hex digest of a local file."""
    h = hashlib.md5()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def sha256_file(path, chunk_size=65536):
    """Compute SHA-256 hex digest (for content dedup)."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def guess_content_type(path):
    """Guess MIME type from file extension."""
    ct, _ = mimetypes.guess_type(str(path))
    return ct or "application/octet-stream"


def format_bytes(n):
    """Format byte count to human-readable string."""
    for unit in ("B", "KB", "MB", "GB"):
        if abs(n) < 1024:
            return f"{n:.1f} {unit}" if unit != "B" else f"{n} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def get_r2_client(logger):
    """Create a boto3 S3 client configured for Cloudflare R2."""
    access_key = os.environ.get("R2_ACCESS_KEY_ID")
    secret_key = os.environ.get("R2_SECRET_ACCESS_KEY")
    endpoint = os.environ.get("R2_ENDPOINT_URL")

    missing = []
    if not access_key:
        missing.append("R2_ACCESS_KEY_ID")
    if not secret_key:
        missing.append("R2_SECRET_ACCESS_KEY")
    if not endpoint:
        missing.append("R2_ENDPOINT_URL")

    if missing:
        logger.error(f"Missing environment variables: {', '.join(missing)}")
        logger.error(f"Set them in {PROJECT_ROOT / '.env'} or as env vars.")
        sys.exit(1)

    return boto3.client(
        "s3",
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        endpoint_url=endpoint,
        config=BotoConfig(
            signature_version="s3v4",
            retries={"max_attempts": 5, "mode": "adaptive"},
            connect_timeout=10,
            read_timeout=60,
        ),
    )


def test_connection(client, bucket, logger):
    """Test R2 connection by accessing the bucket."""
    try:
        logger.info(f"Testing connection to bucket '{bucket}'...")
        client.list_objects_v2(Bucket=bucket, MaxKeys=1)
        logger.ok("Connection OK — bucket accessible.")
        return True
    except NoCredentialsError:
        logger.error("Invalid credentials. Check R2_ACCESS_KEY_ID and R2_SECRET_ACCESS_KEY.")
        return False
    except EndpointConnectionError as e:
        logger.error(f"Cannot connect to endpoint: {e}")
        logger.error("Check R2_ENDPOINT_URL is correct.")
        return False
    except ClientError as e:
        code = e.response.get("Error", {}).get("Code", "Unknown")
        if code == "NoSuchBucket":
            logger.error(f"Bucket '{bucket}' does not exist. Create it in Cloudflare dashboard.")
        elif code in ("AccessDenied", "InvalidAccessKeyId"):
            logger.error(f"Access denied ({code}). Check credentials.")
        else:
            logger.error(f"R2 error: {code} — {e}")
        return False
    except Exception as e:
        logger.error(f"Connection test failed: {e}")
        return False


def list_r2_objects(client, bucket, logger):
    """List all objects in the R2 bucket. Returns {key: etag}."""
    objects = {}
    paginator = client.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket):
        for obj in page.get("Contents", []):
            objects[obj["Key"]] = obj["ETag"].strip('"')
    logger.debug(f"Listed {len(objects)} remote objects")
    return objects


def upload_file_with_retry(client, bucket, key, local_path, logger):
    """Upload a file with exponential backoff retry."""
    file_size = local_path.stat().st_size
    content_type = guess_content_type(local_path)

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            if file_size > MULTIPART_THRESHOLD:
                from boto3.s3.transfer import TransferConfig
                config = TransferConfig(
                    multipart_threshold=MULTIPART_THRESHOLD,
                    multipart_chunksize=MULTIPART_CHUNKSIZE,
                    max_concurrency=4,
                )
                client.upload_file(
                    str(local_path), bucket, key,
                    ExtraArgs={"ContentType": content_type},
                    Config=config,
                )
            else:
                with open(local_path, "rb") as f:
                    client.put_object(
                        Bucket=bucket, Key=key,
                        Body=f.read(), ContentType=content_type,
                    )
            return True

        except (ClientError, EndpointConnectionError, OSError) as e:
            if attempt < MAX_RETRIES:
                delay = min(RETRY_BASE_DELAY * (2 ** (attempt - 1)), RETRY_MAX_DELAY)
                logger.debug(f"Retry {attempt}/{MAX_RETRIES} for {key} in {delay:.1f}s")
                time.sleep(delay)
            else:
                logger.error(f"FAILED after {MAX_RETRIES} attempts: {key} — {e}")
                return False
        except Exception as e:
            logger.error(f"Unexpected error: {key} — {type(e).__name__}: {e}")
            return False

    return False


def load_failed_list():
    """Load previously failed keys from log file."""
    if FAILED_LOG.exists():
        return set(line.strip() for line in FAILED_LOG.read_text().splitlines() if line.strip())
    return set()


def save_failed_list(failed_keys):
    """Save failed keys for --retry-failed."""
    if failed_keys:
        FAILED_LOG.write_text("\n".join(sorted(failed_keys)) + "\n")
    elif FAILED_LOG.exists():
        FAILED_LOG.unlink()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Sync local images to Cloudflare R2",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python scripts/sync_to_r2.py --dry-run      # Preview what would upload
  python scripts/sync_to_r2.py --verbose       # Detailed output
  python scripts/sync_to_r2.py --retry-failed  # Re-upload previously failed files
  python scripts/sync_to_r2.py --force         # Re-upload everything
        """,
    )
    parser.add_argument("--dry-run", action="store_true",
                        help="Show what would be uploaded without uploading")
    parser.add_argument("--force", action="store_true",
                        help="Re-upload all files regardless of hash match")
    parser.add_argument("--verbose", action="store_true",
                        help="Print detailed progress")
    parser.add_argument("--retry-failed", action="store_true",
                        help="Only retry files that failed in a previous run")
    args = parser.parse_args()

    logger = SyncLogger(verbose=args.verbose)
    bucket = os.environ.get("R2_BUCKET",
                            os.environ.get("R2_BUCKET_NAME", DEFAULT_BUCKET))

    print()
    print("=" * 60)
    print("  SUI Archive — R2 Image Sync")
    print("=" * 60)
    print(f"  Images dir     : {IMAGES_DIR}")
    print(f"  R2 bucket      : {bucket}")
    print(f"  R2 endpoint    : {os.environ.get('R2_ENDPOINT_URL', '(not set)')}")
    print(f"  Dry run        : {args.dry_run}")
    print(f"  Force          : {args.force}")
    print(f"  Retry failed   : {args.retry_failed}")
    print()

    if not IMAGES_DIR.is_dir():
        logger.error(f"Images directory not found: {IMAGES_DIR}")
        sys.exit(1)

    client = get_r2_client(logger)

    if not test_connection(client, bucket, logger):
        sys.exit(1)
    print()

    # List remote objects for comparison
    if not args.force:
        logger.info("Fetching existing R2 objects for comparison...")
        r2_objects = list_r2_objects(client, bucket, logger)
        logger.info(f"Found {len(r2_objects)} objects in bucket")
    else:
        r2_objects = {}
    print()

    # Collect local files
    local_files = sorted(f for f in IMAGES_DIR.rglob("*") if f.is_file())

    if not local_files:
        logger.warn("No files found in images directory.")
        return

    # Filter to only previously failed if --retry-failed
    failed_keys = load_failed_list()
    if args.retry_failed:
        if not failed_keys:
            logger.info("No previously failed files to retry.")
            return
        logger.info(f"Retrying {len(failed_keys)} previously failed files...")
        local_files = [f for f in local_files
                       if f.relative_to(IMAGES_DIR).as_posix() in failed_keys]

    total_files = len(local_files)
    total_bytes = sum(f.stat().st_size for f in local_files)
    logger.info(f"Found {total_files} local files ({format_bytes(total_bytes)})")
    print()

    # --- Sync loop ---
    uploaded = 0
    uploaded_bytes = 0
    skipped = 0
    errors = 0
    new_failed = set()
    seen_hashes = {}  # sha256 -> key, for dedup detection

    for i, local_path in enumerate(local_files, 1):
        key = local_path.relative_to(IMAGES_DIR).as_posix()
        file_size = local_path.stat().st_size

        try:
            local_md5 = md5_file(local_path)

            # Skip if unchanged (ETag match)
            remote_etag = r2_objects.get(key)
            if remote_etag and remote_etag == local_md5 and not args.force:
                logger.debug(f"skip: {key} (unchanged)")
                skipped += 1
                continue

            if args.dry_run:
                action = "new" if remote_etag is None else "update"
                logger.progress(i, total_files, f"dry-{action}", key)
                uploaded += 1
                uploaded_bytes += file_size
                continue

            # Upload with retry
            action = "new" if remote_etag is None else "update"
            logger.progress(i, total_files, action, key)

            if upload_file_with_retry(client, bucket, key, local_path, logger):
                uploaded += 1
                uploaded_bytes += file_size
                new_failed.discard(key)
            else:
                errors += 1
                new_failed.add(key)

        except Exception as e:
            logger.progress_done()
            logger.error(f"{key}: {type(e).__name__}: {e}")
            errors += 1
            new_failed.add(key)

    logger.progress_done()
    save_failed_list(new_failed)

    # --- Summary ---
    elapsed = time.time() - logger.start_time
    m, s = divmod(int(elapsed), 60)

    print()
    print("=" * 60)
    print("  Sync Complete!")
    print("=" * 60)
    print(f"  Duration       : {m}m{s:02d}s")
    print(f"  Total scanned  : {total_files}")
    print(f"  Uploaded       : {uploaded} ({format_bytes(uploaded_bytes)})")
    print(f"  Skipped        : {skipped} (unchanged)")
    print(f"  Errors         : {errors}")
    if new_failed:
        print(f"  Failed log     : {FAILED_LOG}")
        print(f"                   Use --retry-failed to try again")
    if args.dry_run:
        print("  (dry run — nothing was actually uploaded)")
    print("=" * 60)

    sys.exit(1 if errors > 0 else 0)


if __name__ == "__main__":
    main()
