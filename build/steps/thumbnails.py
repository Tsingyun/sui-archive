"""
Step 5: thumbnails — Image thumbnail generation.

Scans the images/ directory, generates WebP thumbnail variants for each image,
handles GIF poster frames, updates the images table metadata, and produces
an images-manifest.json file.
"""

import json
import os
import mimetypes
from pathlib import Path

try:
    from PIL import Image
except ImportError:
    Image = None


def run(db, config, output_dir, logger):
    """Generate thumbnail variants for all images in the archive.

    Args:
        db: sqlite3.Connection with row_factory=Row.
        config: dict from config.yaml.
        output_dir: Path to the build output directory (deploy/ or _build/).
        logger: Logger with .step()/.info()/.warn()/.success() methods.
    """
    logger.step("Step 5: thumbnails — Generating image thumbnails")

    if Image is None:
        logger.warn("Pillow (PIL) is not installed. Skipping thumbnail generation.")
        logger.warn("Install with: pip install Pillow")
        return

    thumb_config = config.get("thumbnails", {})
    if not thumb_config.get("enabled", True):
        logger.info("Thumbnail generation disabled in config. Skipping.")
        return

    variants = thumb_config.get("variants", [
        {"width": 300, "suffix": "w300"},
        {"width": 600, "suffix": "w600"},
        {"width": 1200, "suffix": "w1200"},
    ])
    fmt = thumb_config.get("format", "webp")
    quality = thumb_config.get("quality", 80)
    gif_poster_enabled = thumb_config.get("gif_poster", True)
    gif_poster_width = thumb_config.get("gif_poster_width", 600)
    incremental = config.get("_incremental", False)

    # Resolve project root (injected by build.py)
    project_root = Path(config.get("_project_root", "."))
    images_dir = project_root / "images"
    thumbs_dir = project_root / "thumbs"
    thumbs_dir.mkdir(parents=True, exist_ok=True)

    if not images_dir.is_dir():
        logger.warn(f"Images directory not found: {images_dir}")
        logger.warn("Skipping thumbnail generation.")
        return

    # Query all images from the database
    rows = db.execute(
        "SELECT id, uuid, filename, storage_path, width, height, file_size, mime_type "
        "FROM images WHERE is_deleted = 0 ORDER BY id"
    ).fetchall()

    total_generated = 0
    total_skipped = 0
    total_errors = 0
    manifest_entries = []
    updates_needed = []

    for row in rows:
        img_id = row["id"]
        filename = row["filename"]
        db_width = row["width"]
        db_height = row["height"]
        db_file_size = row["file_size"]
        db_mime_type = row["mime_type"]

        # Resolve the original file path
        src_path = images_dir / filename
        if not src_path.is_file():
            total_skipped += 1
            continue

        # Open the image to get dimensions if not in DB
        try:
            with Image.open(src_path) as img:
                orig_width, orig_height = img.size
                orig_format = img.format or _guess_format(filename)
        except Exception as e:
            logger.warn(f"Cannot open image {filename}: {e}")
            total_errors += 1
            continue

        # Determine MIME type
        mime_type = db_mime_type or mimetypes.guess_type(filename)[0] or f"image/{orig_format.lower()}"

        # Queue DB update for NULL metadata fields
        update_fields = {}
        if db_width is None:
            update_fields["width"] = orig_width
        if db_height is None:
            update_fields["height"] = orig_height
        if db_file_size is None:
            try:
                update_fields["file_size"] = src_path.stat().st_size
            except OSError:
                pass
        if db_mime_type is None:
            update_fields["mime_type"] = mime_type

        if update_fields:
            updates_needed.append((img_id, update_fields))

        # Use DB values if available, otherwise use what we just read
        actual_width = db_width if db_width is not None else orig_width
        actual_height = db_height if db_height is not None else orig_height

        # Build the base name (without extension) for thumbnail naming
        name_stem = Path(filename).stem  # e.g. "1210001435340570626_00@original"

        # Track which variants are generated for this image
        generated_variants = []
        is_gif = orig_format.upper() == "GIF" or filename.lower().endswith(".gif")

        # Check incremental mode: skip if all thumbnails already exist and are newer
        if incremental:
            all_exist = True
            src_mtime = src_path.stat().st_mtime
            for v in variants:
                thumb_name = f"{name_stem}_{v['suffix']}.{fmt}"
                thumb_path = thumbs_dir / thumb_name
                if not thumb_path.is_file() or thumb_path.stat().st_mtime < src_mtime:
                    all_exist = False
                    break
            if is_gif and gif_poster_enabled and all_exist:
                poster_name = f"{name_stem}_poster.{fmt}"
                poster_path = thumbs_dir / poster_name
                if not poster_path.is_file() or poster_path.stat().st_mtime < src_mtime:
                    all_exist = False
            if all_exist:
                total_skipped += 1
                # Still add to manifest
                for v in variants:
                    if actual_width > v["width"]:
                        generated_variants.append(v["suffix"])
                if is_gif and gif_poster_enabled:
                    generated_variants.append("poster")
                manifest_entries.append({
                    "filename": filename,
                    "width": actual_width,
                    "height": actual_height,
                    "variants": generated_variants,
                    "is_gif": is_gif,
                })
                continue

        # Generate thumbnail variants
        for v in variants:
            target_width = v["width"]
            suffix = v["suffix"]

            # Skip if original is smaller than target (don't upscale)
            if actual_width <= target_width:
                continue

            thumb_name = f"{name_stem}_{suffix}.{fmt}"
            thumb_path = thumbs_dir / thumb_name

            try:
                with Image.open(src_path) as img:
                    # Convert to RGB if necessary (for WebP from palette/mode issues)
                    if img.mode in ("P", "LA"):
                        img = img.convert("RGBA")
                    elif img.mode not in ("RGB", "RGBA"):
                        img = img.convert("RGB")

                    # Calculate new height maintaining aspect ratio
                    ratio = target_width / orig_width
                    target_height = max(1, int(orig_height * ratio))

                    resized = img.resize((target_width, target_height), Image.LANCZOS)
                    resized.save(thumb_path, format=fmt.upper(), quality=quality)
                    total_generated += 1
                    generated_variants.append(suffix)
            except Exception as e:
                logger.warn(f"Failed to generate {thumb_name}: {e}")
                total_errors += 1

        # Generate GIF poster frame
        if is_gif and gif_poster_enabled:
            poster_name = f"{name_stem}_poster.{fmt}"
            poster_path = thumbs_dir / poster_name

            try:
                with Image.open(src_path) as img:
                    # Seek to first frame
                    img.seek(0)
                    if img.mode in ("P", "LA"):
                        img = img.convert("RGBA")
                    elif img.mode not in ("RGB", "RGBA"):
                        img = img.convert("RGB")

                    # Only resize if original is wider than poster width
                    if actual_width > gif_poster_width:
                        ratio = gif_poster_width / orig_width
                        poster_height = max(1, int(orig_height * ratio))
                        img = img.resize((gif_poster_width, poster_height), Image.LANCZOS)

                    img.save(poster_path, format=fmt.upper(), quality=quality)
                    total_generated += 1
                    generated_variants.append("poster")
            except Exception as e:
                logger.warn(f"Failed to generate poster {poster_name}: {e}")
                total_errors += 1

        manifest_entries.append({
            "filename": filename,
            "width": actual_width,
            "height": actual_height,
            "variants": generated_variants,
            "is_gif": is_gif,
        })

    # Batch update images table metadata
    if updates_needed:
        for img_id, fields in updates_needed:
            set_clauses = ", ".join(f"{k} = ?" for k in fields)
            values = list(fields.values()) + [img_id]
            db.execute(f"UPDATE images SET {set_clauses} WHERE id = ?", values)
        db.commit()
        logger.info(f"Updated metadata for {len(updates_needed)} images in database")

    # Write images-manifest.json to output data directory
    data_dir = Path(output_dir) / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = data_dir / "images-manifest.json"
    manifest = {
        "total_images": len(manifest_entries),
        "images": manifest_entries,
    }
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    logger.success(
        f"Generated {total_generated} thumbnails "
        f"({total_skipped} skipped, {total_errors} errors)"
    )


def _guess_format(filename):
    """Guess image format from filename extension."""
    ext = Path(filename).suffix.lower()
    format_map = {
        ".png": "PNG",
        ".jpg": "JPEG",
        ".jpeg": "JPEG",
        ".gif": "GIF",
        ".webp": "WEBP",
        ".bmp": "BMP",
        ".tiff": "TIFF",
        ".tif": "TIFF",
    }
    return format_map.get(ext, "PNG")
