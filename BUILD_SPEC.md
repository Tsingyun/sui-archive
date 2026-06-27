# SUI Archive — 构建系统与前端工程设计规范

> **文档版本**: 1.0.0  
> **创建时间**: 2026-06-28  
> **作用域**: 整个项目的构建系统、前端工程、页面设计、图片处理、搜索、SEO、部署、自动化的唯一工程标准。第五阶段（代码开发）必须遵循本文档。

---

## 一、Build Pipeline（构建管道）

### 1.1 设计原则

1. **幂等性** — 多次运行结果完全相同。输出目录先清空再写入，不依赖上次构建的残留状态。
2. **原子性** — 所有产物写入临时目录 `_build/`，完成后一次性重命名为 `deploy/`，不存在"构建了一半"的 deploy 目录。
3. **可分步调试** — 每个步骤可单独运行：`python build/build.py --step validate`。
4. **快速失败** — 校验步骤最先执行，数据有问题立即中止，不浪费后续构建时间。
5. **增量友好** — 图片处理步骤支持增量模式（`--incremental`），只处理新增/变更的图片，缩短日常构建时间。
6. **可复现** — 同一数据库 + 同一源代码 = 同一产物。构建时间戳不影响内容 hash。

### 1.2 完整流程图

```
┌─────────────────────────────────────────────────────────────────────┐
│                      Build Pipeline 完整流程                         │
│                                                                     │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │ Step 0: validate (数据校验)                                  │   │
│  │  PRAGMA integrity_check                                     │   │
│  │  PRAGMA foreign_key_check                                   │   │
│  │  检查 schema_migrations 版本                                │   │
│  │  检查 posts/images 数据完整性                                │   │
│  │  → 失败则中止构建                                            │   │
│  └──────────────────────────┬──────────────────────────────────┘   │
│                             ▼                                       │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │ Step 1: json (生成 JSON 数据文件)                             │   │
│  │  查询 posts + post_media + images + post_stats + authors    │   │
│  │  → data/dynamics-index.json   (年份索引 + 全局元数据)        │   │
│  │  → data/dynamics-{year}.json  (每年动态数据，按需分片)       │   │
│  │  → data/detail/{uuid}.json    (单条动态完整数据)             │   │
│  └──────────────────────────┬──────────────────────────────────┘   │
│                             ▼                                       │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │ Step 2: search (生成搜索索引)                                 │   │
│  │  查询 posts_fts + posts + post_tags + tags                  │   │
│  │  → data/search-index.json  (全文搜索索引)                    │   │
│  │  → data/tag-index.json     (标签索引 + 计数)                 │   │
│  └──────────────────────────┬──────────────────────────────────┘   │
│                             ▼                                       │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │ Step 3: stats (生成统计数据)                                  │   │
│  │  聚合查询 posts + images + post_stats + tags                │   │
│  │  → data/stats.json  (全站统计摘要)                           │   │
│  └──────────────────────────┬──────────────────────────────────┘   │
│                             ▼                                       │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │ Step 4: sitemap (生成 SEO 文件)                              │   │
│  │  → sitemap.xml       (站点地图)                              │   │
│  │  → sitemap-index.xml (站点地图索引)                          │   │
│  │  → robots.txt        (爬虫规则)                              │   │
│  │  → feed.xml          (RSS 订阅源，可选)                      │   │
│  └──────────────────────────┬──────────────────────────────────┘   │
│                             ▼                                       │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │ Step 5: thumbnails (图片处理)                                 │   │
│  │  扫描 images/ 目录，与数据库 images 表比对                    │   │
│  │  生成缩略图: 300px / 600px / 1200px 宽度                    │   │
│  │  转换为 WebP 格式 (quality 80)                               │   │
│  │  GIF → 静态 WebP 海报帧 + 动态标记                          │   │
│  │  更新 images 表的 width/height/file_size                    │   │
│  │  → thumbs/ 目录 (所有缩略图文件)                             │   │
│  │  → data/images-manifest.json (图片清单)                     │   │
│  └──────────────────────────┬──────────────────────────────────┘   │
│                             ▼                                       │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │ Step 6: pages (生成 HTML 页面)                                │   │
│  │  读取 src/html/ 模板 + 数据库数据                            │   │
│  │  注入 Open Graph / Twitter Card / Schema.org 元数据          │   │
│  │  → 静态页面 (index, search, gallery, timeline, stats, ...)  │   │
│  │  → 动态详情页 (d/{id}/index.html × N 条动态)                │   │
│  │  → 标签详情页 (tag/{slug}/index.html × N 个标签)            │   │
│  │  → 404.html (自定义错误页)                                   │   │
│  └──────────────────────────┬──────────────────────────────────┘   │
│                             ▼                                       │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │ Step 7: assets (处理静态资源)                                 │   │
│  │  复制 CSS 文件 → 合并为 style.css                            │   │
│  │  复制 JS 模块 → js/ 目录 (保持 ES Module 结构)              │   │
│  │  复制字体、图标、静态资源                                     │   │
│  │  计算内容 hash → 注入 HTML 引用                              │   │
│  │  注入构建信息 (版本号、构建时间、数据计数)                    │   │
│  │  → style.{hash}.css                                          │   │
│  │  → js/*.js                                                   │   │
│  │  → assets/*                                                  │   │
│  └──────────────────────────┬──────────────────────────────────┘   │
│                             ▼                                       │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │ Step 8: output (产物输出)                                     │   │
│  │  写入 _build/ 临时目录                                       │   │
│  │  生成 build-info.json (构建报告)                             │   │
│  │  原子替换: _build/ → deploy/                                 │   │
│  │  打印构建摘要 (文件数、大小、耗时)                            │   │
│  └──────────────────────────┬──────────────────────────────────┘   │
│                             ▼                                       │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │ Step 9: deploy_pages (部署到 GitHub Pages)                    │   │
│  │  git subtree push deploy/ → gh-pages 分支                   │   │
│  │  支持 --dry-run 预览变更                                     │   │
│  └──────────────────────────┬──────────────────────────────────┘   │
│                             ▼                                       │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │ Step 10: sync_media (同步图片到 Cloudflare R2)                │   │
│  │  增量同步: 原图 + 所有缩略图变体                             │   │
│  │  只上传新增/变更文件                                          │   │
│  │  不删除 R2 已有文件 (防止误删)                               │   │
│  └──────────────────────────┬──────────────────────────────────┘   │
│                             ▼                                       │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │ Step 11: purge_cache (清除 CDN 缓存)                          │   │
│  │  Cloudflare API → Purge All                                 │   │
│  │  仅在有新部署时执行                                          │   │
│  └──────────────────────────┬──────────────────────────────────┘   │
│                             ▼                                       │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │ Step 12: verify (部署验证)                                    │   │
│  │  HTTP 请求验证关键页面 (200 OK)                              │   │
│  │  验证 JSON 数据文件可达                                      │   │
│  │  验证图片 CDN 可达                                           │   │
│  │  验证 sitemap.xml 格式正确                                   │   │
│  │  → 输出验证报告                                              │   │
│  └─────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────┘
```

### 1.3 步骤详细说明

#### Step 0: validate — 数据校验

在所有构建工作开始前，先验证数据库的健康状态。这是"快速失败"原则的核心——如果数据源有问题，后续所有步骤都没有意义。

**执行内容**:

| 检查项 | SQL/方法 | 失败处理 |
|--------|---------|---------|
| 数据库文件存在 | `os.path.exists()` | 中止，提示运行导入脚本 |
| 数据库完整性 | `PRAGMA integrity_check` | 中止，提示从备份恢复 |
| 外键完整性 | `PRAGMA foreign_key_check` | 警告（不中止），列出断裂的外键 |
| Schema 版本 | 查询 `schema_migrations` 最新版本 | 中止，提示运行 migration |
| 数据非空 | `SELECT COUNT(*) FROM posts` | 中止，提示数据为空 |
| 图片文件抽检 | 随机检查 10 个 images 行对应的文件是否存在 | 警告，报告缺失文件数 |

**输出**: 控制台打印校验报告。严重问题返回非零退出码中止构建。

#### Step 1: json — 生成 JSON 数据文件

从 SQLite 查询数据，生成前端需要的所有 JSON 文件。

**生成文件**:

| 文件 | 内容 | 数据来源 | 预估大小 |
|------|------|---------|---------|
| `data/dynamics-index.json` | 年份索引 + 全局配置 | posts 表聚合 | < 10KB |
| `data/dynamics-{year}.json` | 该年所有动态的列表视图数据 | posts + post_media + images + post_stats + authors | 200KB - 800KB/年 |
| `data/detail/{uuid}.json` | 单条动态完整数据 | posts + 所有关联表 | 1-5KB/条 |

**dynamics-index.json 结构**:

```
{
  "archive": {
    "name": "岁己 SUI Archive",
    "url": "https://archive.suijisui.uk",
    "description": "虚拟主播岁己SUI的数字档案馆",
    "target_platform": "bilibili",
    "target_uid": "1954091502"
  },
  "build": {
    "generated_at": "ISO 8601",
    "version": "semver",
    "total_posts": number,
    "total_images": number,
    "total_tags": number
  },
  "years": [
    {
      "year": number,
      "count": number,
      "date_range": { "first": "ISO 8601", "last": "ISO 8601" },
      "months": { "1": count, "2": count, ... },
      "type_counts": { "image": n, "text": n, "repost": n, ... },
      "file": "dynamics-{year}.json"
    }
  ],
  "config": {
    "posts_per_page": 50,
    "default_view": "timeline"
  }
}
```

**dynamics-{year}.json 结构**（列表视图，不含完整文本）:

