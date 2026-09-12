/**
 * SUI Archive -- Search Page
 *
 * Client-side full-text search across all archived posts. The search index
 * is loaded lazily on first interaction and cached in memory. All matching,
 * filtering, and highlighting runs entirely in the browser.
 */

import { $, createElement, debounce, formatNumber } from './dom.js';
import { fetchSearchIndex } from './api.js';
import { SEARCH_DEBOUNCE_MS } from './config.js';

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

/** Maps post_type values to Chinese display labels. */
const TYPE_LABELS = {
  image:  '图片',
  text:   '文字',
  repost: '转发',
  video:  '视频',
};

/** Maximum number of tag options shown in the filter panel. */
const MAX_TAG_FILTERS = 20;

/** Characters of context shown before/after the first match in a snippet. */
const SNIPPET_CONTEXT = 50;

/** Maximum length of the highlighted text snippet. */
const SNIPPET_MAX_CHARS = 300;

// ---------------------------------------------------------------------------
// Module state
// ---------------------------------------------------------------------------

/** @type {Object[]|null} Cached search index entries. */
let entries = null;

/** @type {boolean} Whether the index is currently being fetched. */
let isLoadingIndex = false;

/** @type {Promise<void>|null} In-flight index load promise for deduplication. */
let indexLoadPromise = null;

/** @type {string[]} Sorted unique years extracted from entries. */
let availableYears = [];

/** @type {{slug: string, count: number}[]} Top tags sorted by frequency. */
let availableTags = [];

/** DOM element references (resolved on init). */
let searchInput    = null;
let searchBtn      = null;
let filterType     = null;
let filterYear     = null;
let filterImages   = null;
let filterTags     = null;
let resultsCount   = null;
let resultsContainer = null;

// ---------------------------------------------------------------------------
// Index loading
// ---------------------------------------------------------------------------

/**
 * Load the search index on demand.
 *
 * Returns immediately if the index is already loaded. If a load is already
 * in progress, returns the existing promise so callers share one fetch.
 *
 * @returns {Promise<void>}
 */
function ensureIndex() {
  if (entries) return Promise.resolve();
  if (indexLoadPromise) return indexLoadPromise;

  isLoadingIndex = true;
  showLoadingState();

  indexLoadPromise = fetchSearchIndex().then((data) => {
    isLoadingIndex = false;

    if (!data || !Array.isArray(data.entries)) {
      entries = [];
      showEmptyIndexMessage();
      return;
    }

    entries = data.entries;
    buildFilterOptions();
  }).catch((err) => {
    isLoadingIndex = false;
    entries = [];
    console.error('[search] Failed to load search index:', err);
    showErrorMessage();
  });

  return indexLoadPromise;
}

/**
 * Extract unique years and top tags from the loaded entries and populate
 * the filter dropdowns.
 */
function buildFilterOptions() {
  if (!entries || entries.length === 0) return;

  // -- Years ---------------------------------------------------------------
  const yearSet = new Set();
  for (const entry of entries) {
    if (entry.published_at) {
      yearSet.add(entry.published_at.slice(0, 4));
    }
  }
  availableYears = Array.from(yearSet).sort((a, b) => b.localeCompare(a));

  if (filterYear) {
    // Preserve the currently selected value if any
    const current = filterYear.value;
    // Clear existing dynamic options (keep the default empty option)
    while (filterYear.options.length > 1) {
      filterYear.remove(1);
    }
    for (const year of availableYears) {
      const opt = document.createElement('option');
      opt.value = year;
      opt.textContent = `${year}年`;
      filterYear.appendChild(opt);
    }
    if (current && availableYears.includes(current)) {
      filterYear.value = current;
    }
  }

  // -- Tags ----------------------------------------------------------------
  const tagCounts = new Map();
  for (const entry of entries) {
    if (Array.isArray(entry.tags)) {
      for (const tag of entry.tags) {
        tagCounts.set(tag, (tagCounts.get(tag) ?? 0) + 1);
      }
    }
  }
  availableTags = Array.from(tagCounts.entries())
    .map(([slug, count]) => ({ slug, count }))
    .sort((a, b) => b.count - a.count)
    .slice(0, MAX_TAG_FILTERS);

  if (filterTags) {
    const currentSelection = Array.from(filterTags.selectedOptions).map((o) => o.value);
    filterTags.innerHTML = '';
    for (const { slug, count } of availableTags) {
      const opt = document.createElement('option');
      opt.value = slug;
      opt.textContent = `${slug} (${count})`;
      if (currentSelection.includes(slug)) {
        opt.selected = true;
      }
      filterTags.appendChild(opt);
    }
  }
}

