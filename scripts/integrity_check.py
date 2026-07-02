#!/usr/bin/env python3
"""
SUI Archive - Daily Integrity Check

Validates the entire digital archive for consistency without fetching
new data from any social platform. Auto-repairs when possible,
generates detailed reports for issues that cannot be fixed.

Usage:
    python scripts/integrity_check.py [--auto-repair] [--output report.json]
"""

import argparse
import json
import logging
import os
import re
import sqlite3
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

try:
    from dotenv import load_dotenv
    _env = PROJECT_ROOT / ".env"
    if _env.exists():
        load_dotenv(_env)
except ImportError:
    pass

DB_PATH = PROJECT_ROOT / "data" / "sui-archive.db"
DEPLOY_DIR = PROJECT_ROOT / "deploy"
IMAGES_DIR = PROJECT_ROOT / "images"
BUILD_SCRIPT = PROJECT_ROOT / "build" / "build.py"
CST = timezone(timedelta(hours=8))
logger = logging.getLogger("integrity")


class IntegrityReport:
    def __init__(self):
        self.started_at = datetime.now(tz=CST).isoformat()
        self.sections = []
        self.total_issues = 0
        self.total_repaired = 0
        self.total_unresolvable = 0
        self.needs_rebuild = False

    def add_section(self, name, status, issues=None, repaired=0, unresolvable=0, details=None):
        section = {"name": name, "status": status, "issues": issues or [],
                   "repaired": repaired, "unresolvable": unresolvable}
        if details:
            section["details"] = details
        self.sections.append(section)
        self.total_issues += len(issues or [])
        self.total_repaired += repaired
        self.total_unresolvable += unresolvable

    @property
    def passed(self):
        return self.total_unresolvable == 0

    def to_dict(self):
        return {"started_at": self.started_at,
                "finished_at": datetime.now(tz=CST).isoformat(),
                "passed": self.passed,
                "total_issues": self.total_issues,
                "total_repaired": self.total_repaired,
                "total_unresolvable": self.total_unresolvable,
                "needs_rebuild": self.needs_rebuild,
                "sections": self.sections}

    def to_markdown(self):
        lines = ["## Archive Integrity Report", "",
                 f"**Started:** {self.started_at}",
                 f"**Result:** {'PASSED' if self.passed else 'FAILED'}"]
        if self.total_issues:
            lines.append(f"**Issues:** {self.total_issues} total, {self.total_repaired} repaired, {self.total_unresolvable} unresolvable")
        lines += ["", "| Check | Status | Issues | Repaired |",
                  "|-------|--------|--------|----------|"]
        for s in self.sections:
            icon = {"pass": "OK", "fail": "FAIL", "repaired": "FIXED", "warning": "WARN"}.get(s["status"], "?")
            lines.append(f"| {s['name']} | {icon} | {len(s.get('issues', []))} | {s.get('repaired', 0)} |")
        lines.append("")
        for s in self.sections:
            if s["unresolvable"] > 0 and s.get("issues"):
                lines.append(f"### {s['name']} - Unresolvable")
                for iss in s["issues"]:
                    if not iss.startswith("[repaired]"):
                        lines.append(f"- {iss}")
                lines.append("")
        return "\n".join(lines)


def _connect_db():
    conn = sqlite3.connect(str(DB_PATH), timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row
    return conn


def _load_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f), None
    except json.JSONDecodeError as e:
        return None, f"Invalid JSON: {e}"
    except FileNotFoundError:
        return None, "File not found"
    except Exception as e:
        return None, str(e)


def _run_build(lg):
    import subprocess
    if not BUILD_SCRIPT.exists():
        lg.error("Build script not found: %s", BUILD_SCRIPT)
        return False
    lg.info("Triggering full rebuild: python build/build.py")
    proc = subprocess.run(
        [sys.executable, "-X", "utf8", str(BUILD_SCRIPT)],
        cwd=str(PROJECT_ROOT), capture_output=True, text=True, timeout=600)
    if proc.returncode != 0:
        lg.error("Build failed (exit %d)", proc.returncode)
        if proc.stderr:
            for line in proc.stderr.strip().split("\n")[-10:]:
                lg.error("  BUILD: %s", line)
        return False
    lg.info("Rebuild completed successfully")
    return True


