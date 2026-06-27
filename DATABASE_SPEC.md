# SUI Archive — SQLite 数据库设计规范

> **文档版本**: 1.0.0  
> **创建时间**: 2026-06-28  
> **作用域**: 整个项目的唯一数据库标准。第四阶段（JSON 规范）和第五阶段（代码开发）必须遵循本文档。

---

## 一、概述

### 1.1 角色定位

SQLite 数据库取代 `dynamics.json`，成为本地唯一真实数据源（Single Source of Truth）。

网站所有 JSON 文件、搜索索引、统计数据、页面，都由构建管道从数据库生成。数据库不为网页便利而设计——它优先保证数据完整性、可维护性和可迁移性。

### 1.2 当前数据规模

| 类别 | 当前数量 | 10年预估 |
|------|---------|---------|
| 动态 (posts) | 3,547 | ~10,000 |
| 图片 (images) | 1,083 | ~5,000 |
| 平台 (platforms) | 1 | ~5 |
| 标签 (tags) | 0 (待建) | ~200 |
| 转发原作者 (authors) | ~40 | ~200 |
| 统计快照 (post_stats) | 3,547 | ~50,000 |

SQLite 单表可轻松处理百万级数据。当前及预估规模不构成性能瓶颈。

### 1.3 数据库文件

```
data/sui-archive.db        # 主数据库文件
data/sui-archive.db-wal    # WAL 模式日志 (运行时)
data/sui-archive.db-shm    # 共享内存文件 (运行时)
```

启用 WAL 模式以支持并发读取（构建管道读取的同时允许写入）。

---

## 二、设计原则

1. **第三范式 (3NF)** — 消除传递依赖，不允许为查询方便而冗余存储
2. **主键稳定** — 一旦分配，永不变更，永不回收
3. **外键强制** — 所有关联关系通过 FOREIGN KEY 约束，启用 `PRAGMA foreign_keys = ON`
4. **时间格式统一** — 所有时间字段使用 ISO 8601 格式，存储为 TEXT：`YYYY-MM-DDTHH:MM:SS+08:00`
5. **平台无关** — 表结构不绑定任何特定平台，平台特有数据放入 JSON 扩展字段
6. **可扩展字段** — 每张表包含 `platform_metadata` 或 `notes` TEXT 字段（JSON 格式），用于未来扩展，无需修改表结构
7. **Schema 版本化** — 通过 `schema_migrations` 表管理数据库版本，所有变更通过 Migration 脚本执行

---

## 三、数据模型问题与修正建议

在正式设计数据库之前，审查现有数据模型（Phase 2）和当前数据（dynamics.json），发现以下问题：

### 问题 1：`text_with_emoji` 完全冗余

**现状**: 3547/3547 条动态的 `text` 与 `text_with_emoji` 完全相同。B站表情包已以 `[表情名]` 形式存在于 `text` 中。

**建议**: 删除 `text_with_emoji` 字段。数据库只存 `plain_text`（纯文本，表情为 `[名]`）。未来如需结构化表情渲染，使用 `rich_text` JSON 字段（见 posts 表设计）。

### 问题 2：40 张图片缺少 URL

**现状**: 旧归档导入的 40 张原创图片 `content.images[].url` 为空字符串。这些图片文件存在于磁盘但无法溯源到 B站 CDN。

**建议**: 数据库的 `source_url` 字段允许为 NULL。构建一个一次性脚本，根据文件名中的 `dynamic_id` 调用 API 补全 URL，或标记为 `url_unknown`。

### 问题 3：85 条转发缺少原作者信息

**现状**: 463 条转发中，85 条的 `repost_content.author_name` 为空。原因是 B站 detail API 高频返回 412/空响应。

**建议**: 数据库允许 `original_author_id` 为 NULL。未来可通过批量重试 detail API（增加延迟到 3-5 秒）逐步补全。

### 问题 4：`major_type` 是 B站特有概念

**现状**: `content.major_type` 使用 B站的 `MAJOR_TYPE_DRAW`、`MAJOR_TYPE_COMMON` 等值，不具备平台通用性。

**建议**: 数据库使用通用的 `post_type` 枚举（`text`, `image`, `video`, `audio`, `article`, `live`, `repost`, `mixed`），将 `major_type` 移入 `platform_metadata` JSON 中作为溯源。

### 问题 5：stats 缺少 views

**现状**: 3547/3547 条动态的 `stats.views` 为 NULL。B站 API 对他人空间不返回浏览量。

**建议**: `post_stats.views` 允许为 NULL。未来如果爬取自己的动态或通过其他方式获得 views，可直接填入。

### 问题 6：转发内容的嵌入 vs 引用

**现状**: `repost_content` 作为嵌套 JSON 对象嵌入在转发动态中，包含原动态的文本、图片、作者信息。

**建议**: 在数据库中，转发通过 `repost_of_id` 外键引用原始 posts 行。若原始动态不在归档中或已删除，将快照存入 `repost_snapshot` JSON 字段。图片仍通过 `images` 表和 `post_media` 关联表存储（与所属的转发 post 关联，而非与原 post 关联）。

---

## 四、数据表设计

共 11 张表（含 1 张 FTS5 虚拟表）。

---

### 4.1 platforms — 平台注册表

**用途**: 记录所有数据来源平台。每接入一个新平台，新增一行。当前仅 B站一行。

| 字段 | 类型 | 空 | 默认值 | 说明 |
|------|------|:---:|--------|------|
| id | INTEGER | NOT NULL | AUTOINCREMENT | 主键 |
| key | TEXT | NOT NULL | — | 平台标识，小写，如 `bilibili`、`weibo`、`x`、`youtube` |
| display_name | TEXT | NOT NULL | — | 显示名称，如 `哔哩哔哩` |
| home_url | TEXT | NULL | — | 平台首页 URL |
| icon_url | TEXT | NULL | — | 平台图标 URL |
| config | TEXT | NULL | — | JSON，平台级配置（API 端点、认证方式等） |
| created_at | TEXT | NOT NULL | CURRENT_TIMESTAMP | 记录创建时间 |

