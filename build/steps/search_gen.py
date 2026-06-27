"""
Build Step: search_gen (Step 2)
Generates search and tag index files from SQLite:
  - data/search-index.json   (full-text search index for client-side search)
  - data/tag-index.json      (tag definitions with post/image counts)
"""

import json
import os
from datetime import datetime


# ---------------------------------------------------------------------------
# search-index.json
# ---------------------------------------------------------------------------

def _generate_search_index(db, config, output_dir, logger):
    """
    Generate data/search-index.json.

    Each entry contains the full plain_text (not truncated) so the
    client-side search engine can match arbitrary substrings.
    repost_text is resolved from the original post when available,
    falling back to the JSON snapshot.
    """
    search_cfg = config.get('search', {})
    max_text_len = search_cfg.get('max_text_length', 5000)

    # All posts with image counts, ordered newest-first
    posts = db.execute("""
        SELECT
            p.uuid,
            p.platform_post_id,
            p.plain_text,
            p.repost_snapshot,
            p.repost_of_id,
            p.post_type,
            p.published_at,
            (
                SELECT COUNT(*)
                FROM post_media pm
                WHERE pm.post_id = p.id
                  AND pm.image_id IS NOT NULL
            ) AS image_count
        FROM posts p
        ORDER BY p.published_at DESC
    """).fetchall()

    entries = []
    for post in posts:
        # Resolve repost text -----------------------------------------------
        # Priority: 1) original post in DB  2) snapshot JSON
        repost_text = None
        if post['repost_of_id'] is not None:
            orig = db.execute(
                'SELECT plain_text FROM posts WHERE id = ?',
                (post['repost_of_id'],),
            ).fetchone()
            if orig:
                repost_text = orig['plain_text']

        if repost_text is None and post['repost_snapshot']:
            try:
                snapshot = json.loads(post['repost_snapshot'])
                repost_text = (
                    snapshot.get('text')
                    or snapshot.get('plain_text')
                )
            except (json.JSONDecodeError, TypeError):
                pass

        # Tag slugs for this post -------------------------------------------
        tag_rows = db.execute("""
            SELECT t.slug
            FROM post_tags pt
            JOIN tags t ON pt.tag_id = t.id
            WHERE pt.post_id = (
                SELECT id FROM posts WHERE uuid = ?
            )
        """, (post['uuid'],)).fetchall()

        # Truncate extremely long text to keep index size manageable --------
        full_text = post['plain_text'] or ''
        if max_text_len and len(full_text) > max_text_len:
            full_text = full_text[:max_text_len]

        if repost_text and max_text_len and len(repost_text) > max_text_len:
            repost_text = repost_text[:max_text_len]

        image_count = post['image_count'] or 0

        entries.append({
            'uuid':             post['uuid'],
            'platform_post_id': post['platform_post_id'],
            'text':             full_text,
            'repost_text':      repost_text,
            'post_type':        post['post_type'],
            'published_at':     post['published_at'][:10],   # YYYY-MM-DD
            'has_images':       image_count > 0,
            'image_count':      image_count,
            'tags':             [t['slug'] for t in tag_rows],
        })

    search_data = {
        'generated_at':  datetime.now().isoformat(),
        'total_entries': len(entries),
        'entries':       entries,
    }

    data_dir = os.path.join(output_dir, 'data')
    os.makedirs(data_dir, exist_ok=True)

    search_path = os.path.join(data_dir, 'search-index.json')
    with open(search_path, 'w', encoding='utf-8') as fh:
        json.dump(search_data, fh, ensure_ascii=False, indent=2)

    logger.info(f'[search] Generated search-index.json ({len(entries)} entries)')


# ---------------------------------------------------------------------------
# tag-index.json
# ---------------------------------------------------------------------------

def _generate_tag_index(db, config, output_dir, logger):
    """
    Generate data/tag-index.json.

    Each tag entry carries its own post_count, image_count, and the
    date of the most recent post bearing that tag — enabling the
    front-end tag cloud and tag listing page without extra queries.
    """
    tags = db.execute("""
        SELECT
            t.name,
            t.slug,
            t.category,
            t.color,
            COUNT(DISTINCT pt.post_id) AS post_count,
            COALESCE(SUM(
                (SELECT COUNT(*)
                 FROM post_media pm
                 WHERE pm.post_id = pt.post_id
                   AND pm.image_id IS NOT NULL)
            ), 0) AS image_count,
            MAX(DATE(p.published_at))  AS latest_post_date
        FROM tags t
        LEFT JOIN post_tags pt ON t.id = pt.tag_id
        LEFT JOIN posts       p  ON pt.post_id = p.id
        GROUP BY t.id
        ORDER BY post_count DESC, t.name
    """).fetchall()

    tag_list = []
    for tag in tags:
        tag_list.append({
            'name':             tag['name'],
            'slug':             tag['slug'],
            'category':         tag['category'],
            'color':            tag['color'],
            'post_count':       tag['post_count'] or 0,
            'image_count':      tag['image_count'] or 0,
            'latest_post_date': tag['latest_post_date'],
        })

    tag_data = {
        'total_tags': len(tag_list),
        'tags':       tag_list,
    }

    data_dir = os.path.join(output_dir, 'data')
    os.makedirs(data_dir, exist_ok=True)

    tag_path = os.path.join(data_dir, 'tag-index.json')
    with open(tag_path, 'w', encoding='utf-8') as fh:
        json.dump(tag_data, fh, ensure_ascii=False, indent=2)

    logger.info(f'[search] Generated tag-index.json ({len(tag_list)} tags)')


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def run(db, config, output_dir, logger):
    """
    Generate search and tag index files.

    Args:
        db:         sqlite3.Connection with row_factory=sqlite3.Row.
        config:     dict loaded from config.yaml.
        output_dir: path to build output directory.
        logger:     logging.Logger instance.
    """
    logger.info('[search] Starting search index generation ...')

    data_dir = os.path.join(output_dir, 'data')
    os.makedirs(data_dir, exist_ok=True)

    _generate_search_index(db, config, output_dir, logger)
    _generate_tag_index(db, config, output_dir, logger)

    logger.info('[search] Search index generation complete')
