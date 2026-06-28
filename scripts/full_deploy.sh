#!/usr/bin/env bash
set -euo pipefail

# Full deployment pipeline: build + sync images + deploy pages + verify
#
# Usage: bash scripts/full_deploy.sh [--skip-images] [--skip-build] [--dry-run]
#
# Options:
#   --skip-images  Skip syncing images to R2
#   --skip-build   Skip the build pipeline (use existing deploy/ output)
#   --dry-run      Show what would happen without making changes

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# Parse arguments
SKIP_IMAGES=false
SKIP_BUILD=false
DRY_RUN=false

for arg in "$@"; do
    case "$arg" in
        --skip-images) SKIP_IMAGES=true ;;
        --skip-build)  SKIP_BUILD=true ;;
        --dry-run)     DRY_RUN=true ;;
        *)
            echo "Unknown option: $arg"
            echo "Usage: bash scripts/full_deploy.sh [--skip-images] [--skip-build] [--dry-run]"
            exit 1
            ;;
    esac
done

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

info()  { echo -e "${GREEN}[INFO]${NC} $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $*"; }
error() { echo -e "${RED}[ERROR]${NC} $*" >&2; }
step()  { echo -e "${CYAN}[STEP]${NC} $*"; }

start_time=$(date +%s)

echo ""
echo "=============================================="
echo "  SUI Archive - Full Deployment Pipeline"
echo "=============================================="
echo ""
echo "  Skip build  : $SKIP_BUILD"
echo "  Skip images : $SKIP_IMAGES"
echo "  Dry run     : $DRY_RUN"
echo ""

# ---------------------------------------------------------------------------
# Step 1: Build
# ---------------------------------------------------------------------------

if [ "$SKIP_BUILD" = false ]; then
    step "Step 1/4: Running build pipeline..."
    cd "$PROJECT_ROOT"
    python build/build.py
    info "Build complete."
    echo ""
else
    warn "Step 1/4: Build skipped (--skip-build)"
    echo ""
fi

# ---------------------------------------------------------------------------
# Step 2: Sync images to R2
# ---------------------------------------------------------------------------

if [ "$SKIP_IMAGES" = false ]; then
    step "Step 2/4: Syncing images to R2..."
    cd "$PROJECT_ROOT"
    sync_args=""
    if [ "$DRY_RUN" = true ]; then
        sync_args="--dry-run"
    fi
    python scripts/sync_to_r2.py $sync_args
    info "Image sync complete."
    echo ""
else
    warn "Step 2/4: Image sync skipped (--skip-images)"
    echo ""
fi

# ---------------------------------------------------------------------------
# Step 3: Deploy to GitHub Pages
# ---------------------------------------------------------------------------

if [ "$DRY_RUN" = true ]; then
    warn "Step 3/4: Deploy to GitHub Pages skipped (dry run)"
    echo ""
else
    step "Step 3/4: Deploying to GitHub Pages..."
    cd "$PROJECT_ROOT"
    bash scripts/deploy_pages.sh
    info "GitHub Pages deploy complete."
    echo ""
fi

# ---------------------------------------------------------------------------
# Step 4: Verify deployment
# ---------------------------------------------------------------------------

if [ "$DRY_RUN" = true ]; then
    warn "Step 4/4: Verification skipped (dry run)"
    echo ""
else
    step "Step 4/4: Verifying deployment..."
    # Wait a moment for GitHub Pages to propagate
    info "Waiting 30 seconds for GitHub Pages to update..."
    sleep 30
    cd "$PROJECT_ROOT"
    bash scripts/verify_deploy.sh
    echo ""
fi

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

end_time=$(date +%s)
elapsed=$((end_time - start_time))

echo ""
echo "=============================================="
info "Deployment pipeline complete!"
echo ""
echo "  Duration : ${elapsed}s"
echo "  Site URL : https://archive.suijisui.uk"
echo "  CDN      : (images served via Cloudflare Worker)"
echo ""
echo "=============================================="
