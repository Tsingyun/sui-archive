"""
Build Step: sitemap_gen (Step 4)
Generates SEO files from SQLite:
  - sitemap.xml   (standard XML Sitemap 1.0)
  - robots.txt    (crawler access rules)
"""

import os
import xml.etree.ElementTree as ET
from datetime import datetime


# Sitemap XML namespace (per sitemaps.org protocol)
SITEMAP_NS = 'http://www.sitemaps.org/schemas/sitemap/0.9'

# Static pages: (path, changefreq, priority)
STATIC_PAGES = [
    ('/',         'daily',   1.0),
    ('/search',   'monthly', 0.6),
    ('/gallery',  'weekly',  0.8),
    ('/timeline', 'monthly', 0.7),
    ('/stats',    'weekly',  0.5),
    ('/tags',     'weekly',  0.6),
    ('/about',    'yearly',  0.3),
]


def _add_url(urlset, site_url, loc, changefreq, priority, lastmod=None):
    """Append a single <url> element to the <urlset> root."""
    url_el = ET.SubElement(urlset, 'url')
    ET.SubElement(url_el, 'loc').text        = site_url.rstrip('/') + loc
    ET.SubElement(url_el, 'changefreq').text  = changefreq
    ET.SubElement(url_el, 'priority').text    = f'{priority:.1f}'
    if lastmod:
        ET.SubElement(url_el, 'lastmod').text = lastmod[:10]


# ---------------------------------------------------------------------------
# sitemap.xml
# ---------------------------------------------------------------------------

def _generate_sitemap(db, config, output_dir, logger):
    """
    Generate sitemap.xml.

    URL categories:
      - Homepage          (1 URL,   priority 1.0, daily)
      - Static pages      (6 URLs,  various priorities)
      - Detail pages      (~N URLs, priority 0.8, never)
      - Tag pages         (~M URLs, priority 0.5, weekly)
    """
    site_cfg  = config.get('site', {})
    site_url  = site_cfg.get('url', 'https://archive.suijisui.uk')

    # Register default namespace so ElementTree emits clean XML
    ET.register_namespace('', SITEMAP_NS)
    urlset = ET.Element('urlset', xmlns=SITEMAP_NS)

    today = datetime.now().strftime('%Y-%m-%d')

    # --- Static pages ---
    for path, changefreq, priority in STATIC_PAGES:
        _add_url(urlset, site_url, path, changefreq, priority,
                 lastmod=today if path == '/' else None)

    # --- Dynamic detail pages  /d/{platform_post_id} ---
    posts = db.execute(
        'SELECT platform_post_id, published_at '
        'FROM posts ORDER BY published_at DESC'
    ).fetchall()

    for post in posts:
        _add_url(
            urlset, site_url,
            f"/d/{post['platform_post_id']}",
            'never', 0.8,
            lastmod=post['published_at'],
        )

    # --- Tag pages  /tag/{slug} ---
    tags = db.execute("""
        SELECT t.slug, MAX(DATE(p.published_at)) AS latest
        FROM tags t
        LEFT JOIN post_tags pt ON t.id = pt.tag_id
        LEFT JOIN posts       p  ON pt.post_id = p.id
        GROUP BY t.id
    """).fetchall()

    for tag in tags:
        _add_url(
            urlset, site_url,
            f"/tag/{tag['slug']}",
            'weekly', 0.5,
            lastmod=tag['latest'],
        )

    # Write with proper XML declaration
    tree = ET.ElementTree(urlset)
    sitemap_path = os.path.join(output_dir, 'sitemap.xml')
    tree.write(sitemap_path, encoding='UTF-8', xml_declaration=True)

    total_urls = 1 + len(posts) + len(tags) + (len(STATIC_PAGES) - 1)
    logger.info(f'[sitemap] Generated sitemap.xml ({total_urls} URLs: '
                f'{len(STATIC_PAGES)} static, '
                f'{len(posts)} detail, '
                f'{len(tags)} tag)')


# ---------------------------------------------------------------------------
# robots.txt
# ---------------------------------------------------------------------------

def _generate_robots(db, config, output_dir, logger):
    """
    Generate robots.txt.

    Rules (from BUILD_SPEC 7.2):
      - Allow everything by default
      - Point to the sitemap
      - Disallow /data/ (JSON API files, not user-facing content)
      - Disallow /build-info.json (build metadata)
    """
    site_cfg  = config.get('site', {})
    site_url  = site_cfg.get('url', 'https://archive.suijisui.uk')

    robots_content = (
        'User-agent: *\n'
        'Allow: /\n'
        f'Sitemap: {site_url.rstrip("/")}/sitemap.xml\n'
        '\n'
        'Disallow: /data/\n'
        'Disallow: /build-info.json\n'
    )

    robots_path = os.path.join(output_dir, 'robots.txt')
    with open(robots_path, 'w', encoding='utf-8') as fh:
        fh.write(robots_content)

    logger.info('[sitemap] Generated robots.txt')


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def run(db, config, output_dir, logger):
    """
    Generate sitemap.xml and robots.txt.

    Args:
        db:         sqlite3.Connection with row_factory=sqlite3.Row.
        config:     dict loaded from config.yaml.
        output_dir: path to build output directory.
        logger:     logging.Logger instance.
    """
    logger.info('[sitemap] Starting SEO file generation ...')

    os.makedirs(output_dir, exist_ok=True)

    _generate_sitemap(db, config, output_dir, logger)
    _generate_robots(db, config, output_dir, logger)

    logger.info('[sitemap] SEO file generation complete')