```
{
  "year": number,
  "posts": [
    {
      "uuid": "text",
      "platform_post_id": "text",
      "post_type": "text",
      "published_at": "ISO 8601",
      "text_preview": "text — plain_text 截断前 200 字符",
      "text_length": number,
      "has_images": boolean,
      "image_count": number,
      "images": [
        {
          "filename": "text",
          "width": number,
          "height": number,
          "is_cover": boolean
        }
      ],
      "stats": { "likes": n, "comments": n, "forwards": n },
      "is_repost": boolean,
      "repost_author": "text | null",
      "tags": ["text"]
    }
  ]
}
```

**data/detail/{uuid}.json 结构**（完整数据）:

```
{
  "uuid": "text",
  "platform_post_id": "text",
  "platform_name": "text",
  "post_type": "text",
  "published_at": "ISO 8601",
  "source_url": "text | null",
  "plain_text": "text — 完整文本",
  "images": [
    {
      "filename": "text",
      "width": number,
      "height": number,
      "file_size": number,
      "mime_type": "text",
      "is_cover": boolean,
      "is_repost_media": boolean
    }
  ],
  "stats": { "likes": n, "comments": n, "forwards": n, "views": "n | null" },
  "is_repost": boolean,
  "repost": {
    "author_name": "text | null",
    "author_url": "text | null",
    "text": "text | null",
    "source_url": "text | null"
  },
  "tags": [
    { "name": "text", "slug": "text", "color": "text | null" }
  ],
  "related": {
    "prev_uuid": "text | null",
    "next_uuid": "text | null"
  }
}
```

**text_preview 截断规则**: 取 `plain_text` 前 200 个字符。如果原文超过 200 字符，在最后一个完整句子（`。！？` 或换行）处截断，末尾加 `…`。不截断 `[表情名]` 的中间。

#### Step 2: search — 生成搜索索引

从数据库提取可搜索字段，生成供客户端全文搜索使用的索引文件。

**生成文件**:

| 文件 | 内容 | 预估大小 |
|------|------|---------|
| `data/search-index.json` | 搜索索引数组 | 500KB - 2MB |
| `data/tag-index.json` | 标签定义 + 帖子计数 | < 50KB |

**search-index.json 结构**:

```
{
  "generated_at": "ISO 8601",
  "total_entries": number,
  "entries": [
    {
      "uuid": "text",
      "platform_post_id": "text",
      "text": "text — 完整 plain_text",
      "repost_text": "text | null",
      "post_type": "text",
      "published_at": "YYYY-MM-DD",
      "has_images": boolean,
      "image_count": number,
      "tags": ["slug"]
    }
  ]
}
```

**搜索索引设计要点**:

- `text` 字段保留完整文本（不截断），因为搜索需要匹配任意位置
- `repost_text` 单独存储，搜索时可区分原创内容和转发内容
- 不包含图片 URL、统计等非搜索字段，减小文件体积
- `tags` 存储 slug 数组，支持标签筛选

**tag-index.json 结构**:

```
{
  "total_tags": number,
  "tags": [
    {
      "name": "text",
      "slug": "text",
      "category": "text | null",
      "color": "text | null",
      "post_count": number,
      "image_count": number,
      "latest_post_date": "YYYY-MM-DD | null"
    }
  ]
}
```

#### Step 3: stats — 生成统计数据

聚合查询数据库，生成全站统计摘要。

**生成文件**: `data/stats.json`

**stats.json 结构**:

```
{
  "generated_at": "ISO 8601",
  "overview": {
    "total_posts": number,
    "total_images": number,
    "total_tags": number,
    "total_authors": number,
    "date_range": { "first": "ISO 8601", "last": "ISO 8601" },
    "days_active": number
  },
  "by_year": [
    {
      "year": number,
      "posts": number,
      "images": number,
      "reposts": number,
      "avg_likes": number,
      "top_post_uuid": "text | null"
    }
  ],
  "by_type": { "image": n, "text": n, "repost": n, "video": n, ... },
  "by_month": { "1": n, "2": n, ..., "12": n },
  "activity_heatmap": {
    "YYYY-MM-DD": count
  },
  "top_tags": [
    { "slug": "text", "name": "text", "count": number }
  ],
  "top_authors": [
    { "name": "text", "repost_count": number }
  ],
  "engagement": {
    "total_likes": number,
    "total_comments": number,
    "total_forwards": number,
    "avg_likes_per_post": number,
    "most_liked_post_uuid": "text | null"
  }
}
```

**activity_heatmap 设计**: 键为日期字符串 `YYYY-MM-DD`，值为当天发布的动态数。前端用于渲染 GitHub 风格的贡献热力图。只包含有动态的日期（不补零），减小文件体积。

#### Step 4: sitemap — 生成 SEO 文件

**生成文件**:

| 文件 | 内容 |
|------|------|
| `sitemap.xml` | 包含所有页面的站点地图 |
| `robots.txt` | 爬虫访问规则 |
| `feed.xml` | RSS 2.0 订阅源（可选，配置开关） |

**sitemap.xml 包含的 URL**:

| URL 类型 | 数量 | changefreq | priority |
|---------|------|-----------|----------|
| `/` (首页) | 1 | daily | 1.0 |
| `/search` | 1 | monthly | 0.6 |
| `/gallery` | 1 | weekly | 0.8 |
| `/timeline` | 1 | monthly | 0.7 |
| `/stats` | 1 | weekly | 0.5 |
| `/tags` | 1 | weekly | 0.6 |
| `/about` | 1 | yearly | 0.3 |
| `/d/{id}` (动态详情) | ~3,547 | never | 0.8 |
| `/tag/{slug}` (标签页) | ~N | weekly | 0.5 |

**robots.txt 内容**:

```
User-agent: *
Allow: /
Sitemap: https://archive.suijisui.uk/sitemap.xml
Disallow: /data/
```

**feed.xml** (RSS 2.0): 包含最近 50 条动态，每条含标题（文本前 50 字符）、链接、发布时间、描述（完整文本 + 图片 `<img>` 标签）。可通过配置关闭（`config.yaml` 中 `rss.enabled: false`）。

#### Step 5: thumbnails — 图片处理

详见第五章。此步骤扫描 `images/` 目录，为每张图片生成多个 WebP 缩略图变体，并更新数据库的 `images` 表元数据。

#### Step 6: pages — 生成 HTML 页面

读取 `src/html/` 中的模板文件，注入数据库数据和 SEO 元信息，生成最终 HTML。

**页面生成策略**:

| 页面类型 | 生成方式 | 数量 |
|---------|---------|------|
| 首页、搜索、画廊、时间轴、统计、标签、关于 | 构建时生成完整 HTML | 各 1 个 |
| 动态详情页 `/d/{id}` | 构建时为每条动态生成轻量 HTML 存根 | ~3,547 个 |
| 标签详情页 `/tag/{slug}` | 构建时为每个标签生成 HTML | ~N 个 |
| 404 页面 | 构建时生成 | 1 个 |

**动态详情页 HTML 存根内容**（~2-3KB/条）:

- `<head>`: 完整 SEO 元标签（title, description, OG, Twitter Card, Schema.org）
- `<body>`: 服务端渲染的纯文本内容（搜索引擎可抓取）+ 占位容器
- `<script>`: 加载 JS 模块，客户端渲染交互元素（图片、灯箱等）

**为什么生成 HTML 存根**:

- SEO: 搜索引擎爬虫不需要执行 JavaScript 即可获取页面内容
- OG/Twitter Card: 社交平台抓取 meta 标签时需要静态 HTML
- 性能: 首屏文本内容无需等待 JSON 加载
- 可访问性: 无 JavaScript 环境仍可阅读文本

**URL 结构映射**:

```
URL 路径                → 物理文件
/                      → deploy/index.html
/search                → deploy/search.html  (或 deploy/search/index.html)
/gallery               → deploy/gallery.html
/timeline              → deploy/timeline.html
/stats                 → deploy/stats.html
/tags                  → deploy/tags.html
/about                 → deploy/about.html
/d/{platform_post_id}  → deploy/d/{platform_post_id}/index.html
/tag/{slug}            → deploy/tag/{slug}/index.html
/404                   → deploy/404.html
```

**注**: GitHub Pages 自动将 `/path` 映射到 `/path/index.html`。所以 `/d/1218285761518895113` 对应物理文件 `deploy/d/1218285761518895113/index.html`。

#### Step 7: assets — 处理静态资源

**CSS 处理**: 将 `src/css/` 中的多个 CSS 文件按顺序合并为单个 `style.{hash}.css`。合并顺序：variables → reset → base → layout → components → pages → utilities。不使用预处理器，不做 minify（保持可读性，Cloudflare 自动压缩）。

**JS 处理**: 将 `src/js/` 中的 ES Module 文件原样复制到 `deploy/js/` 目录。保持模块结构不变，不做打包、不做转译。计算 `app.js` 的内容 hash 用于缓存控制（`app.{hash}.js`）。

**资源复制**: 将 `src/assets/` 中的图标、字体、OG 图片等复制到 `deploy/assets/`。

**构建信息注入**: 在 HTML 模板的指定位置注入构建时间、版本号、数据统计。注入方式为查找 `<!-- BUILD_INFO -->` 占位符并替换。

### 1.4 构建配置

构建配置存储在 `build/config.yaml`，控制所有步骤的行为。

```
site:
  name: "岁己 SUI Archive"
  url: "https://archive.suijisui.uk"
  description: "虚拟主播岁己SUI的数字档案馆"
  language: "zh-CN"
  author: "SUI Archive Team"

database:
  path: "data/sui-archive.db"

output:
  dir: "deploy"
  temp_dir: "_build"
  clean_before_build: true

json:
  text_preview_length: 200
  detail_dir: "data/detail"

search:
  enabled: true
  max_text_length: 5000

sitemap:
  enabled: true
  changefreq_default: "weekly"

rss:
  enabled: false
  max_items: 50

thumbnails:
  enabled: true
  variants:
    - { width: 300, suffix: "w300" }
    - { width: 600, suffix: "w600" }
    - { width: 1200, suffix: "w1200" }
  format: "webp"
  quality: 80
  gif_poster: true
  gif_poster_width: 600

pages:
  posts_per_page: 50
  gallery_columns: 3
  generate_detail_pages: true
  generate_tag_pages: true

css:
  files:
    - variables.css
    - reset.css
    - base.css
    - layout.css
    - components.css
    - pages.css
    - utilities.css
  output: "style.css"

js:
  dir: "js"
  entry: "app.js"
```

