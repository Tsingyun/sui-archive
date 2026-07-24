/**
 * SUI Archive -- Timeline Module
 *
 * Manages the homepage timeline: year-tab switching, paginated post loading,
 * and infinite scroll integration. Fetches data from the build-generated
 * JSON index and per-year data files.
 */

import { fetchIndex, fetchYearData } from './api.js';
import { setState } from './state.js';
import { $ } from './dom.js';
import { POSTS_PER_PAGE, DEFAULT_YEAR } from './config.js';
import { renderPostList, createSkeletonCard } from './post-card.js';
import { initInfiniteScroll } from './infinite-scroll.js';

// ---------------------------------------------------------------------------
// Module state
// ---------------------------------------------------------------------------

/** Cached dynamics-index.json payload. */
let indexData = null;

/** In-memory cache of per-year post arrays, keyed by year (or "all"). */
const yearDataCache = new Map();

/** Currently active infinite-scroll controller. */
let scrollController = null;

/** The current page index (0-based) within the active year's post list. */
let currentPage = 0;

// ---------------------------------------------------------------------------
// DOM references
// ---------------------------------------------------------------------------

function getYearTabsEl() {
  return $('#year-tabs');
}

function getPostListEl() {
  return $('#post-list');
}

function getSentinelEl() {
  return $('#scroll-sentinel');
}

// ---------------------------------------------------------------------------
// Initialisation
// ---------------------------------------------------------------------------

/**
 * Initialise the homepage timeline.
 *
 * 1. Fetch the dynamics index (year list + metadata).
 * 2. Render year tabs.
 * 3. Load posts for the default (latest) year.
 * 4. Wire up infinite scroll.
 */
export async function initTimeline() {
  const yearTabsEl = getYearTabsEl();
  const postListEl = getPostListEl();
  const sentinelEl = getSentinelEl();

  if (!postListEl) {
    console.warn('[timeline] #post-list element not found');
    return;
  }

  // Show loading skeletons immediately
  showSkeletons(postListEl);

  // Fetch the year index
  try {
    indexData = await fetchIndex();
    setState({ indexData });
  } catch (err) {
    console.error('[timeline] Failed to fetch index:', err);
    showError(postListEl, '无法加载数据，请刷新页面重试');
    return;
  }

  // Render tabs
  if (yearTabsEl && indexData?.years) {
    renderYearTabs(yearTabsEl, indexData.years);
  }

  // Determine which year to load first
  const years = indexData?.years ?? [];
  const defaultYear =
    DEFAULT_YEAR ?? (years.length > 0 ? years[0].year : null);

  if (defaultYear != null) {
    await loadYearData(defaultYear, postListEl, sentinelEl);
  } else {
    postListEl.innerHTML = '';
    const empty = document.createElement('p');
    empty.className = 'timeline__empty';
    empty.textContent = '暂无动态数据';
    postListEl.appendChild(empty);
  }
}

// ---------------------------------------------------------------------------
// Year tabs
// ---------------------------------------------------------------------------

/**
 * Render the year-tab selector.
 *
 * Produces a "全部" (all) button followed by individual year buttons in
 * descending order.
 */
function renderYearTabs(container, years) {
  container.innerHTML = '';

  const wrapper = document.createElement('div');
  wrapper.className = 'timeline__years';

  // "All" tab
  const allBtn = createTabButton('全部', 'all');
  wrapper.appendChild(allBtn);

  // Individual year tabs (years array is already sorted descending)
  const sortedYears = [...years].sort((a, b) => b.year - a.year);
  for (const yearInfo of sortedYears) {
    const btn = createTabButton(String(yearInfo.year), yearInfo.year);
    wrapper.appendChild(btn);
  }

  container.appendChild(wrapper);

  // Activate the first real year tab (or "all" if no years exist)
  const defaultYear =
    DEFAULT_YEAR ?? (sortedYears.length > 0 ? sortedYears[0].year : 'all');
  activateTab(wrapper, defaultYear);

  // Event delegation for tab clicks
  wrapper.addEventListener('click', (e) => {
    const btn = e.target.closest('.timeline__year-btn');
    if (!btn) return;

    const year = btn.getAttribute('data-year');
    if (year == null) return;

    activateTab(wrapper, year === 'all' ? 'all' : Number(year));
    handleYearSwitch(year === 'all' ? 'all' : Number(year));
  });
}

/**
 * Create a single tab button element.
 */
function createTabButton(label, yearValue) {
  const btn = document.createElement('button');
  btn.className = 'btn btn--ghost btn--sm timeline__year-btn';
  btn.setAttribute('role', 'tab');
  btn.setAttribute('data-year', String(yearValue));
  btn.textContent = label;
  return btn;
}

/**
 * Mark a specific tab as active and deactivate all siblings.
 */
function activateTab(wrapper, year) {
  const buttons = wrapper.querySelectorAll('.timeline__year-btn');
  for (const btn of buttons) {
    const btnYear = btn.getAttribute('data-year');
    const isActive =
      btnYear === String(year) || (year === 'all' && btnYear === 'all');

    btn.classList.toggle('active', isActive);
    btn.setAttribute('aria-selected', String(isActive));
  }
}

// ---------------------------------------------------------------------------
// Data loading
// ---------------------------------------------------------------------------

