/**
 * SUI Archive -- Gallery Module
 *
 * Displays all archive images in a masonry grid with year-based filtering,
 * progressive lazy loading (w300 -> w600), batched pagination, and
 * lightbox integration. GIF images show a poster frame and open the
 * original in the lightbox on click.
 */

import { $, $$, createElement, formatNumber } from './dom.js';
import { fetchIndex, fetchYearData } from './api.js';
import { IMAGE_BASE, THUMB_BASE } from './config.js';
import { openLightbox } from './lightbox.js';

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

/** Number of images to render per batch. */
const BATCH_SIZE = 60;

// ---------------------------------------------------------------------------
// Module state
// ---------------------------------------------------------------------------

/** Cached dynamics-index.json payload. */
let indexData = null;

/** Flat array of all image objects for the currently selected year/filter. */
let allImages = [];

/** How many images have been rendered so far. */
let displayedCount = 0;

/** Currently selected year ('all' or a number). */
let activeYear = 'all';

/** IntersectionObserver for progressive thumbnail refinement. */
let lazyObserver = null;

/** WeakSet of <img> elements already observed. */
const observed = new WeakSet();

// ---------------------------------------------------------------------------
// DOM references
// ---------------------------------------------------------------------------

function getYearTabsEl() {
  return $('#gallery-year-tabs');
}

function getGridEl() {
  return $('#gallery-grid');
}

function getLoadMoreWrapper() {
  return $('#gallery-load-more');
}

function getLoadBtn() {
  return $('#gallery-load-btn');
}

// ---------------------------------------------------------------------------
// Image URL helpers
// ---------------------------------------------------------------------------

/**
 * Derive a thumbnail URL for a given original filename and size suffix.
 * @param {string} filename - original filename (e.g. "123_00@original.jpg")
 * @param {string} size - "w300", "w600", or "w1200"
 * @returns {string}
 */
function thumbUrl(filename, size) {
  const stem = filename.replace(/\.[^.]+$/, '');
  return `${THUMB_BASE}/${stem}_${size}.webp`;
}

/**
 * Build the original full-resolution URL.
 * @param {string} filename
 * @returns {string}
 */
function originalUrl(filename) {
  return `${IMAGE_BASE}/${filename}`;
}

/**
 * Build the poster frame URL for GIF images.
 * @param {string} filename
 * @returns {string}
 */
function posterUrl(filename) {
  const stem = filename.replace(/\.[^.]+$/, '');
  return `${THUMB_BASE}/${stem}_poster.webp`;
}

/**
 * Check whether a filename points to a GIF.
 * @param {string} filename
 * @returns {boolean}
 */
function isGif(filename) {
  return /\.gif$/i.test(filename);
}

// ---------------------------------------------------------------------------
// Initialisation
// ---------------------------------------------------------------------------

/** Whether the load-more button listener has been attached. */
let loadMoreInitialised = false;

/**
 * Initialise the gallery page.
 *
 * 1. Fetch the dynamics index to build year tabs.
 * 2. Load images for the default year.
 * 3. Wire up filtering, lazy loading, and lightbox.
 */
export async function initGallery() {
  const gridEl = getGridEl();
  const tabsEl = getYearTabsEl();

  if (!gridEl) {
    console.warn('[gallery] #gallery-grid element not found');
    return;
  }

  // Show skeleton placeholders immediately
  showSkeletons(gridEl, 12);

  // Initialise the progressive-loading observer
  initLazyObserver();

  // Wire up the load-more button (once)
  if (!loadMoreInitialised) {
    setupLoadMore();
    loadMoreInitialised = true;
  }

  // Fetch the year index
  try {
    indexData = await fetchIndex();
  } catch (err) {
    console.error('[gallery] Failed to fetch index:', err);
    showError(gridEl, '无法加载数据，请刷新页面重试');
    return;
  }

  if (!indexData?.years?.length) {
    gridEl.innerHTML = '';
    gridEl.appendChild(
      createElement('p', { class: 'gallery-empty' }, ['暂无图片数据']),
    );
    return;
  }

  // Render year filter tabs
  if (tabsEl) {
    renderYearTabs(tabsEl, indexData.years);
  }

  // Load images for all years by default
  await switchYear('all');
}