### 1.5 命令行接口

```
python build/build.py                    # 完整构建（所有步骤）
python build/build.py --step validate    # 只运行数据校验
python build/build.py --step json        # 只生成 JSON
python build/build.py --step search      # 只生成搜索索引
python build/build.py --step thumbnails  # 只处理图片
python build/build.py --step pages       # 只生成 HTML
python build/build.py --step assets      # 只处理静态资源
python build/build.py --step output      # 只执行输出（需先完成前面步骤）
python build/build.py --incremental      # 增量模式（跳过未变更的图片）
python build/build.py --dry-run          # 预览模式（不写入 deploy/）
python build/build.py --verbose          # 详细日志输出
```

### 1.6 构建产物校验

构建完成后自动执行产物自检：

| 检查项 | 方法 |
|--------|------|
| 所有 HTML 文件存在且非空 | 遍历 deploy/ 下的 .html |
| 所有 JSON 文件格式合法 | 尝试 `json.load()` 每个 .json |
| dynamics-index.json 中年份数与实际文件数一致 | 交叉验证 |
| search-index.json 条目数与 posts 表一致 | 计数比对 |
| 详情页 HTML 数量与 posts 表一致 | 计数比对 |
| 缩略图数量 = images 行数 × variants 数 | 计数比对 |
| 所有 CSS 引用的图片/字体文件存在 | 检查 assets/ |
| build-info.json 存在且格式正确 | json.load() |

---

## 二、工程目录

### 2.1 仓库完整目录

```
sui-archive/                              # 仓库根目录 (main 分支)
│
├── PROJECT_SPEC.md                       # 项目宪法
├── ARCHITECTURE.md                       # 系统架构文档
├── DATABASE_SPEC.md                      # 数据库设计规范
├── BUILD_SPEC.md                         # 本文档 — 构建与前端工程规范
├── README.md                             # 项目简介
├── .gitignore                            # Git 忽略规则
│
├── data/                                 # === 数据层 ===
│   ├── sui-archive.db                    # SQLite 数据库 (Single Source of Truth)
│   ├── sui-archive.db-wal                # WAL 日志 (运行时, gitignored)
│   ├── sui-archive.db-shm                # 共享内存 (运行时, gitignored)
│   └── schema.sql                        # 数据库 DDL (版本控制)
│
├── images/                               # === 媒体层 ===
│   ├── *_@original.png                   # 原创原图
│   ├── *_@original.jpg                   # 原创原图 (JPEG)
│   ├── *_@original.gif                   # 原创原图 (GIF)
│   └── *_@repost.*                       # 转发图片
│
├── build/                                # === 构建系统 ===
│   ├── build.py                          # 构建入口 (命令行接口)
│   ├── config.yaml                       # 构建配置 (见 1.4 节)
│   ├── steps/                            # 构建步骤模块
│   │   ├── __init__.py                   # 步骤注册表
│   │   ├── validate.py                   # Step 0: 数据校验
│   │   ├── json_gen.py                   # Step 1: JSON 生成
│   │   ├── search_gen.py                 # Step 2: 搜索索引生成
│   │   ├── stats_gen.py                  # Step 3: 统计数据生成
│   │   ├── sitemap_gen.py                # Step 4: SEO 文件生成
│   │   ├── thumbnails.py                 # Step 5: 图片处理
│   │   ├── pages.py                      # Step 6: HTML 页面生成
│   │   ├── assets.py                     # Step 7: 静态资源处理
│   │   └── output.py                     # Step 8: 产物输出
│   └── utils/                            # 构建工具函数
│       ├── __init__.py
│       ├── db.py                         # 数据库连接管理
│       ├── hash.py                       # 内容 hash 计算
│       ├── text.py                       # 文本截断/清理
│       └── logger.py                     # 构建日志
│
├── src/                                  # === 前端源代码 ===
│   ├── html/                             # HTML 模板
│   │   ├── index.html                    # 首页模板
│   │   ├── search.html                   # 搜索页模板
│   │   ├── gallery.html                  # 画廊页模板
│   │   ├── timeline.html                 # 时间轴页模板
│   │   ├── stats.html                    # 统计页模板
│   │   ├── tags.html                     # 标签列表页模板
│   │   ├── about.html                    # 关于页模板
│   │   ├── detail.html                   # 动态详情页模板 (构建时批量渲染)
│   │   ├── tag-detail.html               # 标签详情页模板
│   │   ├── 404.html                      # 自定义 404 页
│   │   └── partials/                     # HTML 片段 (header/footer/nav)
│   │       ├── head.html                 # <head> 公共部分
│   │       ├── header.html               # 页头导航
│   │       ├── footer.html               # 页脚
│   │       └── og-tags.html              # Open Graph 模板
│   ├── css/                              # 样式文件
│   │   ├── variables.css                 # CSS 变量 (颜色、字体、间距)
│   │   ├── reset.css                     # CSS 重置
│   │   ├── base.css                      # 基础元素样式
│   │   ├── layout.css                    # 布局系统 (grid/flex)
│   │   ├── components.css                # 组件样式 (卡片、按钮、标签)
│   │   ├── pages.css                     # 页面特有样式
│   │   └── utilities.css                 # 工具类
│   ├── js/                               # JavaScript 模块
│   │   ├── app.js                        # 应用入口
│   │   ├── config.js                     # 前端配置
│   │   ├── router.js                     # 客户端路由
│   │   ├── state.js                      # 全局状态管理
│   │   ├── api.js                        # 数据加载层
│   │   ├── dom.js                        # DOM 操作工具
│   │   ├── i18n.js                       # 国际化工具 (预留)
│   │   ├── timeline.js                   # 时间轴模块
│   │   ├── post-card.js                  # 动态卡片渲染
│   │   ├── post-detail.js                # 动态详情渲染
│   │   ├── search.js                     # 搜索引擎
│   │   ├── gallery.js                    # 图片画廊
│   │   ├── lightbox.js                   # 图片灯箱
│   │   ├── tag-filter.js                 # 标签筛选
│   │   ├── infinite-scroll.js            # 无限滚动
│   │   ├── lazy-load.js                  # 懒加载
│   │   ├── stats.js                      # 统计图表
│   │   └── share.js                      # 分享功能
│   └── assets/                           # 静态资源
│       ├── favicon.svg                   # 网站图标 (SVG)
│       ├── favicon.ico                   # 网站图标 (ICO 兼容)
│       ├── apple-touch-icon.png          # iOS 图标
│       ├── og-image.png                  # 默认 OG 分享图 (1200×630)
│       ├── manifest.json                 # Web App Manifest
│       └── fonts/                        # 自托管字体 (woff2)
│           └── (字体文件)
│
├── media/                                # === 媒体同步 ===
│   ├── sync_to_r2.py                     # R2 同步脚本
│   ├── r2_config.yaml                    # R2 连接配置
│   └── sync_report.log                   # 同步日志 (gitignored)
│
├── deploy/                               # === 构建产物 (gitignored) ===
│   └── (由 build 管道生成, 推送到 gh-pages 分支)
│
├── worker/                               # === Cloudflare Worker ===
│   ├── index.js                          # Worker 逻辑
│   ├── wrangler.toml                     # Worker 部署配置
│   └── package.json                      # Worker 依赖 (仅 wrangler)
│
├── scripts/                              # === 辅助工具 ===
│   ├── import_from_json.py               # 从 dynamics.json 导入到 SQLite
│   ├── validate_data.py                  # 独立数据校验
│   ├── compute_sha256.py                 # 回填图片 SHA-256
│   ├── backup.py                         # 数据库备份
│   └── stats_report.py                   # 独立统计报告
│
├── deploy_scripts/                       # === 部署脚本 ===
│   ├── deploy_pages.sh                   # GitHub Pages 部署
│   ├── full_deploy.sh                    # 一键完整部署
│   └── verify_deploy.sh                  # 部署验证
│
└── docs/                                 # === 项目文档 ===
    ├── CONTRIBUTING.md                   # 贡献指南
    └── CHANGELOG.md                      # 变更日志
```

### 2.2 目录职责说明

| 目录 | 职责 | 版本控制 | 备注 |
|------|------|---------|------|
| `data/` | 存储 SQLite 数据库和 DDL | ✅ 提交 `sui-archive.db` 和 `schema.sql` | WAL/SHM 运行时文件 gitignored |
| `images/` | 存储所有原始图片文件 | ✅ 提交所有图片 | 只放原始图片，缩略图由构建生成 |
| `build/` | Python 构建管道源代码 | ✅ 提交 | 不含构建产物 |
| `src/` | 前端源代码（HTML/CSS/JS） | ✅ 提交 | 模板文件，构建时渲染 |
| `media/` | R2 同步脚本 | ✅ 提交脚本，gitignored 日志 | |
| `deploy/` | 构建产物输出目录 | ❌ gitignored | 推送到 gh-pages 分支 |
| `worker/` | Cloudflare Worker 代码 | ✅ 提交 | 独立部署，有自己的 package.json |
| `scripts/` | 一次性辅助工具 | ✅ 提交 | 迁移、校验、备份等 |
| `deploy_scripts/` | 部署自动化脚本 | ✅ 提交 | Shell 脚本，纯 ASCII |

### 2.3 构建产物目录 (deploy/)