**约束**:
- `UNIQUE(key)`

**索引**:
- `idx_platforms_key ON platforms(key)` — 通过 key 快速查找

**数据量**: < 10 行

---

### 4.2 authors — 内容作者

**用途**: 记录转发动态中被引用内容的原作者。主账号（岁己SUI）的信息存储在 `platforms.config` 中，不在此表中。此表专门用于追踪"别人发了什么，岁己转发了"中的"别人"。

| 字段 | 类型 | 空 | 默认值 | 说明 |
|------|------|:---:|--------|------|
| id | INTEGER | NOT NULL | AUTOINCREMENT | 主键 |
| platform_id | INTEGER | NOT NULL | — | FK → platforms.id |
| platform_user_id | TEXT | NULL | — | 平台上的用户 ID（如 B站 mid） |
| display_name | TEXT | NOT NULL | — | 显示名称 |
| profile_url | TEXT | NULL | — | 个人主页 URL |
| avatar_url | TEXT | NULL | — | 头像 URL |
| bio | TEXT | NULL | — | 简介 |
| created_at | TEXT | NOT NULL | CURRENT_TIMESTAMP | 首次发现时间 |
| updated_at | TEXT | NULL | — | 最近更新时间 |

**约束**:
- `UNIQUE(platform_id, platform_user_id)` — 同平台同用户只记录一次
- `FOREIGN KEY(platform_id) REFERENCES platforms(id)`

**索引**:
- `idx_authors_platform ON authors(platform_id, platform_user_id)` — 去重查找
- `idx_authors_name ON authors(display_name)` — 按名称查找

**数据量**: 当前 ~40 人（去重后的转发原作者），未来 ~200

---

### 4.3 posts — 动态主表

**用途**: 存储所有平台的所有动态。这是整个数据库的核心表。

| 字段 | 类型 | 空 | 默认值 | 说明 |
|------|------|:---:|--------|------|
| id | INTEGER | NOT NULL | AUTOINCREMENT | 内部主键 |
| uuid | TEXT | NOT NULL | — | v4 UUID，外部引用标识符 |
| platform_id | INTEGER | NOT NULL | — | FK → platforms.id |
| platform_post_id | TEXT | NOT NULL | — | 平台原始动态 ID（如 B站 dynamic_id） |
| post_type | TEXT | NOT NULL | — | 通用类型枚举（见下方） |
| platform_post_type | TEXT | NULL | — | 平台原始类型字符串（如 `DYNAMIC_TYPE_DRAW`） |
| published_at | TEXT | NOT NULL | — | 发布时间，ISO 8601 |
| archived_at | TEXT | NOT NULL | — | 入库时间，ISO 8601 |
| source_url | TEXT | NULL | — | 原始链接（如 `https://t.bilibili.com/{id}`） |
| plain_text | TEXT | NULL | — | 纯文本内容，B站表情显示为 `[表情名]` |
| rich_text | TEXT | NULL | — | JSON，结构化富文本节点数组（预留） |
| language | TEXT | NULL | `zh-CN` | 内容语言，BCP 47 格式 |
| repost_of_id | INTEGER | NULL | — | FK → posts.id，转发的原动态（在库内时） |
| repost_snapshot | TEXT | NULL | — | JSON，原动态快照（原动态已删或不在库中时） |
| original_author_id | INTEGER | NULL | — | FK → authors.id，转发原动态的作者 |
| platform_metadata | TEXT | NULL | — | JSON，平台特有字段 |
| is_pinned | INTEGER | NOT NULL | 0 | 是否置顶 |
| is_deleted | INTEGER | NOT NULL | 0 | 是否已从原平台删除 |
| schema_version | INTEGER | NOT NULL | 1 | 该行数据的 schema 版本 |

**post_type 枚举值**:

| 值 | 含义 | B站映射 |
|----|------|--------|
| `text` | 纯文字 | DYNAMIC_TYPE_WORD |
| `image` | 含图片 | DYNAMIC_TYPE_DRAW (有图) |
| `video` | 视频 | DYNAMIC_TYPE_AV |
| `audio` | 音频 | DYNAMIC_TYPE_MUSIC |
| `article` | 长文/专栏 | DYNAMIC_TYPE_ARTICLE |
| `live` | 直播相关 | DYNAMIC_TYPE_LIVE |
| `repost` | 转发/引用 | DYNAMIC_TYPE_FORWARD |
| `mixed` | 混合类型 | 其他 |

**约束**:
- `UNIQUE(platform_id, platform_post_id)` — 同平台同 ID 不重复
- `UNIQUE(uuid)` — UUID 全局唯一
- `FOREIGN KEY(platform_id) REFERENCES platforms(id)`
- `FOREIGN KEY(repost_of_id) REFERENCES posts(id) ON DELETE SET NULL`
- `FOREIGN KEY(original_author_id) REFERENCES authors(id) ON DELETE SET NULL`
- `CHECK(post_type IN ('text','image','video','audio','article','live','repost','mixed'))`
- `CHECK(is_pinned IN (0,1))`
- `CHECK(is_deleted IN (0,1))`

**索引**:
- `idx_posts_published ON posts(published_at DESC)` — 时间轴排序（核心索引）
- `idx_posts_platform ON posts(platform_id)` — 按平台筛选
- `idx_posts_type ON posts(post_type)` — 按类型筛选
- `idx_posts_repost_of ON posts(repost_of_id) WHERE repost_of_id IS NOT NULL` — 查找某动态被谁转发
- `idx_posts_author ON posts(original_author_id) WHERE original_author_id IS NOT NULL` — 查找某人被转发的内容
- `idx_posts_platform_id ON posts(platform_id, platform_post_id)` — 通过平台 ID 精确查找

