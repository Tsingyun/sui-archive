# SUI Archive — 系统架构设计文档

> **文档版本**: 2.0.0  
> **创建时间**: 2026-06-28  
> **最近更新**: 2026-06-28 (同步 BUILD_SPEC.md)  
> **状态**: 与 BUILD_SPEC.md / DATABASE_SPEC.md / PROJECT_SPEC.md 共同构成项目规范体系  
> **作用域**: 整个项目的架构标准。各模块的详细设计见对应的专项规范文档。

---

## 一、整体架构

### 1.1 架构模型

```
┌──────────────────────────────────────────────────────────────┐
│                      本地工作站 (Single Source of Truth)       │
│                                                              │
│   ┌──────────┐    ┌────────────┐    ┌───────────────────┐   │
│   │ data/    │───▶│ build/     │───▶│ deploy/           │   │
│   │ 原始数据  │    │ 构建管道    │    │ 网站产物           │   │
│   └──────────┘    └────────────┘    └───────────────────┘   │
│        │                                     │              │
│        │          ┌────────────┐             │              │
│   ┌──────────┐   │ media/     │             │              │
│   │ images/  │──▶│ 媒体同步    │             │              │
│   │ 原始图片  │   └────────────┘             │              │
│   └──────────┘        │                     │              │
└────────────────────────┼─────────────────────┼──────────────┘
                         │                     │
                         ▼                     ▼
              ┌──────────────────┐   ┌──────────────────┐
              │ Cloudflare R2    │   │ GitHub Pages      │
              │ 图片对象存储      │   │ 静态网站托管       │
              └────────┬─────────┘   └────────┬─────────┘
                       │                      │
                       ▼                      ▼
              ┌─────────────────────────────────────────┐
              │        Cloudflare CDN / Edge            │
              │  archive.suijisui.uk                    │
              │                                         │
              │  /images/*  →  Worker  →  R2            │
              │  /*         →  GitHub Pages             │
              └─────────────────────────────────────────┘
```

### 1.2 核心原则

**本地优先**: 本地数据是唯一的真实数据源。网站、R2 都只是数据的展示副本和分发副本。即使 GitHub、Cloudflare 全部不可用，本地数据完整存在。

**构建时生成**: 所有 HTML、JSON、索引在构建时由 Python 脚本生成。运行时零服务端逻辑。网站是纯静态产物。

**解耦三层**: 数据层（JSON）、表现层（HTML/CSS/JS）、媒体层（图片）三者完全独立。任意一层可单独替换，不影响其他层。

**图片路径抽象**: 前端统一使用 `/images/{filename}` 引用图片。前端不知道也不关心图片实际存在 R2、NAS 还是本地。切换存储后端只需修改 Cloudflare Worker 路由，前端代码零改动。

**零框架依赖**: 前端不使用 React/Vue/Angular 等框架。使用原生 HTML + CSS + JavaScript。原因：框架每 3-5 年过时，原生 Web 标准 20 年兼容。数字档案馆必须能存活 10 年以上。

---

## 二、系统组成

整个系统由五个独立模块组成，每个模块可单独替换：

### 2.1 数据模块 (Data)

**职责**: 存储所有原始动态数据和图片文件。

- `data/sui-archive.db` — SQLite 数据库，唯一真实数据源 (Single Source of Truth)
- `images/` — 所有图片文件，按统一命名规范存储

数据模块不做任何转换、过滤或排序。它只负责存储。数据质量由上游爬虫保证，由构建管道的校验步骤检查。数据库完整设计见 `DATABASE_SPEC.md`。

### 2.2 构建管道 (Build Pipeline)

**职责**: 将 SQLite 数据库和原始图片转换为可部署的静态网站。

**完整设计见 `BUILD_SPEC.md`**——该文档是构建系统和前端工程的唯一标准。

构建管道是 Python 脚本 (`build/build.py`)，共 13 步（Step 0-12）：