```
deploy/                                   # 此目录推送到 gh-pages 分支
├── index.html                            # 首页
├── search.html                           # 搜索页 (或 search/index.html)
├── gallery.html                          # 画廊页
├── timeline.html                         # 时间轴页
├── stats.html                            # 统计页
├── tags.html                             # 标签列表页
├── about.html                            # 关于页
├── 404.html                              # 自定义 404
│
├── style.{hash}.css                      # 合并后的样式表
│
├── js/                                   # JavaScript 模块 (保持 ES Module)
│   ├── app.{hash}.js                     # 入口模块
│   ├── config.js
│   ├── router.js
│   ├── state.js
│   ├── api.js
│   ├── dom.js
│   ├── timeline.js
│   ├── post-card.js
│   ├── post-detail.js
│   ├── search.js
│   ├── gallery.js
│   ├── lightbox.js
│   ├── tag-filter.js
│   ├── infinite-scroll.js
│   ├── lazy-load.js
│   ├── stats.js
│   └── share.js
│
├── data/                                 # 构建生成的 JSON 数据
│   ├── dynamics-index.json
│   ├── dynamics-2022.json
│   ├── dynamics-2023.json
│   ├── dynamics-2024.json
│   ├── dynamics-2025.json
│   ├── dynamics-2026.json
│   ├── search-index.json
│   ├── tag-index.json
│   ├── stats.json
│   ├── images-manifest.json
│   └── detail/                           # 单条动态详情 JSON
│       ├── {uuid-1}.json
│       ├── {uuid-2}.json
│       └── ...
│
├── d/                                    # 动态详情页 HTML
│   ├── {platform_post_id_1}/
│   │   └── index.html
│   ├── {platform_post_id_2}/
│   │   └── index.html
│   └── ...
│
├── tag/                                  # 标签详情页 HTML
│   ├── {slug-1}/
│   │   └── index.html
│   └── ...
│
├── assets/                               # 静态资源
│   ├── favicon.svg
│   ├── favicon.ico
│   ├── apple-touch-icon.png
│   ├── og-image.png
│   ├── manifest.json
│   └── fonts/
│
├── sitemap.xml
├── robots.txt
├── feed.xml                              # RSS (如果启用)
└── build-info.json                       # 构建报告
```

### 2.4 .gitignore 规则

```
# 数据库运行时文件
data/*.db-wal
data/*.db-shm
data/*.db.bak*

# 构建产物
deploy/
_build/

# 缩略图缓存 (构建时生成)
thumbs/

# 媒体同步日志
media/sync_report.log
media/*.log

# 环境变量
.env
.env.*

# 编辑器
.vscode/
.idea/
*.swp

# 操作系统
.DS_Store
Thumbs.db

# Python
__pycache__/
*.pyc
.venv/
```

---

## 三、前端工程结构

### 3.1 JavaScript 模块划分

采用 ES Modules（`<script type="module">`），按职责分为三层。

**核心层** — 提供基础设施，被所有功能模块依赖：

| 模块 | 文件 | 职责 |
|------|------|------|
| 入口 | `app.js` | 应用初始化：检测页面类型 → 加载配置 → 初始化路由 → 渲染当前页面 |
| 配置 | `config.js` | 导出站点常量：API 路径、分页参数、缩略图尺寸、断点值 |
| 路由 | `router.js` | 基于 `popstate` 的客户端路由。页面间导航不重新加载 HTML，只替换内容区 |
| 状态 | `state.js` | 全局状态容器：当前年份、筛选条件、搜索词等。使用发布-订阅模式通知变更 |
| 数据 | `api.js` | 封装所有 `fetch()` 调用。负责加载 JSON、缓存结果、错误处理 |
| DOM | `dom.js` | DOM 操作工具：创建元素、事件委托、模板渲染、滚动位置管理 |
| 国际化 | `i18n.js` | 文本模板管理（预留，当前只有中文） |

**功能层** — 实现具体交互功能：

| 模块 | 文件 | 职责 |
|------|------|------|
| 时间轴 | `timeline.js` | 年份切换、月份导航、数据按年加载 |
| 卡片 | `post-card.js` | 渲染单条动态的卡片视图（文本、缩略图网格、统计、标签） |
| 详情 | `post-detail.js` | 渲染动态详情页（完整文本、全尺寸图片、灯箱入口、转发信息） |
| 搜索 | `search.js` | 加载搜索索引、客户端全文匹配、结果高亮、筛选器 |
| 画廊 | `gallery.js` | 瀑布流/网格布局、图片懒加载、分页或无限滚动 |
| 灯箱 | `lightbox.js` | 全屏图片查看器：缩放、左右切换、键盘快捷键、手势支持 |
| 标签 | `tag-filter.js` | 标签云渲染、标签选择/取消、与时间轴联动 |
| 无限滚动 | `infinite-scroll.js` | 基于 Intersection Observer 的无限滚动，支持哨兵元素 |
| 懒加载 | `lazy-load.js` | 图片懒加载（Intersection Observer）+ 渐进式加载（缩略图 → 大图） |
| 统计 | `stats.js` | 渲染统计图表（热力图、柱状图、饼图），使用 Canvas API 或 SVG |
| 分享 | `share.js` | Web Share API + 复制链接 + 社交平台分享 URL 生成 |

**页面层** — 每个页面一个初始化函数，在 `app.js` 中按路由调用：

```
app.js 路由映射:
  "/"        → 调用 timeline.js 初始化首页
  "/search"  → 调用 search.js 初始化搜索页
  "/gallery" → 调用 gallery.js 初始化画廊页
  "/timeline" → 调用 timeline.js 初始化时间轴页
  "/stats"   → 调用 stats.js 初始化统计页
  "/tags"    → 调用 tag-filter.js 初始化标签页
  "/d/*"     → 调用 post-detail.js 初始化详情页
  "/tag/*"   → 调用 tag-filter.js 初始化标签详情页
```

### 3.2 CSS 组织方式

不使用预处理器，不使用 CSS-in-JS。通过 CSS 自定义属性（变量）实现主题化和一致性。

**文件顺序**（构建时按此顺序合并）:

| 文件 | 职责 | 大小预估 |
|------|------|---------|
| `variables.css` | CSS 自定义属性：颜色、字体、间距、圆角、阴影、断点 | ~3KB |
| `reset.css` | 最小化 CSS 重置（不用 normalize.css，只做必要的跨浏览器统一） | ~1KB |
| `base.css` | 基础元素样式：body、h1-h6、p、a、img、ul、table | ~3KB |
| `layout.css` | 布局系统：CSS Grid 页面骨架、Flex 组件排列、容器宽度 | ~3KB |
| `components.css` | 可复用组件：卡片、按钮、标签、徽章、输入框、导航栏、页脚 | ~5KB |
| `pages.css` | 页面特有样式：首页时间轴、搜索结果、画廊网格、统计图表 | ~5KB |
| `utilities.css` | 工具类：`.visually-hidden`、`.truncate`、`.skeleton`、`.fade-in` | ~2KB |

**合并后**: 单个 `style.{hash}.css`，约 22KB（未压缩），Cloudflare 自动 gzip 后约 5KB。

**CSS 变量设计**（`variables.css` 核心内容）:

```
颜色体系:
  --color-bg:           页面背景
  --color-surface:      卡片/容器背景
  --color-text:         主文本
  --color-text-secondary: 次要文本
  --color-accent:       强调色
  --color-border:       边框色
  --color-tag-*:        标签分类颜色

字体体系:
  --font-sans:          无衬线字体栈 (HarmonyOS Sans SC, system-ui, ...)
  --font-mono:          等宽字体栈
  --font-size-*:        字号阶梯 (xs, sm, base, lg, xl, 2xl)
  --line-height-*:      行高

间距体系:
  --space-*:            间距阶梯 (1, 2, 3, 4, 6, 8, 12, 16)

布局:
  --container-max:      最大内容宽度
  --sidebar-width:      侧边栏宽度
  --grid-gap:           网格间距

圆角:
  --radius-sm, --radius-md, --radius-lg

阴影:
  --shadow-sm, --shadow-md, --shadow-lg

动画:
  --transition-fast:    150ms
  --transition-normal:  300ms

断点 (用于 JS 读取):
  --breakpoint-sm:      640px
  --breakpoint-md:      768px
  --breakpoint-lg:      1024px
  --breakpoint-xl:      1280px
```

**暗色模式**: 通过 `@media (prefers-color-scheme: dark)` 覆盖 CSS 变量实现。不需要 JS 切换（跟随系统设置）。所有颜色通过变量定义，暗色模式只需重新定义变量值。

### 3.3 页面组件划分

每个页面由以下组件组合而成，组件通过 JavaScript 动态渲染：

| 组件 | 渲染模块 | 使用页面 |
|------|---------|---------|
| 导航栏 (Navbar) | `dom.js` | 所有页面 |
| 页脚 (Footer) | `dom.js` | 所有页面 |
| 动态卡片 (PostCard) | `post-card.js` | 首页、时间轴、搜索结果、标签页 |
| 图片网格 (ImageGrid) | `gallery.js` | 画廊、动态详情 |
| 图片灯箱 (Lightbox) | `lightbox.js` | 所有含图片的页面 |
| 搜索框 (SearchBox) | `search.js` | 搜索页、导航栏 |
| 筛选面板 (FilterPanel) | `tag-filter.js` | 时间轴、搜索页、标签页 |
| 年份选择器 (YearPicker) | `timeline.js` | 首页、时间轴 |
| 统计卡片 (StatCard) | `stats.js` | 统计页 |
| 热力图 (Heatmap) | `stats.js` | 统计页、首页 |
| 标签云 (TagCloud) | `tag-filter.js` | 标签页、搜索页 |
| 骨架屏 (Skeleton) | `dom.js` | 所有页面（加载中状态） |
| 分页器 (Pagination) | `infinite-scroll.js` | 画廊（可选替代无限滚动） |
| 分享面板 (SharePanel) | `share.js` | 动态详情页 |

### 3.4 资源加载策略

**首屏加载优化**:

