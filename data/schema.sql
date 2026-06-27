-- ============================================================================
-- SUI Archive — SQLite Database Schema
-- Version: 1.0.0 (initial_schema)
-- Generated from DATABASE_SPEC.md
-- ============================================================================

-- --------------------------------------------------------------------------
-- PRAGMA Configuration
-- These must be set on every connection. foreign_keys is per-connection,
-- journal_mode persists in the database file header.
-- --------------------------------------------------------------------------
PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;

-- ==========================================================================
-- 1. platforms — Platform Registry
-- Records all data-source platforms. One row per platform.
-- Currently only Bilibili.
-- ==========================================================================
CREATE TABLE platforms (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    key          TEXT    NOT NULL,                   -- Platform identifier, lowercase (e.g. 'bilibili', 'weibo')
    display_name TEXT    NOT NULL,                   -- Display name (e.g. '哔哩哔哩')
    home_url     TEXT,                               -- Platform homepage URL
    icon_url     TEXT,                               -- Platform icon URL
    config       TEXT,                               -- JSON, platform-level configuration (API endpoints, auth, etc.)
    created_at   TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP,  -- Record creation time (ISO 8601)

    UNIQUE(key)
);

CREATE INDEX idx_platforms_key ON platforms(key);

-- ==========================================================================
-- 2. authors — Content Authors
-- Tracks original authors of reposted content. The main account (SUI) is
-- stored in platforms.config, not here. This table is for "who posted the
-- original content that SUI reposted".
-- ==========================================================================
CREATE TABLE authors (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    platform_id      INTEGER NOT NULL,               -- FK -> platforms.id
    platform_user_id TEXT,                           -- User ID on the platform (e.g. Bilibili mid)
    display_name     TEXT    NOT NULL,               -- Display name
    profile_url      TEXT,                           -- Profile page URL
    avatar_url       TEXT,                           -- Avatar URL
    bio              TEXT,                           -- Biography / description
    created_at       TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP,  -- First discovered time (ISO 8601)
    updated_at       TEXT,                           -- Last updated time (ISO 8601)

    UNIQUE(platform_id, platform_user_id),
    FOREIGN KEY(platform_id) REFERENCES platforms(id)
);

CREATE INDEX idx_authors_platform ON authors(platform_id, platform_user_id);
CREATE INDEX idx_authors_name ON authors(display_name);

-- ==========================================================================
-- 3. posts — Main Posts Table
-- Stores all posts from all platforms. This is the core table of the entire
-- database.
-- ==========================================================================
CREATE TABLE posts (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    uuid                TEXT    NOT NULL,            -- v4 UUID, external reference identifier
    platform_id         INTEGER NOT NULL,            -- FK -> platforms.id
    platform_post_id    TEXT    NOT NULL,            -- Original platform post ID (e.g. Bilibili dynamic_id)
    post_type           TEXT    NOT NULL,            -- Universal type enum: text|image|video|audio|article|live|repost|mixed
    platform_post_type  TEXT,                        -- Original platform type string (e.g. 'DYNAMIC_TYPE_DRAW')
    published_at        TEXT    NOT NULL,            -- Publish time, ISO 8601
    archived_at         TEXT    NOT NULL,            -- Archive ingestion time, ISO 8601
    source_url          TEXT,                        -- Original link (e.g. 'https://t.bilibili.com/{id}')
    plain_text          TEXT,                        -- Plain text content; Bilibili emojis shown as '[emoji_name]'
    rich_text           TEXT,                        -- JSON, structured rich text node array (reserved)
    language            TEXT             DEFAULT 'zh-CN',  -- Content language, BCP 47 format
    repost_of_id        INTEGER,                    -- FK -> posts.id, the original post being reposted (if in DB)
    repost_snapshot     TEXT,                        -- JSON, snapshot of original post (if deleted or not in DB)
    original_author_id  INTEGER,                    -- FK -> authors.id, author of the reposted original
    platform_metadata   TEXT,                        -- JSON, platform-specific fields
    is_pinned           INTEGER NOT NULL DEFAULT 0,  -- Whether pinned/featured
    is_deleted          INTEGER NOT NULL DEFAULT 0,  -- Whether deleted from the source platform
    schema_version      INTEGER NOT NULL DEFAULT 1,  -- Row-level schema version

    UNIQUE(platform_id, platform_post_id),
    UNIQUE(uuid),
    FOREIGN KEY(platform_id)        REFERENCES platforms(id),
    FOREIGN KEY(repost_of_id)       REFERENCES posts(id)   ON DELETE SET NULL,
    FOREIGN KEY(original_author_id) REFERENCES authors(id) ON DELETE SET NULL,
    CHECK(post_type IN ('text','image','video','audio','article','live','repost','mixed')),
    CHECK(is_pinned  IN (0, 1)),
    CHECK(is_deleted IN (0, 1))
);

