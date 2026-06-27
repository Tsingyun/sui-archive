"""
Build Step: validate (Step 0)
Validates database health before build begins.
Fast-fail principle — abort build if data source is unhealthy.
"""

import os


# All 11 tables defined in the database schema (DATABASE_SPEC section 4)
ALL_TABLES = [
    'platforms', 'authors', 'posts', 'images', 'media',
    'tags', 'post_tags', 'post_media', 'post_stats',
    'posts_fts', 'schema_migrations',
]


def run(db, config, output_dir, logger):
    """
    Run all database validation checks.

    Args:
        db:         sqlite3.Connection with row_factory=sqlite3.Row.
                    WAL mode and foreign_keys already enabled.
        config:     dict loaded from config.yaml.
        output_dir: path to build output directory (unused by validate).
        logger:     logging.Logger instance.

    Raises:
        RuntimeError: on any fatal validation failure.
    """
    errors = []
    warnings = []

    # ------------------------------------------------------------------
    # 1. PRAGMA integrity_check  (fatal on failure)
    # ------------------------------------------------------------------
    logger.info('[validate] Running PRAGMA integrity_check ...')
    result = db.execute('PRAGMA integrity_check').fetchone()
    integrity_value = result[0] if result else None
    if integrity_value != 'ok':
        msg = f'Database integrity check FAILED: {integrity_value}'
        logger.error(msg)
        errors.append(msg)
    else:
        logger.info('[validate] Integrity check: ok')

    # ------------------------------------------------------------------
    # 2. PRAGMA foreign_key_check  (warn only, do not abort)
    # ------------------------------------------------------------------
    logger.info('[validate] Running PRAGMA foreign_key_check ...')
    fk_issues = db.execute('PRAGMA foreign_key_check').fetchall()
    if fk_issues:
        msg = f'Foreign key check found {len(fk_issues)} issue(s):'
        logger.warning(msg)
        for issue in fk_issues[:20]:
            logger.warning(f'  table={issue["table"]}, rowid={issue["rowid"]}, '
                           f'parent={issue["parent"]}, fkid={issue["fkid"]}')
        if len(fk_issues) > 20:
            logger.warning(f'  ... and {len(fk_issues) - 20} more')
        warnings.append(msg)
    else:
        logger.info('[validate] Foreign key check: ok')

    # ------------------------------------------------------------------
    # 3. Schema version check  (fatal — must have at least version 1)
    # ------------------------------------------------------------------
    logger.info('[validate] Checking schema_migrations ...')
    try:
        row = db.execute(
            'SELECT MAX(version) AS max_ver FROM schema_migrations'
        ).fetchone()
        max_ver = row['max_ver'] if row else None
        if max_ver is None or max_ver < 1:
            msg = (f'schema_migrations: expected version >= 1, '
                   f'found {max_ver}. Run migration scripts first.')
            logger.error(msg)
            errors.append(msg)
        else:
            logger.info(f'[validate] Schema version: {max_ver}')
    except Exception as e:
        msg = f'schema_migrations table missing or unreadable: {e}'
        logger.error(msg)
        errors.append(msg)

    # ------------------------------------------------------------------
    # 4. Posts table non-empty check  (fatal)
    # ------------------------------------------------------------------
    logger.info('[validate] Checking posts table ...')
    post_count = db.execute('SELECT COUNT(*) AS cnt FROM posts').fetchone()['cnt']
    if post_count == 0:
        msg = 'posts table is empty. Run the import script first.'
        logger.error(msg)
        errors.append(msg)
    else:
        logger.info(f'[validate] Posts table: {post_count} rows')

    # ------------------------------------------------------------------
    # 5. Image file spot check  (warn only)
    #    Pick 10 random image rows, verify files exist on disk.
    # ------------------------------------------------------------------
    logger.info('[validate] Spot-checking image files ...')
    sample_rows = db.execute(
        'SELECT filename, storage_path FROM images '
        'ORDER BY RANDOM() LIMIT 10'
    ).fetchall()

    if not sample_rows:
        logger.info('[validate] No images in database, skipping file spot check')
    else:
        found_count = 0
        missing_count = 0
        for img in sample_rows:
            # storage_path is relative (e.g. "images/xxx.png").
            # Resolve against project root (parent of the build/ directory).
            file_path = os.path.join(
                os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
                img['storage_path'],
            )
            if os.path.exists(file_path):
                found_count += 1
            else:
                missing_count += 1
                logger.warning(f'  Missing image file: {img["filename"]} '
                               f'(expected at {file_path})')

        logger.info(f'[validate] Image spot check: '
                     f'{found_count} found, {missing_count} missing '
                     f'(out of {len(sample_rows)} sampled)')
        if missing_count > 0:
            warnings.append(
                f'{missing_count} of {len(sample_rows)} sampled image files missing'
            )

    # ------------------------------------------------------------------
    # 6. Table row count summary
    # ------------------------------------------------------------------
    logger.info('[validate] Table row counts:')
    for table_name in ALL_TABLES:
        try:
            count = db.execute(
                f'SELECT COUNT(*) AS cnt FROM "{table_name}"'
            ).fetchone()['cnt']
            logger.info(f'  {table_name:25s} {count:>8,}')
        except Exception as exc:
            logger.warning(f'  {table_name:25s} ERROR: {exc}')

    # ------------------------------------------------------------------
    # Final summary — abort if any fatal errors
    # ------------------------------------------------------------------
    if errors:
        summary = (f'Validation FAILED with {len(errors)} error(s) '
                   f'and {len(warnings)} warning(s)')
        logger.error(f'[validate] {summary}')
        raise RuntimeError(summary)

    if warnings:
        logger.warning(f'[validate] Validation passed with '
                       f'{len(warnings)} warning(s)')
    else:
        logger.info('[validate] All validation checks passed')