| 步骤 | 模块 | 职责 |
|------|------|------|
| 0. 校验 | `validate.py` | 数据库完整性、外键、Schema 版本检查 |
| 1. JSON | `json_gen.py` | 从 SQLite 查询，生成按年分片的 JSON + 详情 JSON |
| 2. 搜索 | `search_gen.py` | 生成搜索索引和标签索引 |
| 3. 统计 | `stats_gen.py` | 聚合查询生成统计摘要 |
| 4. SEO | `sitemap_gen.py` | 生成 sitemap.xml、robots.txt、RSS |
| 5. 缩略图 | `thumbnails.py` | 生成 WebP 缩略图变体 (300/600/1200px) |
| 6. 页面 | `pages.py` | 生成所有 HTML 页面（含动态详情页存根） |
| 7. 资源 | `assets.py` | 合并 CSS、复制 JS 模块、计算内容 hash |
| 8. 输出 | `output.py` | 原子替换写入 deploy/ 目录 |
| 9. 部署 | `deploy_pages.sh` | 推送到 gh-pages 分支 |
| 10. 同步 | `sync_to_r2.py` | 增量同步图片到 R2 |
| 11. 缓存 | `purge_cache.sh` | 清除 Cloudflare CDN 缓存 |
| 12. 验证 | `verify_deploy.sh` | HTTP 验证部署可达性 |

每个步骤可单独运行（`--step` 参数），支持增量模式（`--incremental`）。

### 2.3 媒体同步 (Media Sync)

**职责**: 将本地图片同步到 Cloudflare R2。

- `media/sync_to_r2.py` — 增量同步脚本
- `media/r2_config.json` — R2 连接配置

同步策略：
- 对比本地文件名与 R2 对象列表
- 仅上传新增和变更的文件
- 不删除 R2 上已有但本地不存在的文件（防止误删）
- 生成同步报告日志

### 2.4 部署管道 (Deploy)

**职责**: 将构建产物部署到 GitHub Pages。

- `deploy/deploy_pages.sh` — 将 deploy/ 目录推送到 gh-pages 分支

部署策略：
- 使用独立的 `gh-pages` 分支（不使用 docs/ 目录，保持 main 分支干净）
- 使用 `git subtree push` 或 `gh-pages` 工具
- 支持 dry-run 模式预览变更

### 2.5 Cloudflare Worker (Image Proxy)

**职责**: 作为图片的反向代理层，将 `/images/*` 请求转发到 R2。

- `worker/index.js` — Worker 源代码
- `worker/wrangler.toml` — Worker 部署配置

Worker 逻辑：
```
请求 → 解析路径 → 匹配 R2 对象 → 返回图片
                                  → 404 时返回占位图
                                  → 添加 CORS 头
                                  → 添加缓存头 (1年)
```

Worker 是解耦层的核心。更换 R2 为其他存储时，只需修改 Worker 内部逻辑，前端完全无感知。

---

## 三、目录结构

### 3.1 仓库目录 (Git Repository)

```
sui-archive/
├── PROJECT_SPEC.md              # 项目宪法 — 所有开发者的必读文档
├── ARCHITECTURE.md              # 本文档 — 详细架构设计
├── README.md                    # 项目简介与快速开始
│
├── data/                        # 数据层
│   ├── dynamics.json            # 主数据文件 (Single Source of Truth)
│   └── schema.json              # 数据 schema 定义
│
├── images/                      # 媒体层 — 所有原始图片
│   ├── {id}_00@original.png
│   ├── {id}_01@original.jpg
│   └── {id}_100@repost.jpg
│
├── build/                       # 构建管道
│   ├── build.py                 # 构建入口
│   ├── config.yaml              # 构建配置
│   ├── steps/                   # 构建步骤模块
│   │   ├── __init__.py
│   │   ├── loader.py            # 数据加载与校验
│   │   ├── normalizer.py        # 数据规范化
│   │   ├── chunker.py           # 数据分片
│   │   ├── search.py            # 搜索索引生成
│   │   ├── manifest.py          # 图片清单生成
│   │   ├── assets.py            # 静态资源处理
│   │   └── writer.py            # 产物输出
│   └── utils/
│       ├── __init__.py
│       └── helpers.py           # 通用工具函数
│
├── src/                         # 网站源代码
│   ├── html/                    # HTML 模板
│   │   ├── index.html           # 首页/时间轴
│   │   ├── dynamic.html         # 单条动态页
│   │   ├── search.html          # 搜索页
│   │   ├── gallery.html         # 图片画廊
│   │   └── about.html           # 关于页
│   ├── css/
│   │   └── style.css            # 全站样式
│   ├── js/
│   │   ├── app.js               # 主应用逻辑
│   │   ├── timeline.js          # 时间轴模块
│   │   ├── search.js            # 搜索模块
│   │   ├── gallery.js           # 图片画廊模块
│   │   └── lightbox.js          # 图片灯箱
│   └── assets/                  # 图标、字体等静态资源
│       ├── favicon.svg
│       └── og-image.png
│
├── worker/                      # Cloudflare Worker
│   ├── index.js
│   ├── wrangler.toml
│   └── package.json
│
├── media/                       # 媒体同步
│   ├── sync_to_r2.py
│   └── r2_config.yaml
│
├── deploy/                      # 部署脚本
│   └── deploy_pages.sh
│
├── scripts/                     # 辅助工具
│   ├── validate_data.py         # 数据校验
│   └── stats.py                 # 统计报告
│
└── .gitignore
```

