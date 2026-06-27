# PROJECT_SPEC.md — SUI Archive 项目宪法

> **所有开发者（包括 AI Agent）在开始任何工作前，必须先阅读本文件。**
>
> 本文件是项目的最高权威。任何代码、配置、设计如与本文件冲突，以本文件为准。

---

## 1. 项目使命

SUI Archive 是虚拟主播「岁己 SUI」的数字档案馆。

永久保存她在所有平台公开发布的内容（动态、图片、视频信息），即使原平台删除，也能继续访问。

**不是粉丝站，不是博客，不是社交工具。是档案馆。**

---

## 2. 架构原则（不可违反）

1. **本地数据是唯一真实数据源** — 网站和云端都是数据的展示副本
2. **完全静态** — 零服务端逻辑，所有内容由构建管道在本地生成
3. **三层解耦** — 数据层(JSON)、表现层(HTML/CSS/JS)、媒体层(图片) 可独立替换
4. **图片路径抽象** — 前端只用 `/images/{filename}`，永不出现存储后端地址
5. **零框架依赖** — 前端使用原生 HTML + CSS + JavaScript，不用 React/Vue/Angular
6. **零平台锁定** — 任何组件可替换为同类替代品，不影响其他组件

---

## 3. 技术栈

| 层级 | 技术 | 备注 |
|------|------|------|
| 数据源 | SQLite 数据库 + 本地图片文件 | F: 盘永久保存 |
| 数据库 | SQLite (WAL 模式) | `data/sui-archive.db`，唯一真实数据源 |
| 构建工具 | Python | `build/build.py`，从 SQLite 生成 JSON |
| 网站托管 | GitHub Pages | `gh-pages` 分支 |
| 图片存储 | Cloudflare R2 | `sui-archive-images` bucket |
| 图片代理 | Cloudflare Worker | `/images/*` → R2 |
| CDN | Cloudflare | 全站加速 |
| 域名 | `archive.suijisui.uk` | |
| 前端 | 原生 HTML + CSS + JS | ES Modules, 无框架 |

---

## 4. 目录规范

```
sui-archive/                     # 仓库根目录
├── PROJECT_SPEC.md              # 本文件 (项目宪法)
├── ARCHITECTURE.md              # 系统架构设计文档
├── DATABASE_SPEC.md             # SQLite 数据库设计规范
├── BUILD_SPEC.md                # 构建系统与前端工程设计规范
├── README.md
│
├── data/                        # 数据层 — 数据库与数据文件
│   ├── sui-archive.db           # SQLite 数据库 (Single Source of Truth)
│   ├── sui-archive.db-wal       # WAL 日志 (运行时自动生成)
│   ├── sui-archive.db-shm       # 共享内存 (运行时自动生成)
│   └── schema.sql               # 数据库 DDL (版本控制)
│
├── images/                      # 媒体层 — 只放图片文件
│   └── *.png / *.jpg / *.gif
│
├── build/                       # 构建管道 — Python 脚本
│   ├── build.py
│   ├── config.yaml
│   └── steps/
│
├── src/                         # 网站源代码 — HTML/CSS/JS
│   ├── html/
│   ├── css/
│   ├── js/
│   └── assets/
│
├── worker/                      # Cloudflare Worker
├── media/                       # 媒体同步脚本
├── deploy/                      # 部署脚本 + 构建产物 (gitignored, 由 build 生成)
├── scripts/                     # 辅助工具
└── .gitignore
```

**规则**:
- `data/` 只放 SQLite 数据库文件和 schema.sql，不放脚本、不放图片
- `images/` 只能放图片文件，不放其他任何东西
- `src/` 只放源代码，构建产物输出到 `deploy/`
- `deploy/` 是构建产物目录，推送到 `gh-pages` 分支，不提交到 `main`

---

## 5. 数据 Schema

**数据库完整定义见 `DATABASE_SPEC.md`**——该文档是项目的唯一数据库标准，包含所有表结构、字段、约束、索引和数据迁移规范。

### 5.1 数据库概览

| 表 | 职责 |
|----|------|
| `platforms` | 平台信息（B站、微博等） |
| `authors` | 转发原作者信息 |
| `posts` | 核心表，所有动态/帖子 |
| `images` | 图片元数据，关联到 posts |
| `media` | 其他媒体类型（视频、音频） |
| `tags` / `post_tags` | 标签系统 |
| `post_media` | 帖子与媒体的多对多关联 |
| `post_stats` | 统计数据时序表 |
| `posts_fts` | FTS5 全文搜索虚拟表 |
| `schema_migrations` | Schema 版本管理 |

