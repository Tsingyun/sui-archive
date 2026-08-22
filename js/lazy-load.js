/**
 * SUI Archive -- Image Lazy Loading
 *
 * IntersectionObserver-based lazy loading with progressive image refinement.
 * Loads a w300 thumbnail first, then prefetches w600 in the background and
 * swaps it in seamlessly. GIF images show a poster frame and load the
 * original only on click.
 */

import { LAZY_LOAD_THRESHOLD, THUMB_BASE } from './config.js';

// ---------------------------------------------------------------------------
// Module state
// ---------------------------------------------------------------------------

let observer = null;

/** WeakSet of <img> elements already observed or loaded. */
const observed = new WeakSet();

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/**
 * Derive the thumbnail URL for a given original image path and size suffix.
 *
 * Thumbnail naming convention (produced by the build pipeline):
 *   /thumbs/{stem}_w{size}.webp
 *
 * @param {string} src   Original image src, e.g. "/images/123_00@original.png"
 * @param {string} size  Suffix such as "w300" or "w600".
 * @returns {string}
 */
function thumbUrl(src, size) {
  const filename = src.split('/').pop();
  const stem = filename.replace(/\.[^.]+$/, '');
  return `${THUMB_BASE}/${stem}_${size}.webp`;
}

/**
 * Check whether a src points to a GIF file.
 */
function isGif(src) {
  return /\.gif(\?.*)?$/i.test(src);
}

/**
 * Derive the GIF poster URL (a static WebP frame generated at build time).
 */
function posterUrl(src) {
  const filename = src.split('/').pop();
  const stem = filename.replace(/\.[^.]+$/, '');
  return `${THUMB_BASE}/${stem}_poster.webp`;
}

/**
 * Preload an image URL and verify it loads successfully.
 *
 * Uses fetch() rather than new Image() so we can inspect the HTTP status.
 * The Worker returns a 404 SVG placeholder for missing images, which
 * Image().onload treats as valid -- fetch().ok correctly rejects it.
 *
 * @param {string} src
 * @returns {Promise<string>} resolves with src on success
 */
async function preload(src) {
  const response = await fetch(src, { mode: 'cors' });
  if (!response.ok) {
    throw new Error(`HTTP ${response.status}`);
  }
  // Verify the browser can decode the image
  const blob = await response.blob();
  const blobUrl = URL.createObjectURL(blob);
  try {
    await new Promise((resolve, reject) => {
      const img = new Image();
      img.onload = resolve;
      img.onerror = reject;
      img.src = blobUrl;
    });
  } finally {
    URL.revokeObjectURL(blobUrl);
  }
  return src;
}

// ---------------------------------------------------------------------------
// Core loading logic
// ---------------------------------------------------------------------------

/**
 * Progressive image load:
 *  1. Set the w300 thumbnail immediately (fast, low bandwidth).
 *  2. In the background, preload w600 and swap when ready.
 *  3. For GIFs: show the poster frame; click triggers full GIF download.
 *
 * @param {HTMLImageElement} img  The target <img> element.
 * @param {string}           src  The original image URL from data-src.
 */
async function progressiveLoad(img, src) {
  img.setAttribute('data-loaded', 'loading');

  // --- GIF path ----------------------------------------------------------
  if (isGif(src)) {
    const poster = posterUrl(src);
    try {
      await preload(poster);
      img.src = poster;
    } catch {
      // Poster failed -- try the original GIF directly
      img.src = src;
    }

    img.setAttribute('data-loaded', 'poster');
    img.style.cursor = 'pointer';
    img.title = 'Click to load GIF';

    // One-time click handler: swap poster for real GIF
    const onClick = () => {
      img.removeEventListener('click', onClick);
      img.style.cursor = 'default';
      img.title = '';

      const gif = new Image();
      gif.onload = () => {
        img.src = src;
        img.setAttribute('data-loaded', 'true');
      };
      gif.onerror = () => {
        // Keep the poster visible on failure
      };
      gif.src = src;
    };
    img.addEventListener('click', onClick);
    return;
  }

  // --- Standard image path -----------------------------------------------

  // Step 1: show w300 thumbnail instantly
  const smallSrc = thumbUrl(src, 'w300');
  try {
    await preload(smallSrc);
    img.src = smallSrc;
  } catch {
    // w300 not available -- fall back to original
    img.src = src;
    img.setAttribute('data-loaded', 'true');
    return;
  }

  // Step 2: prefetch w600 in background and swap
  const largeSrc = thumbUrl(src, 'w600');
  try {
    await preload(largeSrc);
    // Only swap if the element is still in the DOM
    if (img.isConnected) {
      img.src = largeSrc;
    }
  } catch {
    // w600 unavailable -- keep the w300 version
  }

  img.setAttribute('data-loaded', 'true');
}

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

/**
 * Initialise the global IntersectionObserver for lazy-loading images.
 *
 * Call once during application bootstrap. After this, any <img data-src="...">
 * element that enters the viewport (with 200 px look-ahead) will automatically
 * begin loading.
 *
 * @returns {void}
 */
export function initLazyLoad() {
  if (observer) return; // already initialised

  observer = new IntersectionObserver(
    (entries) => {
      for (const entry of entries) {
        if (!entry.isIntersecting) continue;

        const img = /** @type {HTMLImageElement} */ (entry.target);
        const src = img.getAttribute('data-src');

        if (src) {
          observer.unobserve(img);
          progressiveLoad(img, src);
        }
      }
    },
    {
      rootMargin: `${LAZY_LOAD_THRESHOLD}px`,
    },
  );
}

/**
 * Manually observe an image element for lazy loading.
 *
 * If the observer has not been initialised yet, it will be created lazily.
 * Images already observed are silently ignored (no double-observation).
 *
 * @param {HTMLImageElement} img  An <img> with a `data-src` attribute.
 */
export function observeImage(img) {
  if (!img || observed.has(img)) return;
  observed.add(img);

  if (!observer) initLazyLoad();

  const src = img.getAttribute('data-src');
  if (!src) return;

  observer.observe(img);
}

/**
 * Immediately load an image without waiting for the observer.
 *
 * Useful for above-the-fold images that should render as quickly as possible.
 *
 * @param {HTMLImageElement} img  The target <img> element.
 * @param {string}           src  The image URL to load.
 */
export function loadImage(img, src) {
  if (!img || !src) return;

  observed.add(img);
  img.setAttribute('data-src', src);
  progressiveLoad(img, src);
}