```
1. <link rel="preconnect">  →  Cloudflare CDN
2. <link rel="preload" as="style">  →  style.{hash}.css
3. <link rel="preload" as="fetch" crossorigin>  →  dynamics-index.json
4. <link rel="stylesheet">  →  style.{hash}.css
5. <script type="module">  →  app.{hash}.js (defer, 不阻塞渲染)
6. 页面渲染 (HTML + CSS 已就绪, 显示骨架屏)
7. app.js 加载 → 请求 dynamics-index.json → 渲染首页
8. 滚动到图片 → lazy-load.js 触发 → 加载缩略图
9. 用户打开搜索 → 按需加载 search-index.json
```

**资源优先级**:

| 优先级 | 资源 | 加载方式 |
|--------|------|---------|
| 关键 (阻塞渲染) | `style.{hash}.css` | `<link rel="stylesheet">` |
| 高 | `app.{hash}.js`、`dynamics-index.json` | preload + module |
| 中 | 首屏缩略图 (前 6 张) | `<img loading="eager">` |
| 低 | 非首屏缩略图 | Intersection Observer 懒加载 |
| 按需 | `dynamics-{year}.json`、`search-index.json`、`detail/*.json` | 用户操作时 fetch |
| 后台 | 非当前年份的 JSON、`tag-index.json` | idle 时预取 |

**JS 模块按需加载**: 非当前页面的 JS 模块通过 `import()` 动态导入。例如用户访问首页时，只加载 `app.js` + `config.js` + `router.js` + `state.js` + `api.js` + `dom.js` + `timeline.js` + `post-card.js` + `infinite-scroll.js` + `lazy-load.js`。`search.js`、`gallery.js`、`stats.js` 等模块在用户导航到对应页面时才加载。

### 3.5 配置管理

**后端配置** (`build/config.yaml`): 控制构建行为。Python 读取。

**前端配置** (`src/js/config.js`): 构建时从 `config.yaml` 提取前端需要的值，注入到 `config.js` 中。

```
config.js 导出内容:
  SITE_NAME          — 站点名称
  SITE_URL           — 站点 URL
  API_BASE           — 数据文件基础路径 ("/data")
  INDEX_URL           — dynamics-index.json 路径
  SEARCH_INDEX_URL    — search-index.json 路径
  TAG_INDEX_URL       — tag-index.json 路径
  STATS_URL           — stats.json 路径
  POSTS_PER_PAGE     — 每页条数
  THUMB_VARIANTS     — 缩略图尺寸列表
  DEFAULT_YEAR       — 默认显示年份
  IMAGE_BASE         — 图片路径基础 ("/images")
  THUMB_BASE         — 缩略图路径基础 ("/images")
```

构建时通过 Python 读取 `config.yaml`，生成 `config.js` 的内容，覆盖 `src/js/config.js` 中的占位值。这样源代码中的 `config.js` 始终有合理的默认值（开发时用），构建产物中的 `config.js` 包含真实配置。

### 3.6 资源引用规范

**HTML 中引用 CSS**:
```
<link rel="stylesheet" href="/style.{hash}.css">
```

**HTML 中引用 JS**:
```
<script type="module" src="/js/app.{hash}.js"></script>
```

**JS 中引用数据**:
```
const data = await fetch(config.INDEX_URL);
```

**HTML/JS 中引用图片**:
```
原图:    /images/{dynamic_id}_{index}@{quality}.{ext}
缩略图:  /images/{dynamic_id}_{index}@{quality}_{size}.webp
GIF海报: /images/{dynamic_id}_{index}@{quality}_poster.webp
```

**禁止引用**:
- ❌ 不引用 R2 存储地址
- ❌ 不引用 B站 CDN 地址
- ❌ 不引用第三方 CDN（字体除外）
- ❌ 不使用 hash routing (`#/path`)

---

## 四、网站页面规划

### 4.1 页面总览

| 页面 | URL | 模板 | 职责 |
|------|-----|------|------|
| 首页 | `/` | `index.html` | 时间轴视图，最新 50 条动态，无限滚动，年份/类型筛选 |
| 动态详情 | `/d/{id}` | `detail.html` | 单条动态完整内容：全文、全尺寸图片、统计、标签、分享 |
| 搜索 | `/search` | `search.html` | 全文搜索 + 标签搜索 + 高级筛选 |
| 图片画廊 | `/gallery` | `gallery.html` | 瀑布流展示所有图片，灯箱放大，年份/类型筛选 |
| 时间轴 | `/timeline` | `timeline.html` | 年-月-日层级浏览，可视化时间线 |
| 统计 | `/stats` | `stats.html` | 数据总览：热力图、类型分布、月度趋势、Top 排行 |
| 标签列表 | `/tags` | `tags.html` | 所有标签的云视图，按分类分组 |
| 标签详情 | `/tag/{slug}` | `tag-detail.html` | 单个标签下的所有动态，时间排序 |
| 关于 | `/about` | `about.html` | 项目介绍、数据来源、技术说明 |
| 404 | `/*` | `404.html` | 自定义错误页，搜索建议，导航回首页 |

### 4.2 各页面详细设计

#### 首页 (`/`)

**职责**: 档案馆的主入口。以时间倒序展示动态，提供浏览和筛选功能。

**内容**:
- 顶部导航栏（站名 + 搜索入口 + 页面链接）
- 年份选择器（横向标签页：All | 2026 | 2025 | 2024 | ...）
- 类型筛选器（全部 | 图片 | 文字 | 转发）
- 动态卡片列表（50 条/页，无限滚动）
- 底部加载状态（骨架屏 → 加载更多 → 到底提示）

**数据加载**:
1. 加载 `dynamics-index.json` → 获取年份列表
2. 加载当前年份的 `dynamics-{year}.json` → 渲染卡片
3. 用户滚动到底 → 加载下一页或下一年数据

**跳转关系**:
- 点击卡片 → `/d/{platform_post_id}`
- 点击标签 → `/tag/{slug}`
- 点击搜索图标 → `/search`
- 导航栏 → 其他页面

#### 动态详情页 (`/d/{platform_post_id}`)

**职责**: 展示单条动态的完整内容。

**内容**:
- 面包屑导航（首页 > 2024 > 这条动态）
- 完整文本（不截断）
- 全尺寸图片网格（点击打开灯箱）
- 互动统计（点赞、评论、转发数）
- 标签列表（可点击跳转）
- 转发信息（如果是转发：原作者、原动态文本）
- 平台链接（跳转到 B站原始页面）
- 上一条/下一条导航
- 分享按钮

**数据加载**:
1. HTML 存根已包含文本内容（SEO）
2. JS 加载 `detail/{uuid}.json` → 渲染图片、统计、交互元素

**跳转关系**:
- 面包屑 → 首页 / 对应年份
- 标签 → `/tag/{slug}`
- 上/下一条 → 相邻动态
- 平台链接 → B站原始页面（新窗口）

#### 搜索页 (`/search`)

**职责**: 全文搜索和高级筛选。

**内容**:
- 搜索输入框（支持实时搜索，300ms 防抖）
- 筛选面板（类型、年份、有图片、标签）
- 搜索结果列表（与首页卡片相同样式，关键词高亮）
- 搜索统计（找到 N 条结果，耗时 Xms）

**数据加载**:
1. 页面加载时请求 `search-index.json` + `tag-index.json`
2. 用户输入时客户端匹配（不发送网络请求）
3. 搜索算法：简单的 `String.includes()` 匹配 + 排序

**搜索策略**:
- 全文匹配：`text` 和 `repost_text` 字段
- 标签匹配：`tags` 数组
- 多关键词：空格分隔，AND 逻辑（所有关键词必须出现）
- 排序：默认按时间倒序，可切换为相关度

**跳转关系**:
- 点击结果 → `/d/{platform_post_id}`
- 点击标签筛选 → `/tag/{slug}` 或更新当前结果

#### 图片画廊 (`/gallery`)

**职责**: 以图片为主的浏览视图。

**内容**:
- 年份筛选器
- 瀑布流/网格图片展示
- 图片懒加载（Intersection Observer）
- 点击打开灯箱
- 图片下方显示所属动态的日期和简短文本

**数据加载**:
1. 加载 `dynamics-index.json` → 年份列表
2. 加载当前年份 `dynamics-{year}.json` → 提取有图片的动态
3. 使用 `images-manifest.json` 获取图片尺寸信息
4. 渲染缩略图网格

**跳转关系**:
- 点击图片 → 灯箱
- 灯箱中"查看动态" → `/d/{platform_post_id}`

#### 时间轴页 (`/timeline`)

**职责**: 按年-月-日层级浏览动态。

**内容**:
- 年份列表（显示每年动态数和日期范围）
- 选中年的月份列表（1-12 月，每月动态数）
- 选中月的日期列表（每天的动态标题/预览）
- 选中日的动态列表

**数据加载**:
1. `dynamics-index.json` → 年份/月份计数
2. 按需加载 `dynamics-{year}.json` → 按日分组

**跳转关系**:
- 点击日期 → 展开当天动态
- 点击动态 → `/d/{platform_post_id}`

#### 统计页 (`/stats`)

**职责**: 档案馆的数据总览仪表板。

**内容**:
- 概览数字卡片（总动态、总图片、总标签、时间跨度）
- GitHub 风格活动热力图
- 每月发布量柱状图
- 类型分布饼图
- 年度对比趋势图
- Top 标签
- Top 转发原作者

**数据加载**: `stats.json`

**图表实现**: 使用原生 Canvas API 或纯 SVG 渲染。不使用 Chart.js 等第三方库（零框架依赖原则）。热力图参考 suijisui.uk 的实现方式。

#### 标签列表页 (`/tags`)

**职责**: 展示所有标签，提供分类浏览。

**内容**:
- 按分类分组的标签列表（content / topic / emotion / character）
- 标签云（大小反映关联动态数）
- 每个标签显示名称和动态计数

**数据加载**: `tag-index.json`

**跳转关系**:
- 点击标签 → `/tag/{slug}`

#### 标签详情页 (`/tag/{slug}`)