// ---------------------------------------------------------------------------
// Query parsing
// ---------------------------------------------------------------------------

/**
 * Parse a search query string into individual keyword tokens.
 *
 * Supports:
 *   - Plain keywords separated by spaces (AND logic)
 *   - Quoted exact phrases: "exact phrase"
 *
 * @param {string} query - raw search input
 * @returns {string[]} array of lowercased keyword strings
 */
function parseQuery(query) {
  if (!query) return [];

  const tokens = [];
  const lower = query.toLowerCase();
  let i = 0;

  while (i < lower.length) {
    // Skip whitespace
    if (lower[i] === ' ') {
      i++;
      continue;
    }

    // Quoted phrase
    if (lower[i] === '"') {
      const end = lower.indexOf('"', i + 1);
      if (end !== -1) {
        const phrase = lower.slice(i + 1, end).trim();
        if (phrase) tokens.push(phrase);
        i = end + 1;
      } else {
        // Unclosed quote -- treat rest as a single token
        const rest = lower.slice(i + 1).trim();
        if (rest) tokens.push(rest);
        break;
      }
      continue;
    }

    // Plain word -- read until next space
    let j = i;
    while (j < lower.length && lower[j] !== ' ') j++;
    const word = lower.slice(i, j).trim();
    if (word) tokens.push(word);
    i = j;
  }

  return tokens;
}

// ---------------------------------------------------------------------------
// Search & filter
// ---------------------------------------------------------------------------

/**
 * Count total occurrences of a keyword in a text string.
 *
 * @param {string} text - lowercased text to search
 * @param {string} keyword - lowercased keyword
 * @returns {number}
 */
function countOccurrences(text, keyword) {
  if (!text || !keyword) return 0;
  let count = 0;
  let pos = 0;
  while (true) {
    const idx = text.indexOf(keyword, pos);
    if (idx === -1) break;
    count++;
    pos = idx + 1;
  }
  return count;
}

/**
 * Run the search algorithm on all entries with the given query tokens
 * and active filters.
 *
 * @param {string[]} tokens - parsed keyword tokens (already lowercased)
 * @param {Object} filters - active filter values
 * @param {string} filters.type - post type filter ('' = all)
 * @param {string} filters.year - year filter ('' = all)
 * @param {boolean} filters.imagesOnly - only show posts with images
 * @param {string[]} filters.tags - selected tag slugs (AND logic)
 * @returns {Object[]} matched entries sorted by date descending
 */
function searchEntries(tokens, filters) {
  if (!entries) return [];

  const results = [];

  for (const entry of entries) {
    // -- Filter: type ------------------------------------------------------
    if (filters.type && entry.post_type !== filters.type) continue;

    // -- Filter: year ------------------------------------------------------
    if (filters.year && entry.published_at) {
      if (!entry.published_at.startsWith(filters.year)) continue;
    }

    // -- Filter: images ----------------------------------------------------
    if (filters.imagesOnly && !entry.has_images) continue;

    // -- Filter: tags (AND) ------------------------------------------------
    if (filters.tags.length > 0) {
      const entryTags = entry.tags ?? [];
      const allMatch = filters.tags.every((t) => entryTags.includes(t));
      if (!allMatch) continue;
    }

    // -- Keyword matching --------------------------------------------------
    if (tokens.length === 0) {
      // No keywords -- include all entries that pass filters
      results.push({ entry, score: 0 });
      continue;
    }

    const searchText = [entry.text, entry.repost_text]
      .filter(Boolean)
      .map((t) => t.toLowerCase())
      .join('\n');

    let totalScore = 0;
    let allMatch = true;

    for (const token of tokens) {
      const c = countOccurrences(searchText, token);
      if (c === 0) {
        allMatch = false;
        break;
      }
      totalScore += c;
    }

    if (allMatch) {
      results.push({ entry, score: totalScore });
    }
  }

  // Sort by published_at descending (newest first).
  // Results with the same date preserve relevance order.
  results.sort((a, b) => {
    const da = a.entry.published_at ?? '';
    const db = b.entry.published_at ?? '';
    return db.localeCompare(da);
  });

  return results;
}

// ---------------------------------------------------------------------------
// Highlighting & snippets
// ---------------------------------------------------------------------------

