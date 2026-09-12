/**
 * SUI Archive -- Tag Filter Module
 *
 * Powers two pages:
 *   1. Tags page (/tags)          - renders a tag cloud of all tags
 *   2. Tag detail (/tag/{slug})   - lists posts bearing a specific tag
 *
 * Data sources:
 *   - /data/tag-index.json    (tag metadata with counts)
 *   - /data/search-index.json (full-text entries with tag slugs)
 */

import { $, createElement } from './dom.js';
import { fetchTagIndex, fetchSearchIndex } from './api.js';
import { renderPostList } from './post-card.js';

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

/** Minimum font size for tag cloud items (rem). */
const MIN_FONT_SIZE = 0.8;

/** Maximum font size for tag cloud items (rem). */
const MAX_FONT_SIZE = 2.0;

/** Maximum character length for text previews extracted from search entries. */
const TEXT_PREVIEW_LENGTH = 140;

// ---------------------------------------------------------------------------
// Tags page (/tags)
// ---------------------------------------------------------------------------

/**
 * Initialise the tags page.
 *
 * Fetches the tag index and renders a tag cloud inside #tag-cloud.
 * Each tag is sized logarithmically by post count and links to its
 * respective detail page at /tag/{slug}.
 */
export async function initTagsPage() {
  const container = $('#tag-cloud');
  if (!container) {
    console.warn('[tag-filter] #tag-cloud element not found');
    return;
  }

  let tagData;
  try {
    tagData = await fetchTagIndex();
  } catch (err) {
    console.error('[tag-filter] Failed to fetch tag index:', err);
    showEmptyState(container, '无法加载标签数据，请刷新页面重试');
    return;
  }

  const tags = tagData?.tags ?? [];

  if (tags.length === 0) {
    showEmptyState(container, '暂无标签');
    return;
  }

  renderTagCloud(container, tags);
}

// ---------------------------------------------------------------------------
// Tag cloud rendering
// ---------------------------------------------------------------------------

/**
 * Render the tag cloud into a container element.
 *
 * Font sizes are computed on a logarithmic scale so that tags with very
 * high counts do not dominate excessively. Tags carrying a `color` field
 * receive a tinted background and matching border colour.
 *
 * @param {HTMLElement} container - the #tag-cloud element
 * @param {Object[]}    tags     - array of tag objects from tag-index.json
 */
function renderTagCloud(container, tags) {
  container.innerHTML = '';

  // Pre-compute log-scale parameters for font sizing
  const counts = tags.map((t) => t.post_count ?? 0);
  const minCount = Math.min(...counts);
  const maxCount = Math.max(...counts);
  const logMin = Math.log(minCount + 1);
  const logMax = Math.log(maxCount + 1);
  const logRange = logMax - logMin || 1; // guard against zero range

  // Sort alphabetically (Chinese-aware) for consistent display
  const sortedTags = [...tags].sort((a, b) =>
    a.name.localeCompare(b.name, 'zh-CN'),
  );

  const fragment = document.createDocumentFragment();

  for (const tag of sortedTags) {
    const count = tag.post_count ?? 0;
    const logVal = Math.log(count + 1);
    const ratio = (logVal - logMin) / logRange;
    const fontSize = MIN_FONT_SIZE + ratio * (MAX_FONT_SIZE - MIN_FONT_SIZE);

    // Build inline style string
    let style = `font-size: ${fontSize.toFixed(2)}rem`;
    if (tag.color) {
      style += `; background-color: ${tag.color}20; border-color: ${tag.color}`;
    }

    const el = createElement(
      'a',
      {
        class: 'tag-cloud__item tag',
        href: `/tag/${tag.slug}`,
        style,
        title: `${tag.name}: ${count}条动态`,
      },
      [
        tag.name,
        createElement('span', { class: 'tag-cloud__count' }, [String(count)]),
      ],
    );

    fragment.appendChild(el);
  }

  container.appendChild(fragment);
}

// ---------------------------------------------------------------------------
// Tag detail page (/tag/{slug})
// ---------------------------------------------------------------------------

/**
 * Initialise the tag detail page.
 *
 * Extracts the tag slug from the URL, fetches the tag index for metadata
 * and the search index for matching posts, then renders the filtered list.
 */
