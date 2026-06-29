#!/usr/bin/env bash
set -euo pipefail

# Verify deployment by checking key URLs, content, and headers.
#
# Usage: bash scripts/verify_deploy.sh [base_url]
#
# Default base_url: https://archive.suijisui.uk

BASE_URL="${1:-https://archive.suijisui.uk}"
PASS=0
FAIL=0
SKIP=0
TOTAL=0

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

# ---------------------------------------------------------------------------
# Check helpers
# ---------------------------------------------------------------------------

check_status() {
    local url="$1" expected="$2" desc="$3"
    TOTAL=$((TOTAL + 1))
    local status
    status=$(curl -s -o /dev/null -w "%{http_code}" --max-time 15 "$url" 2>/dev/null || echo "000")
    if [ "$status" = "$expected" ]; then
        echo -e "  ${GREEN}PASS${NC} [$status] $desc"
        PASS=$((PASS + 1))
    else
        echo -e "  ${RED}FAIL${NC} [$status expected $expected] $desc"
        echo "       $url"
        FAIL=$((FAIL + 1))
    fi
}

check_json() {
    local url="$1" desc="$2"
    TOTAL=$((TOTAL + 1))
    local status body
    status=$(curl -s -o /dev/null -w "%{http_code}" --max-time 15 "$url" 2>/dev/null || echo "000")
    if [ "$status" != "200" ]; then
        echo -e "  ${RED}FAIL${NC} [$status] $desc"
        FAIL=$((FAIL + 1))
        return
    fi
    body=$(curl -s --max-time 15 "$url" 2>/dev/null || echo "")
    if echo "$body" | python -X utf8 -c "import sys,json; json.load(sys.stdin)" 2>/dev/null; then
        echo -e "  ${GREEN}PASS${NC} [200, valid JSON] $desc"
        PASS=$((PASS + 1))
    else
        echo -e "  ${RED}FAIL${NC} [200, invalid JSON] $desc"
        FAIL=$((FAIL + 1))
    fi
}

check_header() {
    local url="$1" header_name="$2" expected_pattern="$3" desc="$4"
    TOTAL=$((TOTAL + 1))
    local header_value
    header_value=$(curl -sI --max-time 15 "$url" 2>/dev/null | grep -i "^${header_name}:" | head -1 | sed "s/^[^:]*: *//" | tr -d '\r')
    if echo "$header_value" | grep -qi "$expected_pattern" 2>/dev/null; then
        echo -e "  ${GREEN}PASS${NC} $desc"
        PASS=$((PASS + 1))
    else
        echo -e "  ${RED}FAIL${NC} $desc (header: $header_name = '$header_value')"
        FAIL=$((FAIL + 1))
    fi
}

check_content() {
    local url="$1" pattern="$2" desc="$3"
    TOTAL=$((TOTAL + 1))
    local body
    body=$(curl -s --max-time 15 "$url" 2>/dev/null || echo "")
    if echo "$body" | grep -q "$pattern" 2>/dev/null; then
        echo -e "  ${GREEN}PASS${NC} $desc"
        PASS=$((PASS + 1))
    else
        echo -e "  ${RED}FAIL${NC} $desc (pattern '$pattern' not found)"
        FAIL=$((FAIL + 1))
    fi
}

check_image() {
    local url="$1" desc="$2"
    TOTAL=$((TOTAL + 1))
    local status content_type
    status=$(curl -s -o /dev/null -w "%{http_code}" --max-time 15 "$url" 2>/dev/null || echo "000")
    if [ "$status" = "200" ]; then
        content_type=$(curl -sI --max-time 15 "$url" 2>/dev/null | grep -i "^content-type:" | head -1 | tr -d '\r')
        echo -e "  ${GREEN}PASS${NC} [200] $desc ($content_type)"
        PASS=$((PASS + 1))
    elif [ "$status" = "404" ]; then
        echo -e "  ${YELLOW}SKIP${NC} [404] $desc (image not uploaded to R2 yet?)"
        SKIP=$((SKIP + 1))
    else
        echo -e "  ${RED}FAIL${NC} [$status] $desc"
        FAIL=$((FAIL + 1))
    fi
}

# ---------------------------------------------------------------------------
# Run checks
# ---------------------------------------------------------------------------

echo ""
echo "=============================================="
echo "  SUI Archive — Deployment Verification"
echo "  Base URL: $BASE_URL"
echo "  Time:     $(date -u '+%Y-%m-%d %H:%M:%S UTC')"
echo "=============================================="
echo ""

# --- 1. Core Pages ---
echo "── Core Pages ──"
check_status "$BASE_URL/" "200" "Homepage"
check_status "$BASE_URL/search" "200" "Search page"
check_status "$BASE_URL/gallery" "200" "Gallery page"
check_status "$BASE_URL/timeline" "200" "Timeline page"
check_status "$BASE_URL/stats" "200" "Stats page"
check_status "$BASE_URL/tags" "200" "Tags page"
check_status "$BASE_URL/about" "200" "About page"
check_status "$BASE_URL/404.html" "200" "Custom 404 page"
echo ""

