"""
Step 8: output — Build report generation.

Generates build-info.json with build metadata, database statistics, and
file counts. The atomic swap of _build/ -> deploy/ is handled by build.py.
"""

import json
import os
from datetime import datetime, timezone
from pathlib import Path


def run(db, config, output_dir, logger):
    """Generate the build-info.json report.

    Args:
        db: sqlite3.Connection with row_factory=Row.
        config: dict from config.yaml.
        output_dir: Path to the build output directory.
        logger: Logger with .step()/.info()/.warn()/.success() methods.
    """
    logger.step("Step 8: output — Generating build report")

    output_dir = Path(output_dir)

    # Gather build metadata
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    version = config.get("_version", "1.0.0")
    duration_seconds = config.get("_duration_seconds", 0)

    # Database statistics
    db_stats = _collect_db_stats(db, logger)

    # File counts in output directory
    file_stats = _collect_file_stats(output_dir)

    # Assemble report
    report = {
        "generated_at": generated_at,
        "version": version,
        "duration_seconds": round(duration_seconds, 2),
        "site": {
            "name": config.get("site", {}).get("name", ""),
            "url": config.get("site", {}).get("url", ""),
        },
        "database": db_stats,
        "output_files": file_stats,
    }

    # Write report
    report_path = output_dir / "build-info.json"
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    logger.success(f"Build report written to {report_path.name}")
    logger.info(
        f"  Posts: {db_stats.get('total_posts', 0)}, "
        f"Images: {db_stats.get('total_images', 0)}, "
        f"Tags: {db_stats.get('total_tags', 0)}"
    )
    logger.info(
        f"  Output: {file_stats.get('total_files', 0)} files, "
        f"{_human_size(file_stats.get('total_size', 0))}"
    )


# ---------------------------------------------------------------------------
# Database statistics
# ---------------------------------------------------------------------------

def _collect_db_stats(db, logger):
    """Query the database for summary statistics."""
    stats = {}

    try:
        stats["total_posts"] = db.execute(
            "SELECT COUNT(*) AS c FROM posts WHERE is_deleted = 0"
        ).fetchone()["c"]
    except Exception:
        stats["total_posts"] = 0

    try:
        stats["total_images"] = db.execute(
            "SELECT COUNT(*) AS c FROM images WHERE is_deleted = 0"
        ).fetchone()["c"]
    except Exception:
        stats["total_images"] = 0

    try:
        stats["total_tags"] = db.execute(
            "SELECT COUNT(*) AS c FROM tags"
        ).fetchone()["c"]
    except Exception:
        stats["total_tags"] = 0

    try:
        stats["total_authors"] = db.execute(
            "SELECT COUNT(*) AS c FROM authors"
        ).fetchone()["c"]
    except Exception:
        stats["total_authors"] = 0

    try:
        date_range = db.execute("""
            SELECT
                MIN(published_at) AS first_post,
                MAX(published_at) AS last_post
            FROM posts WHERE is_deleted = 0
        """).fetchone()
        stats["date_range"] = {
            "first": date_range["first_post"] or None,
            "last": date_range["last_post"] or None,
        }
    except Exception:
        stats["date_range"] = {"first": None, "last": None}

    try:
        years = db.execute("""
            SELECT DISTINCT CAST(strftime('%Y', published_at) AS INTEGER) AS yr
            FROM posts WHERE is_deleted = 0
            ORDER BY yr
        """).fetchall()
        stats["years"] = [r["yr"] for r in years]
    except Exception:
        stats["years"] = []

    try:
        stats["total_post_stats_snapshots"] = db.execute(
            "SELECT COUNT(*) AS c FROM post_stats"
        ).fetchone()["c"]
    except Exception:
        stats["total_post_stats_snapshots"] = 0

    return stats


# ---------------------------------------------------------------------------
# File statistics
# ---------------------------------------------------------------------------

def _collect_file_stats(output_dir):
    """Count files and total size in the output directory."""
    output_dir = Path(output_dir)
    total_files = 0
    total_size = 0
    by_extension = {}

    if not output_dir.is_dir():
        return {"total_files": 0, "total_size": 0, "by_extension": {}}

    for fpath in output_dir.rglob("*"):
        if not fpath.is_file():
            continue
        total_files += 1
        fsize = fpath.stat().st_size
        total_size += fsize
        ext = fpath.suffix.lower() or "(no ext)"
        by_extension[ext] = by_extension.get(ext, 0) + 1

    return {
        "total_files": total_files,
        "total_size": total_size,
        "by_extension": dict(sorted(by_extension.items(), key=lambda x: -x[1])),
    }


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def _human_size(size_bytes):
    """Convert bytes to a human-readable string."""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    elif size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f} MB"
    else:
        return f"{size_bytes / (1024 * 1024 * 1024):.1f} GB"