### 3.2 设计要点

- `data/` 和 `images/` 在仓库根目录，方便 build 脚本直接引用
- `src/` 只存放源代码，不存放构建产物
- `deploy/` 目录是构建产物目录（由 build 生成），通过 `git subtree push` 推送到 gh-pages
- `worker/` 独立目录，有自己的 `package.json`，可独立部署
- 所有配置文件使用 YAML 格式（比 JSON 支持注释，比 TOML 更通用）

---

## 四、数据流

### 4.1 完整数据流

```
  ┌─────────────┐
  │ B站 API     │  (爬虫已完成，不再开发)
  └──────┬──────┘
         │
         ▼
  ┌─────────────────────────────────────┐
  │ data/sui-archive.db                 │  ← 本地唯一真实数据源
  │ images/*.png/jpg/gif                │
  └──────────────┬──────────────────────┘
                 │
         ┌───────┴───────┐
         │               │
         ▼               ▼
  ┌─────────────┐ ┌──────────────┐
  │ build.py    │ │ sync_to_r2.py│
  │ 构建管道     │ │ 媒体同步      │
  └──────┬──────┘ └──────┬───────┘
         │               │
         ▼               ▼
  ┌─────────────┐ ┌──────────────┐
  │ deploy/     │ │ Cloudflare   │
  │ 静态网站产物 │ │ R2           │
  └──────┬──────┘ └──────┬───────┘
         │               │
         ▼               │
  ┌─────────────┐        │
  │ gh-pages    │        │
  │ 分支推送     │        │
  └──────┬──────┘        │
         │               │
         └───────┬───────┘
                 ▼
         ┌──────────────┐
         │ Cloudflare   │
         │ CDN Edge     │
         └──────────────┘
```

### 4.2 构建管道内部数据流

**详细流程图见 `BUILD_SPEC.md` 第一章。**

```
data/sui-archive.db
        │
        ▼
   [0. validate.py]
   PRAGMA integrity_check + foreign_key_check
   检查 schema_migrations 版本
        │
        ▼
   [1. json_gen.py]
   查询 posts + post_media + images + post_stats
   → dynamics-index.json (年份索引)
   → dynamics-{year}.json (按年分片)
   → detail/{uuid}.json (单条详情)
        │
        ▼
   [2. search_gen.py]
   查询 posts + post_tags + tags
   → search-index.json (搜索索引)
   → tag-index.json (标签索引)
        │
        ▼
   [3. stats_gen.py]
   聚合查询 → stats.json (统计数据)
        │
        ▼
   [4. sitemap_gen.py]
   → sitemap.xml + robots.txt + feed.xml
        │
        ▼
   [5. thumbnails.py]
   扫描 images/ → 生成 WebP 缩略图 (w300/w600/w1200)
   → images-manifest.json (图片清单)
        │
        ▼
   [6. pages.py]
   读取 src/html/ 模板 + 数据库数据
   → 所有 HTML 页面 (含 N 个动态详情存根)
        │
        ▼
   [7. assets.py]
   合并 CSS → style.{hash}.css
   复制 JS 模块 → js/
   计算内容 hash, 注入构建信息
        │
        ▼
   [8. output.py]
   原子替换 _build/ → deploy/
   → build-info.json (构建报告)
```