**职责**: 展示某个标签下的所有动态。

**内容**:
- 标签名称和描述
- 动态列表（与首页卡片相同样式）
- 时间排序

**数据加载**:
1. `tag-index.json` → 标签信息
2. 通过标签关联查询对应年份的 `dynamics-{year}.json`

**跳转关系**:
- 返回 → `/tags`
- 点击动态 → `/d/{platform_post_id}`

#### 关于页 (`/about`)

**职责**: 项目说明。

**内容**:
- 档案馆介绍（这是什么、为什么存在）
- 数据来源说明（B站、爬取时间范围）
- 技术栈说明（静态网站、GitHub Pages、Cloudflare）
- 数据规模（实时从 `stats.json` 读取）
- 联系方式 / 反馈渠道

#### 404 页面

**职责**: 处理不存在的 URL。

**内容**:
- 友好的错误提示
- 搜索框（"也许你在找..."）
- 快捷导航（首页、搜索、画廊）
- GitHub Pages 的 SPA 路由支持（404.html 中包含路由重定向逻辑）

### 4.3 导航结构

```
┌──────────────────────────────────────────────────────────┐
│  [Logo] 岁己 SUI Archive                                 │
│                                                          │
│  首页 | 时间轴 | 画廊 | 标签 | 统计 | 关于    [🔍搜索]  │
└──────────────────────────────────────────────────────────┘
```

- 导航栏固定在页面顶部（`position: sticky`）
- 移动端折叠为汉堡菜单
- 搜索图标点击展开搜索框（桌面端）或跳转搜索页（移动端）
- 当前页面高亮显示

**页脚**:

```
┌──────────────────────────────────────────────────────────┐
│  岁己 SUI Archive                                        │
│  收录 3,547 条动态 · 1,083 张图片 · 2022-2026           │
│  最后更新: 2026-06-28                                    │
│                                                          │
│  B站主页 | GitHub | RSS                                  │
└──────────────────────────────────────────────────────────┘
```

页脚数据从 `dynamics-index.json` 读取，构建时注入。

### 4.4 URL 设计规范

1. **短路径**: 所有 URL 使用短路径，无文件扩展名
2. **语义化**: 动态详情用 `/d/{platform_post_id}`（用户可识别的 ID）
3. **可分享**: 不使用 hash routing，保证链接可分享、可书签
4. **查询参数**: 筛选用 query 参数：`/search?q=关键词&type=image`、`/gallery?year=2024`
5. **Canonical**: 每个页面输出 `<link rel="canonical">` 标签

---

## 五、图片处理

### 5.1 图片变体策略

为每张图片生成多个 WebP 变体，用于不同显示场景。原图保留在 `images/` 和 R2 中作为永久归档。

| 变体 | 宽度 | 格式 | 质量 | 用途 | 命名后缀 |
|------|------|------|------|------|---------|
| 原图 | 原始 | 原始 | 原始 | 灯箱全尺寸、归档 | 无（保持原名） |
| 大图 | 1200px | WebP | 80 | 详情页单图展示 | `_w1200` |
| 中图 | 600px | WebP | 80 | 卡片大图、双列布局 | `_w600` |
| 缩略图 | 300px | WebP | 80 | 画廊网格、卡片缩略图 | `_w300` |
| GIF 海报 | 600px | WebP | 80 | GIF 的静态首帧 | `_poster` |

**命名规范**:

```
原图:    {dynamic_id}_{index:02d}@{quality}.{ext}
缩略图:  {dynamic_id}_{index:02d}@{quality}_{variant}.webp
GIF海报: {dynamic_id}_{index:02d}@{quality}_poster.webp

示例:
1210001435340570626_00@original.png              — 原始文件
1210001435340570626_00@original_w1200.webp       — 1200px WebP
1210001435340570626_00@original_w600.webp        — 600px WebP
1210001435340570626_00@original_w300.webp        — 300px WebP
1210001435340570626_02@original.gif              — 原始 GIF
1210001435340570626_02@original_poster.webp      — GIF 静态海报帧
```

**缩放规则**:
- 保持纵横比（等比缩放）
- 如果原图宽度小于目标宽度，不放大（保持原始尺寸）
- 高度自动计算

### 5.2 缩略图生成流程

```
遍历 images 表:
  对每条记录:
    1. 读取原图文件
    2. 获取原图 width/height（如未知则用 Pillow 读取）
    3. 对每个 variant (w300, w600, w1200):
       a. 如果原图宽度 ≤ variant 宽度 → 跳过（不放大）
       b. 等比缩放到目标宽度
       c. 转换为 WebP (quality=80)
       d. 写入 thumbs/ 目录
    4. 如果是 GIF:
       a. 提取第一帧
       b. 缩放到 600px 宽度
       c. 转换为 WebP
       d. 写入 thumbs/ 目录 (_poster.webp)
    5. 更新 images 表: width, height, file_size, mime_type
```

**增量模式**: 检查 thumbs/ 目录中是否已存在该图片的所有变体。如果存在且修改时间晚于原图，跳过。

**工具**: Python Pillow 库。构建环境的唯一外部依赖。

### 5.3 R2 存储结构

R2 Bucket 中同时存放原图和缩略图，扁平结构：

```
Bucket: sui-archive-images
├── 1210001435340570626_00@original.png           — 原图
├── 1210001435340570626_00@original_w1200.webp    — 缩略图
├── 1210001435340570626_00@original_w600.webp     — 缩略图
├── 1210001435340570626_00@original_w300.webp     — 缩略图
├── 1210001435340570626_02@original.gif           — 原图 GIF
├── 1210001435340570626_02@original_poster.webp   — GIF 海报
└── ...
```

**Cloudflare Worker 路由**: `/images/*` 统一代理到 R2，不区分原图和缩略图。文件名中已包含足够的信息来区分。

### 5.4 响应式图片

HTML 中使用 `<img>` 的 `srcset` 属性，让浏览器根据设备像素比和视口宽度选择最佳尺寸：

```
<img
  src="/images/{id}_{idx}@{q}_w600.webp"
  srcset="/images/{id}_{idx}@{q}_w300.webp 300w,
          /images/{id}_{idx}@{q}_w600.webp 600w,
          /images/{id}_{idx}@{q}_w1200.webp 1200w"
  sizes="(max-width: 640px) 100vw,
         (max-width: 1024px) 50vw,
         33vw"
  loading="lazy"
  alt="动态图片"
  width="600"
  height="计算值"
>
```

**sizes 策略**:
- 手机 (< 640px): 图片占满视口宽度
- 平板 (640-1024px): 两列布局，每张图 50vw
- 桌面 (> 1024px): 三列布局，每张图 33vw

**fallback**: `src` 指向 600px 变体，作为不支持 srcset 的浏览器的回退。

### 5.5 懒加载策略

| 场景 | 策略 | 实现 |
|------|------|------|
| 首屏图片（前 6 张） | 立即加载 | `<img loading="eager">` |
| 非首屏图片 | 进入视口时加载 | Intersection Observer |
| 灯箱大图 | 用户点击时加载 | 点击事件触发 fetch |
| 画廊滚动 | 渐进加载 | 先显示 w300 → 替换为 w600 |
| GIF | 点击播放 | 显示海报帧 → 点击后加载原图 GIF |

**渐进式加载**: 图片先加载 w300 缩略图（~10KB），显示后在后台预取 w600（~30KB），替换显示。用户在灯箱中查看时加载 w1200 或原图。

### 5.6 图片缓存策略

| 资源 | Cache-Control | 说明 |
|------|--------------|------|
| 原图 | `public, max-age=31536000, immutable` | 原图永不变更 |
| 缩略图 | `public, max-age=31536000, immutable` | 缩略图永不变更（同名文件内容不变） |
| GIF 海报 | `public, max-age=31536000, immutable` | 同上 |

由于图片文件名包含 `dynamic_id` 和 `index`，且内容永不修改，使用 `immutable` 标记可以避免浏览器不必要的 revalidation 请求。

### 5.7 未来媒体类型扩展

| 类型 | 处理方式 |
|------|---------|
| 视频封面 | 提取视频首帧或指定时间点作为封面图，存入 images 表，`quality = 'thumbnail'` |
| 头像 | 存储为 `authors.avatar_url`，本地缓存到 images/ 目录，命名 `avatar_{platform_user_id}.{ext}` |
| GIF | 已有处理方案（海报帧 + 原图懒加载） |
| Live Photo | 提取静态帧作为封面，视频部分存入 media/ 目录 |
| 长截图 | 按标准缩略图策略处理，宽度自适应 |

---

## 六、搜索系统

### 6.1 搜索架构

```
构建时:
  SQLite (posts + posts_fts + post_tags + tags)
    → search_gen.py
    → search-index.json + tag-index.json
    → 部署到 GitHub Pages

运行时:
  用户输入关键词
    → search.js 加载 search-index.json (首次)
    → 浏览器内存中全文匹配
    → 实时显示结果 (无需网络请求)
```

**为什么选择客户端搜索**:

- 无服务端：GitHub Pages 不支持服务端逻辑
- 数据量可控：3,547 条动态的搜索索引约 1-2MB，可接受一次性加载
- 即时响应：加载索引后，搜索在毫秒内完成，无网络延迟
- 离线可用：索引加载后缓存在内存中，后续搜索不需要网络

### 6.2 搜索类型

| 搜索类型 | 实现方式 | 匹配字段 |
|---------|---------|---------|
| 全文搜索 | `text.includes(keyword)` | `text`, `repost_text` |
| 标签搜索 | `tags.includes(slug)` | `tags` 数组 |
| 时间搜索 | 日期范围过滤 | `published_at` |
| 类型搜索 | 枚举匹配 | `post_type` |
| 图片搜索 | `has_images === true` | `has_images` |
| 组合搜索 | 上述条件的 AND 组合 | 多字段 |

### 6.3 搜索算法