def check_sqlite(report):
    issues = []
    if not DB_PATH.exists():
        report.add_section("SQLite", "fail", ["Database file not found"])
        return None
    try:
        conn = _connect_db()
    except Exception as e:
        report.add_section("SQLite", "fail", [f"Cannot open database: {e}"])
        return None

    # integrity
    row = conn.execute("PRAGMA integrity_check").fetchone()
    if row[0] != "ok":
        issues.append(f"integrity_check failed: {row[0]}")

    # foreign keys
    fk = conn.execute("PRAGMA foreign_key_check").fetchall()
    if fk:
        issues.append(f"foreign_key_check: {len(fk)} violation(s)")

    # indexes
    idx_rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='index' AND name LIKE 'idx_%'").fetchall()
    idx_names = {r[0] for r in idx_rows}
    expected_idx = ["idx_platforms_key", "idx_authors_platform", "idx_posts_published",
                    "idx_posts_platform", "idx_posts_type", "idx_images_filename",
                    "idx_images_sha256", "idx_post_media_post", "idx_post_stats_post"]
    missing_idx = [i for i in expected_idx if i not in idx_names]
    if missing_idx:
        issues.append(f"Missing indexes: {', '.join(missing_idx)}")

    # duplicate posts
    dup = conn.execute("""
        SELECT platform_post_id, COUNT(*) c FROM posts WHERE platform_id=1
        GROUP BY platform_post_id HAVING c>1""").fetchall()
    if dup:
        issues.append(f"Duplicate posts: {len(dup)} platform_post_id(s)")

    # duplicate images
    dup_i = conn.execute("""
        SELECT filename, COUNT(*) c FROM images GROUP BY filename HAVING c>1""").fetchall()
    if dup_i:
        issues.append(f"Duplicate images: {len(dup_i)} filename(s)")

    # orphan post_media
    orphan_pm = conn.execute("""
        SELECT COUNT(*) FROM post_media pm
        LEFT JOIN images i ON pm.image_id=i.id
        WHERE pm.image_id IS NOT NULL AND i.id IS NULL""").fetchone()[0]
    if orphan_pm:
        issues.append(f"Orphan post_media: {orphan_pm}")

    # orphan post_stats
    orphan_ps = conn.execute("""
        SELECT COUNT(*) FROM post_stats ps
        LEFT JOIN posts p ON ps.post_id=p.id WHERE p.id IS NULL""").fetchone()[0]
    if orphan_ps:
        issues.append(f"Orphan post_stats: {orphan_ps}")

    # null content (exclude image-only posts which legitimately have no text)
    null_c = conn.execute("""
        SELECT COUNT(*) FROM posts p
        WHERE p.plain_text IS NULL AND p.repost_snapshot IS NULL
          AND p.post_type NOT IN ('image')
          AND (SELECT COUNT(*) FROM post_media pm WHERE pm.post_id=p.id) = 0""").fetchone()[0]
    if null_c:
        issues.append(f"Posts with no content: {null_c}")

    # bad timestamps
    bad_ts = conn.execute("""
        SELECT COUNT(*) FROM posts
        WHERE published_at < '2020-01-01' OR published_at > '2099-12-31'""").fetchone()[0]
    if bad_ts:
        issues.append(f"Suspicious timestamps: {bad_ts}")

    # FTS sync
    db_count = conn.execute("SELECT COUNT(*) FROM posts").fetchone()[0]
    fts_count = conn.execute("SELECT COUNT(*) FROM posts_fts").fetchone()[0]
    if db_count != fts_count:
        issues.append(f"FTS5 desync: posts={db_count}, fts={fts_count}")

    counts = {"posts": db_count,
              "images": conn.execute("SELECT COUNT(*) FROM images").fetchone()[0],
              "authors": conn.execute("SELECT COUNT(*) FROM authors").fetchone()[0],
              "tags": conn.execute("SELECT COUNT(*) FROM tags").fetchone()[0],
              "post_stats": conn.execute("SELECT COUNT(*) FROM post_stats").fetchone()[0]}
    conn.close()

    status = "pass" if not issues else "fail"
    report.add_section("SQLite", status, issues, details=counts)
    return counts


