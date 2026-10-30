/**
 * SUI Archive -- Internationalization (i18n) Module
 *
 * Reserved for future multi-language support. Currently only Chinese (zh-CN)
 * is used. This module provides a simple key-value lookup so that all
 * user-facing strings are centralised in one place rather than scattered
 * across feature modules.
 *
 * When multi-language support is added, extend the `strings` map with
 * additional locale keys and implement locale detection / switching.
 */

// ---------------------------------------------------------------------------
// String catalogue (zh-CN only for now)
// ---------------------------------------------------------------------------

const strings = {
  // General
  'site.name':          '岁己 SUI Archive',
  'site.description':   '虚拟主播岁己SUI的数字档案馆',
  'loading':            '加载中...',
  'error':              '出错了',
  'retry':              '重试',
  'close':              '关闭',
  'back':               '返回',
  'more':               '加载更多',
  'allLoaded':          '已加载全部',
  'noData':             '暂无数据',

  // Post types
  'type.image':         '图片',
  'type.text':          '文字',
  'type.repost':        '转发',
  'type.video':         '视频',
  'type.mixed':         '混合',

  // Stats
  'stats.likes':        '点赞',
  'stats.comments':     '评论',
  'stats.forwards':     '转发',
  'stats.views':        '浏览',

  // Timeline
  'timeline.all':       '全部',
  'timeline.posts':     '条动态',

  // Search
  'search.placeholder': '搜索动态内容...',
  'search.noResults':   '没有找到相关内容',
  'search.hint':        '请输入搜索关键词',
  'search.results':     '找到 {n} 条结果',

  // Gallery
  'gallery.title':      '画廊',
  'gallery.loadMore':   '加载更多',

  // Lightbox
  'lightbox.prev':      '上一张',
  'lightbox.next':      '下一张',
  'lightbox.close':     '关闭',

  // Share
  'share.copy':         '复制链接',
  'share.copied':       '已复制!',
  'share.failed':       '复制失败',
  'share.weibo':        '分享到微博',
  'share.twitter':      '分享到 Twitter',

  // Tags
  'tags.empty':         '暂无标签',
  'tags.posts':         '条动态',

  // Errors
  'error.pageNotFound': '页面未找到',
  'error.loadFailed':   '页面加载失败',
  'error.network':      '无法加载数据，请检查网络连接',
};

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

/**
 * Look up a localised string by key.
 * Supports simple interpolation: t('search.results', { n: 42 }) → "找到 42 条结果"
 *
 * @param {string} key
 * @param {Object} [params]  Interpolation parameters.
 * @returns {string}
 */
export function t(key, params = {}) {
  let str = strings[key] ?? key;
  for (const [k, v] of Object.entries(params)) {
    str = str.replace(new RegExp(`\\{${k}\\}`, 'g'), String(v));
  }
  return str;
}

/**
 * Get the current locale.
 * @returns {string}
 */
export function getLocale() {
  return 'zh-CN';
}

/**
 * Placeholder for future locale switching.
 * @param {string} _locale
 */
export function setLocale(_locale) {
  console.warn('[i18n] Locale switching is not yet implemented.');
}