CREATE INDEX idx_posts_published   ON posts(published_at DESC);
CREATE INDEX idx_posts_platform    ON posts(platform_id);
CREATE INDEX idx_posts_type        ON posts(post_type);
CREATE INDEX idx_posts_repost_of   ON posts(repost_of_id)       WHERE repost_of_id IS NOT NULL;
CREATE INDEX idx_posts_author      ON posts(original_author_id)  WHERE original_author_id IS NOT NULL;
CREATE INDEX idx_posts_platform_id ON posts(platform_id, platform_post_id);

-- ==========================================================================
-- 4. images — Image Table
-- Stores metadata for all image files. Each image is one row, linked to
-- posts via the post_media association table.
-- ==========================================================================
CREATE TABLE images (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    uuid            TEXT    NOT NULL,                -- v4 UUID, external reference identifier
    filename        TEXT    NOT NULL,                -- Disk filename (e.g. '1210001435340570626_00@original.png')
    storage_path    TEXT    NOT NULL,                -- Relative path (e.g. 'images/121000...@original.png')
    sha256          TEXT,                            -- File SHA-256 hash (deduplication & integrity)
    file_size       INTEGER,                        -- File size in bytes
    width           INTEGER,                        -- Image width in pixels
    height          INTEGER,                        -- Image height in pixels
    mime_type       TEXT,                            -- MIME type (e.g. 'image/png')
    quality         TEXT    NOT NULL DEFAULT 'original',  -- Quality label: original | thumbnail | repost
    source_url      TEXT,                            -- Original CDN URL (provenance)
    is_cover        INTEGER NOT NULL DEFAULT 0,     -- Whether this is the cover image of its parent post
    is_deleted      INTEGER NOT NULL DEFAULT 0,     -- Whether the file has been deleted from disk
    perceptual_hash TEXT,                            -- Perceptual hash (similar image detection, reserved)
    exif_data       TEXT,                            -- JSON, EXIF metadata (reserved)
    archived_at     TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP,  -- Ingestion time (ISO 8601)

    UNIQUE(filename),
    UNIQUE(uuid),
    UNIQUE(sha256),
    CHECK(quality   IN ('original', 'thumbnail', 'repost')),
    CHECK(is_cover  IN (0, 1)),
    CHECK(is_deleted IN (0, 1))
);

CREATE INDEX idx_images_filename ON images(filename);
CREATE INDEX idx_images_sha256   ON images(sha256) WHERE sha256 IS NOT NULL;
CREATE INDEX idx_images_quality  ON images(quality);

-- ==========================================================================
-- 5. media — General Media Table
-- Stores media types beyond images (video, audio, GIF, etc.). Currently
-- empty; structure pre-built for future use.
-- ==========================================================================
CREATE TABLE media (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    uuid               TEXT    NOT NULL,             -- v4 UUID
    media_type         TEXT    NOT NULL,             -- Type enum: video|audio|gif|live_photo|document
    filename           TEXT    NOT NULL,             -- Disk filename
    storage_path       TEXT    NOT NULL,             -- Relative path
    sha256             TEXT,                         -- SHA-256 hash
    file_size          INTEGER,                     -- File size in bytes
    mime_type          TEXT,                         -- MIME type
    duration_ms        INTEGER,                     -- Duration in milliseconds (video/audio)
    width              INTEGER,                     -- Width in pixels (video)
    height             INTEGER,                     -- Height in pixels (video)
    thumbnail_image_id INTEGER,                     -- FK -> images.id, thumbnail reference
    source_url         TEXT,                         -- Original URL
    platform_metadata  TEXT,                         -- JSON, platform-specific fields
    archived_at        TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP,  -- Ingestion time (ISO 8601)

    UNIQUE(filename),
    UNIQUE(uuid),
    UNIQUE(sha256),
    FOREIGN KEY(thumbnail_image_id) REFERENCES images(id) ON DELETE SET NULL,
    CHECK(media_type IN ('video', 'audio', 'gif', 'live_photo', 'document'))
);