**基本匹配**:
- 多关键词以空格分隔，AND 逻辑（所有关键词必须出现）
- 大小写不敏感（中文无此问题，英文 `toLowerCase()` 处理）
- 支持引号精确匹配：`"精确短语"` 作为一个整体匹配

**排序**:
- 默认：按发布时间倒序（最新在前）
- 可选：按关键词出现次数排序（简单相关度）

**高亮**:
- 搜索结果中关键词用 `<mark>` 标签包裹
- 显示匹配文本的上下文片段（前后各 50 字符）

### 6.4 搜索 UI

```
┌─────────────────────────────────────────────────────────────┐
│  [🔍 搜索框                                     ] [搜索]  │
├─────────────────────────────────────────────────────────────┤
│  筛选: [全部类型 ▾] [全部年份 ▾] [☐ 仅图片] [标签 ▾]     │
├─────────────────────────────────────────────────────────────┤
│  找到 42 条结果 (耗时 3ms)                                  │
│                                                             │
│  ┌─────────────────────────────────────────────────────┐   │
│  │  [卡片: 匹配的关键词高亮显示]                        │   │
│  └─────────────────────────────────────────────────────┘   │
│  ┌─────────────────────────────────────────────────────┐   │
│  │  [卡片: ...]                                        │   │
│  └─────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

### 6.5 搜索性能保障

| 数据量 | 索引大小 | 首次加载 | 搜索耗时 | 优化手段 |
|--------|---------|---------|---------|---------|
| 3,500 条 | ~1MB | < 1s | < 5ms | 无需优化 |
| 10,000 条 | ~3MB | < 2s | < 10ms | gzip 压缩 |
| 50,000 条 | ~15MB | < 5s | < 30ms | 分片加载 |
| 100,000 条 | ~30MB | 不可接受 | — | 按年份分片 + 按需加载 |

**十万级数据的优化方案**（未来）:

1. **按年分片**: `search-index-2024.json`、`search-index-2025.json`，用户选中年份后才加载对应索引
2. **索引压缩**: 移除停用词、截断超长文本、使用更紧凑的 JSON 结构
3. **Web Worker**: 将搜索计算移至 Worker 线程，不阻塞 UI
4. **预构建倒排索引**: 构建时生成关键词→文档 ID 的映射，运行时直接查表

---

## 七、SEO 策略

### 7.1 Sitemap

**格式**: XML Sitemap 1.0 标准。

**包含的 URL**: 所有公开页面（首页、搜索、画廊、时间轴、统计、标签、关于、所有动态详情页、所有标签详情页）。

**不包含**: `/data/` 下的 JSON 文件、`/js/` 下的脚本文件、`/assets/` 下的静态资源。

**更新频率**: 每次构建时重新生成。

### 7.2 robots.txt

```
User-agent: *
Allow: /
Sitemap: https://archive.suijisui.uk/sitemap.xml

