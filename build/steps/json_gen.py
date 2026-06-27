"""
Build Step: json_gen (Step 1)
Generates all JSON data files from SQLite:
  - data/dynamics-index.json   (year index + global metadata)
  - data/dynamics-{year}.json  (per-year post listings)
  - data/detail/{uuid}.json    (per-post full detail)
"""

import json
import os
from datetime import datetime


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _truncate_text(text, max_len=200):
    """
    Truncate plain_text to *max_len* characters at a sentence boundary.

    Rules (from BUILD_SPEC 1.3, Step 1):
      - If text fits within max_len, return as-is.
      - Otherwise, cut at the last sentence-ending punctuation
        (Chinese period/full-stop, exclamation, question mark, or newline)
        that falls within the first max_len characters.
      - Never break inside a [bracket emoji] tag.
      - Append an ellipsis character when truncated.
    """
    if not text:
        return ''
    if len(text) <= max_len:
        return text

    truncated = text[:max_len]

    # Do not cut inside a [emoji] tag — find the last safe cut point
    last_open_bracket = truncated.rfind('[')
    last_close_bracket = truncated.rfind(']')
    safe_end = max_len
    if last_open_bracket > last_close_bracket:
        # Inside an unclosed bracket tag — pull back to before the '['
        safe_end = last_open_bracket

    cut_region = truncated[:safe_end]

    # Try each sentence-ending character; take the latest one
    best = -1
    for sep in ('。', '！', '？', '\n'):
        idx = cut_region.rfind(sep)
        if idx > best:
            best = idx

    if best > 0:
        result = cut_region[:best + 1]
    else:
        result = cut_region

    return result.rstrip() + '…'


def _get_repost_info(db, post):
    """
    Build the ``repost`` sub-object for a detail JSON.

    Handles two cases:
      1. repost_of_id is set  → look up the original post in the DB.
      2. repost_snapshot is set → parse the JSON snapshot.
    In both cases, the author name comes from the authors table
    via original_author_id.
    """
    repost_data = {
        'author_name': None,
        'author_url': None,
        'text': None,
        'source_url': None,
    }

    # Resolve author name / URL from original_author_id
    if post['original_author_id'] is not None:
        author = db.execute(
            'SELECT display_name, profile_url '
            'FROM authors WHERE id = ?',
            (post['original_author_id'],),
        ).fetchone()
        if author:
            repost_data['author_name'] = author['display_name']
            repost_data['author_url'] = author['profile_url']

    # Case 1: original post lives in the database
    if post['repost_of_id'] is not None:
        orig = db.execute(
            'SELECT plain_text, source_url '
            'FROM posts WHERE id = ?',
            (post['repost_of_id'],),
        ).fetchone()
        if orig:
            repost_data['text'] = orig['plain_text']
            repost_data['source_url'] = orig['source_url']

    # Case 2: only a JSON snapshot is available (original deleted / absent)
    elif post['repost_snapshot']:
        try:
            snapshot = json.loads(post['repost_snapshot'])
            repost_data['text'] = (
                snapshot.get('text')
                or snapshot.get('plain_text')
            )
            if repost_data['source_url'] is None:
                repost_data['source_url'] = snapshot.get('source_url')
            # Fall back to snapshot author if authors table lookup failed
            if repost_data['author_name'] is None:
                repost_data['author_name'] = snapshot.get('author_name')
        except (json.JSONDecodeError, TypeError):
            pass

    return repost_data


# ---------------------------------------------------------------------------
# dynamics-index.json
# ---------------------------------------------------------------------------