# --- 2. Data / JSON ---
echo "── Data Files ──"
check_json "$BASE_URL/data/dynamics-index.json" "dynamics-index.json"
check_json "$BASE_URL/data/stats.json" "stats.json"
check_json "$BASE_URL/data/search-index.json" "search-index.json"
echo ""

# --- 3. Assets ---
echo "── Static Assets ──"
check_status "$BASE_URL/style.css" "200" "Stylesheet (style.css)"
check_status "$BASE_URL/js/app.js" "200" "Entry JavaScript (app.js)"
check_status "$BASE_URL/js/config.js" "200" "Config module (config.js)"
check_status "$BASE_URL/js/router.js" "200" "Router module (router.js)"
echo ""

# --- 4. SEO ---
echo "── SEO ──"
check_status "$BASE_URL/sitemap.xml" "200" "Sitemap XML"
check_status "$BASE_URL/robots.txt" "200" "robots.txt"
check_content "$BASE_URL/sitemap.xml" "urlset" "Sitemap contains <urlset>"
check_content "$BASE_URL/robots.txt" "User-agent" "robots.txt contains User-agent"
echo ""

# --- 5. Open Graph ---
echo "── Open Graph ──"
check_content "$BASE_URL/" "og:title" "Homepage has og:title"
check_content "$BASE_URL/" "og:description" "Homepage has og:description"
check_content "$BASE_URL/" "og:url" "Homepage has og:url"
check_content "$BASE_URL/" "twitter:card" "Homepage has twitter:card"
echo ""

# --- 6. Detail Page ---
echo "── Detail Page ──"
# Extract a real detail page URL from dynamics-index.json
DETAIL_PATH=""
DETAIL_JSON=$(curl -s --max-time 15 "$BASE_URL/data/dynamics-index.json" 2>/dev/null || echo "")
if [ -n "$DETAIL_JSON" ]; then
    DETAIL_PATH=$(echo "$DETAIL_JSON" | python -X utf8 -c "
import sys, json
try:
    data = json.load(sys.stdin)
    years = data.get('years', [])
    if years:
        # Pick the latest year
        year_info = years[0]
        file_name = year_info.get('file', '')
        print(file_name)
except:
    pass
" 2>/dev/null || echo "")

    if [ -n "$DETAIL_PATH" ]; then
        # Fetch year data and get a post ID
        YEAR_JSON=$(curl -s --max-time 15 "$BASE_URL/data/$DETAIL_PATH" 2>/dev/null || echo "")
        POST_ID=$(echo "$YEAR_JSON" | python -X utf8 -c "
import sys, json
try:
    data = json.load(sys.stdin)
    posts = data.get('posts', [])
    if posts:
        print(posts[0].get('platform_post_id', ''))
except:
    pass
" 2>/dev/null || echo "")

        if [ -n "$POST_ID" ]; then
            check_status "$BASE_URL/d/$POST_ID/" "200" "Detail page (/d/$POST_ID/)"
            check_content "$BASE_URL/d/$POST_ID/" "og:type" "Detail page has og:type"
            check_content "$BASE_URL/d/$POST_ID/" "schema.org" "Detail page has Schema.org markup"
        else
            echo -e "  ${YELLOW}SKIP${NC} Could not extract post ID from year data"
            SKIP=$((SKIP + 1))
        fi
    else
        echo -e "  ${YELLOW}SKIP${NC} Could not determine year file from index"
        SKIP=$((SKIP + 1))
    fi
else
    echo -e "  ${YELLOW}SKIP${NC} Could not fetch dynamics-index.json"
    SKIP=$((SKIP + 1))
fi
echo ""

# --- 7. Image Worker ---
echo "── Image CDN (Cloudflare Worker) ──"
# Try to load a known image path from the year data
if [ -n "${POST_ID:-}" ]; then
    IMAGE_PATH=$(echo "$YEAR_JSON" | python -X utf8 -c "
import sys, json
try:
    data = json.load(sys.stdin)
    posts = data.get('posts', [])
    for p in posts:
        if p.get('images'):
            print(p['images'][0]['filename'])
            break
except:
    pass
" 2>/dev/null || echo "")
    if [ -n "$IMAGE_PATH" ]; then
        check_image "$BASE_URL/images/$IMAGE_PATH" "Image via Worker: $IMAGE_PATH"
    else
        echo -e "  ${YELLOW}SKIP${NC} No image filename found in test data"
        SKIP=$((SKIP + 1))
    fi
else
    echo -e "  ${YELLOW}SKIP${NC} No post ID available for image test"
    SKIP=$((SKIP + 1))
fi
echo ""

# --- Summary ---
echo "=============================================="
echo "  Results: $PASS passed, $FAIL failed, $SKIP skipped ($TOTAL total)"
echo ""
if [ "$FAIL" -gt 0 ]; then
    echo -e "  ${RED}Some checks failed!${NC}"
    echo "=============================================="
    exit 1
else
    echo -e "  ${GREEN}All checks passed!${NC}"
    echo "=============================================="
    exit 0
fi