# 禁止抓取数据文件和构建元信息
Disallow: /data/
Disallow: /build-info.json
```

**为什么禁止 `/data/`**: JSON 数据文件是前端 API，不是面向用户的内容。搜索引擎应通过 HTML 页面索引内容，而非 JSON 文件。

### 7.3 Open Graph 标签

每个页面（尤其是动态详情页）输出完整的 OG 标签，确保社交分享时展示美观的卡片。

**动态详情页 OG 标签**:

```
<meta property="og:type" content="article">
<meta property="og:title" content="{text_preview}">
<meta property="og:description" content="{text_preview_100chars}">
<meta property="og:url" content="https://archive.suijisui.uk/d/{platform_post_id}">
<meta property="og:image" content="https://archive.suijisui.uk/images/{cover_image_w600}">
<meta property="og:image:width" content="600">
<meta property="og:image:height" content="{calculated}">
<meta property="og:site_name" content="岁己 SUI Archive">
<meta property="og:locale" content="zh_CN">
<meta property="article:published_time" content="{ISO 8601}">
```

**无图片动态**: `og:image` 使用默认的 `og-image.png`（1200×630 档案馆 logo 图）。

### 7.4 Twitter Card

```
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="{text_preview}">
<meta name="twitter:description" content="{text_preview_100chars}">
<meta name="twitter:image" content="https://archive.suijisui.uk/images/{cover_image_w600}">
```

**为什么需要**: X (Twitter) 使用独立的 meta 标签系统，不读取 OG 标签。需要单独输出。

### 7.5 Schema.org 结构化数据

为动态详情页输出 JSON-LD 格式的结构化数据：

```
{
  "@context": "https://schema.org",
  "@type": "SocialMediaPosting",
  "headline": "{text_preview}",
  "datePublished": "{ISO 8601}",
  "author": {
    "@type": "Person",
    "name": "岁己SUI"
  },
  "image": ["{cover_image_url}"],
  "url": "https://archive.suijisui.uk/d/{platform_post_id}",
  "interactionStatistic": [
    { "@type": "InteractionCounter", "interactionType": "Like", "userInteractionCount": n },
    { "@type": "InteractionCounter", "interactionType": "Comment", "userInteractionCount": n },
    { "@type": "InteractionCounter", "interactionType": "Share", "userInteractionCount": n }
  ]
}
```

**为什么需要**: Google 等搜索引擎利用结构化数据生成富摘要（Rich Snippets），提升搜索结果的展示效果和点击率。

### 7.6 Canonical URL

每个页面输出 `<link rel="canonical">` 标签，声明该页面的权威 URL：

```
<link rel="canonical" href="https://archive.suijisui.uk/d/{platform_post_id}">
```

**为什么需要**: 防止搜索引擎将 `archive.suijisui.uk` 和 `{username}.github.io/sui-archive` 视为两个不同页面（重复内容惩罚）。

### 7.7 分享卡片

| 平台 | 读取的标签 | 效果 |
|------|----------|------|
| Facebook / LinkedIn | Open Graph | 大图文卡片 |
| X (Twitter) | Twitter Card | 大图文卡片 |
| Telegram | Open Graph | 链接预览 + 缩略图 |
| Discord | Open Graph | 嵌入预览 |
| 微信 | `<title>` + `<meta description>` | 小图标 + 标题 + 描述 |
| LINE | Open Graph | 缩略图 + 标题 |

**默认分享图**: `og-image.png`（1200×630），当动态没有图片时使用。内容为档案馆 logo + 站名 + 描述。

### 7.8 其他 SEO 要素

| 要素 | 实现 |
|------|------|
| `<title>` | 每页独立标题：`{页面名} - 岁己 SUI Archive` |
| `<meta description>` | 每页独立描述（首页用站点描述，详情页用文本预览） |
| `<meta lang>` | `zh-CN` |
| `<meta viewport>` | `width=device-width, initial-scale=1` |
| `hreflang` | 当前只有中文，未来多语言时添加 |
| `<link rel="icon">` | SVG favicon + ICO fallback |
| `<link rel="apple-touch-icon">` | iOS 主屏图标 |
| `<link rel="manifest">` | Web App Manifest (PWA 预留) |
| 语义化 HTML | `<article>`, `<time>`, `<nav>`, `<main>`, `<aside>` 等 |

---

## 八、部署架构

### 8.1 部署流程全景

```
本地工作站
    │
    ├── Step 1: 构建
    │   python build/build.py
    │   → deploy/ 目录 (完整静态网站)
    │
    ├── Step 2: 部署到 GitHub Pages
    │   deploy_scripts/deploy_pages.sh
    │   → git subtree push deploy/ → gh-pages 分支
    │   → GitHub Pages 自动部署 (~1-2 分钟)
    │
    ├── Step 3: 同步图片到 R2
    │   python media/sync_to_r2.py
    │   → 增量上传原图 + 缩略图到 R2
    │
    └── Step 4: 清除 CDN 缓存
        deploy_scripts/purge_cache.sh
        → Cloudflare API Purge All

            ┌────────────────────┐
            │   GitHub Pages     │  ← HTML/CSS/JS/JSON
            │   (gh-pages 分支)  │
            └────────┬───────────┘
                     │
            ┌────────┴───────────┐
            │   Cloudflare CDN   │  ← 全球边缘缓存
            │                    │
            │  路由规则:          │
            │  /images/*         │──────→ Cloudflare Worker → R2
            │  /*                │──────→ GitHub Pages Origin
            └────────┬───────────┘
                     │
                     ▼
            ┌────────────────────┐
            │     浏览器          │
            │  archive.suijisui.uk│
            └────────────────────┘
```

### 8.2 缓存策略

| 资源类型 | Cloudflare Edge Cache | Browser Cache | 更新机制 |
|---------|----------------------|---------------|---------|
| HTML 页面 | 1 小时 | 5 分钟 | 部署后 Purge All |
| CSS (`style.{hash}.css`) | 1 年 | 1 年 | 文件名含 hash，变更即换名 |
| JS (`app.{hash}.js`) | 1 年 | 1 年 | 同上 |
| JS 模块 (其他) | 7 天 | 7 天 | 部署后 Purge All |
| `/data/*.json` | 1 小时 | 10 分钟 | 部署后 Purge All |
| `/images/*` (原图) | 1 年 | 1 年 | immutable，永不变更 |
| `/images/*` (缩略图) | 1 年 | 1 年 | immutable，永不变更 |

**Cache-Control 头注入**:

- HTML: 通过 Cloudflare Page Rules 设置
- CSS/JS: 构建时在 HTML 中引用 hash 文件名，Cloudflare 默认缓存
- JSON: 通过 Cloudflare Page Rules 设置 `/data/*`
- 图片: 通过 Cloudflare Worker 添加 `Cache-Control: public, max-age=31536000, immutable`

### 8.3 更新策略

**日常更新**（新增动态数据）:

```
1. 更新 SQLite 数据库 (新增动态)
2. 下载新图片到 images/
3. python build/build.py            → 重新构建
4. python media/sync_to_r2.py       → 增量同步新图片 + 缩略图
5. deploy_scripts/deploy_pages.sh   → 推送到 gh-pages
6. deploy_scripts/purge_cache.sh    → 清除 CDN 缓存
```

**样式/功能更新**（代码变更）:

```
1. 修改 src/ 中的源代码
2. python build/build.py            → 重新构建
3. deploy_scripts/deploy_pages.sh   → 推送到 gh-pages
4. deploy_scripts/purge_cache.sh    → 清除 CDN 缓存
   (无需同步 R2，图片未变)
```

**一键完整部署**:

```
deploy_scripts/full_deploy.sh
→ 自动执行: build → sync_r2 → deploy_pages → purge_cache → verify
```

### 8.4 回滚策略

**代码回滚**:

```
1. git revert 或 git reset 到上一个正常版本
2. python build/build.py
3. deploy_scripts/deploy_pages.sh
```

**数据回滚**:

```
1. 从备份恢复 SQLite 数据库
   cp data/sui-archive.db.bak.{date} data/sui-archive.db
2. python build/build.py
3. deploy_scripts/deploy_pages.sh
```

**gh-pages 回滚**:

```
1. cd deploy/
2. git log 查看历史
3. git reset --hard {commit} 到上一个正常版本
4. git push origin gh-pages --force
```

**R2 回滚**: R2 中的图片只增不删（同步策略不删除远端文件），因此不需要回滚。即使本地数据库回滚，R2 上的图片仍然存在，不影响旧版网站。

### 8.5 部署验证

每次部署后自动执行验证（`deploy_scripts/verify_deploy.sh`）：

| 检查项 | 方法 | 预期 |
|--------|------|------|
| 首页可达 | `curl -s -o /dev/null -w "%{http_code}"` | 200 |
| 搜索页可达 | 同上 | 200 |
| 最新一条动态详情页可达 | 同上 | 200 |
| dynamics-index.json 可下载且格式正确 | `curl + json.tool` | 有效 JSON |
| 最新图片 CDN 可达 | `curl -I /images/{latest}` | 200, Content-Type 正确 |
| sitemap.xml 格式正确 | `curl + xmllint` | 有效 XML |
| robots.txt 存在 | `curl` | 200 |

---

## 九、自动化

### 9.1 一键构建

```
python build/build.py
```

完整构建：校验 → JSON → 搜索 → 统计 → SEO → 缩略图 → HTML → 资源 → 输出。
增量模式 `--incremental` 跳过未变更的图片处理。

### 9.2 一键部署

```
deploy_scripts/full_deploy.sh
```

依次执行：构建 → R2 同步 → GitHub Pages 部署 → CDN 缓存清除 → 部署验证。

### 9.3 自动同步

**R2 同步脚本** (`media/sync_to_r2.py`):

- 读取 `images/` 目录和 `thumbs/` 目录的所有文件
- 对比 R2 Bucket 中的对象列表
- 仅上传新增和变更的文件（通过文件大小 + 修改时间判断）
- 不删除 R2 已有文件
- 生成同步报告：上传 N 个文件，跳过 M 个文件，总大小 X MB
- 支持 `--dry-run` 预览

### 9.4 自动备份

**数据库备份** (`scripts/backup.py`):

```
执行内容:
  1. PRAGMA wal_checkpoint(TRUNCATE)  — 将 WAL 数据写入主文件
  2. 使用 SQLite Online Backup API 复制数据库（不锁库）
  3. 压缩备份文件: sui-archive.db.bak.{YYYYMMDD}.gz
  4. 保留最近 30 天的备份，删除更早的
  5. 记录备份大小和 SHA-256 校验和
```

**完整归档备份** (每月手动):

```
tar -czf sui-archive-full-{YYYYMMDD}.tar.gz \
    data/ images/ build/ src/ worker/ media/ scripts/
```

### 9.5 自动校验

构建管道的 Step 0 (validate) 每次构建时自动执行。另外可独立运行：

```
python scripts/validate_data.py
```

独立校验脚本执行更全面的检查：

| 检查项 | 说明 |
|--------|------|
| `PRAGMA integrity_check` | 数据库文件完整性 |
| `PRAGMA foreign_key_check` | 外键引用完整性 |
| 图片文件与数据库一致性 | 数据库中有记录但磁盘无文件 → 报告缺失 |
| 磁盘文件与数据库一致性 | 磁盘有文件但数据库无记录 → 报告孤立文件 |
| FTS5 同步检查 | `INSERT INTO posts_fts(posts_fts) VALUES('integrity-check')` |
| 统计一致性 | posts 表行数 vs dynamics-index.json 中的 total |
| SHA-256 校验 | 对已有 sha256 的图片重新计算并比对 |

### 9.6 自动缩略图生成

构建管道的 Step 5 (thumbnails) 自动处理。支持增量模式：

```
python build/build.py --step thumbnails --incremental
```

只处理 `images/` 中新增的图片（检查 thumbs/ 中是否已有对应变体）。

### 9.7 未来 CI/CD 预留方案

当项目迁移到自动化 CI/CD 时（如 GitHub Actions），预设以下工作流：

**工作流 1: 构建与部署**（手动触发 或 push 到 main 分支时）

```
trigger: push to main / workflow_dispatch
steps:
  1. checkout
  2. setup Python + Pillow
  3. python build/build.py
  4. python media/sync_to_r2.py (需要 R2 密钥 secrets)
  5. deploy to gh-pages
  6. purge Cloudflare cache (需要 CF API token secret)
  7. verify deployment
```

**工作流 2: 数据校验**（每日定时）

```
trigger: cron (daily at 03:00 UTC)
steps:
  1. checkout
  2. setup Python
  3. python scripts/validate_data.py
  4. 如果失败 → 发送通知
```

**工作流 3: 自动备份**（每周定时）

```
trigger: cron (weekly Sunday 04:00 UTC)
steps:
  1. checkout
  2. python scripts/backup.py
  3. upload backup to artifact storage
```

**CI/CD 迁移注意事项**:

- R2 Access Key 和 Cloudflare API Token 存储为 GitHub Secrets
- 数据库文件 (`sui-archive.db`) 需要通过 Git LFS 或外部存储提供
- 图片目录 (`images/`) 体积较大（~2.2GB），不适合 GitHub Actions 直接处理，建议 R2 同步在本地执行
- 构建步骤（HTML/JSON/CSS/JS）适合 CI 环境

---

## 附录 A：构建产物文件清单

| 文件/目录 | 来源步骤 | 说明 |
|----------|---------|------|
| `index.html` | Step 6 | 首页 |
| `search.html` | Step 6 | 搜索页 |
| `gallery.html` | Step 6 | 画廊页 |
| `timeline.html` | Step 6 | 时间轴页 |
| `stats.html` | Step 6 | 统计页 |
| `tags.html` | Step 6 | 标签列表页 |
| `about.html` | Step 6 | 关于页 |
| `404.html` | Step 6 | 自定义 404 |
| `d/{id}/index.html` ×N | Step 6 | 动态详情页 |
| `tag/{slug}/index.html` ×N | Step 6 | 标签详情页 |
| `style.{hash}.css` | Step 7 | 合并样式表 |
| `js/*.js` | Step 7 | JavaScript 模块 |
| `data/dynamics-index.json` | Step 1 | 年份索引 |
| `data/dynamics-{year}.json` ×N | Step 1 | 年份数据 |
| `data/detail/{uuid}.json` ×N | Step 1 | 详情数据 |
| `data/search-index.json` | Step 2 | 搜索索引 |
| `data/tag-index.json` | Step 2 | 标签索引 |
| `data/stats.json` | Step 3 | 统计数据 |
| `data/images-manifest.json` | Step 5 | 图片清单 |
| `assets/*` | Step 7 | 静态资源 |
| `sitemap.xml` | Step 4 | 站点地图 |
| `robots.txt` | Step 4 | 爬虫规则 |
| `feed.xml` | Step 4 | RSS（可选） |
| `build-info.json` | Step 8 | 构建报告 |

## 附录 B：前端模块依赖关系

```
app.js
  ├── config.js
  ├── router.js
  │     └── state.js
  ├── api.js
  │     └── config.js
  ├── dom.js
  └── (按页面动态加载)
        ├── timeline.js
        │     ├── api.js
        │     ├── post-card.js
        │     │     ├── dom.js
        │     │     └── lazy-load.js
        │     └── infinite-scroll.js
        ├── search.js
        │     ├── api.js
        │     ├── post-card.js
        │     └── tag-filter.js
        ├── gallery.js
        │     ├── api.js
        │     ├── lazy-load.js
        │     └── lightbox.js
        ├── post-detail.js
        │     ├── api.js
        │     ├── lightbox.js
        │     └── share.js
        └── stats.js
              └── api.js
```

## 附录 C：与现有文档的变更说明

本文档对 ARCHITECTURE.md 和 PROJECT_SPEC.md 中的以下内容进行了细化和扩展：

| 原文档 | 原内容 | 本文档变更 |
|--------|--------|---------|
| ARCHITECTURE §2.2 | 7 步构建管道 (基于 JSON) | 扩展为 13 步 (Step 0-12)，基于 SQLite |
| ARCHITECTURE §3.1 | 基础目录结构 | 细化为完整仓库目录 + 构建产物目录 |
| ARCHITECTURE §4.3 | 构建产物结构 | 增加 detail/ 子目录和缩略图变体 |
| ARCHITECTURE §5.1 | 5 个页面 | 扩展为 10 个页面 |
| ARCHITECTURE §5.3 | 5 个 JS 模块 | 扩展为 3 层 18 个模块 |
| ARCHITECTURE §6.1 | 图片命名 | 增加缩略图变体命名规范 |
| ARCHITECTURE §7 | 部署架构 | 增加缓存策略、回滚策略、验证流程 |
| PROJECT_SPEC §5 | 构建产物 JSON | 增加 detail JSON、search-index、tag-index、stats 结构定义 |

---

> **本文件是活文档。如需修改，必须同步更新 ARCHITECTURE.md 对应章节。**
