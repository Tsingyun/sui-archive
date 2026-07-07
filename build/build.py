#!/usr/bin/env python3
"""
SUI Archive Build Pipeline — Main Entry Point.

Usage:
    python build/build.py                        # Full build (all steps)
    python build/build.py --step validate        # Single step
    python build/build.py --step json --step search  # Multiple steps
    python build/build.py --incremental          # Skip unchanged thumbnails
    python build/build.py --verbose              # Detailed logging
    python build/build.py --dry-run              # Preview without writing to deploy/
"""

import argparse
import importlib
import os
import shutil
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Ensure the project root is on sys.path so that `build.steps.*` is importable
# ---------------------------------------------------------------------------

def _find_project_root(start_dir=None):
    """Walk up from start_dir until PROJECT_SPEC.md is found.

    Falls back to the directory containing this script's parent (build/).
    """
    if start_dir is None:
        start_dir = Path(__file__).resolve().parent  # build/

    current = start_dir
    for _ in range(10):
        if (current / "PROJECT_SPEC.md").is_file():
            return current
        parent = current.parent
        if parent == current:
            break
        current = parent

    # Fallback: assume script is in build/, so root is parent
    return Path(__file__).resolve().parent.parent


PROJECT_ROOT = _find_project_root()

# Add project root to sys.path if not already there
_root_str = str(PROJECT_ROOT)
if _root_str not in sys.path:
    sys.path.insert(0, _root_str)


# ---------------------------------------------------------------------------
# Step registry — ordered list of (step_name, module_name)
# ---------------------------------------------------------------------------

STEP_REGISTRY = [
    ("validate",   "validate"),
    ("json",       "json_gen"),
    ("search",     "search_gen"),
    ("stats",      "stats_gen"),
    ("sitemap",    "sitemap_gen"),
    ("thumbnails", "thumbnails"),
    ("pages",      "pages"),
    ("assets",     "assets"),
    ("output",     "output"),
]

STEP_ORDER = [name for name, _ in STEP_REGISTRY]


# ---------------------------------------------------------------------------
# Logger
# ---------------------------------------------------------------------------

class BuildLogger:
    """Simple structured logger for the build pipeline."""

    def __init__(self, verbose=False):
        self.verbose = verbose

    def step(self, message):
        print(f"\n{'='*60}")
        print(f"  {message}")
        print(f"{'='*60}")

    def info(self, message):
        print(f"  [INFO] {message}")

    def warn(self, message):
        print(f"  [WARN] {message}")

    # Alias: some steps use the Python stdlib 'warning' convention
    warning = warn

    def success(self, message):
        print(f"  [OK]   {message}")

    def error(self, message):
        print(f"  [ERR]  {message}")

    def debug(self, message):
        if self.verbose:
            print(f"  [DBG]  {message}")


# ---------------------------------------------------------------------------
# Config loading
# ---------------------------------------------------------------------------