**platform_metadata JSON 结构** (B站示例):
```
{
  "major_type": "MAJOR_TYPE_DRAW",
  "bilibili_mid": "1954091502",
  "comment_type": 11,
  "comment_id_str": "399442753",
  "tags": [],
  "topic": null
}
```

**rich_text JSON 结构** (预留，当前不填充):
```
[
  {"type": "text", "text": "晚安晚安"},
  {"type": "emoji", "text": "[岁己收藏集表情包_晚安]", "emoji_id": 108163, "package_id": 7923},
  {"type": "text", "text": "谢谢你来看"}
]
```

**数据量**: 当前 3,547 行，10 年 ~10,000 行

---

### 4.4 images — 图片表

**用途**: 记录所有图片文件的完整元数据。每张图片一行，通过 `post_media` 关联到动态。

| 字段 | 类型 | 空 | 默认值 | 说明 |
|------|------|:---:|--------|------|
| id | INTEGER | NOT NULL | AUTOINCREMENT | 内部主键 |
| uuid | TEXT | NOT NULL | — | v4 UUID，外部引用标识符 |
| filename | TEXT | NOT NULL | — | 磁盘文件名（如 `1210001435340570626_00@original.png`） |
| storage_path | TEXT | NOT NULL | — | 相对路径（如 `images/121000...@original.png`） |
| sha256 | TEXT | NULL | — | 文件 SHA-256 哈希值（用于去重和完整性校验） |
| file_size | INTEGER | NULL | — | 文件大小（字节） |
| width | INTEGER | NULL | — | 图片宽度（像素） |
| height | INTEGER | NULL | — | 图片高度（像素） |
| mime_type | TEXT | NULL | — | MIME 类型（如 `image/png`） |
| quality | TEXT | NOT NULL | `original` | 质量标识：`original` / `thumbnail` / `repost` |
| source_url | TEXT | NULL | — | 原始 CDN URL（溯源用） |
| is_cover | INTEGER | NOT NULL | 0 | 是否为所属动态的封面图 |
| is_deleted | INTEGER | NOT NULL | 0 | 文件是否已从磁盘删除 |
| perceptual_hash | TEXT | NULL | — | 感知哈希（用于相似图检测，预留） |
| exif_data | TEXT | NULL | — | JSON，EXIF 元数据（预留） |
| archived_at | TEXT | NOT NULL | CURRENT_TIMESTAMP | 入库时间 |

**约束**:
- `UNIQUE(filename)` — 文件名全局唯一
- `UNIQUE(uuid)` — UUID 全局唯一
- `UNIQUE(sha256)` — 哈希值唯一（当非 NULL 时，实现内容去重）
- `CHECK(quality IN ('original','thumbnail','repost'))`
- `CHECK(is_cover IN (0,1))`
- `CHECK(is_deleted IN (0,1))`

**索引**:
- `idx_images_filename ON images(filename)` — 通过文件名查找
- `idx_images_sha256 ON images(sha256) WHERE sha256 IS NOT NULL` — 内容去重查找
- `idx_images_quality ON images(quality)` — 按质量类型筛选

**数据量**: 当前 1,083 行，10 年 ~5,000 行

---

### 4.5 media — 通用媒体表

**用途**: 存储图片和视频以外的媒体类型。当未来出现视频、音频、GIF 等文件时使用。当前为空表，预建结构。

| 字段 | 类型 | 空 | 默认值 | 说明 |
|------|------|:---:|--------|------|
| id | INTEGER | NOT NULL | AUTOINCREMENT | 内部主键 |
| uuid | TEXT | NOT NULL | — | v4 UUID |
| media_type | TEXT | NOT NULL | — | 类型枚举（见下方） |
| filename | TEXT | NOT NULL | — | 磁盘文件名 |
| storage_path | TEXT | NOT NULL | — | 相对路径 |
| sha256 | TEXT | NULL | — | SHA-256 哈希 |
| file_size | INTEGER | NULL | — | 文件大小（字节） |
| mime_type | TEXT | NULL | — | MIME 类型 |
| duration_ms | INTEGER | NULL | — | 时长（毫秒），视频/音频 |
| width | INTEGER | NULL | — | 宽度（像素），视频 |
| height | INTEGER | NULL | — | 高度（像素），视频 |
| thumbnail_image_id | INTEGER | NULL | — | FK → images.id，缩略图 |
| source_url | TEXT | NULL | — | 原始 URL |
| platform_metadata | TEXT | NULL | — | JSON，平台特有字段 |
| archived_at | TEXT | NOT NULL | CURRENT_TIMESTAMP | 入库时间 |

**media_type 枚举值**: `video`, `audio`, `gif`, `live_photo`, `document`

**约束**:
- `UNIQUE(filename)`
- `UNIQUE(uuid)`
- `UNIQUE(sha256)` WHERE NOT NULL
- `FOREIGN KEY(thumbnail_image_id) REFERENCES images(id) ON DELETE SET NULL`
- `CHECK(media_type IN ('video','audio','gif','live_photo','document'))`

**索引**:
- `idx_media_type ON media(media_type)`
- `idx_media_filename ON media(filename)`

**数据量**: 当前 0，未来按需增长

---

### 4.6 tags — 标签表

**用途**: 存储标签定义。标签用于对动态进行分类和检索。

| 字段 | 类型 | 空 | 默认值 | 说明 |
|------|------|:---:|--------|------|
| id | INTEGER | NOT NULL | AUTOINCREMENT | 内部主键 |
| uuid | TEXT | NOT NULL | — | v4 UUID |
| name | TEXT | NOT NULL | — | 标签名称（主要显示语言，中文） |
| slug | TEXT | NOT NULL | — | URL 友好标识（如 `singing-clip`） |
| display_names | TEXT | NULL | — | JSON，多语言名称 `{"zh":"翻唱","en":"Cover"}` |
| category | TEXT | NULL | — | 标签分类（如 `content`、`topic`、`emotion`、`character`） |
| parent_id | INTEGER | NULL | — | FK → tags.id，父标签（支持层级） |
| description | TEXT | NULL | — | 标签说明 |
| color | TEXT | NULL | — | 显示颜色 HEX（如 `#00C8FF`） |
| sort_order | INTEGER | NOT NULL | 0 | 排序权重 |
| created_at | TEXT | NOT NULL | CURRENT_TIMESTAMP | 创建时间 |