### 4.3 构建产物结构

**详细产物目录见 `BUILD_SPEC.md` 附录 A。**

```
deploy/                          # ← 此目录推送到 gh-pages
├── index.html                   # 首页
├── search.html                  # 搜索页
├── gallery.html                 # 图片画廊
├── timeline.html                # 时间轴页
├── stats.html                   # 统计页
├── tags.html                    # 标签列表页
├── about.html                   # 关于页
├── 404.html                     # 自定义 404
├── style.{hash}.css             # 合并后的样式表 (内容 hash)
├── js/                          # JavaScript ES 模块
├── data/
│   ├── dynamics-index.json      # 年份索引 + 全局元数据
│   ├── dynamics-2022.json       # 2022年动态
│   ├── ...
│   ├── dynamics-2026.json
│   ├── detail/                  # 单条动态详情 JSON
│   ├── search-index.json        # 搜索索引
│   ├── tag-index.json           # 标签索引
│   ├── stats.json               # 统计数据
│   └── images-manifest.json     # 图片清单
├── assets/
│   ├── favicon.svg
│   └── og-image.png
├── sitemap.xml
├── robots.txt
└── build-info.json              # 构建报告
```

### 4.4 前端数据加载流程

```
用户访问 archive.suijisui.uk
        │
        ▼
浏览器加载 index.html
        │
        ▼
JS 请求 /data/dynamics-index.json
        │ 获取年份列表、每年动态数、日期范围
        │
        ▼
按用户浏览位置，按需加载 /data/dynamics-{year}.json
        │ 只加载当前可见年份的数据
        │
        ▼
用户搜索时，加载 /data/search-index.json
        │ 客户端全文搜索
        │
        ▼
图片引用 /images/{filename}
        │ Cloudflare Worker → R2
```

---

## 五、网站目录规划

### 5.1 页面规划

**详细页面设计见 `BUILD_SPEC.md` 第四章。**

| 页面 | URL | 职责 |
|------|-----|------|
| 首页 | `/` | 时间轴视图，最新 50 条动态，无限滚动，年份/类型筛选 |
| 动态详情 | `/d/{platform_post_id}` | 完整内容：全文、全尺寸图片、统计、标签、分享 |
| 搜索 | `/search` | 全文搜索 + 标签搜索 + 高级筛选 |
| 图片画廊 | `/gallery` | 瀑布流展示所有图片，灯箱放大，年份筛选 |
| 时间轴 | `/timeline` | 年-月-日层级浏览，可视化时间线 |
| 统计 | `/stats` | 数据总览：热力图、类型分布、月度趋势、Top 排行 |
| 标签列表 | `/tags` | 所有标签的云视图，按分类分组 |
| 标签详情 | `/tag/{slug}` | 单个标签下的所有动态 |
| 关于 | `/about` | 项目介绍、数据来源、技术说明 |
| 404 | `/*` | 自定义错误页，搜索建议，导航回首页 |

### 5.2 URL 设计规范

- 所有 URL 使用短路径，无文件扩展名
- 动态详情页使用动态 ID：`/d/1218285761518895113`
- 搜索使用 query 参数：`/search?q=keyword&type=DRAW`
- 画廊使用 query 参数：`/gallery?year=2024&page=2`
- 不使用 hash routing (`#/`)，保证链接可分享、可书签

### 5.3 前端架构

**详细模块设计见 `BUILD_SPEC.md` 第三章。**

前端使用原生 HTML + CSS + JavaScript，不使用任何框架。共 18 个 JS 模块，分为三层：

- **核心层**: `app.js`、`config.js`、`router.js`、`state.js`、`api.js`、`dom.js`、`i18n.js`
- **功能层**: `timeline.js`、`post-card.js`、`post-detail.js`、`search.js`、`gallery.js`、`lightbox.js`、`tag-filter.js`、`infinite-scroll.js`、`lazy-load.js`、`stats.js`、`share.js`