/**
 * Handle a year-tab click: tear down the old scroll controller, clear the
 * post list, load data for the new year, and re-render.
 */
async function handleYearSwitch(year) {
  const postListEl = getPostListEl();
  const sentinelEl = getSentinelEl();

  if (!postListEl) return;

  // Tear down existing infinite scroll
  if (scrollController) {
    scrollController.destroy();
    scrollController = null;
  }

  // Reset pagination
  currentPage = 0;

  setState({ currentYear: year, posts: [], currentPage: 0 });

  // Clear the feed
  postListEl.innerHTML = '';

  // Reset the sentinel element
  if (sentinelEl) {
    sentinelEl.textContent = '';
    sentinelEl.classList.remove('scroll-sentinel--done');
  }

  // Show skeletons
  showSkeletons(postListEl);

  // Load data
  await loadYearData(year, postListEl, sentinelEl);
}

/**
 * Fetch posts for a given year (or all years), render the first page,
 * and start infinite scroll.
 */
async function loadYearData(year, postListEl, sentinelEl) {
  let posts;

  try {
    if (year === 'all') {
      posts = await loadAllYears();
    } else {
      posts = await loadSingleYear(year);
    }
  } catch (err) {
    console.error(`[timeline] Failed to load data for year ${year}:`, err);
    showError(postListEl, '加载数据失败，请刷新页面重试');
    return;
  }

  // Store in state
  setState({ posts, currentYear: year });

  // Clear skeletons
  postListEl.innerHTML = '';

  // Handle empty result
  if (posts.length === 0) {
    const empty = document.createElement('p');
    empty.className = 'timeline__empty';
    empty.textContent =
      year === 'all' ? '暂无动态数据' : `${year} 年暂无动态`;
    postListEl.appendChild(empty);
    return;
  }

  // Render first page
  const firstPage = posts.slice(0, POSTS_PER_PAGE);
  currentPage = 1;
  renderPostList(postListEl, firstPage, 0);

  // If everything fits in one page, we're done
  if (posts.length <= POSTS_PER_PAGE) {
    showAllLoaded(sentinelEl, posts.length);
    return;
  }

  // Set up infinite scroll for remaining pages
  setupInfiniteScroll(posts, postListEl, sentinelEl);
}

/**
 * Load a single year's data (with cache).
 */
async function loadSingleYear(year) {
  if (yearDataCache.has(year)) {
    return yearDataCache.get(year);
  }

  const data = await fetchYearData(year);
  const posts = data?.posts ?? [];
  yearDataCache.set(year, posts);
  return posts;
}

/**
 * Load all years' data, merge, and sort by date descending.
 */
async function loadAllYears() {
  if (yearDataCache.has('all')) {
    return yearDataCache.get('all');
  }

  const years = indexData?.years ?? [];

  // Fetch all year files concurrently
  const fetches = years.map((y) => {
    if (yearDataCache.has(y.year)) {
      return Promise.resolve(yearDataCache.get(y.year));
    }
    return fetchYearData(y.year).then((data) => {
      const posts = data?.posts ?? [];
      yearDataCache.set(y.year, posts);
      return posts;
    });
  });

  const results = await Promise.all(fetches);
  const allPosts = results.flat();

  // Sort by published_at descending
  allPosts.sort((a, b) => {
    const dateA = new Date(a.published_at).getTime();
    const dateB = new Date(b.published_at).getTime();
    return dateB - dateA;
  });

  yearDataCache.set('all', allPosts);
  return allPosts;
}

// ---------------------------------------------------------------------------
// Infinite scroll
// ---------------------------------------------------------------------------

/**
 * Wire up infinite scroll for the remaining pages of a loaded year.
 */
function setupInfiniteScroll(posts, postListEl, sentinelEl) {
  if (scrollController) {
    scrollController.destroy();
    scrollController = null;
  }

  scrollController = initInfiniteScroll(sentinelEl, async () => {
    const start = currentPage * POSTS_PER_PAGE;
    const end = start + POSTS_PER_PAGE;

    if (start >= posts.length) {
      return false; // signal no more data
    }

    const nextPage = posts.slice(start, end);
    renderPostList(postListEl, nextPage, start);
    currentPage++;

    // Return false when we've reached the last page
    if (end >= posts.length) {
      return false;
    }

    return undefined; // more data may be available
  });
}

// ---------------------------------------------------------------------------
// UI helpers
// ---------------------------------------------------------------------------

/**
 * Append skeleton cards to the post list container.
 */
function showSkeletons(container, count = 3) {
  for (let i = 0; i < count; i++) {
    container.appendChild(createSkeletonCard());
  }
}

/**
 * Show the "all loaded" message in the sentinel element.
 */
function showAllLoaded(sentinelEl, totalCount) {
  if (!sentinelEl) return;

  sentinelEl.classList.add('scroll-sentinel--done');
  sentinelEl.textContent = `已加载全部 ${totalCount} 条动态`;
}

/**
 * Display an error message in the post list container.
 */
function showError(container, message) {
  container.innerHTML = '';
  const errorEl = document.createElement('div');
  errorEl.className = 'timeline__error';
  errorEl.setAttribute('role', 'alert');
  errorEl.textContent = message;
  container.appendChild(errorEl);
}