def check_json(report, db_counts):
    issues = []
    data_dir = DEPLOY_DIR / "data"
    if not data_dir.exists():
        report.add_section("JSON", "fail", ["deploy/data/ missing"])
        report.needs_rebuild = True
        return

    required = ["dynamics-index.json", "search-index.json", "stats.json",
                 "tag-index.json", "images-manifest.json"]
    loaded = {}
    if db_counts:
        try:
            conn = _connect_db()
            years = conn.execute("""
                SELECT DISTINCT CAST(SUBSTR(published_at,1,4) AS INTEGER) yr
                FROM posts WHERE yr>=2020 ORDER BY yr""").fetchall()
            conn.close()
            for r in years:
                required.append(f"dynamics-{r[0]}.json")
        except Exception:
            pass

    for fname in required:
        data, err = _load_json(data_dir / fname)
        if err:
            issues.append(f"{fname}: {err}")
        else:
            loaded[fname] = data

    idx = loaded.get("dynamics-index.json")
    if idx and db_counts:
        t = idx.get("build", {}).get("total_posts", 0)
        if t != db_counts["posts"]:
            issues.append(f"dynamics-index total_posts={t} vs DB={db_counts['posts']}")

    si = loaded.get("search-index.json")
    if si and db_counts:
        st = si.get("total_entries", 0)
        sa = len(si.get("entries", []))
        if st != sa:
            issues.append(f"search-index total_entries={st} != actual={sa}")
        if db_counts["posts"] != sa:
            issues.append(f"search-index entries={sa} vs DB posts={db_counts['posts']}")

    stats = loaded.get("stats.json")
    if stats and db_counts:
        sp = stats.get("overview", {}).get("total_posts", 0)
        if sp != db_counts["posts"]:
            issues.append(f"stats total_posts={sp} vs DB={db_counts['posts']}")
        sim = stats.get("overview", {}).get("total_images", 0)
        if sim != db_counts["images"]:
            issues.append(f"stats total_images={sim} vs DB={db_counts['images']}")

    img = loaded.get("images-manifest.json")
    if img and db_counts:
        mt = img.get("total_images", 0)
        ma = len(img.get("images", []))
        if mt != ma:
            issues.append(f"images-manifest total={mt} != actual={ma}")
        if db_counts["images"] != ma:
            issues.append(f"images-manifest images={ma} vs DB={db_counts['images']}")

    if any("missing" in i.lower() or "not found" in i.lower() for i in issues):
        report.needs_rebuild = True
    report.add_section("JSON", "pass" if not issues else "fail", issues)


def check_html(report, db_counts):
    issues = []
    if not DEPLOY_DIR.exists():
        report.add_section("HTML", "fail", ["deploy/ missing"])
        report.needs_rebuild = True
        return

    for page in ["index.html", "about.html", "gallery.html", "search.html",
                 "stats.html", "tags.html", "timeline.html", "404.html"]:
        p = DEPLOY_DIR / page
        if not p.exists():
            issues.append(f"Missing: {page}")
        elif p.stat().st_size < 100:
            issues.append(f"Too small: {page} ({p.stat().st_size}B)")

    dd = DEPLOY_DIR / "d"
    if not dd.exists():
        issues.append("Missing deploy/d/")
    elif db_counts:
        dirs = {d.name for d in dd.iterdir() if d.is_dir()}
        actual = len(dirs)
        expected = db_counts["posts"]
        if actual != expected:
            issues.append(f"Detail pages: {actual} vs DB posts={expected}")

        for d in sorted(dirs)[:10]:
            idx = dd / d / "index.html"
            if not idx.exists():
                issues.append(f"Missing d/{d}/index.html")
            elif idx.stat().st_size < 200:
                issues.append(f"Too small: d/{d}/index.html")
            else:
                try:
                    c = idx.read_text(encoding="utf-8", errors="ignore")[:2000]
                    if "<title>" not in c:
                        issues.append(f"No <title>: d/{d}/")
                    if "og:title" not in c:
                        issues.append(f"No og:title: d/{d}/")
                except Exception:
                    pass

    if issues and any("missing" in i.lower() for i in issues):
        report.needs_rebuild = True
    report.add_section("HTML", "pass" if not issues else "fail", issues)


