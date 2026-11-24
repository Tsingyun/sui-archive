// SUI Archive Frontend Configuration
export const SITE_NAME = '岁己 SUI Archive';
export const SITE_URL = 'https://archive.suijisui.uk';
export const API_BASE = '/data';
export const INDEX_URL = `${API_BASE}/dynamics-index.json`;
export const SEARCH_INDEX_URL = `${API_BASE}/search-index.json`;
export const TAG_INDEX_URL = `${API_BASE}/tag-index.json`;
export const STATS_URL = `${API_BASE}/stats.json`;
export const POSTS_PER_PAGE = 50;
export const THUMB_VARIANTS = ['w300', 'w600', 'w1200'];
export const DEFAULT_YEAR = null; // null = latest year
export const IMAGE_BASE = '/images';
export const THUMB_BASE = '/thumbs';
export const SEARCH_DEBOUNCE_MS = 300;
export const LAZY_LOAD_THRESHOLD = 200; // px before viewport
export const EAGER_LOAD_COUNT = 6; // first N images load eagerly
