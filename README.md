# SUI Archive

A digital archive for VTuber [岁己 SUI](https://space.bilibili.com/1954091502).

Permanently preserves publicly posted social media dynamics — even if the original platform deletes them, this archive remains accessible.

**Live**: [archive.suijisui.uk](https://archive.suijisui.uk)

## Architecture

```
SQLite (SSOT) -> Python Build Pipeline -> Static HTML/JSON -> GitHub Pages
                                         Images -> Cloudflare R2 -> CDN
```

- **Data**: SQLite database (WAL mode), single source of truth
- **Build**: Python pipeline generates all JSON, HTML, search indexes, thumbnails
- **Hosting**: GitHub Pages (gh-pages branch)
- **Images**: Cloudflare R2, proxied via Cloudflare Worker
- **CDN**: Cloudflare edge cache
- **Frontend**: Vanilla HTML + CSS + JavaScript (ES Modules, zero frameworks)

## Quick Start

```bash
git clone https://github.com/Tsingyun/sui-archive.git
cd sui-archive
python build/build.py
cd deploy && python -m http.server 8090
```

## Project Structure

```
sui-archive/
  data/              SQLite database + DDL
  images/            Original images (gitignored, stored locally)
  build/             Python build pipeline
  src/               Frontend source (HTML/CSS/JS)
  media/             R2 sync scripts
  worker/            Cloudflare Worker (image proxy)
  scripts/           Utility tools
  deploy_scripts/    Deployment automation
  deploy/            Build output (gitignored, pushed to gh-pages)
```

## Documentation

| Document | Purpose |
|----------|---------|
| [PROJECT_SPEC.md](PROJECT_SPEC.md) | Project constitution |
| [ARCHITECTURE.md](ARCHITECTURE.md) | System architecture overview |
| [DATABASE_SPEC.md](DATABASE_SPEC.md) | SQLite database design (11 tables) |
| [BUILD_SPEC.md](BUILD_SPEC.md) | Build pipeline and frontend engineering |

## Tech Stack

- **Backend**: Python 3.10+, SQLite, Pillow
- **Frontend**: HTML5, CSS3, Vanilla JS (ES Modules)
- **Hosting**: GitHub Pages, Cloudflare (CDN + R2)
- **Fonts**: Fraunces + Nunito (Google Fonts)

## Design

**Organic / Natural** — Wabi-sabi inspired. Earth tones, organic shapes, paper grain texture, soft shadows.

## License

[MIT](LICENSE)