/**
 * Escape characters that have special meaning in HTML.
 *
 * @param {string} str - raw string
 * @returns {string} HTML-safe string
 */
function escapeHTML(str) {
  return str
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

/**
 * Escape special regex characters in a string for safe use in RegExp.
 *
 * @param {string} str
 * @returns {string}
 */
function escapeRegex(str) {
  return str.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

/**
 * Build a highlighted context snippet around the first match of any keyword.
 *
 * The snippet shows up to SNIPPET_CONTEXT characters before and after the
 * first occurrence of any keyword, with matching keywords wrapped in <mark>.
 *
 * @param {string} text - original (non-lowercased) post text
 * @param {string[]} tokens - lowercased keyword tokens
 * @returns {string} HTML string with <mark> highlights
 */
function buildSnippet(text, tokens) {
  if (!text) return '';

  const lowerText = text.toLowerCase();

  // Find the position of the first keyword match
  let firstIdx = -1;
  let firstLen = 0;

  for (const token of tokens) {
    const idx = lowerText.indexOf(token);
    if (idx !== -1 && (firstIdx === -1 || idx < firstIdx)) {
      firstIdx = idx;
      firstLen = token.length;
    }
  }

  // Determine snippet boundaries
  let start = 0;
  let end = text.length;

  if (firstIdx !== -1) {
    start = Math.max(0, firstIdx - SNIPPET_CONTEXT);
    end = Math.min(text.length, firstIdx + firstLen + SNIPPET_CONTEXT);
  } else {
    // No match found in this text -- just take the beginning
    end = Math.min(text.length, SNIPPET_MAX_CHARS);
  }

  let snippet = text.slice(start, end);

  // Add ellipsis indicators
  const prefix = start > 0 ? '...' : '';
  const suffix = end < text.length ? '...' : '';

  // Build the highlighted HTML
  let highlighted = highlightKeywords(snippet, tokens);

  // Truncate if still too long
  if (highlighted.length > SNIPPET_MAX_CHARS * 3) {
    highlighted = highlighted.slice(0, SNIPPET_MAX_CHARS * 3);
  }

  return prefix + highlighted + suffix;
}

/**
 * Wrap all occurrences of the given keywords in <mark> tags within a string.
 * Matching is case-insensitive. HTML special characters are escaped first.
 *
 * @param {string} text - raw text (not yet HTML-escaped)
 * @param {string[]} tokens - lowercased keywords
 * @returns {string} HTML string
 */
function highlightKeywords(text, tokens) {
  if (!text || tokens.length === 0) return escapeHTML(text);

  // Build a combined regex for all tokens
  const escaped = tokens.map(escapeRegex);
  const pattern = new RegExp(`(${escaped.join('|')})`, 'gi');

  // Split text by matches, escape each segment, and wrap matches in <mark>
  const parts = text.split(pattern);
  let html = '';

  for (let i = 0; i < parts.length; i++) {
    const part = parts[i];
    if (!part) continue;
    const escapedPart = escapeHTML(part);
    // Odd indices are captured matches from the split
    if (i % 2 === 1) {
      html += `<mark class="search-highlight">${escapedPart}</mark>`;
    } else {
      html += escapedPart;
    }
  }

  return html;
}

// ---------------------------------------------------------------------------
// Rendering
// ---------------------------------------------------------------------------

/**
 * Show skeleton loading placeholders in the results container.
 */
function showLoadingState() {
  if (!resultsContainer) return;
  resultsContainer.innerHTML = '';

  for (let i = 0; i < 5; i++) {
    const skeleton = createElement('div', { class: 'skeleton--card' });
    skeleton.appendChild(
      createElement('div', { class: 'skeleton__line skeleton__line--short' }),
    );
    for (let j = 0; j < 3; j++) {
      skeleton.appendChild(
        createElement('div', {
          class: `skeleton__line${j === 2 ? ' skeleton__line--medium' : ''}`,
        }),
      );
    }
    resultsContainer.appendChild(skeleton);
  }
}

/**
 * Display a message when the search index could not be loaded.
 */
function showErrorMessage() {
  if (!resultsContainer) return;
  resultsContainer.innerHTML = '';
  const msg = createElement('div', {
    class: 'search-results__empty',
    style: { textAlign: 'center', padding: '2rem 1rem', color: 'var(--muted-foreground, #666)' },
  }, ['搜索索引加载失败，请稍后重试。']);
  resultsContainer.appendChild(msg);
}

/**
 * Display a message when the search index is empty.
 */
function showEmptyIndexMessage() {
  if (!resultsContainer) return;
  resultsContainer.innerHTML = '';
  const msg = createElement('div', {
    class: 'search-results__empty',
    style: { textAlign: 'center', padding: '2rem 1rem', color: 'var(--muted-foreground, #666)' },
  }, ['搜索索引为空。']);
  resultsContainer.appendChild(msg);
}

/**
 * Display the initial hint message before any search is performed.
 */
function showInitialHint() {
  if (!resultsContainer) return;
  if (resultsContainer.children.length > 0) return; // already has content
  const hint = createElement('div', {
    class: 'search-results__empty',
    style: { textAlign: 'center', padding: '2rem 1rem', color: 'var(--muted-foreground, #666)' },
  }, ['请输入搜索关键词']);
  resultsContainer.appendChild(hint);
}

/**
 * Update the results count display.
 *
 * @param {number} count
 */
function updateResultsCount(count) {
  if (!resultsCount) return;

  if (count > 0) {
    resultsCount.textContent = `找到 ${formatNumber(count)} 条结果`;
  } else {
    resultsCount.textContent = '没有找到相关内容';
  }
}

/**
 * Create a single search result card element.
 *
 * @param {Object} entry - search index entry
 * @param {string[]} tokens - keyword tokens for highlighting
 * @returns {HTMLAnchorElement}
 */
function createResultCard(entry, tokens) {
  const href = `/d/${entry.platform_post_id}`;
  const card = createElement('a', {
    class: 'post-card card card--interactive',
    href,
  });

  // -- Header --------------------------------------------------------------
  const header = createElement('div', { class: 'post-card__header' });

  const date = createElement('time', {
    class: 'post-card__date',
    datetime: entry.published_at,
  });
  date.textContent = entry.published_at ?? '';

  const typeLabel = TYPE_LABELS[entry.post_type] ?? entry.post_type ?? '';
  const typeTag = createElement('span', { class: 'post-card__type tag' });
  typeTag.textContent = typeLabel;

  header.appendChild(date);
  header.appendChild(typeTag);
  card.appendChild(header);

  // -- Text snippet with highlighting --------------------------------------
  const mainText = entry.text ?? '';
  const repostText = entry.repost_text ?? '';

  // Build snippet from whichever field has the first match
  const snippetSource = mainText || repostText;
  if (snippetSource) {
    const textDiv = createElement('div', { class: 'post-card__text' });
    textDiv.innerHTML = buildSnippet(snippetSource, tokens);
    card.appendChild(textDiv);
  }

  // -- Image indicator -----------------------------------------------------
  if (entry.has_images) {
    const imgDiv = createElement('div', { class: 'post-card__images post-card__images--1' });
    const countSpan = createElement('span', { class: 'post-card__img-count' });
    countSpan.textContent = `\u{1F4F7} ${entry.image_count ?? 0}张图片`;
    imgDiv.appendChild(countSpan);
    card.appendChild(imgDiv);
  }

  return card;
}

/**
 * Render the full set of search results into the container.
 *
 * @param {Object[]} results - array of { entry, score } objects
 * @param {string[]} tokens - keyword tokens for highlighting
 */
function renderResults(results, tokens) {
  if (!resultsContainer) return;
  resultsContainer.innerHTML = '';

  updateResultsCount(results.length);

  if (results.length === 0) return;

  const fragment = document.createDocumentFragment();
  for (const { entry } of results) {
    fragment.appendChild(createResultCard(entry, tokens));
  }
  resultsContainer.appendChild(fragment);
}

// ---------------------------------------------------------------------------
// Search execution
// ---------------------------------------------------------------------------

/**
 * Read the current state of all form controls and execute the search.
 *
 * @param {boolean} [skipIfEmpty=false] - if true, do nothing when the query is empty
 */
async function executeSearch(skipIfEmpty = false) {
  const query = (searchInput?.value ?? '').trim();

  if (skipIfEmpty && !query) {
    return;
  }

  // Load index if not yet available
  await ensureIndex();
  if (!entries) return;

  const tokens = parseQuery(query);

  // Read filter values
  const filters = {
    type: filterType?.value ?? '',
    year: filterYear?.value ?? '',
    imagesOnly: filterImages?.checked ?? false,
    tags: filterTags
      ? Array.from(filterTags.selectedOptions).map((o) => o.value)
      : [],
  };

  const results = searchEntries(tokens, filters);
  renderResults(results, tokens);

  // Update URL without triggering navigation
  updateSearchURL(query, filters);
}

/**
 * Debounced version of executeSearch for input events.
 */
let debouncedSearch = null;

/**
 * Update the browser URL to reflect the current search query.
 *
 * @param {string} query
 * @param {Object} filters
 */
function updateSearchURL(query, filters) {
  const params = new URLSearchParams();

  if (query) params.set('q', query);
  if (filters.type) params.set('type', filters.type);
  if (filters.year) params.set('year', filters.year);
  if (filters.imagesOnly) params.set('images', '1');
  if (filters.tags.length > 0) params.set('tags', filters.tags.join(','));

  const qs = params.toString();
  const newURL = qs ? `/search?${qs}` : '/search';

  history.replaceState(null, '', newURL);
}

/**
 * Read URL query parameters and populate form controls accordingly.
 *
 * @returns {{ query: string, filters: Object }}
 */
function readURLParams() {
  const params = new URLSearchParams(window.location.search);

  return {
    query: params.get('q') ?? '',
    type: params.get('type') ?? '',
    year: params.get('year') ?? '',
    imagesOnly: params.get('images') === '1',
    tags: (params.get('tags') ?? '').split(',').filter(Boolean),
  };
}

// ---------------------------------------------------------------------------
// Event handlers
// ---------------------------------------------------------------------------

/**
 * Handle input events on the search field (debounced).
 */
function onSearchInput() {
  if (debouncedSearch) {
    debouncedSearch();
  }
}

/**
 * Handle explicit search submission (button click or Enter key).
 */
function onSearchSubmit(e) {
  if (e) e.preventDefault();
  if (debouncedSearch) debouncedSearch.cancel();
  executeSearch();
}

/**
 * Handle filter changes -- run search immediately.
 */
function onFilterChange() {
  executeSearch(true);
}

/**
 * Preload the index when the search input receives focus.
 */
function onSearchFocus() {
  ensureIndex();
}

// ---------------------------------------------------------------------------
// Initialisation
// ---------------------------------------------------------------------------

/**
 * Initialise the search page.
 *
 * Called by app.js when the search route is detected. Resolves DOM element
 * references, attaches event listeners, and handles URL query parameters.
 */
export async function initSearch() {
  // Resolve DOM references
  searchInput      = $('#search-input');
  searchBtn        = $('#search-btn');
  filterType       = $('#filter-type');
  filterYear       = $('#filter-year');
  filterImages     = $('#filter-images');
  filterTags       = $('#filter-tags');
  resultsCount     = $('#results-count');
  resultsContainer = $('#search-results');

  // Create the debounced search function
  debouncedSearch = debounce(() => executeSearch(), SEARCH_DEBOUNCE_MS);

  // Attach event listeners
  if (searchInput) {
    searchInput.addEventListener('input', onSearchInput);
    searchInput.addEventListener('focus', onSearchFocus, { once: true });
    searchInput.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') onSearchSubmit(e);
    });
  }

  if (searchBtn) {
    searchBtn.addEventListener('click', onSearchSubmit);
  }

  if (filterType) {
    filterType.addEventListener('change', onFilterChange);
  }
  if (filterYear) {
    filterYear.addEventListener('change', onFilterChange);
  }
  if (filterImages) {
    filterImages.addEventListener('change', onFilterChange);
  }
  if (filterTags) {
    filterTags.addEventListener('change', onFilterChange);
  }

  // Handle URL query parameters
  const urlParams = readURLParams();
  if (urlParams.query) {
    if (searchInput) searchInput.value = urlParams.query;
  }
  if (urlParams.type && filterType) {
    filterType.value = urlParams.type;
  }
  if (urlParams.imagesOnly && filterImages) {
    filterImages.checked = true;
  }

  // If there's a query in the URL, load index and run the search immediately
  if (urlParams.query) {
    await ensureIndex();

    // Apply tag filters after index is loaded (options are populated then)
    if (urlParams.year && filterYear) {
      filterYear.value = urlParams.year;
    }
    if (urlParams.tags.length > 0 && filterTags) {
      for (const opt of filterTags.options) {
        opt.selected = urlParams.tags.includes(opt.value);
      }
    }

    executeSearch();
  } else {
    // No query -- show the initial hint prompting the user to type
    showInitialHint();
  }
}