def _generate_index(db, config, output_dir, logger):
    """Generate data/dynamics-index.json and return per-year metadata."""

    site_cfg = config.get('site', {})
    json_cfg = config.get('json', {})
    posts_per_page = json_cfg.get('text_preview_length',
                                  config.get('pages', {}).get('posts_per_page', 50))

    # Aggregate totals
    total_posts  = db.execute('SELECT COUNT(*) AS n FROM posts').fetchone()['n']
    total_images = db.execute('SELECT COUNT(*) AS n FROM images').fetchone()['n']
    total_tags   = db.execute('SELECT COUNT(*) AS n FROM tags').fetchone()['n']

    # Per-year aggregation
    year_rows = db.execute("""
        SELECT
            CAST(strftime('%Y', published_at) AS INTEGER) AS year,
            COUNT(*)                                       AS cnt,
            MIN(published_at)                              AS first_date,
            MAX(published_at)                              AS last_date
        FROM posts
        GROUP BY strftime('%Y', published_at)
        ORDER BY year DESC
    """).fetchall()

    years = []
    year_post_data = {}   # year → [post rows]  (for dynamics-{year}.json)

    for yr in year_rows:
        year_val = yr['year']

        # Monthly breakdown
        month_rows = db.execute("""
            SELECT
                CAST(strftime('%m', published_at) AS INTEGER) AS m,
                COUNT(*)                                       AS cnt
            FROM posts
            WHERE strftime('%Y', published_at) = ?
            GROUP BY m
        """, (str(year_val),)).fetchall()
        months = {str(row['m']): row['cnt'] for row in month_rows}

        # Type breakdown
        type_rows = db.execute("""
            SELECT post_type, COUNT(*) AS cnt
            FROM posts
            WHERE strftime('%Y', published_at) = ?
            GROUP BY post_type
        """, (str(year_val),)).fetchall()
        type_counts = {row['post_type']: row['cnt'] for row in type_rows}

        years.append({
            'year':        year_val,
            'count':       yr['cnt'],
            'date_range':  {'first': yr['first_date'], 'last': yr['last_date']},
            'months':      months,
            'type_counts': type_counts,
            'file':        f'dynamics-{year_val}.json',
        })

        # Cache posts for this year (used by _generate_year_files)
        year_post_data[year_val] = db.execute("""
            SELECT p.*
            FROM posts p
            WHERE strftime('%Y', p.published_at) = ?
            ORDER BY p.published_at DESC
        """, (str(year_val),)).fetchall()

    # Assemble index document
    index_data = {
        'archive': {
            'name':             site_cfg.get('name', '岁己 SUI Archive'),
            'url':              site_cfg.get('url', 'https://archive.suijisui.uk'),
            'description':      site_cfg.get('description', ''),
            'target_platform':  'bilibili',
            'target_uid':       '1954091502',
        },
        'build': {
            'generated_at': datetime.now().isoformat(),
            'version':      '0.1.0',
            'total_posts':  total_posts,
            'total_images': total_images,
            'total_tags':   total_tags,
        },
        'years': years,
        'config': {
            'posts_per_page': posts_per_page,
        },
    }

    data_dir = os.path.join(output_dir, 'data')
    os.makedirs(data_dir, exist_ok=True)

    index_path = os.path.join(data_dir, 'dynamics-index.json')
    with open(index_path, 'w', encoding='utf-8') as fh:
        json.dump(index_data, fh, ensure_ascii=False, indent=2)

    logger.info(f'[json] Generated dynamics-index.json '
                f'({len(years)} years, {total_posts} posts)')
    return year_post_data


# ---------------------------------------------------------------------------
# dynamics-{year}.json
# ---------------------------------------------------------------------------