**约束**:
- `UNIQUE(name)`
- `UNIQUE(slug)`
- `UNIQUE(uuid)`
- `FOREIGN KEY(parent_id) REFERENCES tags(id) ON DELETE SET NULL`

**索引**:
- `idx_tags_slug ON tags(slug)`
- `idx_tags_category ON tags(category) WHERE category IS NOT NULL`
- `idx_tags_parent ON tags(parent_id) WHERE parent_id IS NOT NULL`

**数据量**: 当前 0，未来 ~200

---

### 4.7 post_tags — 动态-标签关联

**用途**: 多对多关联表。一条动态可打多个标签，一个标签可关联多条动态。

| 字段 | 类型 | 空 | 默认值 | 说明 |
|------|------|:---:|--------|------|
| id | INTEGER | NOT NULL | AUTOINCREMENT | 内部主键 |
| post_id | INTEGER | NOT NULL | — | FK → posts.id |
| tag_id | INTEGER | NOT NULL | — | FK → tags.id |
| tagged_at | TEXT | NOT NULL | CURRENT_TIMESTAMP | 打标时间 |

**约束**:
- `UNIQUE(post_id, tag_id)` — 同一动态同一标签不重复
- `FOREIGN KEY(post_id) REFERENCES posts(id) ON DELETE CASCADE`
- `FOREIGN KEY(tag_id) REFERENCES tags(id) ON DELETE CASCADE`

**索引**:
- `idx_post_tags_post ON post_tags(post_id)` — 查某动态的所有标签
- `idx_post_tags_tag ON post_tags(tag_id)` — 查某标签下的所有动态

**数据量**: 取决于标注进度，预估 ~5,000-10,000

---

### 4.8 post_media — 动态-媒体关联

**用途**: 多对多关联表。将图片（images）和通用媒体（media）关联到动态。一条动态可含多张图片，一张图片理论上也可被多条动态引用（如去重场景）。

| 字段 | 类型 | 空 | 默认值 | 说明 |
|------|------|:---:|--------|------|
| id | INTEGER | NOT NULL | AUTOINCREMENT | 内部主键 |
| post_id | INTEGER | NOT NULL | — | FK → posts.id |
| image_id | INTEGER | NULL | — | FK → images.id，关联图片 |
| media_id | INTEGER | NULL | — | FK → media.id，关联其他媒体 |
| sort_order | INTEGER | NOT NULL | 0 | 在动态中的排序（从 0 开始） |
| is_repost_media | INTEGER | NOT NULL | 0 | 是否为转发内容中的媒体（非原创） |

**约束**:
- `UNIQUE(post_id, image_id)` WHERE image_id IS NOT NULL
- `UNIQUE(post_id, media_id)` WHERE media_id IS NOT NULL
- `FOREIGN KEY(post_id) REFERENCES posts(id) ON DELETE CASCADE`
- `FOREIGN KEY(image_id) REFERENCES images(id) ON DELETE CASCADE`
- `FOREIGN KEY(media_id) REFERENCES media(id) ON DELETE CASCADE`
- `CHECK(image_id IS NOT NULL OR media_id IS NOT NULL)` — 至少关联一种媒体

**索引**:
- `idx_post_media_post ON post_media(post_id)` — 查某动态的所有媒体
- `idx_post_media_image ON post_media(image_id) WHERE image_id IS NOT NULL`
- `idx_post_media_media ON post_media(media_id) WHERE media_id IS NOT NULL`

**数据量**: 当前 ~1,100（图片关联），随图片增长

**设计说明**: `is_repost_media` 字段标识该图片属于转发动态的原创内容还是被转发内容。对于转发动态 `1217759413282013185`，其 `100@repost.png` 图片关联到该转发 post，且 `is_repost_media = 1`，表示这是"被转发的原动态的图片"。

---

### 4.9 post_stats — 动态互动统计

**用途**: 存储动态的互动数据快照。设计为时间序列——同一条动态可在不同时间点记录多组统计，以追踪数据变化。

| 字段 | 类型 | 空 | 默认值 | 说明 |
|------|------|:---:|--------|------|
| id | INTEGER | NOT NULL | AUTOINCREMENT | 内部主键 |
| post_id | INTEGER | NOT NULL | — | FK → posts.id |
| views | INTEGER | NULL | — | 浏览量（B站对他人空间不返回，故允许 NULL） |
| likes | INTEGER | NOT NULL | 0 | 点赞数 |
| comments | INTEGER | NOT NULL | 0 | 评论数 |
| forwards | INTEGER | NOT NULL | 0 | 转发数 |
| snapshot_at | TEXT | NOT NULL | CURRENT_TIMESTAMP | 快照采集时间 |

**约束**:
- `FOREIGN KEY(post_id) REFERENCES posts(id) ON DELETE CASCADE`

**索引**:
- `idx_post_stats_post ON post_stats(post_id, snapshot_at DESC)` — 查某动态的最新统计
- `idx_post_stats_time ON post_stats(snapshot_at)` — 按时间范围查找

**数据量**: 当前 3,547（每条动态一个快照）。若未来定期采集，将增长为 N × 采集次数。

**设计说明**: 3NF 要求统计数据不与 post 本体混存（stats 随时间变化，post 元数据不变）。当前每条动态只有一个快照，但表结构已支持未来多次采集。查询最新统计时使用 `ORDER BY snapshot_at DESC LIMIT 1` 或通过子查询。

---

### 4.10 posts_fts — 全文搜索虚拟表

**用途**: 基于 SQLite FTS5 扩展的全文搜索索引。支持中文分词。

**虚拟表定义** (逻辑结构，非普通表):

