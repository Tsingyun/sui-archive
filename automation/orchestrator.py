"""
orchestrator.py — Main pipeline coordinator.

This is the entry point called by GitHub Actions. It coordinates:
    1. Quick check (lightweight update detection)
    2. Incremental fetch (posts + images)
    3. Database write
    4. Build pipeline
    5. R2 image sync
    6. Git commit & push
    7. Deploy & verify

Usage:
    python -m automation.orchestrator [--quick-check-only] [--skip-deploy]
"""

import json
import logging
import os
import subprocess
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

from .config import (
    PROJECT_ROOT,
    DB_PATH,
    IMAGES_DIR,
    HOST_MID,
    SKIP_TYPES,
    PLATFORM_ID,
    REPOST_INDEX_OFFSET,
    R2_BUCKET,
    GITHUB_REPOSITORY,
    SITE_URL,
)
from .bilibili_api import BilibiliClient, APIError
from .quick_check import QuickChecker, QuickCheckResult
from .fetcher import (
    IncrementalFetcher,
    FetchResult,
    ParsedPost,
    ImageRecord,
    _parse_item,
    _make_image_filename,
    _clean_img_url,
    _extract_images,
    _file_sha256,
)
from .db_writer import DatabaseWriter

logger = logging.getLogger(__name__)
CST = timezone(timedelta(hours=8))


# ---------------------------------------------------------------------------
# Pipeline Result
# ---------------------------------------------------------------------------

class PipelineResult:
    """Aggregated metrics from the full pipeline run."""

    def __init__(self):
        self.quick_check: Optional[QuickCheckResult] = None
        self.fetch_result: Optional[FetchResult] = None
        self.db_stats: dict = {}
        self.build_seconds: float = 0
        self.r2_sync_seconds: float = 0
        self.deploy_seconds: float = 0
        self.total_seconds: float = 0
        self.has_updates: bool = False
        self.error: Optional[str] = None

    def summary(self) -> dict:
        return {
            "has_updates": self.has_updates,
            "quick_check_ms": round(self.quick_check.elapsed_ms) if self.quick_check else 0,
            "new_posts": self.fetch_result.total_new_posts if self.fetch_result else 0,
            "new_images": self.fetch_result.total_new_images if self.fetch_result else 0,
            "downloaded_images": self.fetch_result.total_downloaded_images if self.fetch_result else 0,
            "failed_images": self.fetch_result.failed_images if self.fetch_result else 0,
            "posts_added": self.db_stats.get("posts_added", 0),
            "images_added": self.db_stats.get("images_added", 0),
            "build_seconds": round(self.build_seconds, 1),
            "r2_sync_seconds": round(self.r2_sync_seconds, 1),
            "deploy_seconds": round(self.deploy_seconds, 1),
            "total_seconds": round(self.total_seconds, 1),
            "error": self.error,
        }

    def github_output(self) -> str:
        """Format for GitHub Actions step output (key=value lines)."""
        s = self.summary()
        lines = [
            f"has_updates={'true' if s['has_updates'] else 'false'}",
            f"new_posts={s['new_posts']}",
            f"new_images={s['new_images']}",
            f"posts_added={s['posts_added']}",
            f"images_added={s['images_added']}",
            f"build_seconds={s['build_seconds']}",
            f"total_seconds={s['total_seconds']}",
        ]
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