CREATE INDEX idx_media_type     ON media(media_type);
CREATE INDEX idx_media_filename ON media(filename);

-- ==========================================================================
-- 6. tags — Tag Definitions
-- Stores tag definitions for post classification and retrieval.
-- ==========================================================================
CREATE TABLE tags (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    uuid          TEXT    NOT NULL,                  -- v4 UUID
    name          TEXT    NOT NULL,                  -- Tag name (primary display language, Chinese)
    slug          TEXT    NOT NULL,                  -- URL-friendly identifier (e.g. 'singing-clip')
    display_names TEXT,                              -- JSON, multilingual names {"zh":"翻唱","en":"Cover"}
    category      TEXT,                              -- Tag category (e.g. 'content', 'topic', 'emotion', 'character')
    parent_id     INTEGER,                          -- FK -> tags.id, parent tag (hierarchical)
    description   TEXT,                              -- Tag description
    color         TEXT,                              -- Display color HEX (e.g. '#00C8FF')
    sort_order    INTEGER NOT NULL DEFAULT 0,        -- Sort weight
    created_at    TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP,  -- Creation time (ISO 8601)

    UNIQUE(name),
    UNIQUE(slug),
    UNIQUE(uuid),
    FOREIGN KEY(parent_id) REFERENCES tags(id) ON DELETE SET NULL
);

CREATE INDEX idx_tags_slug     ON tags(slug);
CREATE INDEX idx_tags_category ON tags(category)  WHERE category IS NOT NULL;
CREATE INDEX idx_tags_parent   ON tags(parent_id) WHERE parent_id IS NOT NULL;

-- ==========================================================================
-- 7. post_tags — Post-Tag Association
-- Many-to-many junction table. A post can have multiple tags; a tag can
-- be applied to multiple posts.
-- ==========================================================================
CREATE TABLE post_tags (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    post_id   INTEGER NOT NULL,                     -- FK -> posts.id
    tag_id    INTEGER NOT NULL,                     -- FK -> tags.id
    tagged_at TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP,  -- Tagging time (ISO 8601)

    UNIQUE(post_id, tag_id),
    FOREIGN KEY(post_id) REFERENCES posts(id) ON DELETE CASCADE,
    FOREIGN KEY(tag_id)  REFERENCES tags(id)  ON DELETE CASCADE
);

CREATE INDEX idx_post_tags_post ON post_tags(post_id);
CREATE INDEX idx_post_tags_tag  ON post_tags(tag_id);

-- ==========================================================================
-- 8. post_media — Post-Media Association
-- Many-to-many junction table. Links images and general media to posts.
-- A post can contain multiple images; an image can theoretically be
-- referenced by multiple posts (e.g. deduplication scenarios).
-- ==========================================================================
CREATE TABLE post_media (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    post_id         INTEGER NOT NULL,               -- FK -> posts.id
    image_id        INTEGER,                        -- FK -> images.id, associated image
    media_id        INTEGER,                        -- FK -> media.id, associated other media
    sort_order      INTEGER NOT NULL DEFAULT 0,     -- Display order within the post (0-based)
    is_repost_media INTEGER NOT NULL DEFAULT 0,     -- Whether this media belongs to reposted content (not original)

    UNIQUE(post_id, image_id),
    UNIQUE(post_id, media_id),
    FOREIGN KEY(post_id)  REFERENCES posts(id)  ON DELETE CASCADE,
    FOREIGN KEY(image_id) REFERENCES images(id) ON DELETE CASCADE,
    FOREIGN KEY(media_id) REFERENCES media(id)  ON DELETE CASCADE,
    CHECK(image_id IS NOT NULL OR media_id IS NOT NULL)
);