| 字段 | 说明 |
|------|------|
| plain_text | 动态纯文本内容 |
| repost_text | 转发原动态的文本（若有） |
| post_type | 动态类型（用于加权） |
| language | 内容语言 |

**分词器**: `tokenize="unicode61"` 作为基础分词器。若部署环境支持 ICU 分词，优先使用 `tokenize="icu zh_CN"` 实现中文分词。

**content 同步**: 使用 `content="posts"` 和 `content_rowid="id"` 参数，使 FTS 表自动与 posts 表关联。通过触发器保持同步。

**触发器**:

| 触发器名 | 事件 | 动作 |
|----------|------|------|
| `fts_ai_post_insert` | AFTER INSERT ON posts | 向 FTS 表插入新行 |
| `fts_ai_post_update` | AFTER UPDATE ON posts | 更新 FTS 表对应行 |
| `fts_ai_post_delete` | AFTER DELETE ON posts | 从 FTS 表删除对应行 |

**数据量**: 与 posts 表 1:1，~3,547 行

---

### 4.11 schema_migrations — Schema 版本管理

**用途**: 记录所有数据库结构变更历史。每次 Migration 新增一行。

| 字段 | 类型 | 空 | 默认值 | 说明 |
|------|------|:---:|--------|------|
| version | INTEGER | NOT NULL | — | 主键，版本号，从 1 开始递增 |
| name | TEXT | NOT NULL | — | Migration 名称（如 `initial_schema`） |
| description | TEXT | NULL | — | 变更说明 |
| applied_at | TEXT | NOT NULL | CURRENT_TIMESTAMP | 应用时间 |
| checksum | TEXT | NULL | — | Migration 脚本的 SHA-256，防篡改 |

**约束**:
- `UNIQUE(version)`

**无索引**: 表极小（< 100 行），不需要索引。

---

## 五、主键设计

### 5.1 策略总览

| 表 | 主键 | 外部标识 | 理由 |
|-----|------|---------|------|
| posts | INTEGER AUTO | uuid + (platform_id, platform_post_id) | INTEGER 高效索引；uuid 供外部引用；联合唯一保证幂等导入 |
| images | INTEGER AUTO | uuid + filename | INTEGER 高效；filename 是物理标识；uuid 供外部引用 |
| media | INTEGER AUTO | uuid | 与 images 保持一致 |
| authors | INTEGER AUTO | (platform_id, platform_user_id) | 内部使用，不需要 uuid |
| tags | INTEGER AUTO | uuid + slug | slug 用于 URL，uuid 供外部引用 |
| platforms | INTEGER AUTO | key | key 即为业务标识 |
| post_tags | INTEGER AUTO | (post_id, tag_id) | 联合唯一约束 |
| post_media | INTEGER AUTO | (post_id, image_id) | 联合唯一约束 |
| post_stats | INTEGER AUTO | (post_id, snapshot_at) | 时间序列 |
| schema_migrations | version | — | 版本号即主键 |

### 5.2 为什么不用 UUID 作为主键？

**UUID 作主键的缺点**:
- 占用 36 字节 vs INTEGER 的 8 字节
- B-tree 索引碎片化（UUID 无序，导致页分裂）
- 外键引用时体积翻倍
- 人类不可读，调试困难

**UUID 作主键的优点**:
- 全局唯一，跨数据库合并无冲突
- 不暴露数据量

**本项目的选择**: INTEGER 作内部主键（性能最优），UUID 作为 UNIQUE 字段（外部引用）。本项目不需要跨数据库合并（单一 SQLite 文件），UUID 主键的优势不适用。

### 5.3 为什么保留 platform_post_id？

`platform_post_id` 是平台上的原始 ID（如 B站的 `1218285761518895113`）。保留它的理由：

1. **溯源**: 可直接定位到原平台的原始内容
2. **幂等导入**: 重复导入时通过 `(platform_id, platform_post_id)` 唯一约束跳过已存在的数据
3. **前端 URL**: 动态详情页的 URL 使用 `platform_post_id`（如 `/d/1218285761518895113`），因为这是用户可识别的标识
4. **与 API 对接**: 未来补全数据时，通过 platform_post_id 调用平台 API

### 5.4 图片为什么不用 SHA-256 作主键？

理想情况下，SHA-256 是图片的最佳主键——内容寻址，天然去重。但当前数据存在限制：

- 1083 张图片的 SHA-256 尚未计算（需要扫描文件）
- 40 张图片缺少 source_url，无法通过重新下载补全

**当前方案**: INTEGER 主键 + filename UNIQUE + sha256 UNIQUE(NULLABLE)。导入时先不填 sha256。后续运行一次性脚本计算所有文件的哈希并回填。当 sha256 非 NULL 时，UNIQUE 约束自动生效实现去重。

---

## 六、索引设计

### 6.1 索引总览

| 索引名 | 表 | 列 | 类型 | 查询场景 |
|--------|-----|-----|------|---------|
| `idx_posts_published` | posts | published_at DESC | 普通 | 时间轴排序、分页 |
| `idx_posts_platform` | posts | platform_id | 普通 | 按平台筛选 |
| `idx_posts_type` | posts | post_type | 普通 | 按类型筛选 |
| `idx_posts_repost_of` | posts | repost_of_id (部分) | 部分 | 查某动态被谁转发 |
| `idx_posts_author` | posts | original_author_id (部分) | 部分 | 查某人被转发的内容 |
| `idx_posts_platform_id` | posts | platform_id, platform_post_id | 联合唯一 | 幂等导入、精确查找 |
| `idx_images_filename` | images | filename | 唯一 | 文件名查找 |
| `idx_images_sha256` | images | sha256 (部分) | 部分 | 内容去重 |
| `idx_post_tags_post` | post_tags | post_id | 普通 | 动态→标签 |
| `idx_post_tags_tag` | post_tags | tag_id | 普通 | 标签→动态 |
| `idx_post_media_post` | post_media | post_id | 普通 | 动态→媒体 |
| `idx_post_media_image` | post_media | image_id (部分) | 部分 | 图片→动态 |
| `idx_post_stats_post` | post_stats | post_id, snapshot_at DESC | 联合 | 最新统计 |
| `idx_authors_platform` | authors | platform_id, platform_user_id | 联合唯一 | 作者去重 |
| `idx_authors_name` | authors | display_name | 普通 | 按名称查找 |
| `posts_fts` | posts_fts | plain_text, repost_text | FTS5 | 全文搜索 |

