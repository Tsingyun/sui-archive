"""
Build Step: stats_gen (Step 3)
Generates the site-wide statistics file from SQLite:
  - data/stats.json
"""

import json
import os
from datetime import datetime


# ---------------------------------------------------------------------------
# Overview
# ---------------------------------------------------------------------------

def _build_overview(db):
    """Aggregate high-level totals."""
    total_posts   = db.execute('SELECT COUNT(*) AS n FROM posts').fetchone()['n']
    total_images  = db.execute('SELECT COUNT(*) AS n FROM images').fetchone()['n']
    total_tags    = db.execute('SELECT COUNT(*) AS n FROM tags').fetchone()['n']
    total_authors = db.execute('SELECT COUNT(*) AS n FROM authors').fetchone()['n']

    date_row = db.execute(
        'SELECT MIN(published_at) AS first_dt, '
        '       MAX(published_at) AS last_dt '
        'FROM posts'
    ).fetchone()

    # Count distinct calendar days that have at least one post
    days_active = db.execute(
        "SELECT COUNT(DISTINCT strftime('%Y-%m-%d', published_at)) AS n "
        'FROM posts'
    ).fetchone()['n']

    return {
        'total_posts':   total_posts,
        'total_images':  total_images,
        'total_tags':    total_tags,
        'total_authors': total_authors,
        'date_range': {
            'first': date_row['first_dt'] if date_row else None,
            'last':  date_row['last_dt']  if date_row else None,
        },
        'days_active': days_active,
    }


# ---------------------------------------------------------------------------
# by_year
# ---------------------------------------------------------------------------

def _build_by_year(db):
    """Per-year breakdown: posts, images, reposts, avg_likes, top post."""
    year_rows = db.execute("""
        SELECT
            CAST(strftime('%Y', p.published_at) AS INTEGER) AS year,
            COUNT(*)                                        AS posts,
            COUNT(DISTINCT CASE
                WHEN pm.image_id IS NOT NULL THEN pm.image_id
            END)                                            AS images,
            SUM(CASE WHEN p.post_type = 'repost' THEN 1 ELSE 0 END) AS reposts
        FROM posts p
        LEFT JOIN post_media pm ON p.id = pm.post_id
        GROUP BY strftime('%Y', p.published_at)
        ORDER BY year DESC
    """).fetchall()

    result = []
    for row in year_rows:
        # Average likes from the latest stats snapshot per post this year
        avg_likes_row = db.execute("""
            SELECT COALESCE(AVG(ls.likes), 0) AS avg_likes
            FROM (
                SELECT ps.likes
                FROM post_stats ps
                JOIN posts p2 ON ps.post_id = p2.id
                WHERE strftime('%Y', p2.published_at) = ?
                  AND ps.snapshot_at = (
                      SELECT MAX(ps2.snapshot_at)
                      FROM post_stats ps2
                      WHERE ps2.post_id = ps.post_id
                  )
            ) ls
        """, (str(row['year']),)).fetchone()

        avg_likes = round(avg_likes_row['avg_likes'], 1) if avg_likes_row else 0

        # Top-liked post this year (using latest snapshot)
        top_post_row = db.execute("""
            SELECT p3.uuid
            FROM posts p3
            JOIN post_stats ps3 ON p3.id = ps3.post_id
            WHERE strftime('%Y', p3.published_at) = ?
              AND ps3.snapshot_at = (
                  SELECT MAX(ps4.snapshot_at)
                  FROM post_stats ps4
                  WHERE ps4.post_id = ps3.post_id
              )
            ORDER BY ps3.likes DESC
            LIMIT 1
        """, (str(row['year']),)).fetchone()

        result.append({
            'year':          row['year'],
            'posts':         row['posts'],
            'images':        row['images'],
            'reposts':       row['reposts'],
            'avg_likes':     avg_likes,
            'top_post_uuid': top_post_row['uuid'] if top_post_row else None,
        })

    return result


# ---------------------------------------------------------------------------
# by_type
# ---------------------------------------------------------------------------

def _build_by_type(db):
    """Count of posts per post_type."""
    rows = db.execute(
        'SELECT post_type, COUNT(*) AS cnt '
        'FROM posts GROUP BY post_type'
    ).fetchall()
    return {row['post_type']: row['cnt'] for row in rows}


# ---------------------------------------------------------------------------
# by_month  (lifetime totals per calendar month 1-12)
# ---------------------------------------------------------------------------

def _build_by_month(db):
    """Aggregate post counts by calendar month (1-12), across all years."""
    rows = db.execute("""
        SELECT
            CAST(strftime('%m', published_at) AS INTEGER) AS m,
            COUNT(*) AS cnt
        FROM posts
        GROUP BY m
    """).fetchall()
    return {str(row['m']): row['cnt'] for row in rows}