export async function initTagDetail() {
  const slug = extractSlugFromURL();
  if (!slug) {
    console.warn('[tag-filter] Could not extract tag slug from URL');
    return;
  }

  const countEl = $('#tag-post-count');
  const listEl = $('#tag-post-list');

  if (!listEl) {
    console.warn('[tag-filter] #tag-post-list element not found');
    return;
  }

  // Fetch tag index and search index concurrently
  let tagData;
  let searchData;
  try {
    [tagData, searchData] = await Promise.all([
      fetchTagIndex(),
      fetchSearchIndex(),
    ]);
  } catch (err) {
    console.error('[tag-filter] Failed to fetch data:', err);
    showError(listEl, '无法加载数据，请刷新页面重试');
    return;
  }

  // Look up tag metadata (used for page title, breadcrumb, etc.)
  const tagInfo = findTagBySlug(tagData?.tags ?? [], slug);

  if (!tagInfo && countEl) {
    countEl.textContent = '未找到该标签信息';
  }

  // Filter search entries that carry this tag slug
  const entries = searchData?.entries ?? [];
  const matchingPosts = entries
    .filter((entry) => Array.isArray(entry.tags) && entry.tags.includes(slug))
    .sort((a, b) => {
      const dateA = new Date(a.published_at).getTime();
      const dateB = new Date(b.published_at).getTime();
      return dateB - dateA; // newest first
    });

  // Display post count
  if (countEl) {
    countEl.textContent = `共 ${matchingPosts.length} 条动态`;
  }

  // Render results or empty state
  if (matchingPosts.length === 0) {
    showEmptyState(listEl, '该标签下暂无动态');
    return;
  }

  // Adapt search entries to post-card-compatible objects and render
  const posts = matchingPosts.map(adaptSearchEntry);
  renderPostList(listEl, posts, 0);
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/**
 * Extract the tag slug from the current URL path.
 *
 * Matches paths like `/tag/{slug}` and `/tag/{slug}/`.
 *
 * @returns {string|null} the decoded slug, or null if the path doesn't match
 */
function extractSlugFromURL() {
  const match = window.location.pathname.match(/^\/tag\/([^/]+)\/?$/);
  return match ? decodeURIComponent(match[1]) : null;
}

/**
 * Find a tag object by slug within a tags array.
 *
 * @param {Object[]} tags - array of tag objects
 * @param {string}   slug - the slug to look up
 * @returns {Object|null}
 */
function findTagBySlug(tags, slug) {
  return tags.find((t) => t.slug === slug) ?? null;
}

/**
 * Adapt a search-index entry into a post object compatible with
 * `createPostCard()` from post-card.js.
 *
 * The search index carries a subset of the fields present in per-year
 * dynamics files, so some fields are synthesised (text_preview) or
 * omitted (images array, stats).
 *
 * @param {Object} entry - a search-index entry
 * @returns {Object} a post-like object renderable by createPostCard
 */
function adaptSearchEntry(entry) {
  return {
    uuid: entry.uuid,
    platform_post_id: entry.platform_post_id,
    published_at: entry.published_at,
    post_type: entry.post_type,
    text_preview: truncateText(entry.text, TEXT_PREVIEW_LENGTH),
    has_images: entry.has_images ?? false,
    images: [], // image details are not stored in the search index
    image_count: entry.image_count ?? 0,
    stats: {},  // engagement stats are not available in the search index
    tags: entry.tags ?? [],
  };
}

/**
 * Truncate text to a maximum length, appending an ellipsis if clipped.
 *
 * @param {string} text   - source text
 * @param {number} maxLen - maximum character count
 * @returns {string}
 */
function truncateText(text, maxLen) {
  if (!text) return '';
  if (text.length <= maxLen) return text;
  return text.slice(0, maxLen).trimEnd() + '\u2026';
}

/**
 * Display a centered empty-state message in a container.
 *
 * @param {HTMLElement} container - target element
 * @param {string}      message  - text to display
 */
function showEmptyState(container, message) {
  container.innerHTML = '';
  const el = createElement(
    'p',
    {
      class: 'tag-filter__empty',
      style: {
        textAlign: 'center',
        padding: '2rem 1rem',
        color: 'var(--muted-foreground, #666)',
      },
    },
    [message],
  );
  container.appendChild(el);
}

/**
 * Display an error message in a container.
 *
 * @param {HTMLElement} container - target element
 * @param {string}      message  - error text
 */
function showError(container, message) {
  container.innerHTML = '';
  const el = createElement(
    'div',
    {
      class: 'tag-filter__error',
      role: 'alert',
      style: {
        textAlign: 'center',
        padding: '2rem 1rem',
        color: 'var(--destructive, #c00)',
      },
    },
    [message],
  );
  container.appendChild(el);
}