### 6.2 索引设计理由

**为什么 published_at 是 DESC？** 时间轴的默认视图是"最新在前"。DESC 索引避免了排序时的 filesort 操作。

**为什么使用部分索引 (WHERE ... IS NOT NULL)？** `repost_of_id`、`sha256` 等字段大部分为 NULL。部分索引只包含非 NULL 行，体积更小、查询更快。

**为什么不用复合索引覆盖所有查询？** 遵循"按需建索引"原则。当前索引覆盖已知的查询模式。未来新增查询模式时，通过 Migration 添加索引。

### 6.3 FTS5 全文搜索索引

FTS5 虚拟表 `posts_fts` 提供全文搜索能力：

- **中文分词**: 优先使用 ICU 分词器（`tokenize="icu zh_CN"`），退化为 unicode61
- **搜索字段**: `plain_text`（主权重）、`repost_text`（次权重）
- **过滤字段**: `post_type`、`language`（用于 WHERE 过滤，不参与搜索）
- **排序**: 默认按 FTS5 的 `rank` 排序（BM25 相关性），可切换为时间排序

**FTS5 与 posts 表的同步**通过三个触发器实现（INSERT / UPDATE / DELETE），确保搜索索引始终与主表一致。

---

## 七、查询优化

### 7.1 核心查询分析

**Q1: 首页时间轴（最新 20 条动态 + 图片 + 统计）**

```
查询路径:
  posts 表 → WHERE platform_id = ? → ORDER BY published_at DESC → LIMIT 20
  对每条结果:
    JOIN post_media → JOIN images (获取图片列表)
    JOIN post_stats → ORDER BY snapshot_at DESC LIMIT 1 (获取最新统计)
    LEFT JOIN posts AS orig ON repost_of_id (获取转发原动态)
```

**性能**: `idx_posts_published` 覆盖排序，LIMIT 20 保证只扫描少量行。post_media 和 images 通过主键/索引查找，O(1)。单次查询预估 < 5ms（10K 数据量）。

**Q2: 按年份浏览**

```
查询路径:
  posts → WHERE published_at >= '2024-01-01' AND published_at < '2025-01-01'
  → ORDER BY published_at DESC
```

**性能**: 范围扫描 `idx_posts_published`，2024 年约 858 行，预估 < 2ms。

**Q3: 全文搜索**

```
查询路径:
  posts_fts → MATCH '关键词' → ORDER BY rank → LIMIT 50
  JOIN posts ON rowid (获取完整数据)
```

**性能**: FTS5 内部倒排索引，O(1) 查找 + O(k) 排序（k=匹配数）。3.5K 文档规模下 < 10ms。

**Q4: 标签查询**

```
查询路径:
  tags → WHERE slug = ? (获取 tag_id)
  post_tags → WHERE tag_id = ? (获取 post_ids)
  posts → WHERE id IN (...) → ORDER BY published_at DESC
```

**性能**: 三级索引查找，每级 O(log N)。预估 < 5ms。

**Q5: 单条动态详情页**

```
查询路径:
  posts → WHERE platform_id = ? AND platform_post_id = ? (精确匹配)
  LEFT JOIN authors ON original_author_id
  JOIN post_media → JOIN images
  JOIN post_stats (最新一条)
  LEFT JOIN posts AS orig ON repost_of_id
  LEFT JOIN post_tags → JOIN tags
```

**性能**: 联合唯一索引 `idx_posts_platform_id` 保证 O(log N) 精确定位。其余均为外键/主键查找。预估 < 3ms。

**Q6: 统计查询**

```
查询路径:
  SELECT COUNT(*), strftime('%Y', published_at) FROM posts GROUP BY year
  SELECT COUNT(*) FROM images
  SELECT COUNT(*) FROM posts WHERE post_type = 'image'
```

**性能**: 全表 COUNT 在 10K 行规模下 < 5ms。若未来数据量增长，可通过 `post_stats` 快照或物化视图缓存结果。

### 7.2 十万级数据预估

| 查询 | 10K 行 | 100K 行 | 优化手段 |
|------|--------|---------|---------|
| 时间轴分页 | < 5ms | < 10ms | LIMIT + OFFSET 或游标分页 |
| 全文搜索 | < 10ms | < 50ms | FTS5 天然高效 |
| 标签查询 | < 5ms | < 20ms | 索引覆盖 |
| 年度统计 | < 5ms | < 100ms | 可用缓存或物化视图 |

SQLite 在 10 万行级别仍然高效。若未来达到百万级，考虑按月分片或使用外部搜索引擎。

---

## 八、数据一致性

### 8.1 事务策略

| 操作 | 事务类型 | 说明 |
|------|---------|------|
| 初始导入 | 单一大事务 | 所有 3547 条动态在一个事务内插入，确保原子性 |
| 增量导入 | 按批次事务 | 每 100 条一个事务，失败时只回滚当前批次 |
| 构建管道读取 | 只读事务 | `BEGIN DEFERRED` + 只做 SELECT |
| 单条更新 | 隐式事务 | 单行 UPDATE 自动事务 |

### 8.2 约束策略

- **FOREIGN KEY**: 全部启用，`PRAGMA foreign_keys = ON`（每次连接后执行）
- **ON DELETE CASCADE**: post_tags、post_media、post_stats — 删除动态时自动清理关联
- **ON DELETE SET NULL**: posts.repost_of_id、posts.original_author_id — 被引用记录删除时置空
- **CHECK 约束**: 所有枚举字段（post_type、quality、media_type）均有 CHECK 约束
- **UNIQUE 约束**: 所有业务唯一性均通过 UNIQUE 约束保证，不依赖应用层

