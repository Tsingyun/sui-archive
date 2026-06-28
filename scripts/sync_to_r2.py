#!/usr/bin/env python3
"""Sync local images to Cloudflare R2 bucket.

Usage:
    python scripts/sync_to_r2.py [--dry-run] [--force] [--verbose]

Environment variables (or .env file):
    R2_ACCESS_KEY_ID       - Cloudflare R2 access key ID
    R2_SECRET_ACCESS_KEY   - Cloudflare R2 secret access key
    R2_BUCKET_NAME         - R2 bucket name (default: sui-archive-images)
    R2_ENDPOINT_URL        - R2 S3-compatible endpoint URL
"""

import argparse
import hashlib
import mimetypes
import os
import sys
from pathlib import Path

# Try to load .env file if python-dotenv is available
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

import boto3
from botocore.config import Config as BotoConfig


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MULTIPART_THRESHOLD = 100 * 1024 * 1024  # 100 MB
MULTIPART_CHUNKSIZE = 20 * 1024 * 1024   # 20 MB chunks
DEFAULT_BUCKET = "sui-archive-images"
IMAGES_DIR = Path(__file__).resolve().parent.parent / "images"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def md5_file(path: Path, chunk_size: int = 8192) -> str:
    """Compute MD5 hex digest of a local file."""
    h = hashlib.md5()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def guess_content_type(path: Path) -> str:
    """Guess MIME type from file extension."""
    ct, _ = mimetypes.guess_type(str(path))
    return ct or "application/octet-stream"


def get_r2_client():
    """Create a boto3 S3 client configured for Cloudflare R2."""
    access_key = os.environ.get("R2_ACCESS_KEY_ID")
    secret_key = os.environ.get("R2_SECRET_ACCESS_KEY")
    endpoint = os.environ.get("R2_ENDPOINT_URL")

    if not all([access_key, secret_key, endpoint]):
        print("ERROR: Missing required environment variables.")
        print("  R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, R2_ENDPOINT_URL must be set.")
        sys.exit(1)

    return boto3.client(
        "s3",
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        endpoint_url=endpoint,
        config=BotoConfig(
            signature_version="s3v4",
            retries={"max_attempts": 3, "mode": "standard"},
        ),
    )


def list_r2_objects(client, bucket: str) -> dict:
    """List all objects in the R2 bucket and return {key: etag} mapping."""
    objects = {}
    paginator = client.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket):
        for obj in page.get("Contents", []):
            # ETag from S3 is quoted MD5 for simple uploads
            etag = obj["ETag"].strip('"')
            objects[obj["Key"]] = etag
    return objects


def upload_file(client, bucket: str, key: str, local_path: Path, verbose: bool):
    """Upload a single file to R2, using multipart for large files."""
    file_size = local_path.stat().st_size
    content_type = guess_content_type(local_path)

    extra_args = {"ContentType": content_type}

    if file_size > MULTIPART_THRESHOLD:
        if verbose:
            print(f"  [multipart] {key} ({file_size / (1024*1024):.1f} MB)")
        from boto3.s3.transfer import TransferConfig
        config = TransferConfig(
            multipart_threshold=MULTIPART_THRESHOLD,
            multipart_chunksize=MULTIPART_CHUNKSIZE,
        )
        client.upload_file(
            str(local_path), bucket, key,
            ExtraArgs=extra_args,
            Config=config,
        )
    else:
        if verbose:
            print(f"  [upload] {key} ({file_size / 1024:.1f} KB)")
        with open(local_path, "rb") as f:
            client.put_object(
                Bucket=bucket,
                Key=key,
                Body=f.read(),
                ContentType=content_type,
            )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Sync local images to Cloudflare R2")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be uploaded without uploading")
    parser.add_argument("--force", action="store_true", help="Re-upload all files regardless of hash match")
    parser.add_argument("--verbose", action="store_true", help="Print detailed progress")
    args = parser.parse_args()

    bucket = os.environ.get("R2_BUCKET_NAME", DEFAULT_BUCKET)

    if not IMAGES_DIR.is_dir():
        print(f"ERROR: Images directory not found: {IMAGES_DIR}")
        sys.exit(1)

    print(f"Images directory : {IMAGES_DIR}")
    print(f"R2 bucket        : {bucket}")
    print(f"R2 endpoint      : {os.environ.get('R2_ENDPOINT_URL', '(not set)')}")
    print(f"Dry run          : {args.dry_run}")
    print(f"Force upload     : {args.force}")
    print()

    client = get_r2_client()

    # List existing objects in R2
    if not args.force:
        print("Fetching existing R2 objects...")
        r2_objects = list_r2_objects(client, bucket)
        print(f"  Found {len(r2_objects)} objects in bucket")
    else:
        r2_objects = {}
    print()

    # Walk local images directory
    total = 0
    uploaded = 0
    skipped = 0
    errors = 0

    local_files = sorted(IMAGES_DIR.rglob("*"))
    local_files = [f for f in local_files if f.is_file()]

    if not local_files:
        print("No files found in images directory.")
        return

    print(f"Scanning {len(local_files)} local files...")
    print()

    for local_path in local_files:
        total += 1
        # Use forward slashes for S3 keys regardless of OS
        relative = local_path.relative_to(IMAGES_DIR).as_posix()
        key = relative

        try:
            local_md5 = md5_file(local_path)

            # Compare with remote ETag
            remote_etag = r2_objects.get(key)
            if remote_etag and remote_etag == local_md5 and not args.force:
                if args.verbose:
                    print(f"  [skip] {key} (unchanged)")
                skipped += 1
                continue

            if args.dry_run:
                action = "would upload" if remote_etag is None else "would update"
                print(f"  [dry-run] {action}: {key}")
                uploaded += 1
                continue

            # Upload
            reason = "new" if remote_etag is None else "changed"
            if args.verbose or not remote_etag:
                print(f"  [{reason}] {key}")

            upload_file(client, bucket, key, local_path, args.verbose)
            uploaded += 1

        except Exception as e:
            print(f"  [ERROR] {key}: {e}")
            errors += 1

    # Summary
    print()
    print("=" * 50)
    print("Sync complete!")
    print(f"  Total files  : {total}")
    print(f"  Uploaded     : {uploaded}")
    print(f"  Skipped      : {skipped}")
    print(f"  Errors       : {errors}")
    print("=" * 50)

    if errors > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