def load_config(project_root):
    """Load build/config.yaml and return as dict."""
    config_path = project_root / "build" / "config.yaml"
    if not config_path.is_file():
        print(f"[ERROR] Config file not found: {config_path}")
        print("  Expected at: build/config.yaml")
        sys.exit(1)

    try:
        import yaml
    except ImportError:
        print("[ERROR] PyYAML is required. Install with: pip install pyyaml")
        sys.exit(1)

    with open(config_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    if not isinstance(config, dict):
        print(f"[ERROR] Invalid config format in {config_path}")
        sys.exit(1)

    return config


# ---------------------------------------------------------------------------
# Database connection
# ---------------------------------------------------------------------------

def connect_db(project_root, config):
    """Open a read-only SQLite connection with recommended PRAGMAs."""
    db_relpath = config.get("database", {}).get("path", "data/sui-archive.db")
    db_path = project_root / db_relpath

    if not db_path.is_file():
        print(f"[ERROR] Database not found: {db_path}")
        print("  Run the import script first to create the database.")
        sys.exit(1)

    # Open in read-write mode (thumbnails step updates image metadata)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    conn.execute("PRAGMA journal_mode = WAL")

    return conn


# ---------------------------------------------------------------------------
# Step loading and execution
# ---------------------------------------------------------------------------

def load_step_module(module_name):
    """Dynamically import a step module from build.steps package."""
    full_name = f"build.steps.{module_name}"
    try:
        return importlib.import_module(full_name)
    except ImportError as e:
        return None
    except Exception as e:
        print(f"  [WARN] Error importing {full_name}: {e}")
        return None


def run_steps(steps_to_run, config, db, output_dir, logger):
    """Execute the specified build steps in order.

    Returns:
        dict of step results (step_name -> return value or None).
    """
    results = {}

    for step_name in steps_to_run:
        # Find the module name for this step
        module_name = None
        for name, mod in STEP_REGISTRY:
            if name == step_name:
                module_name = mod
                break

        if module_name is None:
            logger.warn(f"Unknown step: {step_name}")
            continue

        mod = load_step_module(module_name)
        if mod is None:
            logger.warn(
                f"Step module not found: build.steps.{module_name} — skipping '{step_name}'"
            )
            results[step_name] = None
            continue

        if not hasattr(mod, "run"):
            logger.warn(
                f"Step module build.steps.{module_name} has no run() function — skipping"
            )
            results[step_name] = None
            continue

        try:
            result = mod.run(db, config, output_dir, logger)
            results[step_name] = result
        except SystemExit:
            raise
        except KeyboardInterrupt:
            raise
        except Exception as e:
            logger.error(f"Step '{step_name}' failed: {e}")
            import traceback
            traceback.print_exc()
            print(f"\n[ABORT] Build aborted due to error in step '{step_name}'.")
            sys.exit(1)

    return results


# ---------------------------------------------------------------------------
# Atomic swap: _build/ -> deploy/
# ---------------------------------------------------------------------------

def atomic_swap(temp_dir, deploy_dir, logger):
    """Atomically replace deploy/ with _build/.

    On Windows, os.replace() works for directories only if the target
    doesn't exist. So we remove deploy/ first, then rename.
    """
    temp_dir = Path(temp_dir)
    deploy_dir = Path(deploy_dir)

    if not temp_dir.is_dir():
        logger.warn(f"Temp directory does not exist: {temp_dir}")
        return False

    # Remove existing deploy/ if present
    if deploy_dir.exists():
        logger.info(f"Removing existing {deploy_dir.name}/ ...")
        shutil.rmtree(str(deploy_dir))

    # Rename _build/ -> deploy/
    try:
        os.rename(str(temp_dir), str(deploy_dir))
        logger.success(f"Atomic swap: {temp_dir.name}/ -> {deploy_dir.name}/")
        return True
    except OSError as e:
        logger.error(f"Failed to swap directories: {e}")
        return False


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------

def parse_args():
    parser = argparse.ArgumentParser(
        description="SUI Archive Build Pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python build/build.py                     Full build
  python build/build.py --step validate     Run only data validation
  python build/build.py --step json --step search   Run JSON + search
  python build/build.py --incremental       Skip unchanged thumbnails
  python build/build.py --dry-run           Preview without deploying
  python build/build.py --verbose           Show detailed logs
        """,
    )
    parser.add_argument(
        "--step",
        action="append",
        dest="steps",
        choices=STEP_ORDER,
        help="Run only the specified step(s). Can be repeated.",
    )
    parser.add_argument(
        "--incremental",
        action="store_true",
        help="Skip unchanged thumbnails (only process new/modified images).",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Show detailed logging output.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Build to temp directory without swapping to deploy/.",
    )
    return parser.parse_args()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    args = parse_args()
    logger = BuildLogger(verbose=args.verbose)

    start_time = time.monotonic()
    build_timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    logger.step("SUI Archive Build Pipeline")
    logger.info(f"Project root: {PROJECT_ROOT}")
    logger.info(f"Timestamp:    {build_timestamp}")

    # Load config
    config = load_config(PROJECT_ROOT)

    # Inject runtime metadata into config for step modules
    config["_project_root"] = str(PROJECT_ROOT)
    config["_incremental"] = args.incremental
    config["_dry_run"] = args.dry_run
    config["_version"] = "1.0.0"

    # Determine output directories
    output_config = config.get("output", {})
    deploy_name = output_config.get("dir", "deploy")
    temp_name = output_config.get("temp_dir", "_build")

    deploy_dir = PROJECT_ROOT / deploy_name
    temp_dir = PROJECT_ROOT / temp_name

    if args.dry_run:
        output_dir = temp_dir
        logger.info(f"Mode: DRY RUN — output to {temp_name}/")
    else:
        output_dir = temp_dir
        logger.info(f"Output to {temp_name}/ (will swap to {deploy_name}/)")

    # Create output directory and required subdirs
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "data").mkdir(parents=True, exist_ok=True)
    (output_dir / "data" / "detail").mkdir(parents=True, exist_ok=True)

    # Clean output if configured
    if output_config.get("clean_before_build", True):
        logger.info("Cleaning output directory...")
        for child in output_dir.iterdir():
            if child.is_file():
                child.unlink()
            elif child.is_dir():
                shutil.rmtree(str(child))
        # Recreate required subdirs
        (output_dir / "data").mkdir(parents=True, exist_ok=True)
        (output_dir / "data" / "detail").mkdir(parents=True, exist_ok=True)

    # Connect to database
    db = connect_db(PROJECT_ROOT, config)

    try:
        # Determine which steps to run
        if args.steps:
            steps_to_run = args.steps
            logger.info(f"Steps to run: {', '.join(steps_to_run)}")
        else:
            steps_to_run = STEP_ORDER[:]
            logger.info(f"Running all {len(steps_to_run)} steps")

        # Execute steps
        results = run_steps(steps_to_run, config, db, str(output_dir), logger)

        # Record build duration
        elapsed = time.monotonic() - start_time
        config["_duration_seconds"] = elapsed

        # If output step was not explicitly run but all steps completed,
        # make sure build-info.json is current
        if "output" not in results and not args.steps:
            # output step already ran in run_steps
            pass
        elif "output" in results:
            pass
        else:
            # If running specific steps without output, generate a minimal report
            output_mod = load_step_module("output")
            if output_mod and hasattr(output_mod, "run"):
                config["_duration_seconds"] = time.monotonic() - start_time
                output_mod.run(db, config, str(output_dir), logger)

    finally:
        db.close()

    # Atomic swap: _build/ -> deploy/
    if not args.dry_run:
        atomic_swap(temp_dir, deploy_dir, logger)
    else:
        logger.info(f"DRY RUN complete. Output in: {temp_dir}")

    # Print summary
    elapsed = time.monotonic() - start_time
    print(f"\n{'='*60}")
    print(f"  Build completed in {elapsed:.1f}s")
    print(f"  Steps executed: {len(steps_to_run)}")
    if not args.dry_run:
        print(f"  Deploy directory: {deploy_dir}")
    else:
        print(f"  Temp directory:   {temp_dir}")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
