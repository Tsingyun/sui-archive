#!/usr/bin/env bash
set -euo pipefail

# Deploy static site to GitHub Pages (gh-pages branch)
#
# Usage: bash scripts/deploy_pages.sh
#
# This script:
#   1. Validates the deploy/ directory exists and has content
#   2. Creates a temporary git repository with deploy/ contents
#   3. Force-pushes to the gh-pages branch on origin
#   4. Cleans up the temporary directory
#
# Safety: This script NEVER force-pushes to main/master.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
DEPLOY_DIR="$PROJECT_ROOT/deploy"

# Colors for output (work on both Linux and Windows Git Bash)
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

info()  { echo -e "${GREEN}[INFO]${NC} $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $*"; }
error() { echo -e "${RED}[ERROR]${NC} $*" >&2; }

# ---------------------------------------------------------------------------
# Pre-flight checks
# ---------------------------------------------------------------------------

# Check deploy/ directory exists and is not empty
if [ ! -d "$DEPLOY_DIR" ]; then
    error "deploy/ directory not found: $DEPLOY_DIR"
    error "Run the build pipeline first: python build/build.py"
    exit 1
fi

file_count=$(find "$DEPLOY_DIR" -type f | wc -l)
if [ "$file_count" -eq 0 ]; then
    error "deploy/ directory is empty: $DEPLOY_DIR"
    error "Run the build pipeline first: python build/build.py"
    exit 1
fi

info "Found $file_count files in deploy/"

# Check we're on main branch
cd "$PROJECT_ROOT"
current_branch=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "unknown")
if [ "$current_branch" != "main" ] && [ "$current_branch" != "master" ]; then
    warn "Current branch is '$current_branch', not 'main' or 'master'."
    warn "Proceeding anyway, but make sure your deploy/ output is up to date."
fi

# Check that origin remote exists
if ! git remote get-url origin &>/dev/null; then
    error "No 'origin' remote configured. Cannot push to GitHub Pages."
    exit 1
fi

origin_url=$(git remote get-url origin)
info "Origin: $origin_url"

# ---------------------------------------------------------------------------
# Deploy using orphan branch in a temp directory
# ---------------------------------------------------------------------------

TEMP_DIR=$(mktemp -d)
trap 'rm -rf "$TEMP_DIR"' EXIT

info "Created temp directory: $TEMP_DIR"

# Initialize a fresh git repo in the temp directory
cd "$TEMP_DIR"
git init --quiet
git checkout --orphan gh-pages

# Copy all deploy/ contents (excluding hidden files like .git)
info "Copying deploy/ contents..."
# Use cp -a for preserving attributes; works on both Linux and Git Bash on Windows
cp -a "$DEPLOY_DIR"/. "$TEMP_DIR"/

# Add .nojekyll to bypass Jekyll processing on GitHub Pages
touch "$TEMP_DIR/.nojekyll"

# Commit
git add -A
git commit --quiet -m "Deploy: $(date -u '+%Y-%m-%d %H:%M:%S UTC')"

# Add origin remote
git remote add origin "$origin_url"

# Force push to gh-pages branch
info "Pushing to gh-pages branch..."
git push --force origin gh-pages 2>&1

echo ""
echo "=============================================="
info "Deployed successfully to GitHub Pages!"
echo ""
echo "  Branch : gh-pages"
echo "  Commit : $(git rev-parse --short HEAD)"
echo "  URL    : https://archive.suijisui.uk"
echo ""
echo "  Note: GitHub Pages may take 1-2 minutes to update."
echo "=============================================="