CSS 按职责拆分为 7 个文件，构建时合并为 `style.{hash}.css`。

设计为 ES Modules，通过 `<script type="module">` 加载。不使用打包工具（构建时直接复制），保证代码可调试、可维护。非当前页面的模块通过 `import()` 动态加载。

---

## 六、媒体目录规划

### 6.1 图片命名规范

```
{dynamic_id}_{index:02d}@{quality}.{ext}
```

| 部分 | 说明 | 示例 |
|------|------|------|
| `dynamic_id` | B站动态ID | `1218285761518895113` |
| `index` | 图片序号，两位补零 | `00`, `01`, `02` |
| `quality` | 质量标识 | `@original`(原创原图), `@repost`(转发图片) |
| `ext` | 原始文件扩展名 | `.png`, `.jpg`, `.gif` |

示例：
```
1210001435340570626_00@original.png   — 原创动态第1张图(原图)
1210001435340570626_01@original.png   — 原创动态第2张图(原图)
1217759413282013185_100@repost.png    — 转发动态的原内容第1张图
1217759413282013185_101@repost.jpg    — 转发动态的原内容第2张图
```

**缩略图变体** (构建时自动生成, 详见 `BUILD_SPEC.md` 第五章):
```
1210001435340570626_00@original_w1200.webp  — 1200px WebP
1210001435340570626_00@original_w600.webp   — 600px WebP
1210001435340570626_00@original_w300.webp   — 300px WebP (缩略图)
1210001435340570626_02@original_poster.webp — GIF 静态海报帧
```

### 6.2 图片清单 (Image Manifest)

构建时生成 `images-manifest.json`，记录每张图片与动态的关联关系：

```json
{
  "1210001435340570626": {
    "images": [
      {"file": "1210001435340570626_00@original.png", "size": 6150, "width": 4042, "height": 2560},
      {"file": "1210001435340570626_01@original.png", "size": 2342, "width": 2028, "height": 1500}
    ]
  }
}
```

前端通过 manifest 查询某条动态关联的图片文件，而不是在 dynamics.json 中冗余存储文件名。

### 6.3 R2 存储结构

```
Bucket: sui-archive-images
├── 1210001435340570626_00@original.png
├── 1210001435340570626_01@original.png
└── ...
```

R2 使用扁平结构（无子目录），文件名与本地完全一致。R2 对象设置：
- `Content-Type`: 根据扩展名自动识别
- `Cache-Control`: `public, max-age=31536000, immutable`（图片永不变更）

---

## 七、部署架构

### 7.1 DNS 配置

```
archive.suijisui.uk
    │
    ├── A / AAAA  →  Cloudflare Proxy (橙色云)
    │
    └── Cloudflare 路由规则:
        │
        ├── /images/*  →  Worker (image-proxy)  →  R2
        │
        └── /*         →  GitHub Pages Origin
```

### 7.2 Cloudflare 配置

**Worker**: `image-proxy`
- 绑定路由: `archive.suijisui.uk/images/*`
- 绑定 R2 Bucket: `sui-archive-images`
- 缓存策略: Edge Cache 1年，Browser Cache 1年

**Page Rules**:
- `archive.suijisui.uk/*`: Browser Cache TTL 1天（HTML）
- `archive.suijisui.uk/data/*`: Browser Cache TTL 1小时（JSON 数据）
- `archive.suijisui.uk/style.css`: Browser Cache TTL 7天（CSS/JS）

### 7.3 GitHub Pages 配置

- 仓库: `Tsingyun/sui-archive`
- Pages Source: `gh-pages` branch / root
- 不使用 `docs/` 目录（保持 main 分支干净）
- 自定义域名: `archive.suijisui.uk`
- 启用 HTTPS: 通过 Cloudflare（GitHub 自带证书仅备用）

### 7.4 请求路径示例