def _generate_year_files(db, config, output_dir, year_post_data, logger):
    """
    Generate one data/dynamics-{year}.json per year.

    Each file contains the list-view representation of every post
    published in that year: text preview, images, latest stats,
    repost flag, and tag slugs.
    """
    json_cfg = config.get('json', {})
    preview_len = json_cfg.get('text_preview_length', 200)
    data_dir = os.path.join(output_dir, 'data')

    for year_val, posts in year_post_data.items():
        post_list = []

        for post in posts:
            post_id = post['id']

            # Images via post_media → images (ordered by sort_order)
            images = db.execute("""
                SELECT i.filename, i.width, i.height, i.is_cover
                FROM post_media pm
                JOIN images i ON pm.image_id = i.id
                WHERE pm.post_id = ?
                ORDER BY pm.sort_order
            """, (post_id,)).fetchall()

            # Latest stats snapshot (CTE with MAX(snapshot_at) per post)
            stats_row = db.execute("""
                WITH latest AS (
                    SELECT post_id, MAX(snapshot_at) AS max_ts
                    FROM post_stats
                    WHERE post_id = ?
                    GROUP BY post_id
                )
                SELECT ps.likes, ps.comments, ps.forwards
                FROM post_stats ps
                JOIN latest ON ps.post_id = latest.post_id
                           AND ps.snapshot_at = latest.max_ts
            """, (post_id,)).fetchone()

            # Tag slugs
            tag_rows = db.execute("""
                SELECT t.slug
                FROM post_tags pt
                JOIN tags t ON pt.tag_id = t.id
                WHERE pt.post_id = ?
            """, (post_id,)).fetchall()

            # Repost author display name
            repost_author = None
            if post['post_type'] == 'repost' and post['original_author_id']:
                author_row = db.execute(
                    'SELECT display_name FROM authors WHERE id = ?',
                    (post['original_author_id'],),
                ).fetchone()
                if author_row:
                    repost_author = author_row['display_name']

            plain_text = post['plain_text'] or ''
            image_count = len(images)

            post_list.append({
                'uuid':             post['uuid'],
                'platform_post_id': post['platform_post_id'],
                'post_type':        post['post_type'],
                'published_at':     post['published_at'],
                'text_preview':     _truncate_text(plain_text, preview_len),
                'text_length':      len(plain_text),
                'has_images':       image_count > 0,
                'image_count':      image_count,
                'images': [
                    {
                        'filename': img['filename'],
                        'width':    img['width'],
                        'height':   img['height'],
                        'is_cover': bool(img['is_cover']),
                    }
                    for img in images
                ],
                'stats': {
                    'likes':    stats_row['likes']    if stats_row else 0,
                    'comments': stats_row['comments'] if stats_row else 0,
                    'forwards': stats_row['forwards'] if stats_row else 0,
                },
                'is_repost':      post['post_type'] == 'repost',
                'repost_author':  repost_author,
                'tags':           [t['slug'] for t in tag_rows],
            })

        year_data = {'year': year_val, 'posts': post_list}

        year_path = os.path.join(data_dir, f'dynamics-{year_val}.json')
        with open(year_path, 'w', encoding='utf-8') as fh:
            json.dump(year_data, fh, ensure_ascii=False, indent=2)

        logger.info(f'[json] Generated dynamics-{year_val}.json '
                    f'({len(post_list)} posts)')


# ---------------------------------------------------------------------------
# data/detail/{uuid}.json
# ---------------------------------------------------------------------------