### 5.2 构建产物 JSON 文件

| 文件 | 内容 | 大小预估 |
|------|------|---------|
| `dynamics-index.json` | 年份索引、每年动态数、日期范围 | < 10KB |
| `dynamics-{year}.json` | 该年所有动态的结构化数据 | 300KB - 1MB |
| `search-index.json` | 搜索索引 (id, text截断, type, date, has_images) | 1-2MB |
| `images-manifest.json` | 图片文件名 → post 映射 | < 100KB |

> **注意**: 构建产物由 Python 管道从 SQLite 数据库生成，前端只消费这些 JSON 文件，不直接访问数据库。

---

## 6. 命名规范

### 6.1 图片文件

```
{dynamic_id}_{index:02d}@{quality}.{ext}
```

- `dynamic_id`: B站动态ID
- `index`: 从 `00` 开始，两位补零
- `quality`: `@original` (原创原图) 或 `@repost` (转发图片)
- `ext`: 保持原始扩展名 (`.png`, `.jpg`, `.gif`)

### 6.2 代码文件

- Python: `snake_case.py`
- JavaScript: `camelCase.js`
- HTML: `kebab-case.html`
- CSS: `kebab-case.css`
- 配置: `kebab-case.yaml`

### 6.3 Git 规范

- 分支: `main` (源代码), `gh-pages` (构建产物)
- Commit message: `type: description` (如 `build: add search index generation`)
- 类型: `feat`, `fix`, `build`, `data`, `style`, `docs`, `refactor`

---

## 7. 图片引用规则

### 7.1 前端代码中

```html
<!-- 正确 -->
<img src="/images/1210001435340570626_00@original.png">

<!-- 错误 — 绝对不允许出现 -->
<img src="https://xxx.r2.cloudflarestorage.com/...">
<img src="https://i0.hdslb.com/bfs/new_dyn/...">
```

### 7.2 dynamics.json 中

`content.images[].url` 字段保留原始 B站 CDN URL（作为溯源参考），但前端渲染时**必须使用本地文件名**构造 `/images/` 路径，不直接使用此 URL。

---

## 8. 部署方式

```
main 分支:  源代码 + data/ + images/
gh-pages:   deploy/ 目录内容 (由 build 生成)

部署命令:
  python build/build.py          # 构建
  python media/sync_to_r2.py     # 同步图片到 R2
  bash deploy/deploy_pages.sh    # 推送到 gh-pages
```

---

## 9. 开发规范

### 9.1 新增模块前

1. 阅读本文件 (PROJECT_SPEC.md)
2. 阅读 ARCHITECTURE.md 中对应章节
3. 阅读 DATABASE_SPEC.md 了解数据模型
4. 阅读 BUILD_SPEC.md 了解构建管道和前端工程规范
5. 确认新模块放在正确的目录
6. 确认不违反任何架构原则

### 9.2 修改数据前

- **永远不要直接编辑 data/sui-archive.db**
- 如需修正数据，编写 SQL 迁移脚本放在 `scripts/`
- 迁移脚本必须记录版本号到 `schema_migrations` 表
- 迁移脚本必须是可重复执行的（幂等性）

### 9.3 修改前端前

- 不使用任何 npm 包
- 不使用任何构建打包工具 (webpack, vite, esbuild)
- CSS 写在 `src/css/` 中，不使用预处理器
- JS 使用 ES Modules，不使用 TypeScript

### 9.4 新增平台数据时

1. 在 `platforms` 表中注册新平台
2. 在 `build/steps/` 下新增该平台的 normalizer（将原始数据导入 posts 表）
3. normalizer 输出必须符合 `DATABASE_SPEC.md` 中 posts 表的字段规范
4. 前端时间轴增加平台筛选器

---

## 10. 禁止事项

- ❌ 不得在前端代码中出现任何存储后端地址
- ❌ 不得使用 React / Vue / Angular / Svelte 等框架
- ❌ 不得使用 npm / yarn / pnpm
- ❌ 不得将构建产物提交到 main 分支
- ❌ 不得直接编辑 data/sui-archive.db（必须通过迁移脚本修改）
- ❌ 不得在 HTML 中使用内联 JavaScript
- ❌ 不得引入任何需要服务端运行的组件
- ❌ 不得使用第三方 CDN 加载前端依赖（字体除外）
- ❌ 不得在代码中硬编码 API Key 或密钥

---

> **本文件是活文档。如需修改，必须同步更新 ARCHITECTURE.md 对应章节。**