```
用户浏览器
    │
    │  GET archive.suijisui.uk/
    │  → Cloudflare → GitHub Pages → index.html
    │
    │  GET archive.suijisui.uk/data/dynamics-index.json
    │  → Cloudflare → GitHub Pages → data/dynamics-index.json
    │
    │  GET archive.suijisui.uk/images/1210001435340570626_00@original.png
    │  → Cloudflare Worker → R2 → 返回图片
    │  → 缓存到 Cloudflare Edge (1年)
```

---

## 八、同步流程

### 8.1 新增数据后的完整同步流程

当有新动态数据需要归档时（手动或未来自动化）：

```
Step 1: 更新本地数据
    更新 data/sui-archive.db (新增动态)
    下载新图片到 images/

Step 2: 构建网站
    python build/build.py
    → 重新生成 deploy/ 目录所有产物

Step 3: 同步图片到 R2
    python media/sync_to_r2.py
    → 增量上传新图片

Step 4: 部署网站
    bash deploy/deploy_pages.sh
    → 推送 deploy/ 到 gh-pages 分支

Step 5: 验证
    访问 archive.suijisui.uk 确认新内容可见
```

### 8.2 一键同步脚本

```bash
#!/bin/bash
# deploy/full_deploy.sh
set -e

echo "=== SUI Archive Full Deploy ==="

echo "[1/3] Building site..."
python -X utf8 build/build.py

echo "[2/3] Syncing images to R2..."
python -X utf8 media/sync_to_r2.py

echo "[3/3] Deploying to GitHub Pages..."
bash deploy/deploy_pages.sh

echo "=== Deploy Complete ==="
```

### 8.3 增量更新策略

- **仅数据变更**: 只需重新运行 build + deploy_pages（图片未变）
- **仅图片新增**: 只需运行 sync_to_r2（网站 JSON 未变）
- **全量更新**: 运行完整三步

---

## 九、备份方案

### 9.1 备份层级

| 层级 | 内容 | 存储位置 | 频率 |
|------|------|----------|------|
| L1 | Git 仓库 (含 data/) | GitHub | 每次提交 |
| L2 | images/ 目录 | 本地 F: 盘 | 实时 (已有文件) |
| L3 | images/ 目录 | Cloudflare R2 | 每次同步 |
| L4 | 完整归档压缩包 | 外部存储 (NAS/网盘) | 每月 |

### 9.2 备份脚本

```bash
# scripts/backup.sh
# 每月运行一次，生成带日期的压缩包
DATE=$(date +%Y%m%d)
tar -czf "sui-archive-backup-${DATE}.tar.gz" \
    data/ images/ build/ src/ worker/ media/
```

### 9.3 恢复流程

- **网站恢复**: `git clone` → `python build/build.py` → `deploy`
- **图片恢复**: 从 R2 批量下载 或 从本地备份复制
- **完整恢复**: 解压 L4 备份压缩包

### 9.4 数据完整性校验

- `data/dynamics.json` 附带 SHA-256 校验和（存储在 `data/checksums.sha256`）
- 每次构建时自动校验，防止数据被意外篡改
- 图片文件使用文件名中的 `dynamic_id` 与数据关联，无需额外校验

---

## 十、安全设计

### 10.1 静态网站安全

由于是纯静态网站，没有服务端，攻击面极小。主要关注点：

**CSP (Content Security Policy)**:
```
Content-Security-Policy:
  default-src 'self';
  img-src 'self' https://i0.hdslb.com;
  style-src 'self' 'unsafe-inline';
  script-src 'self';
  connect-src 'self';
```

通过 Cloudflare Response Headers 注入，不在 HTML meta 中设置（便于集中管理）。

**其他安全头**:
```
X-Content-Type-Options: nosniff
X-Frame-Options: DENY
Referrer-Policy: strict-origin-when-cross-origin
Permissions-Policy: camera=(), microphone=(), geolocation=()
```

### 10.2 API Key 管理

- R2 Access Key 仅存在于本地环境变量，不提交到 Git
- Worker 通过 Cloudflare Dashboard 或 Wrangler Secret 配置
- `.env` 文件加入 `.gitignore`
- `wrangler.toml` 不含任何密钥（使用 `wrangler secret` 管理）

### 10.3 内容安全