### 8.3 删除策略

**本项目原则上不删除数据**（档案馆性质）。但设计了以下机制以防万一：

- 逻辑删除: `posts.is_deleted = 1`、`images.is_deleted = 1`（标记但不物理删除）
- 物理删除: 通过 CASCADE 自动清理关联表（post_tags、post_media、post_stats）
- 图片文件: `images.is_deleted = 1` 后，同步脚本不再上传该图片，但不从 R2 删除

### 8.4 更新策略

- **posts**: `plain_text`、`platform_metadata` 可更新（补全数据）。`platform_post_id`、`published_at` 不可更新。
- **images**: `sha256`、`file_size`、`width`、`height` 可回填（初始导入时可能不完整）。`filename` 不可更新。
- **post_stats**: 只追加新快照，不修改已有快照。
- **authors**: `display_name`、`avatar_url` 可更新。`platform_user_id` 不可更新。

### 8.5 数据校验策略

- **导入校验**: 每次导入前验证 schema_version、UNIQUE 约束、外键完整性
- **定期校验**: 构建管道的 loader 步骤执行 `PRAGMA integrity_check` 和 `PRAGMA foreign_key_check`
- **图片校验**: 当 sha256 非空时，定期重新计算文件哈希并比对
- **FTS 同步校验**: 定期执行 `INSERT INTO posts_fts(posts_fts) VALUES('integrity-check')`

---

## 九、数据迁移

### 9.1 版本管理

数据库通过 `schema_migrations` 表管理版本。初始版本为 1。

每次变更数据库结构，必须：
1. 编写 Migration 脚本（Python 或 SQL）
2. 版本号 +1
3. 记录变更名称和描述
4. 计算脚本 SHA-256 校验和

### 9.2 字段新增原则

- 新字段必须有默认值或允许 NULL（保证旧数据兼容）
- 新字段不影响现有查询（SELECT * 不用于生产代码）
- 新增字段后，更新本文档对应表定义
- 新增字段后，更新 `schema_version` 列（若有）

### 9.3 字段废弃原则

- **永不物理删除列** — 只标记为废弃（在本文档中标注 DEPRECATED）
- 废弃字段保留至少 2 个版本后才可考虑移除
- 移除前必须确认无任何代码引用该字段
- 移除操作本身也是一次 Migration

### 9.4 新增平台

接入新平台（如微博）的步骤：

1. `INSERT INTO platforms (key, display_name, ...)` 新增平台行
2. 编写该平台的导入脚本，将数据映射到 posts/images/post_media 表
3. 不需要修改表结构——posts 表已设计为平台无关
4. 平台特有的字段放入 `posts.platform_metadata` JSON
5. 更新本文档的 `post_type` 映射表

### 9.5 Migration 执行流程

```
1. 备份数据库: cp sui-archive.db sui-archive.db.bak.{date}
2. 开启事务: BEGIN TRANSACTION
3. 执行 Migration 脚本
4. INSERT INTO schema_migrations
5. COMMIT (成功) 或 ROLLBACK (失败)
6. 验证: PRAGMA integrity_check
7. 更新本文档
```

---

## 十、ER 关系图

```
┌──────────────┐
│  platforms   │
│──────────────│
│ PK id        │
│    key       │◄──────────────────────────────────┐
│    ...       │                                    │
└──────┬───────┘                                    │
       │ 1                                          │
       │                                            │
       │ N                                          │
┌──────┴───────────────────────┐                    │
│          posts               │                    │
│──────────────────────────────│                    │
│ PK id                        │                    │
│    uuid                      │                    │
│ FK platform_id ──────────────┘                    │
│ FK repost_of_id ──→ posts.id (自引用)             │
│ FK original_author_id ──→ authors.id              │
│    post_type                 │                    │
│    published_at              │                    │
│    plain_text                │                    │
│    repost_snapshot           │                    │
│    ...                       │                    │
└──┬──────────┬──────────┬─────┘                    │
   │ 1        │ 1        │ 1                        │
   │          │          │                          │
   │ N        │ N        │ N                        │
┌──┴────┐ ┌──┴──────┐ ┌─┴──────────┐               │
│post_  │ │post_    │ │post_       │               │
│tags   │ │media    │ │stats       │               │
│───────│ │─────────│ │────────────│               │
│FK     │ │FK       │ │FK          │               │
│post_id│ │post_id  │ │post_id     │               │
│FK     │ │FK       │ │snapshot_at │               │
│tag_id │ │image_id │ └────────────┘               │
└───┬───┘ │FK       │                              │
    │     │media_id │                              │
    │ N   └──┬───┬───┘                              │
    │        │   │                                  │
    │        │1  │1                                 │
    │        │   │                                  │
┌───┴────┐ ┌┴───┴─────┐  ┌──────────────┐         │
│  tags  │ │ images   │  │    media     │         │
│────────│ │──────────│  │──────────────│         │
│ PK id  │ │ PK id    │  │ PK id       │         │
│    uuid│ │    uuid  │  │    uuid     │         │
│    name│ │    sha256│  │    sha256   │         │
│ FK     │ │    ...   │  │ FK          │         │
│ parent │ └──────────┘  │ thumbnail_  │         │
│   _id  │               │  image_id   │         │
│  (自引) │               │  ──→images  │         │
└────────┘               └─────────────┘         │
                                                  │
┌──────────────┐                                  │
│   authors    │                                  │
│──────────────│                                  │
│ PK id        │                                  │
│ FK platform_ │──────────────────────────────────┘
│    id        │
│    display_  │
│    name      │
│    ...       │
└──────────────┘

┌──────────────┐     ┌──────────────────┐
│  posts_fts   │     │schema_migrations │
│ (FTS5虚拟表) │     │──────────────────│
│──────────────│     │ PK version       │
│ plain_text   │     │    name          │
│ repost_text  │     │    applied_at    │
│ post_type    │     │    checksum      │
│ language     │     └──────────────────┘
└──────────────┘
     ↕ 触发器同步
   posts 表
```

