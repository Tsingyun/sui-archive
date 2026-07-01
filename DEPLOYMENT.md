# SUI Archive — Deployment & Operations Guide

## Overview

SUI Archive runs as a fully automated pipeline on GitHub Actions. Every 15 minutes it checks for new Bilibili dynamics, and if updates exist, automatically fetches, archives, builds, and deploys — zero human intervention required.

```
Quick Check (266ms) → [no updates?] → exit
                    → [updates?]    → Fetch → DB → Build → R2 Sync → Deploy
```

---

## Initial Setup

### 1. GitHub Secrets

Go to **Repository Settings → Secrets and variables → Actions** and add:

| Secret Name | Description |
|-------------|-------------|
| `BILIBILI_COOKIE` | Bilibili session cookie (SESSDATA + others) |
| `R2_ACCESS_KEY_ID` | Cloudflare R2 S3 access key |
| `R2_SECRET_ACCESS_KEY` | Cloudflare R2 S3 secret key |
| `R2_BUCKET` | R2 bucket name (`sui-archive-images`) |
| `R2_ENDPOINT_URL` | R2 S3-compatible endpoint |
| `CLOUDFLARE_API_TOKEN` | Cloudflare API token (Workers + Zone) |
| `CLOUDFLARE_ZONE_ID` | Cloudflare DNS zone ID (optional, for cache purge) |
| `GH_PAT` | GitHub PAT with `repo` scope (for git push) |

**Notes:**
- `BILIBILI_COOKIE` expires ~every 6 months. When the workflow returns 412 errors, log in to Bilibili and copy a fresh cookie from DevTools → Application → Cookies.
- `GH_PAT` is required for the workflow to push commits. Create one at GitHub → Settings → Developer settings → Personal access tokens → Fine-grained tokens → grant `Contents: Read and write` on this repo.

### 2. DNS Configuration

Point `archive.suijisui.uk` to GitHub Pages:

```
Type: A     Name: archive     Value: 185.199.108.153
Type: A     Name: archive     Value: 185.199.109.153
Type: A     Name: archive     Value: 185.199.110.153
Type: A     Name: archive     Value: 185.199.111.153
```

### 3. Verify

After secrets are configured and DNS propagates:

1. Go to **Actions** tab → **Auto Archive** → **Run workflow**
2. Check the Quick Check job output for `has_updates=true/false`
3. If updates found, the Archive job runs the full pipeline
4. Visit `https://archive.suijisui.uk` to verify

---

## Local Development

### Prerequisites

```bash
pip install -r requirements.txt
cp .env.example .env
# Edit .env with your actual credentials
```

### Run Commands

```bash
# Full pipeline (skip deploy for local testing)
python -X utf8 -m automation --skip-deploy

# Quick Check only (<3 seconds)
python -X utf8 -m automation --quick-check-only

# Skip build (fetch + DB + R2 only)
python -X utf8 -m automation --skip-build --skip-deploy

# Build only (uses existing DB)
python -X utf8 build/build.py

# R2 image sync only
python -X utf8 scripts/sync_to_r2.py
```

---

## Architecture

```
.github/workflows/archive.yml    ← GitHub Actions (3 jobs, every 15 min)

automation/                      ← Pipeline package
  config.py                      ← Centralized configuration
  bilibili_api.py                ← Bilibili API client (retry, rate-limit)
  quick_check.py                 ← Lightweight update detection (<3s)
  fetcher.py                     ← Incremental fetch + image download
  db_writer.py                   ← SQLite transactional writer
  orchestrator.py                ← 6-phase pipeline coordinator

build/                           ← Static site builder (9 steps)
scripts/
  sync_to_r2.py                  ← Incremental R2 upload (ETag compare)
  deploy_pages.sh                ← gh-pages orphan branch deploy

data/
  schema.sql                     ← 11 tables, 3 FTS triggers
  sui-archive.db                 ← SQLite DB (tracked in git)

worker/
  worker.js                      ← Cloudflare Worker image proxy
```

---

## Pipeline Phases

| Phase | Duration | Description |
|-------|----------|-------------|
| 1. Quick Check | ~266ms | Compare latest API vs DB timestamp |
| 2. Fetch | 2-10s | Paginated API fetch, parse, download images |
| 3. DB Write | <1s | Transactional insert with WAL checkpoint |
| 4. Build | ~6min | JSON, HTML, search, stats, thumbnails, sitemap |
| 5. R2 Sync | ~45s | Upload only new/changed images |
| 6. Deploy | ~30s | Git commit/push + Pages deploy + CF purge |

No updates → exits after Phase 1 (~3s total).

---

## Troubleshooting

### 412 Precondition Failed
Cookie expired. Update `BILIBILI_COOKIE` in GitHub Secrets.

### -352 Rate Limit
API rate-limiting. Pipeline auto-waits 60s and retries 3x.

### Build Timeout
Build takes ~6min (thumbnail generation). GitHub Actions timeout is 30min.

---

## Maintenance

### Cookie Renewal (~every 6 months)
When workflow fails with 412: log in to bilibili.com → DevTools → Cookies → copy all → update Secret.

### Adding a New Platform
Schema supports multiple platforms via `platforms` table. Add a fetcher module for the new platform, map post types to the universal enum, rest of pipeline works unchanged.
