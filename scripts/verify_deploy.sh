#!/usr/bin/env bash
set -euo pipefail

# Verify deployment by checking key URLs return expected responses.
#
# Usage: bash scripts/verify_deploy.sh [base_url]
#
# Default base_url: https://archive.suijisui.uk

BASE_URL="${1:-https://archive.suijisui.uk}"
PASS_COUNT=0
FAIL_COUNT=0
TOTAL=0

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

# ---------------------------------------------------------------------------
# Check helpers
# ---------------------------------------------------------------------------

check_status() {
    local url="$1"
    local expected_status="$2"
    local description="$3"
    TOTAL=$((TOTAL + 1))

    local actual_status
    actual_status=$(curl -s -o /dev/null -w "%{http_code}" --max-time 15 "$url" 2>/dev/null || echo "000")

    if [ "$actual_status" = "$expected_status" ]; then
        echo -e "  ${GREEN}PASS${NC} [$actual_status] $description"
        echo "       $url"
        PASS_COUNT=$((PASS_COUNT + 1))
    else
        echo -e "  ${RED}FAIL${NC} [expected $expected_status, got $actual_status] $description"
        echo "       $url"
        FAIL_COUNT=$((FAIL_COUNT + 1))
    fi
}

check_json() {
    local url="$1"
    local description="$2"
    TOTAL=$((TOTAL + 1))

    local response
    local status
    status=$(curl -s -o /dev/null -w "%{http_code}" --max-time 15 "$url" 2>/dev/null || echo "000")
    response=$(curl -s --max-time 15 "$url" 2>/dev/null || echo "")

    if [ "$status" != "200" ]; then
        echo -e "  ${RED}FAIL${NC} [$status] $description"
        echo "       $url"
        FAIL_COUNT=$((FAIL_COUNT + 1))
        return
    fi

    # Validate JSON using Python (available on most systems)
    if echo "$response" | python -c "import sys,json; json.load(sys.stdin)" 2>/dev/null; then
        echo -e "  ${GREEN}PASS${NC} [200, valid JSON] $description"
        echo "       $url"
        PASS_COUNT=$((PASS_COUNT + 1))
    else
        echo -e "  ${RED}FAIL${NC} [200, invalid JSON] $description"
        echo "       $url"
        FAIL_COUNT=$((FAIL_COUNT + 1))
    fi
}

# ---------------------------------------------------------------------------
# Run checks
# ---------------------------------------------------------------------------

echo ""
echo "=============================================="
echo "  Deployment Verification"
echo "  Base URL: $BASE_URL"
echo "=============================================="
echo ""

# 1. Homepage
check_status "$BASE_URL/" "200" "Homepage"

# 2. dynamics-index.json
check_json "$BASE_URL/data/dynamics-index.json" "dynamics-index.json (valid JSON)"

# 3. stats.json
check_json "$BASE_URL/data/stats.json" "stats.json (valid JSON)"

# 4. style.css
check_status "$BASE_URL/style.css" "200" "Stylesheet (style.css)"

# 5. js/app.js
check_status "$BASE_URL/js/app.js" "200" "App JavaScript (js/app.js)"

# 6. 404.html
check_status "$BASE_URL/404.html" "200" "Custom 404 page"

# 7. sitemap.xml
check_status "$BASE_URL/sitemap.xml" "200" "Sitemap (sitemap.xml)"

# 8. Sample detail page - check a dynamic route by fetching a known page
#    We try to extract a detail page URL from dynamics-index.json
SAMPLE_URL=""
if command -v python &>/dev/null; then
    SAMPLE_URL=$(curl -s --max-time 15 "$BASE_URL/data/dynamics-index.json" 2>/dev/null \
        | python -c "
import sys, json
try:
    data = json.load(sys.stdin)
    # Try common structures: list of objects with 'id' or 'url', or dict with keys
    if isinstance(data, list) and len(data) > 0:
        item = data[0]
        if isinstance(item, dict):
            item_id = item.get('id') or item.get('dynamic_id') or item.get('oid', '')
            if item_id:
                print(f'/dynamic/{item_id}')
        elif isinstance(item, str):
            print(f'/dynamic/{item}')
    elif isinstance(data, dict):
        keys = list(data.keys())
        if keys:
            print(f'/dynamic/{keys[0]}')
except:
    pass
" 2>/dev/null || echo "")
fi

if [ -n "$SAMPLE_URL" ]; then
    check_status "$BASE_URL$SAMPLE_URL" "200" "Sample detail page ($SAMPLE_URL)"
else
    # Fallback: just check that the root has content
    TOTAL=$((TOTAL + 1))
    echo -e "  ${YELLOW}SKIP${NC} Sample detail page (could not determine URL from dynamics-index.json)"
fi

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

echo ""
echo "=============================================="
echo "  Results: $PASS_COUNT passed, $FAIL_COUNT failed, $TOTAL total"

if [ "$FAIL_COUNT" -gt 0 ]; then
    echo -e "  ${RED}Some checks failed!${NC}"
    echo "=============================================="
    exit 1
else
    echo -e "  ${GREEN}All checks passed!${NC}"
    echo "=============================================="
    exit 0
fi