### 关系总结

| 关系 | 类型 | 说明 |
|------|------|------|
| platforms → posts | 1:N | 一个平台有多条动态 |
| platforms → authors | 1:N | 一个平台有多个作者 |
| posts → posts | 1:N | 自引用：一条动态可被多条动态转发 |
| posts → authors | N:1 | 转发动态引用原作者 |
| posts → images | M:N | 通过 post_media 关联 |
| posts → media | M:N | 通过 post_media 关联 |
| posts → tags | M:N | 通过 post_tags 关联 |
| posts → post_stats | 1:N | 一条动态可有多次统计快照 |
| tags → tags | 1:N | 自引用：标签层级 |
| media → images | N:1 | 媒体的缩略图是图片 |

---

## 十一、数据映射

### 11.1 现有 dynamics.json → 数据库表

| dynamics.json 字段 | 目标表 | 目标字段 | 转换规则 |
|--------------------|--------|---------|---------|
| dynamic_id | posts | platform_post_id | 直接映射 |
| type | posts | platform_post_type | 直接存储原始值 |
| type → 通用映射 | posts | post_type | DRAW→image, WORD→text, FORWARD→repost, 其他→mixed |
| publish_time | — | — | 不导入（由 published_at 替代） |
| publish_timestamp | posts | published_at | Unix→ISO 8601: `datetime(ts, 'unixepoch', '+8 hours')` |
| content.text | posts | plain_text | 直接映射 |
| content.text_with_emoji | — | — | **丢弃**（与 text 完全相同） |
| content.images | images + post_media | 多字段 | 每条图片创建 images 行 + post_media 关联 |
| content.images[].url | images | source_url | 直接映射（空字符串→NULL） |
| content.images[].width | images | width | 字符串→整数 |
| content.images[].height | images | height | 字符串→整数 |
| content.images[].size_kb | images | file_size | KB×1024→字节 |
| content.major_type | posts | platform_metadata | 移入 JSON: `{"major_type": "..."}` |
| is_repost | posts | post_type | true → post_type='repost' |
| repost_content.id | posts | repost_of_id / repost_snapshot | 若原动态在库中→FK；否则→snapshot |
| repost_content.text | posts.repost_snapshot | JSON 内字段 | 存入 snapshot JSON |
| repost_content.images | images + post_media | — | 图片关联到转发 post，is_repost_media=1 |
| repost_content.author_name | authors | display_name | 创建或查找 author 行 |
| repost_content.author_mid | authors | platform_user_id | 同上 |
| repost_content.deleted | posts | repost_snapshot.deleted | 存入 snapshot JSON |
| stats.likes | post_stats | likes | 创建一条快照 |
| stats.comments | post_stats | comments | 同上 |
| stats.forwards | post_stats | forwards | 同上 |
| stats.views | post_stats | views | NULL（当前全部为 NULL） |

### 11.2 图片文件名解析规则

文件名格式 `{dynamic_id}_{index}@{quality}.{ext}` 解析：

```
1210001435340570626_00@original.png
├─ platform_post_id: 1210001435340570626
├─ sort_order: 0
├─ quality: original
└─ mime_type: image/png (由扩展名推断)

1217759413282013185_100@repost.jpg
├─ platform_post_id: 1217759413282013185
├─ sort_order: 100
├─ quality: repost (→ is_repost_media = 1)
└─ mime_type: image/jpeg
```

### 11.3 转发关联解析规则

```
对于每条 repost 类型的动态:
  1. 取 repost_content.id (原动态 platform_post_id)
  2. 在 posts 表中查找 (platform_id=B站, platform_post_id=原ID)
  3. 若找到:
       → posts.repost_of_id = 找到的行 id
       → posts.repost_snapshot = NULL (无需快照，原动态在库中)
  4. 若未找到:
       → posts.repost_of_id = NULL
       → posts.repost_snapshot = JSON 快照:
         {
           "platform_post_id": "原ID",
           "type": "原类型",
           "text": "原文本",
           "deleted": true/false,
           "author_name": "原作者",
           "author_mid": "原作者ID"
         }
```

---

## 附录 A：SQLite 特殊配置

数据库连接后必须执行的 PRAGMA：

```
PRAGMA journal_mode = WAL;         -- 写前日志，支持并发读写
PRAGMA foreign_keys = ON;          -- 启用外键约束
PRAGMA busy_timeout = 5000;        -- 锁定等待 5 秒
PRAGMA synchronous = NORMAL;       -- WAL 模式下 NORMAL 即可
PRAGMA cache_size = -64000;        -- 64MB 缓存
PRAGMA temp_store = MEMORY;        -- 临时表存内存
```

## 附录 B：完整表清单

| # | 表名 | 类型 | 行数(当前) | 行数(10年) |
|---|------|------|-----------|-----------|
| 1 | platforms | 普通 | 1 | ~5 |
| 2 | authors | 普通 | ~40 | ~200 |
| 3 | posts | 普通 | 3,547 | ~10,000 |
| 4 | images | 普通 | 1,083 | ~5,000 |
| 5 | media | 普通 | 0 | ~500 |
| 6 | tags | 普通 | 0 | ~200 |
| 7 | post_tags | 关联 | 0 | ~10,000 |
| 8 | post_media | 关联 | ~1,100 | ~5,500 |
| 9 | post_stats | 时序 | 3,547 | ~50,000 |
| 10 | posts_fts | FTS5 | 3,547 | ~10,000 |
| 11 | schema_migrations | 管理 | 1 | ~20 |
| — | **合计** | — | **~12,819** | **~91,425** |

---

> **本文档结束。**  
> 后续所有数据库操作必须以本文档为标准。  
> 如需修改表结构，必须先提交变更建议，更新本文档后，再通过 Migration 实施。