// ---------------------------------------------------------------------------
// Year tabs
// ---------------------------------------------------------------------------

/**
 * Render the year-tab selector with image counts.
 *
 * "全部" (all) is always the first tab, followed by individual years
 * in descending order.
 *
 * @param {HTMLElement} container
 * @param {{year: number, image_count?: number, count?: number}[]} years
 */
function renderYearTabs(container, years) {
  container.innerHTML = '';

  const wrapper = createElement('div', { class: 'year-tabs' });

  // Compute total image count across all years
  const totalCount = years.reduce(
    (sum, y) => sum + (y.image_count ?? y.count ?? 0),
    0,
  );

  // "All" tab
  wrapper.appendChild(createTabButton(`全部 ${formatNumber(totalCount)}`, 'all'));

  // Individual year tabs (sorted descending)
  const sorted = [...years].sort((a, b) => b.year - a.year);
  for (const y of sorted) {
    const count = y.image_count ?? y.count ?? 0;
    wrapper.appendChild(createTabButton(`${y.year} ${formatNumber(count)}`, y.year));
  }

  container.appendChild(wrapper);

  // Activate the default tab
  activateTab(wrapper, 'all');

  // Delegated click handler on the wrapper (replaced on each re-render)
  wrapper.addEventListener('click', (e) => {
    const btn = e.target.closest('[role="tab"]');
    if (!btn || !wrapper.contains(btn)) return;

    const year = btn.dataset.year;
    if (year == null) return;

    const parsed = year === 'all' ? 'all' : Number(year);
    activateTab(wrapper, parsed);
    switchYear(parsed);
  });
}

/**
 * Create a single tab button.
 * @param {string} label
 * @param {string|number} yearValue
 * @returns {HTMLButtonElement}
 */
function createTabButton(label, yearValue) {
  return createElement('button', {
    class: 'btn btn--ghost btn--sm',
    role: 'tab',
    'aria-selected': 'false',
    dataset: { year: String(yearValue) },
  }, [label]);
}

/**
 * Mark a specific tab as active and deactivate its siblings.
 * @param {HTMLElement} container
 * @param {string|number} year
 */
function activateTab(container, year) {
  const buttons = $$('[role="tab"]', container);
  for (const btn of buttons) {
    const isActive = btn.dataset.year === String(year);
    btn.classList.toggle('active', isActive);
    btn.setAttribute('aria-selected', String(isActive));
  }
}

// ---------------------------------------------------------------------------
// Data loading
// ---------------------------------------------------------------------------

/**
 * Switch the gallery to display images for a given year (or all years).
 * Clears the grid, fetches data, extracts images, and renders the first batch.
 *
 * @param {string|number} year
 */
async function switchYear(year) {
  const gridEl = getGridEl();
  if (!gridEl) return;

  activeYear = year;

  // Reset state
  allImages = [];
  displayedCount = 0;

  // Clear grid and show skeletons
  gridEl.innerHTML = '';
  showSkeletons(gridEl, 12);

  // Hide load-more while loading
  const loadMore = getLoadMoreWrapper();
  if (loadMore) loadMore.style.display = 'none';

  try {
    allImages = await extractImagesForYear(year);
  } catch (err) {
    console.error(`[gallery] Failed to load images for year ${year}:`, err);
    showError(gridEl, '加载图片失败，请刷新页面重试');
    return;
  }

  // Clear skeletons
  gridEl.innerHTML = '';

  if (allImages.length === 0) {
    gridEl.appendChild(
      createElement('p', { class: 'gallery-empty' }, [
        year === 'all' ? '暂无图片' : `${year} 年暂无图片`,
      ]),
    );
    return;
  }

  // Render first batch
  renderBatch(gridEl);
}

