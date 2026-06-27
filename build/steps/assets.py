"""
Step 7: assets — Static resource processing.

Concatenates CSS files into a single hashed stylesheet, copies JS modules
preserving ES module structure with a hashed entry point, and copies
static assets (icons, fonts, OG images) to the output directory.
"""

import hashlib
import os
import shutil
from pathlib import Path


def run(db, config, output_dir, logger):
    """Process and copy static assets to the build output.

    Args:
        db: sqlite3.Connection with row_factory=Row (unused but required by interface).
        config: dict from config.yaml.
        output_dir: Path to the build output directory.
        logger: Logger with .step()/.info()/.warn()/.success() methods.

    Returns:
        dict with 'css_hash' and 'js_hash' for use by the pages step.
    """
    logger.step("Step 7: assets — Processing static resources")

    output_dir = Path(output_dir)
    project_root = Path(config.get("_project_root", "."))

    result = {"css_hash": "", "js_hash": ""}

    # -------------------------------------------------------------------
    # 1. CSS: concatenate and hash
    # -------------------------------------------------------------------
    result["css_hash"] = _process_css(config, project_root, output_dir, logger)

    # -------------------------------------------------------------------
    # 2. JS: copy modules and hash entry point
    # -------------------------------------------------------------------
    result["js_hash"] = _process_js(config, project_root, output_dir, logger)

    # -------------------------------------------------------------------
    # 3. Static assets: copy src/assets/ -> output_dir/assets/
    # -------------------------------------------------------------------
    _process_static_assets(project_root, output_dir, logger)

    logger.success(
        f"Assets processed — CSS hash: {result['css_hash']}, "
        f"JS hash: {result['js_hash']}"
    )

    return result


# ---------------------------------------------------------------------------
# CSS processing
# ---------------------------------------------------------------------------

def _process_css(config, project_root, output_dir, logger):
    """Concatenate CSS files in configured order, hash, and write."""
    css_config = config.get("css", {})
    css_files = css_config.get("files", [
        "variables.css",
        "reset.css",
        "base.css",
        "layout.css",
        "components.css",
        "pages.css",
        "utilities.css",
    ])
    css_output_name = css_config.get("output", "style.css")

    css_dir = project_root / "src" / "css"
    parts = []

    for fname in css_files:
        fpath = css_dir / fname
        if fpath.is_file():
            content = fpath.read_text(encoding="utf-8")
            parts.append(f"/* === {fname} === */\n{content}")
        else:
            logger.warn(f"CSS file not found: {fname} — skipping")

    if not parts:
        logger.warn("No CSS files found. Writing empty stylesheet.")
        parts.append("/* empty stylesheet */")

    combined = "\n\n".join(parts) + "\n"
    content_hash = _sha256_short(combined)

    # Write as style.{hash}.css
    hashed_name = f"style.{content_hash}.css"
    out_path = output_dir / hashed_name
    out_path.write_text(combined, encoding="utf-8")

    # Also write an un-hashed copy for simple references
    plain_path = output_dir / css_output_name
    plain_path.write_text(combined, encoding="utf-8")

    logger.info(f"CSS: {len(parts)} files concatenated -> {hashed_name} ({len(combined)} bytes)")
    return content_hash


# ---------------------------------------------------------------------------
# JS processing
# ---------------------------------------------------------------------------

def _process_js(config, project_root, output_dir, logger):
    """Copy JS modules to output, hash entry point, rename it."""
    js_config = config.get("js", {})
    js_src_dir = project_root / "src" / js_config.get("dir", "js")
    js_entry = js_config.get("entry", "app.js")

    js_out_dir = output_dir / "js"
    js_out_dir.mkdir(parents=True, exist_ok=True)

    if not js_src_dir.is_dir():
        logger.warn(f"JS source directory not found: {js_src_dir}")
        return ""

    entry_hash = ""
    file_count = 0

    for src_file in sorted(js_src_dir.rglob("*")):
        if not src_file.is_file():
            continue
        # Skip non-JS files (e.g., .map files, etc.)
        if src_file.suffix not in (".js", ".mjs"):
            continue

        rel = src_file.relative_to(js_src_dir)
        dst_file = js_out_dir / rel

        dst_file.parent.mkdir(parents=True, exist_ok=True)

        content = src_file.read_text(encoding="utf-8")

        # Hash the entry point
        if src_file.name == js_entry and rel.parent == Path("."):
            entry_hash = _sha256_short(content)

        dst_file.write_text(content, encoding="utf-8")
        file_count += 1

    # Rename entry point to app.{hash}.js if hash was computed
    if entry_hash:
        entry_src = js_out_dir / js_entry
        entry_stem = Path(js_entry).stem  # "app"
        entry_ext = Path(js_entry).suffix  # ".js"
        hashed_entry = js_out_dir / f"{entry_stem}.{entry_hash}{entry_ext}"

        if entry_src.is_file():
            # Copy the hashed version
            shutil.copy2(str(entry_src), str(hashed_entry))
            # Keep the original too (for module imports that reference by name)

        logger.info(f"JS entry: {js_entry} -> {entry_stem}.{entry_hash}{entry_ext}")
    else:
        logger.warn(f"JS entry point '{js_entry}' not found in {js_src_dir}")

    logger.info(f"JS: {file_count} module files copied to {js_out_dir}")
    return entry_hash


# ---------------------------------------------------------------------------
# Static assets
# ---------------------------------------------------------------------------

def _process_static_assets(project_root, output_dir, logger):
    """Copy src/assets/ to output_dir/assets/."""
    src_assets = project_root / "src" / "assets"
    dst_assets = Path(output_dir) / "assets"

    if not src_assets.is_dir():
        logger.warn(f"Static assets directory not found: {src_assets}")
        return

    # Remove existing output assets to ensure clean state
    if dst_assets.exists():
        shutil.rmtree(str(dst_assets))

    shutil.copytree(str(src_assets), str(dst_assets))

    # Count files copied
    file_count = sum(1 for f in dst_assets.rglob("*") if f.is_file())
    logger.info(f"Assets: {file_count} files copied to {dst_assets}")


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def _sha256_short(content):
    """Compute first 8 characters of SHA-256 hash of content string."""
    if isinstance(content, str):
        content = content.encode("utf-8")
    return hashlib.sha256(content).hexdigest()[:8]