def check_images(report, db_counts):
    issues = []
    missing_images = []
    if not DB_PATH.exists():
        report.add_section("Images", "fail", ["No database"])
        return

    conn = _connect_db()
    images = conn.execute("SELECT filename, sha256, file_size FROM images").fetchall()
    conn.close()

    local_ok, local_missing = 0, 0
    for img in images:
        fpath = IMAGES_DIR / img["filename"]
        if not fpath.exists():
            local_missing += 1
            missing_images.append({"filename": img["filename"], "sha256": img["sha256"],
                                   "expected_size": img["file_size"], "status": "missing_local"})
        else:
            local_ok += 1
            actual = fpath.stat().st_size
            if img["file_size"] and abs(actual - img["file_size"]) > 100:
                issues.append(f"Size mismatch: {img['filename']}")

    if local_missing:
        issues.append(f"Missing {local_missing} image(s) locally (DB has {len(images)})")

    # R2 check
    r2_key = os.environ.get("R2_ACCESS_KEY_ID", "")
    r2_secret = os.environ.get("R2_SECRET_ACCESS_KEY", "")
    r2_bucket = os.environ.get("R2_BUCKET", "sui-archive-images")
    r2_endpoint = os.environ.get("R2_ENDPOINT_URL", "")
    if all([r2_key, r2_secret, r2_endpoint]):
        try:
            import boto3
            from botocore.config import Config as BC
            s3 = boto3.client("s3", endpoint_url=r2_endpoint,
                              aws_access_key_id=r2_key, aws_secret_access_key=r2_secret,
                              config=BC(s3={"addressing_style": "path"}))
            pg = s3.get_paginator("list_objects_v2")
            r2_count = sum(len(p.get("Contents", [])) for p in pg.paginate(Bucket=r2_bucket, PaginationConfig={"PageSize": 1000}))
            if db_counts and r2_count < db_counts.get("images", 0):
                issues.append(f"R2 objects={r2_count} vs DB images={db_counts['images']}")
        except ImportError:
            issues.append("boto3 not installed, R2 check skipped")
        except Exception as e:
            issues.append(f"R2 check error: {e}")
    else:
        issues.append("R2 credentials not configured, skipping R2 check")

    # Missing report
    if missing_images:
        rp = DEPLOY_DIR / "data" / "missing-images.json"
        try:
            rp.parent.mkdir(parents=True, exist_ok=True)
            with open(rp, "w", encoding="utf-8") as f:
                json.dump({"generated_at": datetime.now(tz=CST).isoformat(),
                           "total_missing": len(missing_images), "images": missing_images}, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    status = "pass" if not issues else "warning"
    report.add_section("Images", status, issues,
                       details={"db": len(images), "local_ok": local_ok, "local_missing": local_missing})


def check_search(report, db_counts):
    issues = []
    data, err = _load_json(DEPLOY_DIR / "data" / "search-index.json")
    if err:
        report.add_section("Search", "fail", [err])
        report.needs_rebuild = True
        return
    entries = data.get("entries", [])
    td = data.get("total_entries", 0)
    if td != len(entries):
        issues.append(f"total_entries={td} != actual={len(entries)}")
    if db_counts and db_counts["posts"] != len(entries):
        issues.append(f"entries={len(entries)} vs DB posts={db_counts['posts']}")
    uuids = [e.get("uuid", "") for e in entries]
    dups = len(uuids) - len(set(uuids))
    if dups:
        issues.append(f"Duplicate UUIDs: {dups}")
    empty = sum(1 for e in entries
                 if not e.get("text") and not e.get("repost_text") and not e.get("has_images"))
    if empty > 10:
        issues.append(f"No searchable text or images: {empty}")
    status = "pass" if not issues else "fail"
    if status == "fail":
        report.needs_rebuild = True
    report.add_section("Search", status, issues)


def check_timeline(report, db_counts):
    issues = []
    data, err = _load_json(DEPLOY_DIR / "data" / "dynamics-index.json")
    if err:
        report.add_section("Timeline", "fail", [err])
        report.needs_rebuild = True
        return
    years = data.get("years", [])
    if not years:
        issues.append("No year data")
    ysum = sum(y.get("count", 0) for y in years)
    total = data.get("build", {}).get("total_posts", 0)
    if ysum != total:
        issues.append(f"yearly_sum={ysum} != total_posts={total}")
    if db_counts and total != db_counts["posts"]:
        issues.append(f"index total={total} vs DB={db_counts['posts']}")
    for y in years:
        yr, cnt = y.get("year"), y.get("count", 0)
        ydata, yerr = _load_json(DEPLOY_DIR / "data" / f"dynamics-{yr}.json")
        if yerr:
            issues.append(f"dynamics-{yr}.json: {yerr}")
            continue
        posts_list = ydata.get('posts', []) if isinstance(ydata, dict) else (ydata if isinstance(ydata, list) else [])
        actual = len(posts_list)
        if actual != cnt:
            issues.append(f"dynamics-{yr}.json: {actual} entries, expected {cnt}")
        ms = sum(y.get("months", {}).values())
        if ms != cnt:
            issues.append(f"{yr}: monthly_sum={ms} != year_count={cnt}")
    if not (DEPLOY_DIR / "timeline.html").exists():
        issues.append("Missing timeline.html")
    status = "pass" if not issues else "fail"
    if status == "fail":
        report.needs_rebuild = True
    report.add_section("Timeline", status, issues)


def check_statistics(report, db_counts):
    issues = []
    data, err = _load_json(DEPLOY_DIR / "data" / "stats.json")
    if err:
        report.add_section("Statistics", "fail", [err])
        report.needs_rebuild = True
        return
    ov = data.get("overview", {})
    if db_counts:
        if ov.get("total_posts", 0) != db_counts["posts"]:
            issues.append(f"total_posts mismatch")
        if ov.get("total_images", 0) != db_counts["images"]:
            issues.append(f"total_images mismatch")
        if ov.get("total_tags", 0) != db_counts["tags"]:
            issues.append(f"total_tags mismatch")
        if ov.get("total_authors", 0) != db_counts["authors"]:
            issues.append(f"total_authors mismatch")
    bt = data.get("by_type", {})
    if bt and db_counts and sum(bt.values()) != db_counts["posts"]:
        issues.append(f"by_type sum mismatch")
    bm = data.get("by_month", {})
    if bm and db_counts and sum(bm.values()) != db_counts["posts"]:
        issues.append(f"by_month sum mismatch")
    if not (DEPLOY_DIR / "stats.html").exists():
        issues.append("Missing stats.html")
    status = "pass" if not issues else "fail"
    if status == "fail":
        report.needs_rebuild = True
    report.add_section("Statistics", status, issues)


def check_seo(report, db_counts):
    issues = []
    robots = DEPLOY_DIR / "robots.txt"
    if not robots.exists():
        issues.append("Missing robots.txt")
    elif robots.stat().st_size < 10:
        issues.append("robots.txt too small")
    sitemap = DEPLOY_DIR / "sitemap.xml"
    if not sitemap.exists():
        issues.append("Missing sitemap.xml")
    else:
        try:
            c = sitemap.read_text(encoding="utf-8", errors="ignore")
            uc = c.count("<url>")
            if db_counts and uc < db_counts["posts"]:
                issues.append(f"sitemap URLs={uc} < DB posts={db_counts['posts']}")
        except Exception:
            pass
    dd = DEPLOY_DIR / "d"
    if dd.exists():
        for d in sorted(d.name for d in dd.iterdir() if d.is_dir())[:10]:
            idx = dd / d / "index.html"
            if not idx.exists():
                continue
            try:
                c = idx.read_text(encoding="utf-8", errors="ignore")[:3000]
                if 'rel="canonical"' not in c:
                    issues.append(f"No canonical: d/{d}/")
                if "og:title" not in c:
                    issues.append(f"No og:title: d/{d}/")
            except Exception:
                pass
    if any("missing" in i.lower() and ("robots" in i or "sitemap" in i) for i in issues):
        report.needs_rebuild = True
    report.add_section("SEO", "pass" if not issues else "fail", issues)


def check_assets(report):
    issues = []
    css = DEPLOY_DIR / "style.css"
    if not css.exists():
        issues.append("Missing style.css")
    elif css.stat().st_size < 100:
        issues.append(f"style.css too small ({css.stat().st_size}B)")

    js_dir = DEPLOY_DIR / "js"
    if not js_dir.exists():
        issues.append("Missing js/ directory")
    else:
        expected = ["app.js", "config.js", "dom.js", "state.js", "router.js",
                     "i18n.js", "api.js", "search.js", "gallery.js", "timeline.js",
                     "stats.js", "lightbox.js", "lazy-load.js", "infinite-scroll.js",
                     "post-card.js", "post-detail.js", "tag-filter.js", "share.js"]
        for js in expected:
            if not (js_dir / js).exists():
                issues.append(f"Missing JS: {js}")

    if not (DEPLOY_DIR / "build-info.json").exists():
        issues.append("Missing build-info.json")

    if issues:
        report.needs_rebuild = True
    report.add_section("Assets", "pass" if not issues else "fail", issues)


def auto_repair(report, do_repair):
    if not report.needs_rebuild:
        logger.info("No rebuild needed")
        return False
    if not do_repair:
        logger.warning("Rebuild needed but --auto-repair not specified")
        return False
    logger.info("Auto-repair: triggering full rebuild")
    ok = _run_build(logger)
    if ok:
        for s in report.sections:
            if s["status"] == "fail":
                s["status"] = "repaired"
                s["repaired"] = len(s["issues"])
                s["issues"] = [f"[repaired] {i}" for i in s["issues"]]
                report.total_repaired += s["repaired"]
        report.total_unresolvable = 0
        report.needs_rebuild = False
        logger.info("Auto-repair complete")
        return True
    else:
        logger.error("Auto-repair: rebuild failed")
        for s in report.sections:
            if s["status"] == "fail":
                s["unresolvable"] = len(s["issues"])
        return False


def git_commit_if_repaired(repaired):
    import subprocess
    if not repaired:
        return
    cwd = str(PROJECT_ROOT)
    subprocess.run(["git", "add", "deploy/"], cwd=cwd, capture_output=True, text=True)
    status = subprocess.run(["git", "status", "--porcelain"],
                            cwd=cwd, capture_output=True, text=True)
    if not status.stdout.strip():
        logger.info("No repaired files to commit")
        return
    today = datetime.now(tz=CST).strftime("%Y-%m-%d")
    msg = f"Integrity Check: auto-repair ({today})"
    r = subprocess.run(["git", "commit", "-m", msg], cwd=cwd, capture_output=True, text=True)
    if r.returncode != 0:
        logger.error("Git commit failed: %s", r.stderr)
        return
    logger.info("Committed: %s", msg)
    r = subprocess.run(["git", "push", "origin", "main"],
                       cwd=cwd, capture_output=True, text=True, timeout=120)
    if r.returncode != 0:
        logger.error("Git push failed: %s", r.stderr)
    else:
        logger.info("Pushed to origin/main")


def main():
    parser = argparse.ArgumentParser(description="SUI Archive Integrity Check")
    parser.add_argument("--auto-repair", action="store_true",
                        help="Automatically rebuild if issues found")
    parser.add_argument("--output", type=str, default="",
                        help="Write report JSON to this file")
    parser.add_argument("--markdown", type=str, default="",
                        help="Write report markdown to this file")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="[%(asctime)s] %(levelname)-5s %(name)s: %(message)s",
        datefmt="%H:%M:%S")

    t0 = time.monotonic()
    logger.info("=" * 60)
    logger.info("  SUI Archive Integrity Check")
    logger.info("=" * 60)

    report = IntegrityReport()

    logger.info("[1/9] Checking SQLite ...")
    db_counts = check_sqlite(report)

    logger.info("[2/9] Checking JSON ...")
    check_json(report, db_counts)

    logger.info("[3/9] Checking HTML ...")
    check_html(report, db_counts)

    logger.info("[4/9] Checking Images ...")
    check_images(report, db_counts)

    logger.info("[5/9] Checking Search Index ...")
    check_search(report, db_counts)

    logger.info("[6/9] Checking Timeline ...")
    check_timeline(report, db_counts)

    logger.info("[7/9] Checking Statistics ...")
    check_statistics(report, db_counts)

    logger.info("[8/9] Checking SEO ...")
    check_seo(report, db_counts)

    logger.info("[9/9] Checking Assets ...")
    check_assets(report)

    # Auto-repair
    logger.info("=" * 60)
    repaired = auto_repair(report, args.auto_repair)
    git_commit_if_repaired(repaired)

    elapsed = time.monotonic() - t0
    logger.info("")
    logger.info("=" * 60)
    if report.passed:
        logger.info("  Archive Integrity Check Passed.")
    else:
        logger.info("  Archive Integrity Check FAILED.")
        logger.info("  %d issue(s), %d repaired, %d unresolvable",
                     report.total_issues, report.total_repaired, report.total_unresolvable)
    logger.info("  Duration: %.1fs", elapsed)
    logger.info("=" * 60)

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(report.to_dict(), f, indent=2, ensure_ascii=False)
        logger.info("Report JSON: %s", args.output)

    if args.markdown:
        with open(args.markdown, "w", encoding="utf-8") as f:
            f.write(report.to_markdown())
        logger.info("Report Markdown: %s", args.markdown)

    gh_output = os.environ.get("GITHUB_OUTPUT", "")
    if gh_output:
        with open(gh_output, "a", encoding="utf-8") as f:
            f.write(f"passed={'true' if report.passed else 'false'}\n")
            f.write(f"total_issues={report.total_issues}\n")
            f.write(f"total_repaired={report.total_repaired}\n")
            f.write(f"total_unresolvable={report.total_unresolvable}\n")
            f.write(f"duration_seconds={int(elapsed)}\n")

    if report.passed:
        sys.exit(0)
    elif repaired:
        sys.exit(0)
    else:
        sys.exit(2)


if __name__ == "__main__":
    main()