/**
 * Fetch posts for a year (or all years) and extract image objects.
 *
 * @param {string|number} year
 * @returns {Promise<GalleryImage[]>}
 */
async function extractImagesForYear(year) {
  const years = indexData?.years ?? [];
  let posts = [];

  if (year === 'all') {
    // Fetch all year files concurrently
    const fetches = years.map((y) =>
      fetchYearData(y.year).then((data) => data?.posts ?? []),
    );
    const results = await Promise.all(fetches);
    posts = results.flat();
  } else {
    const data = await fetchYearData(year);
    posts = data?.posts ?? [];
  }

  // Extract images from posts that have them
  /** @type {GalleryImage[]} */
  const images = [];

  for (const post of posts) {
    if (!post.has_images || !Array.isArray(post.images)) continue;

    for (const img of post.images) {
      images.push({
        filename: img.filename,
        width: img.width || 800,
        height: img.height || 600,
        isGif: isGif(img.filename),
        platformPostId: post.platform_post_id,
      });
    }
  }

  return images;
}

// ---------------------------------------------------------------------------
// Rendering
// ---------------------------------------------------------------------------

/**
 * Render the next batch of images into the grid.
 * @param {HTMLElement} gridEl
 */
function renderBatch(gridEl) {
  const start = displayedCount;
  const end = Math.min(start + BATCH_SIZE, allImages.length);
  const batch = allImages.slice(start, end);

  const fragment = document.createDocumentFragment();

  for (let i = 0; i < batch.length; i++) {
    fragment.appendChild(createGalleryItem(batch[i], start + i));
  }

  gridEl.appendChild(fragment);
  displayedCount = end;

  // Update load-more button visibility
  updateLoadMore();
}

/**
 * Create a single gallery item element.
 *
 * @param {GalleryImage} image
 * @param {number} globalIndex - index in the allImages array (for lightbox)
 * @returns {HTMLElement}
 */
function createGalleryItem(image, globalIndex) {
  const { filename, width, height, isGif: gif, platformPostId } = image;

  // Determine the initial src and the higher-quality swap target
  const src300 = gif ? posterUrl(filename) : thumbUrl(filename, 'w300');
  const src600 = gif ? posterUrl(filename) : thumbUrl(filename, 'w600');

  const img = createElement('img', {
    src: src300,
    'data-src': src600,
    alt: `画廊图片 ${globalIndex + 1}`,
    width: String(width),
    height: String(height),
    loading: 'lazy',
    style: { aspectRatio: `${width}/${height}` },
  });

  const link = createElement('a', {
    class: 'gallery-item',
    href: `/d/${platformPostId}`,
    dataset: { filename, index: String(globalIndex) },
    onclick: (e) => handleImageClick(e, globalIndex),
  }, [img]);

  // Register for progressive loading
  observeImage(img);

  return link;
}

/**
 * Handle click on a gallery image: prevent navigation and open lightbox.
 *
 * @param {MouseEvent} e
 * @param {number} clickedIndex
 */
function handleImageClick(e, clickedIndex) {
  e.preventDefault();

  // Build lightbox image array from all currently displayed images
  const lightboxImages = allImages.map((img, index) => ({
    src: img.isGif ? originalUrl(img.filename) : thumbUrl(img.filename, 'w1200'),
    width: img.width,
    height: img.height,
    alt: `画廊图片 ${index + 1}`,
  }));

  openLightbox(lightboxImages, clickedIndex);
}

// ---------------------------------------------------------------------------
// Load-more button
// ---------------------------------------------------------------------------

/**
 * Show or hide the load-more button based on remaining images.
 */
function updateLoadMore() {
  const wrapper = getLoadMoreWrapper();
  const btn = getLoadBtn();

  if (!wrapper || !btn) return;

  if (displayedCount >= allImages.length) {
    // All images shown -- hide the button
    wrapper.style.display = 'none';
  } else {
    wrapper.style.display = '';
    const remaining = allImages.length - displayedCount;
    btn.textContent = `加载更多 (${formatNumber(remaining)} 张)`;
  }
}

