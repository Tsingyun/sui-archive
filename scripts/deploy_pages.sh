#!/usr/bin/env bash
set -euo pipefail

# Deploy static site to GitHub Pages (gh-pages branch)
#
# Usage: bash scripts/deploy_pages.sh
#
# Steps:
#   1. Validate deploy/ directory
#   2. Create orphan gh-pages branch in temp dir
#   3. Force-push to origin/gh-pages
#   4. Wait for GitHub Pages build to complete
#   5. Clean up

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
DEPLOY_DIR="$PROJECT_ROOT/deploy"

# Load .env if present
[ -f "$PROJECT_ROOT/.env" ] && set -a && source "$PROJECT_ROOT/.env" && set +a

GH_REPO="${GITHUB_REPOSITORY:-Tsingyun/sui-archive}"
MAX_WAIT=300  # max seconds to wait for Pages build

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

info()  { echo -e "${GREEN}[INFO]${NC} $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $*"; }
error() { echo -e "${RED}[ERROR]${NC} $*" >&2; }

# ---------------------------------------------------------------------------
# Pre-flight checks
# ---------------------------------------------------------------------------

if [ ! -d "$DEPLOY_DIR" ]; then
    error "deploy/ directory not found: $DEPLOY_DIR"
    error "Run the build pipeline first: python build/build.py"
    exit 1
fi

file_count=$(find "$DEPLOY_DIR" -type f | wc -l)
if [ "$file_count" -eq 0 ]; then
    error "deploy/ directory is empty"
    exit 1
fi

info "Found $file_count files in deploy/"

cd "$PROJECT_ROOT"
if ! git remote get-url origin &>/dev/null; then
    error "No 'origin' remote configured."
    exit 1
fi

origin_url=$(git remote get-url origin)
info "Origin: $origin_url"

# ---------------------------------------------------------------------------
# Deploy via orphan branch
# ---------------------------------------------------------------------------

TEMP_DIR=$(mktemp -d)
trap 'rm -rf "$TEMP_DIR"' EXIT

info "Created temp directory: $TEMP_DIR"

cd "$TEMP_DIR"
git init --quiet
git checkout --orphan gh-pages

# Copy deploy contents
info "Copying deploy/ contents..."
cp -a "$DEPLOY_DIR"/. "$TEMP_DIR"/

# Bypass Jekyll
touch "$TEMP_DIR/.nojekyll"

# Add CNAME for custom domain
echo "archive.suijisui.uk" > "$TEMP_DIR/CNAME"

# Commit
git add -A
git commit --quiet -m "Deploy: $(date -u '+%Y-%m-%d %H:%M:%S UTC')"

# Add remote and push
git remote add origin "$origin_url"
info "Pushing to gh-pages branch..."
git push --force origin gh-pages 2>&1

echo ""

# ---------------------------------------------------------------------------
# Wait for GitHub Pages build
# ---------------------------------------------------------------------------

wait_for_pages() {
    # If GITHUB_TOKEN is set, use the API to check build status
    if [ -n "${GITHUB_TOKEN:-}" ]; then
        info "Waiting for GitHub Pages build to complete..."
        local waited=0
        while [ $waited -lt $MAX_WAIT ]; do
            local build_status
            build_status=$(curl -s -H "Authorization: token $GITHUB_TOKEN" \
                "https://api.github.com/repos/$GH_REPO/pages/builds/latest" \
                2>/dev/null | python -c "import sys,json; print(json.load(sys.stdin).get('status','unknown'))" 2>/dev/null || echo "unknown")

            case "$build_status" in
                built)
                    info "GitHub Pages build complete!"
                    return 0
                    ;;
                errored)
                    error "GitHub Pages build failed!"
                    return 1
                    ;;
                null|unknown)
                    # No build info yet, wait
                    ;;
                *)
                    info "Pages build status: $build_status (waiting...)"
                    ;;
            esac

            sleep 10
            waited=$((waited + 10))
        done
        warn "Timed out waiting for Pages build (${MAX_WAIT}s)"
    else
        info "No GITHUB_TOKEN set — cannot poll Pages build status."
        info "Waiting 60 seconds for DNS/CDN propagation..."
        sleep 60
    fi
}

wait_for_pages

echo ""
echo "=============================================="
info "Deployed to GitHub Pages!"
echo ""
echo "  Branch  : gh-pages"
echo "  Commit  : $(git rev-parse --short HEAD)"
echo "  CNAME   : archive.suijisui.uk"
echo "  URL     : https://archive.suijisui.uk"
echo ""
echo "  GitHub Pages may take 1-2 minutes to update."
echo "=============================================="