- 所有动态文本在构建时进行 XSS 转义（`<`, `>`, `&` → HTML entities）
- 图片 URL 不信任外部来源，仅使用本地 images/ 中的文件
- 转发动态的原作者信息仅作为文本展示，不渲染为链接

---

## 十一、缓存策略

### 11.1 分层缓存

| 资源类型 | Edge Cache | Browser Cache | 更新策略 |
|----------|-----------|---------------|----------|
| HTML 页面 | 1 小时 | 5 分钟 | 每次部署后 Cloudflare Purge |
| CSS / JS | 7 天 | 7 天 | 文件名含 hash，变更即换名 |
| /data/*.json | 1 小时 | 10 分钟 | 每次部署后 Purge |
| /images/* | 1 年 | 1 年 | immutable，永不变更 |

### 11.2 缓存失效策略

**部署后自动 Purge**:
```bash
# deploy/deploy_pages.sh 末尾追加
curl -X POST "https://api.cloudflare.com/client/v4/zones/{zone_id}/purge_cache" \
  -H "Authorization: Bearer ${CF_API_TOKEN}" \
  -d '{"purge_everything":true}'
```

**CSS/JS 版本化**:
- 构建时在文件名中注入内容 hash: `style.a1b2c3d4.css`
- HTML 中引用 hash 后的文件名
- 旧文件在 Edge 缓存过期后自然淘汰

### 11.3 图片缓存优化

- R2 对象设置 `Cache-Control: public, max-age=31536000, immutable`
- Worker 透传 R2 的 Cache-Control 头
- Cloudflare Edge 缓存命中率预期 > 95%（图片不变，只增不删）

---

## 十二、未来扩展方案

### 12.1 新增数据平台

架构设计已预留多平台扩展能力。当需要接入微博、X (Twitter)、YouTube 等平台时：

**数据层扩展**:
```
data/
├── bilibili/
│   ├── dynamics.json          # B站动态 (现有)
│   └── schema.json
├── weibo/
│   ├── posts.json             # 微博帖子
│   └── schema.json
├── twitter/
│   ├── tweets.json
│   └── schema.json
└── youtube/
    ├── videos.json
    └── schema.json
```

**构建管道扩展**: 每个平台有自己的 normalizer 模块，将不同平台的数据格式统一为通用的 ArchiveItem schema。

**前端扩展**: 时间轴增加平台筛选器，画廊增加平台来源标签。

### 12.2 数据量增长

| 数据量级 | 策略调整 |
|---------|---------|
| < 1万条 | 年分片 (当前方案) |
| 1-10万条 | 月分片 `dynamics-2026-06.json` |
| > 10万条 | 引入 SQLite 预生成索引，前端用 sql.js 查询 |
| > 100万条 | 考虑切换为 Astro/Next.js SSG + 服务端增量构建 |

### 12.3 图片量增长

| 图片量级 | 策略调整 |
|---------|---------|
| < 1万张 | 扁平 R2 (当前方案) |
| 1-10万张 | R2 按年月前缀: `2026/06/xxx.png` |
| > 10万张 | 引入缩略图管道，原图+缩略图双版本存储 |
| > 100万张 | 引入 Cloudflare Images 或自建 CDN |

### 12.4 功能扩展

以下功能可通过新增模块实现，不影响现有架构：

- **评论归档**: 新增 `data/comments.json`，前端动态详情页加载评论
- **直播记录**: 新增 `data/streams.json`，时间轴增加直播标记
- **视频字幕/弹幕**: 新增 `data/danmaku/` 目录
- **RSS 订阅**: 构建管道新增 RSS 生成步骤
- **多语言**: HTML 模板系统 + i18n JSON
- **暗色模式**: CSS 变量 + `prefers-color-scheme` 媒体查询

### 12.5 迁移预案

如果未来 GitHub Pages 不可用：
- **Vercel**: `deploy/deploy_vercel.sh`，推送到 Vercel
- **Netlify**: `netlify.toml` 配置，自动从 Git 部署
- **Cloudflare Pages**: Worker 路由改为直接 serve HTML

如果未来 Cloudflare R2 不可用：
- **Backblaze B2**: 修改 Worker 指向 B2
- **AWS S3**: 修改 Worker 指向 S3
- **本地 NAS**: Worker 改为反向代理到 NAS 地址

所有迁移只需修改 Worker 和部署脚本，前端代码零改动。

---

## 十三、为什么这样设计

### 13.1 为什么不用 React/Vue/Next.js？

数字档案馆的生命周期是 10 年以上。过去 10 年，前端框架已经经历了 jQuery → Angular → React → Vue → Svelte 的更替。每 3-5 年，主流框架会有一次大版本破坏性更新。

原生 HTML/CSS/JS 是 Web 标准，20 年前的网页今天仍能正常渲染。对于档案馆这种"设一次，跑十年"的场景，原生技术是唯一可靠的选择。

如果未来确实需要更强的交互性，可以局部引入轻量框架（如 Alpine.js、htmx），而不是全站依赖重型框架。

### 13.2 为什么用 Python 构建而不是 Node.js？

1. 项目中已存在多个 Python 脚本（爬虫、数据处理），保持一致性
2. Python 在数据处理和 JSON 操作方面表现优秀
3. Python 脚本更易读，方便未来不同 AI Agent 理解和修改
4. 构建工具不需要 npm 生态，减少依赖链

### 13.3 为什么图片用 Worker 代理而不是直接引用 R2？

**核心原因：解耦**。

前端代码中出现 `r2.cloudflarestorage.com` 这样的地址意味着平台锁定。一旦需要迁移存储后端，就必须修改所有前端代码和历史 HTML。

Worker 代理模式：前端只写 `/images/xxx.png`，Worker 负责映射到实际存储。迁移时只需修改 Worker（几百行代码），前端零改动。

**附加收益**：
- Cloudflare Edge 缓存图片，全球访问速度一致
- Worker 可以添加 fallback 逻辑（图片不存在时返回占位图）
- 统一 CORS、安全头、日志

### 13.4 为什么用 gh-pages 分支而不是 docs/ 目录？

- `docs/` 目录会污染 main 分支的文件列表
- `gh-pages` 分支与源代码完全隔离
- `main` 分支保持干净，只包含源代码和数据
- 未来切换部署方式时不影响 main 分支

### 13.5 为什么数据按年分片而不是单文件？

1. **加载性能**: 3547 条动态的 JSON 约 3-4MB。单文件意味着用户打开首页就要下载全部数据。年分片后，首屏只需加载 `dynamics-index.json` (几KB) + 当年的数据 (约 800KB)。
2. **可维护性**: 单文件在 Git 中每次修改都会产生 3MB+ 的 diff。分片后每次只影响当年文件。
3. **扩展性**: 数据增长到 10 万条时，只需细化为月分片，不改变架构。

### 13.6 为什么搜索用客户端而不是 Algolia/Meilisearch？

1. 完全静态：不依赖外部搜索服务，避免服务不可用导致搜索失效
2. 零成本：不需要为搜索 API 付费
3. 3500 条动态的搜索索引约 1-2MB，客户端完全可处理
4. 数据量增长后可平滑迁移到月分片索引，无需架构变更

### 13.7 为什么不直接用 Cloudflare Pages？

GitHub Pages 更成熟、更简单、与 Git 工作流集成更紧密。Cloudflare Pages 虽然性能更好，但对于这个规模的静态网站，差异可忽略。

架构设计中已预留了迁移到 Cloudflare Pages 的路径（十二.5 迁移预案），如果未来 GitHub Pages 出现问题，可以无缝切换。

### 13.8 为什么本地数据不做规范化迁移？

当前 `dynamics.json` 存在少量数据质量问题（部分字段为空、text_with_emoji 与 text 重复）。这些问题在**构建管道的 normalizer 步骤**中处理，而不是修改原始数据文件。

原因：原始数据是爬虫的直接产出，修改它就失去了"原始记录"的可追溯性。所有清洗、补全、规范化都在构建时完成，原始数据只增不改。

---

> **本文档结束。**  
> 后续所有开发工作必须以本文档和 `PROJECT_SPEC.md` 为标准。  
> 如需修改架构，必须先更新本文档，经确认后再实施。