/**
 * Wire up the load-more button click handler.
 * Called once during setup; the button triggers renderBatch for the next page.
 */
function setupLoadMore() {
  const btn = getLoadBtn();
  if (!btn) return;

  btn.addEventListener('click', () => {
    const gridEl = getGridEl();
    if (!gridEl || displayedCount >= allImages.length) return;
    renderBatch(gridEl);
  });
}

// ---------------------------------------------------------------------------
// Progressive lazy loading (w300 -> w600 swap)
// ---------------------------------------------------------------------------

/**
 * Initialise the IntersectionObserver for progressive thumbnail refinement.
 *
 * When an image enters the viewport (with 200px look-ahead), the observer
 * preloads the w600 variant and swaps the src once ready.
 */
function initLazyObserver() {
  if (lazyObserver) return;

  lazyObserver = new IntersectionObserver(
    (entries) => {
      for (const entry of entries) {
        if (!entry.isIntersecting) continue;

        const img = /** @type {HTMLImageElement} */ (entry.target);
        const highResSrc = img.getAttribute('data-src');

        if (highResSrc) {
          lazyObserver.unobserve(img);
          upgradeImage(img, highResSrc);
        }
      }
    },
    { rootMargin: '200px' },
  );
}

/**
 * Observe an image element for progressive loading.
 * @param {HTMLImageElement} img
 */
function observeImage(img) {
  if (!img || observed.has(img)) return;
  observed.add(img);

  if (!lazyObserver) initLazyObserver();
  lazyObserver.observe(img);
}

/**
 * Preload the higher-resolution image and swap it in.
 * @param {HTMLImageElement} img
 * @param {string} highResSrc
 */
function upgradeImage(img, highResSrc) {
  const upgrade = new Image();
  upgrade.onload = () => {
    // Only swap if the element is still connected to the DOM
    if (img.isConnected && img.src !== highResSrc) {
      img.src = highResSrc;
    }
  };
  upgrade.src = highResSrc;
}

// ---------------------------------------------------------------------------
// Skeleton loading state
// ---------------------------------------------------------------------------

/**
 * Append skeleton placeholder elements to the grid.
 * @param {HTMLElement} container
 * @param {number} count
 */
function showSkeletons(container, count) {
  for (let i = 0; i < count; i++) {
    const skeleton = createElement('div', {
      class: 'gallery-item gallery-item--skeleton',
      'aria-hidden': 'true',
    }, [
      createElement('div', {
        class: 'gallery-item__placeholder',
        style: {
          width: '100%',
          paddingBottom: `${60 + Math.random() * 40}%`,
          background: 'var(--skeleton-bg, #e5e5e5)',
          borderRadius: 'var(--radius, 8px)',
        },
      }),
    ]);
    container.appendChild(skeleton);
  }
}

// ---------------------------------------------------------------------------
// Error display
// ---------------------------------------------------------------------------

/**
 * Show an error message in the grid container.
 * @param {HTMLElement} container
 * @param {string} message
 */
function showError(container, message) {
  container.innerHTML = '';
  container.appendChild(
    createElement('div', {
      class: 'gallery-error',
      role: 'alert',
    }, [
      createElement('p', {}, [message]),
      createElement('button', {
        class: 'btn btn--ghost btn--sm',
        onclick: () => location.reload(),
      }, ['刷新页面']),
    ]),
  );
}

// ---------------------------------------------------------------------------
// Type definitions
// ---------------------------------------------------------------------------

/**
 * @typedef {Object} GalleryImage
 * @property {string}  filename       - original filename
 * @property {number}  width          - image width in pixels
 * @property {number}  height         - image height in pixels
 * @property {boolean} isGif          - whether the image is a GIF
 * @property {string}  platformPostId - post ID for the detail page link
 */