# ---------------------------------------------------------------------------
# activity_heatmap  (only dates with posts, no zero-fill)
# ---------------------------------------------------------------------------

def _build_heatmap(db):
    """Date → post count for the GitHub-style contribution heatmap."""
    rows = db.execute("""
        SELECT strftime('%Y-%m-%d', published_at) AS dt,
               COUNT(*) AS cnt
        FROM posts
        GROUP BY dt
    """).fetchall()
    return {row['dt']: row['cnt'] for row in rows}


# ---------------------------------------------------------------------------
# top_tags
# ---------------------------------------------------------------------------

def _build_top_tags(db):
    """Tags ranked by number of associated posts."""
    rows = db.execute("""
        SELECT t.slug, t.name, COUNT(pt.post_id) AS cnt
        FROM tags t
        JOIN post_tags pt ON t.id = pt.tag_id
        GROUP BY t.id
        ORDER BY cnt DESC
    """).fetchall()
    return [
        {'slug': r['slug'], 'name': r['name'], 'count': r['cnt']}
        for r in rows
    ]


# ---------------------------------------------------------------------------
# top_authors  (by repost count)
# ---------------------------------------------------------------------------

def _build_top_authors(db):
    """Authors ranked by how many times their content was reposted."""
    rows = db.execute("""
        SELECT a.display_name, COUNT(p.id) AS repost_count
        FROM authors a
        JOIN posts p ON p.original_author_id = a.id
        WHERE p.post_type = 'repost'
        GROUP BY a.id
        ORDER BY repost_count DESC
    """).fetchall()
    return [
        {'name': r['display_name'], 'repost_count': r['repost_count']}
        for r in rows
    ]


# ---------------------------------------------------------------------------
# engagement
# ---------------------------------------------------------------------------

def _build_engagement(db):
    """Aggregate engagement metrics from the latest stats snapshots."""
    totals = db.execute("""
        SELECT
            COALESCE(SUM(ls.likes), 0)    AS total_likes,
            COALESCE(SUM(ls.comments), 0) AS total_comments,
            COALESCE(SUM(ls.forwards), 0) AS total_forwards
        FROM (
            SELECT ps.likes, ps.comments, ps.forwards
            FROM post_stats ps
            WHERE ps.snapshot_at = (
                SELECT MAX(ps2.snapshot_at)
                FROM post_stats ps2
                WHERE ps2.post_id = ps.post_id
            )
        ) ls
    """).fetchone()

    total_posts = db.execute(
        'SELECT COUNT(*) AS n FROM posts'
    ).fetchone()['n']

    total_likes    = totals['total_likes']    if totals else 0
    total_comments = totals['total_comments'] if totals else 0
    total_forwards = totals['total_forwards'] if totals else 0

    avg_likes = round(total_likes / total_posts, 1) if total_posts > 0 else 0

    # Most-liked post (latest snapshot)
    most_liked = db.execute("""
        SELECT p.uuid
        FROM posts p
        JOIN post_stats ps ON p.id = ps.post_id
        WHERE ps.snapshot_at = (
            SELECT MAX(ps2.snapshot_at)
            FROM post_stats ps2
            WHERE ps2.post_id = ps.post_id
        )
        ORDER BY ps.likes DESC
        LIMIT 1
    """).fetchone()

    return {
        'total_likes':          total_likes,
        'total_comments':       total_comments,
        'total_forwards':       total_forwards,
        'avg_likes_per_post':   avg_likes,
        'most_liked_post_uuid': most_liked['uuid'] if most_liked else None,
    }


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def run(db, config, output_dir, logger):
    """
    Generate data/stats.json — the site-wide statistics summary.

    Args:
        db:         sqlite3.Connection with row_factory=sqlite3.Row.
        config:     dict loaded from config.yaml.
        output_dir: path to build output directory.
        logger:     logging.Logger instance.
    """
    logger.info('[stats] Starting statistics generation ...')

    stats = {
        'generated_at':     datetime.now().isoformat(),
        'overview':         _build_overview(db),
        'by_year':          _build_by_year(db),
        'by_type':          _build_by_type(db),
        'by_month':         _build_by_month(db),
        'activity_heatmap': _build_heatmap(db),
        'top_tags':         _build_top_tags(db),
        'top_authors':      _build_top_authors(db),
        'engagement':       _build_engagement(db),
    }

    data_dir = os.path.join(output_dir, 'data')
    os.makedirs(data_dir, exist_ok=True)

    stats_path = os.path.join(data_dir, 'stats.json')
    with open(stats_path, 'w', encoding='utf-8') as fh:
        json.dump(stats, fh, ensure_ascii=False, indent=2)

    logger.info('[stats] Generated stats.json '
                f'({stats["overview"]["total_posts"]} posts, '
                f'{len(stats["activity_heatmap"])} active days, '
                f'{len(stats["top_tags"])} tags)')
    logger.info('[stats] Statistics generation complete')