CREATE INDEX idx_post_media_post  ON post_media(post_id);
CREATE INDEX idx_post_media_image ON post_media(image_id) WHERE image_id IS NOT NULL;
CREATE INDEX idx_post_media_media ON post_media(media_id) WHERE media_id IS NOT NULL;

-- ==========================================================================
-- 9. post_stats — Post Interaction Statistics
-- Time-series snapshots of engagement data. A single post can have
-- multiple snapshots taken at different times to track data changes.
-- ==========================================================================
CREATE TABLE post_stats (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    post_id     INTEGER NOT NULL,                   -- FK -> posts.id
    views       INTEGER,                            -- View count (NULL when unavailable from API)
    likes       INTEGER NOT NULL DEFAULT 0,         -- Like count
    comments    INTEGER NOT NULL DEFAULT 0,         -- Comment count
    forwards    INTEGER NOT NULL DEFAULT 0,         -- Forward/repost count
    snapshot_at TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP,  -- Snapshot capture time (ISO 8601)

    FOREIGN KEY(post_id) REFERENCES posts(id) ON DELETE CASCADE
);

CREATE INDEX idx_post_stats_post ON post_stats(post_id, snapshot_at DESC);
CREATE INDEX idx_post_stats_time ON post_stats(snapshot_at);

-- ==========================================================================
-- 10. posts_fts — Full-Text Search Virtual Table (FTS5)
-- Provides full-text search over post content using SQLite FTS5 extension.
-- Synchronized with the posts table via triggers below.
-- Uses unicode61 tokenizer as baseline; upgrade to ICU tokenizer if the
-- deployment environment supports it.
-- ==========================================================================
CREATE VIRTUAL TABLE posts_fts USING fts5(
    plain_text,
    repost_snapshot,
    post_type,
    language,
    content       = "posts",
    content_rowid = "id",
    tokenize      = "unicode61"
);

-- Trigger: sync FTS index after a new post is inserted
CREATE TRIGGER fts_ai_post_insert AFTER INSERT ON posts BEGIN
    INSERT INTO posts_fts(rowid, plain_text, repost_snapshot, post_type, language)
    VALUES (NEW.id, NEW.plain_text, NEW.repost_snapshot, NEW.post_type, NEW.language);
END;

-- Trigger: sync FTS index after a post is updated
CREATE TRIGGER fts_ai_post_update AFTER UPDATE ON posts BEGIN
    INSERT INTO posts_fts(posts_fts, rowid, plain_text, repost_snapshot, post_type, language)
    VALUES ('delete', OLD.id, OLD.plain_text, OLD.repost_snapshot, OLD.post_type, OLD.language);
    INSERT INTO posts_fts(rowid, plain_text, repost_snapshot, post_type, language)
    VALUES (NEW.id, NEW.plain_text, NEW.repost_snapshot, NEW.post_type, NEW.language);
END;

-- Trigger: sync FTS index after a post is deleted
CREATE TRIGGER fts_ai_post_delete AFTER DELETE ON posts BEGIN
    INSERT INTO posts_fts(posts_fts, rowid, plain_text, repost_snapshot, post_type, language)
    VALUES ('delete', OLD.id, OLD.plain_text, OLD.repost_snapshot, OLD.post_type, OLD.language);
END;

-- ==========================================================================
-- 11. schema_migrations — Schema Version Management
-- Records all database structure changes. Each migration appends one row.
-- ==========================================================================
CREATE TABLE schema_migrations (
    version     INTEGER PRIMARY KEY,                -- Version number, incrementing from 1
    name        TEXT    NOT NULL,                   -- Migration name (e.g. 'initial_schema')
    description TEXT,                               -- Change description
    applied_at  TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP,  -- Application time (ISO 8601)
    checksum    TEXT,                               -- SHA-256 of the migration script (tamper detection)

    UNIQUE(version)
);

-- ==========================================================================
-- Initial Data
-- ==========================================================================

-- Record the initial schema migration
INSERT INTO schema_migrations (version, name, description)
VALUES (1, 'initial_schema', 'Initial database schema with 11 tables, 3 FTS triggers, and all indexes.');

-- Register the Bilibili platform (the sole data source at launch)
INSERT INTO platforms (key, display_name, home_url)
VALUES ('bilibili', '哔哩哔哩', 'https://www.bilibili.com');