def _generate_detail_files(db, config, output_dir, logger):
    """
    Generate one data/detail/{uuid}.json per post.

    Contains the full data payload: complete plain_text, all images
    with file_size and mime_type, full latest stats, repost info
    with author details, tags with color, and prev/next navigation.
    """
    detail_dir = os.path.join(output_dir, 'data', 'detail')
    os.makedirs(detail_dir, exist_ok=True)

    # Fetch all posts ordered chronologically for prev/next computation
    all_posts = db.execute(
        'SELECT * FROM posts ORDER BY published_at ASC'
    ).fetchall()

    # Build index arrays for prev/next lookup
    uuid_list  = [p['uuid'] for p in all_posts]
    uuid_index = {uuid: i for i, uuid in enumerate(uuid_list)}

    count = 0
    for post in all_posts:
        post_id = post['id']
        idx     = uuid_index[post['uuid']]

        prev_uuid = uuid_list[idx - 1] if idx > 0 else None
        next_uuid = (uuid_list[idx + 1]
                     if idx < len(uuid_list) - 1 else None)

        # Platform display name
        platform = db.execute(
            'SELECT display_name FROM platforms WHERE id = ?',
            (post['platform_id'],),
        ).fetchone()

        # Images with full metadata (via post_media → images)
        images = db.execute("""
            SELECT i.filename, i.width, i.height, i.file_size,
                   i.mime_type, i.is_cover, pm.is_repost_media
            FROM post_media pm
            JOIN images i ON pm.image_id = i.id
            WHERE pm.post_id = ?
            ORDER BY pm.sort_order
        """, (post_id,)).fetchall()

        # Latest stats snapshot
        stats_row = db.execute("""
            WITH latest AS (
                SELECT post_id, MAX(snapshot_at) AS max_ts
                FROM post_stats
                WHERE post_id = ?
                GROUP BY post_id
            )
            SELECT ps.likes, ps.comments, ps.forwards, ps.views
            FROM post_stats ps
            JOIN latest ON ps.post_id = latest.post_id
                       AND ps.snapshot_at = latest.max_ts
        """, (post_id,)).fetchone()

        # Tags with color
        tag_rows = db.execute("""
            SELECT t.name, t.slug, t.color
            FROM post_tags pt
            JOIN tags t ON pt.tag_id = t.id
            WHERE pt.post_id = ?
        """, (post_id,)).fetchall()

        # Repost sub-object (author + original text/URL)
        repost_info = _get_repost_info(db, post)

        detail = {
            'uuid':             post['uuid'],
            'platform_post_id': post['platform_post_id'],
            'platform_name':    platform['display_name'] if platform else None,
            'post_type':        post['post_type'],
            'published_at':     post['published_at'],
            'source_url':       post['source_url'],
            'plain_text':       post['plain_text'],
            'images': [
                {
                    'filename':        img['filename'],
                    'width':           img['width'],
                    'height':          img['height'],
                    'file_size':       img['file_size'],
                    'mime_type':       img['mime_type'],
                    'is_cover':        bool(img['is_cover']),
                    'is_repost_media': bool(img['is_repost_media']),
                }
                for img in images
            ],
            'stats': {
                'likes':    stats_row['likes']    if stats_row else 0,
                'comments': stats_row['comments'] if stats_row else 0,
                'forwards': stats_row['forwards'] if stats_row else 0,
                'views':    stats_row['views']    if stats_row else None,
            },
            'is_repost': post['post_type'] == 'repost',
            'repost':    repost_info,
            'tags': [
                {
                    'name':  t['name'],
                    'slug':  t['slug'],
                    'color': t['color'],
                }
                for t in tag_rows
            ],
            'related': {
                'prev_uuid': prev_uuid,
                'next_uuid': next_uuid,
            },
        }

        detail_path = os.path.join(detail_dir, f"{post['uuid']}.json")
        with open(detail_path, 'w', encoding='utf-8') as fh:
            json.dump(detail, fh, ensure_ascii=False, indent=2)
        count += 1

    logger.info(f'[json] Generated {count} detail JSON files')


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def run(db, config, output_dir, logger):
    """
    Generate all JSON data files.

    Args:
        db:         sqlite3.Connection with row_factory=sqlite3.Row.
        config:     dict loaded from config.yaml.
        output_dir: path to build output directory.
        logger:     logging.Logger instance.
    """
    logger.info('[json] Starting JSON generation ...')

    data_dir   = os.path.join(output_dir, 'data')
    detail_dir = os.path.join(data_dir, 'detail')
    os.makedirs(data_dir,   exist_ok=True)
    os.makedirs(detail_dir, exist_ok=True)

    # Step 1 — index (also pre-fetches posts per year for step 2)
    year_post_data = _generate_index(db, config, output_dir, logger)

    # Step 2 — per-year files
    _generate_year_files(db, config, output_dir, year_post_data, logger)

    # Step 3 — per-post detail files
    _generate_detail_files(db, config, output_dir, logger)

    logger.info('[json] JSON generation complete')