class Orchestrator:

    def __init__(self, quick_check_only=False, skip_deploy=False, skip_build=False):
        self.quick_check_only = quick_check_only
        self.skip_deploy = skip_deploy
        self.skip_build = skip_build
        self.client = BilibiliClient()
        self.result = PipelineResult()

    def run(self) -> PipelineResult:
        t0 = time.monotonic()

        try:
            # Phase 1: Quick Check
            logger.info("=" * 60)
            logger.info("Phase 1: Quick Check")
            logger.info("=" * 60)
            checker = QuickChecker(client=self.client)
            qc = checker.check()
            self.result.quick_check = qc

            if not qc.has_updates:
                logger.info(
                    "No new posts detected. Pipeline complete in %.0fms.",
                    qc.elapsed_ms,
                )
                self.result.total_seconds = time.monotonic() - t0
                return self.result

            self.result.has_updates = True
            logger.info(
                "Updates detected: ~%d new post(s). Proceeding to full pipeline.",
                qc.new_count,
            )

            if self.quick_check_only:
                logger.info("--quick-check-only: stopping after quick check.")
                self.result.total_seconds = time.monotonic() - t0
                return self.result

            # Phase 2: Incremental Fetch
            logger.info("=" * 60)
            logger.info("Phase 2: Incremental Fetch")
            logger.info("=" * 60)
            fetch_result = self._fetch_incremental(qc.db_latest_id)
            self.result.fetch_result = fetch_result

            if fetch_result.total_new_posts == 0:
                logger.info("No parseable new posts found. Stopping.")
                self.result.total_seconds = time.monotonic() - t0
                return self.result

            # Phase 3: Database Write
            logger.info("=" * 60)
            logger.info("Phase 3: Database Write")
            logger.info("=" * 60)
            writer = DatabaseWriter()
            db_stats = writer.write_all(fetch_result.posts, fetch_result.images)
            self.result.db_stats = db_stats

            if db_stats["posts_added"] == 0:
                logger.info("No new posts written to DB (all duplicates). Stopping.")
                self.result.total_seconds = time.monotonic() - t0
                return self.result

            # Phase 4: Build Pipeline
            if not self.skip_build:
                logger.info("=" * 60)
                logger.info("Phase 4: Build Pipeline")
                logger.info("=" * 60)
                t_build = time.monotonic()
                self._run_build()
                self.result.build_seconds = time.monotonic() - t_build

            # Phase 5: R2 Image Sync
            logger.info("=" * 60)
            logger.info("Phase 5: R2 Image Sync")
            logger.info("=" * 60)
            t_r2 = time.monotonic()
            self._sync_r2()
            self.result.r2_sync_seconds = time.monotonic() - t_r2

            # Phase 6: Git Commit & Push + Deploy
            if not self.skip_deploy:
                logger.info("=" * 60)
                logger.info("Phase 6: Deploy")
                logger.info("=" * 60)
                t_deploy = time.monotonic()
                self._deploy(db_stats)
                self.result.deploy_seconds = time.monotonic() - t_deploy

        except Exception as e:
            self.result.error = f"{type(e).__name__}: {e}"
            logger.exception("Pipeline error: %s", e)

        self.result.total_seconds = time.monotonic() - t0
        self._print_summary()
        return self.result

    # ------------------------------------------------------------------
    # Phase 2: Incremental fetch with URL extraction
    # ------------------------------------------------------------------

    def _fetch_incremental(self, stop_at_id: str) -> FetchResult:
        """Fetch new posts and download images with proper URL handling."""
        result = FetchResult()
        url_map = {}  # filename → download URL

        # Fetch all new items from the API
        all_raw_items = []
        offset = ""
        found_boundary = False

        logger.info("Fetching new dynamics (stop_at_id=%s)", stop_at_id)

        while not found_boundary:
            page_data = self.client.fetch_feed_page(offset=offset)
            items = page_data.get("items", [])
            result.total_pages += 1

            if not items:
                break

            for item in items:
                dyn_id = str(item.get("id_str", ""))
                dyn_type = item.get("type", "")

                if dyn_type in SKIP_TYPES:
                    continue

                if dyn_id == stop_at_id:
                    found_boundary = True
                    break

                all_raw_items.append(item)

            if not page_data.get("has_more", False):
                break

            offset = page_data.get("offset", "")
            if not offset:
                break

            from .config import DELAY_BETWEEN_PAGES
            time.sleep(DELAY_BETWEEN_PAGES)

        logger.info("Collected %d new items across %d pages", len(all_raw_items), result.total_pages)

        # Parse items and build URL map
        for item in all_raw_items:
            post = _parse_item(item)
            if not post:
                continue

            result.posts.append(post)

            # Extract original image URLs
            mod_dyn = item.get("modules", {}).get("module_dynamic", {}) or {}
            major = mod_dyn.get("major") or {}
            images = _extract_images(major)

            for idx, img_info in enumerate(images):
                if idx < len(post.image_filenames):
                    url_map[post.image_filenames[idx]] = img_info["url"]

            # Extract repost image URLs
            orig = item.get("orig")
            if orig:
                orig_id = str(orig.get("id_str", ""))
                orig_mod_dyn = orig.get("modules", {}).get("module_dynamic", {}) or {}
                orig_major = orig_mod_dyn.get("major") or {}
                orig_images = _extract_images(orig_major)

                for idx, img_info in enumerate(orig_images):
                    if idx < len(post.repost_image_filenames):
                        url_map[post.repost_image_filenames[idx]] = img_info["url"]

        result.total_new_posts = len(result.posts)

        # Download images
        fetcher = IncrementalFetcher(client=self.client)
        fetcher.download_images_with_urls(result, url_map)

        logger.info(
            "Fetch complete: %d posts, %d new images downloaded, %d skipped, %d failed",
            result.total_new_posts,
            result.total_downloaded_images,
            result.skipped_images,
            result.failed_images,
        )
        return result

    # ------------------------------------------------------------------
    # Phase 4: Build
    # ------------------------------------------------------------------

    def _run_build(self):
        """Run the build pipeline via subprocess."""
        build_script = PROJECT_ROOT / "build" / "build.py"
        if not build_script.exists():
            logger.error("Build script not found: %s", build_script)
            return

        logger.info("Running: python build/build.py")
        proc = subprocess.run(
            [sys.executable, "-X", "utf8", str(build_script)],
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            text=True,
            timeout=300,
        )

        if proc.stdout:
            for line in proc.stdout.strip().split("\n")[-20:]:
                logger.info("  BUILD: %s", line)

        if proc.returncode != 0:
            logger.error("Build failed (exit %d)", proc.returncode)
            if proc.stderr:
                for line in proc.stderr.strip().split("\n")[-10:]:
                    logger.error("  BUILD: %s", line)
            raise RuntimeError(f"Build failed with exit code {proc.returncode}")

        logger.info("Build completed successfully")

    # ------------------------------------------------------------------
    # Phase 5: R2 Sync
    # ------------------------------------------------------------------

    def _sync_r2(self):
        """Sync new images to Cloudflare R2."""
        sync_script = PROJECT_ROOT / "scripts" / "sync_to_r2.py"
        if not sync_script.exists():
            logger.warning("R2 sync script not found: %s", sync_script)
            return

        logger.info("Running: python scripts/sync_to_r2.py")
        proc = subprocess.run(
            [sys.executable, "-X", "utf8", str(sync_script)],
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            text=True,
            timeout=600,
        )

        if proc.stdout:
            for line in proc.stdout.strip().split("\n")[-15:]:
                logger.info("  R2: %s", line)

        if proc.returncode != 0:
            logger.warning("R2 sync had issues (exit %d), continuing...", proc.returncode)
        else:
            logger.info("R2 sync completed")

    # ------------------------------------------------------------------
    # Phase 6: Deploy
    # ------------------------------------------------------------------

    def _deploy(self, db_stats: dict):
        """Git commit, push, and deploy to GitHub Pages."""
        posts_added = db_stats.get("posts_added", 0)
        today = datetime.now(tz=CST).strftime("%Y-%m-%d")

        # Git operations
        self._git_commit_and_push(posts_added, today)

        # Deploy to GitHub Pages
        deploy_script = PROJECT_ROOT / "scripts" / "deploy_pages.sh"
        if deploy_script.exists():
            logger.info("Running: bash scripts/deploy_pages.sh")
            proc = subprocess.run(
                ["bash", str(deploy_script)],
                cwd=str(PROJECT_ROOT),
                capture_output=True,
                text=True,
                timeout=300,
            )
            if proc.stdout:
                for line in proc.stdout.strip().split("\n")[-10:]:
                    logger.info("  DEPLOY: %s", line)
            if proc.returncode != 0:
                logger.error("Deploy failed (exit %d)", proc.returncode)
                if proc.stderr:
                    logger.error("  %s", proc.stderr[-500:])
            else:
                logger.info("GitHub Pages deployed")

        # Optional: purge Cloudflare cache
        self._purge_cf_cache()

    def _git_commit_and_push(self, posts_added: int, today: str):
        """Stage changed files, commit, and push."""
        cwd = str(PROJECT_ROOT)

        # Stage key files
        files_to_stage = [
            "data/sui-archive.db",
            "deploy/",
        ]

        for f in files_to_stage:
            subprocess.run(
                ["git", "add", f],
                cwd=cwd, capture_output=True, text=True,
            )

        # Check if there are changes to commit
        status = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=cwd, capture_output=True, text=True,
        )

        if not status.stdout.strip():
            logger.info("No changes to commit")
            return

        # Commit
        msg = f"Auto Archive: +{posts_added} posts ({today})"
        result = subprocess.run(
            ["git", "commit", "-m", msg],
            cwd=cwd, capture_output=True, text=True,
        )

        if result.returncode != 0:
            logger.error("Git commit failed: %s", result.stderr)
            return

        logger.info("Committed: %s", msg)

        # Push
        result = subprocess.run(
            ["git", "push", "origin", "main"],
            cwd=cwd, capture_output=True, text=True, timeout=120,
        )

        if result.returncode != 0:
            logger.error("Git push failed: %s", result.stderr)
            # Retry once
            time.sleep(5)
            result = subprocess.run(
                ["git", "push", "origin", "main"],
                cwd=cwd, capture_output=True, text=True, timeout=120,
            )
            if result.returncode != 0:
                raise RuntimeError(f"Git push failed after retry: {result.stderr}")

        logger.info("Pushed to origin/main")

    def _purge_cf_cache(self):
        """Purge Cloudflare cache for the site (optional, best-effort)."""
        from .config import CLOUDFLARE_API_TOKEN, CLOUDFLARE_ZONE_ID

        if not CLOUDFLARE_API_TOKEN or not CLOUDFLARE_ZONE_ID:
            logger.info("Cloudflare zone not configured, skipping cache purge")
            return

        import requests
        try:
            resp = requests.post(
                f"https://api.cloudflare.com/client/v4/zones/{CLOUDFLARE_ZONE_ID}/purge_cache",
                headers={
                    "Authorization": f"Bearer {CLOUDFLARE_API_TOKEN}",
                    "Content-Type": "application/json",
                },
                json={"purge_everything": True},
                timeout=15,
            )
            data = resp.json()
            if data.get("success"):
                logger.info("Cloudflare cache purged")
            else:
                logger.warning("Cloudflare purge failed: %s", data.get("errors"))
        except Exception as e:
            logger.warning("Cloudflare purge error: %s", e)

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------

    def _print_summary(self):
        s = self.result.summary()
        logger.info("")
        logger.info("=" * 60)
        logger.info("  Pipeline Summary")
        logger.info("=" * 60)
        logger.info("  Has updates     : %s", s["has_updates"])
        logger.info("  Quick Check     : %d ms", s["quick_check_ms"])
        logger.info("  New posts       : %d", s["new_posts"])
        logger.info("  New images      : %d (downloaded: %d, failed: %d)",
                     s["new_images"], s["downloaded_images"], s["failed_images"])
        logger.info("  DB writes       : +%d posts, +%d images",
                     s["posts_added"], s["images_added"])
        logger.info("  Build           : %.1fs", s["build_seconds"])
        logger.info("  R2 sync         : %.1fs", s["r2_sync_seconds"])
        logger.info("  Deploy          : %.1fs", s["deploy_seconds"])
        logger.info("  Total           : %.1fs", s["total_seconds"])
        if s["error"]:
            logger.info("  ERROR           : %s", s["error"])
        logger.info("=" * 60)


# ---------------------------------------------------------------------------
# CLI Entry Point
# ---------------------------------------------------------------------------

def main():
    import argparse

    parser = argparse.ArgumentParser(description="SUI Archive Auto-Pipeline")
    parser.add_argument("--quick-check-only", action="store_true",
                        help="Only run quick check, exit immediately")
    parser.add_argument("--skip-deploy", action="store_true",
                        help="Skip git commit/push and Pages deploy")
    parser.add_argument("--skip-build", action="store_true",
                        help="Skip the build pipeline")
    parser.add_argument("--output-file", type=str, default="",
                        help="Write summary JSON to this file")
    parser.add_argument("--github-output", type=str, default="",
                        help="Write GitHub Actions output to this file")
    args = parser.parse_args()

    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format="[%(asctime)s] %(levelname)-5s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    orchestrator = Orchestrator(
        quick_check_only=args.quick_check_only,
        skip_deploy=args.skip_deploy,
        skip_build=args.skip_build,
    )
    result = orchestrator.run()

    # Write outputs
    if args.output_file:
        with open(args.output_file, "w", encoding="utf-8") as f:
            json.dump(result.summary(), f, indent=2, ensure_ascii=False)
        logger.info("Summary written to %s", args.output_file)

    if args.github_output:
        with open(args.github_output, "a", encoding="utf-8") as f:
            f.write(result.github_output() + "\n")
        logger.info("GitHub output written to %s", args.github_output)

    # Exit code: 0 = success (with or without updates), 1 = error
    sys.exit(1 if result.error else 0)


if __name__ == "__main__":
    main()
