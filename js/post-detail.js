/**
 * Detail page enhancement module for SUI Archive.
 *
 * Loaded directly via `<script type="module" src="/js/post-detail.js">`.
 * Self-executing on import: initializes router, fetches the detail JSON,
 * and progressively enhances the server-rendered HTML stub with:
 *   - Interactive image lightbox
 *   - Share panel
 *   - Prev/next post navigation
 *
 * If any step fails the page still functions (all content is in the HTML stub).
 */

import { $, $$, createElement, formatDate, formatNumber } from './dom.js';
import { fetchJSON } from './api.js';
import { API_BASE, IMAGE_BASE, THUMB_BASE, SITE_NAME } from './config.js';
import { initRouter } from './router.js';
import { openLightbox } from './lightbox.js';
import { createSharePanel } from './share.js';

// ── Helpers ────────────────────────────────────────────────────────────────

/**
 * Extract the UUID from the page DOM.
 * Looks for a `.post-detail__uuid` element and parses its text content.
 * @returns {string|null}
 */
function extractUUIDFromDOM() {
  // Method 1: look for a dedicated .post-detail__uuid span
  const el = $('.post-detail__uuid');
  if (el) {
    const text = el.textContent.trim();
    const match = text.match(/([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})/i);
    if (match) return match[1];
    if (text) return text;
  }

  // Method 2: data-uuid attribute on the article or main element
  const article = $('article.post-detail') || $('article[data-uuid]') || $('[data-uuid]');
  if (article) {
    const uuid = article.getAttribute('data-uuid');
    if (uuid) return uuid;
  }

  return null;
}

/**
 * Build the full image URL for the original file.
 * @param {string} filename
 * @returns {string}
 */
function originalURL(filename) {
  return `${IMAGE_BASE}/${filename}`;
}

/**
 * Build a w600 thumbnail URL from a filename.
 * @param {string} filename
 * @returns {string}
 */
function thumb600URL(filename) {
  return `${THUMB_BASE}/${filename.replace(/(\.[^.]+)$/, '_w600.webp')}`;
}

// ── Feature: Image Lightbox ────────────────────────────────────────────────

/**
 * Make all images in the detail section clickable to open the lightbox.
 * @param {Object} detail - the detail JSON data
 */
function enhanceImages(detail) {
  const section = $('.post-detail__images') || $('.detail__images');
  if (!section || !detail.images || detail.images.length === 0) return;

  // Build the image array for the lightbox
  const lightboxImages = detail.images.map((img, idx) => ({
    src: originalURL(img.filename),
    width: img.width,
    height: img.height,
    alt: `岁己动态图片 ${idx + 1}/${detail.images.length}`,
  }));

  // Attach click handlers to existing <img> elements in the section
  const imgEls = $$('img', section);
  imgEls.forEach((imgEl, index) => {
    const wrapper = imgEl.closest('.post-detail__image') ||
                    imgEl.closest('.detail__image') ||
                    imgEl;

    wrapper.style.cursor = 'zoom-in';
    wrapper.addEventListener('click', () => {
      openLightbox(lightboxImages, index);
    });
  });

  // If there are no <img> elements in the section (edge case), render them
  if (imgEls.length === 0) {
    renderImagesFromScratch(section, detail, lightboxImages);
  }
}

/**
 * Fallback: render image elements from the JSON when the HTML stub has none.
 * @param {Element} section
 * @param {Object} detail
 * @param {Array} lightboxImages
 */
function renderImagesFromScratch(section, detail, lightboxImages) {
  const modifier = detail.images.length === 1 ? '--1' :
                   detail.images.length === 2 ? '--2' : '--multi';
  section.classList.add(`post-detail__images${modifier}`);

  detail.images.forEach((img, index) => {
    const wrapper = createElement('div', {
      class: 'post-detail__image',
      style: { cursor: 'zoom-in' },
      onclick: () => openLightbox(lightboxImages, index),
    });

    const imgEl = createElement('img', {
      src: thumb600URL(img.filename),
      alt: `岁己动态图片 ${index + 1}/${detail.images.length}`,
      width: img.width,
      height: img.height,
      loading: index < 3 ? 'eager' : 'lazy',
      style: { maxWidth: '100%', height: 'auto', display: 'block' },
    });

    wrapper.appendChild(imgEl);
    section.appendChild(wrapper);
  });
}

// ── Feature: Share Panel ───────────────────────────────────────────────────

/**
 * Insert the share panel into the page.
 * @param {Object} detail
 */
function addSharePanel(detail) {
  const url = window.location.href;
  const title = `${SITE_NAME} - ${detail.platform_name} ${formatDate(detail.published_at)}`;
  const text = detail.plain_text
    ? detail.plain_text.slice(0, 100)
    : title;

  const panel = createSharePanel(url, title, text);

  // Insert after stats section, or before footer, or at end of article
  const statsSection = $('.post-detail__stats');
  const footer = $('.post-detail__footer');
  const article = $('.post-detail');

  if (statsSection && statsSection.parentNode) {
    statsSection.parentNode.insertBefore(panel, statsSection.nextSibling);
  } else if (footer) {
    footer.parentNode.insertBefore(panel, footer);
  } else if (article) {
    article.appendChild(panel);
  }
}

// ── Feature: Prev/Next Navigation ──────────────────────────────────────────

/**
 * Fetch a related detail JSON to extract its platform_post_id.
 * Returns null if the fetch fails.
 * @param {string} uuid
 * @returns {Promise<string|null>}
 */
async function fetchRelatedPostId(uuid) {
  if (!uuid) return null;
  const data = await fetchJSON(`${API_BASE}/detail/${uuid}.json`);
  return data?.platform_post_id || null;
}

/**
 * Render prev/next navigation links.
 * @param {Object} detail
 */
async function addPrevNextNav(detail) {
  const nav = $('.post-nav');
  if (!nav) return;

  const { prev_uuid, next_uuid } = detail.related || {};

  // Fetch related post IDs in parallel
  const [prevPostId, nextPostId] = await Promise.all([
    prev_uuid ? fetchRelatedPostId(prev_uuid) : Promise.resolve(null),
    next_uuid ? fetchRelatedPostId(next_uuid) : Promise.resolve(null),
  ]);

  // Build prev link
  const prevLink = prevPostId
    ? createElement('a', {
        class: 'post-nav__link post-nav__link--prev',
        href: `/d/${prevPostId}/`,
        'aria-label': '上一条',
      }, ['← 上一条'])
    : createElement('span', {
        class: 'post-nav__link post-nav__link--prev post-nav__link--disabled',
        'aria-disabled': 'true',
      }, ['← 上一条']);

  // Build next link
  const nextLink = nextPostId
    ? createElement('a', {
        class: 'post-nav__link post-nav__link--next',
        href: `/d/${nextPostId}/`,
        'aria-label': '下一条',
      }, ['下一条 →'])
    : createElement('span', {
        class: 'post-nav__link post-nav__link--next post-nav__link--disabled',
        'aria-disabled': 'true',
      }, ['下一条 →']);

  // Clear existing placeholder content and append links
  nav.innerHTML = '';
  nav.appendChild(prevLink);
  nav.appendChild(nextLink);
}

// ── Feature: Stats Enhancement ─────────────────────────────────────────────

/**
 * Enhance the stats section with formatted numbers from the JSON.
 * Only runs if the section exists and the JSON has stats data.
 * @param {Object} detail
 */
function enhanceStats(detail) {
  if (!detail.stats) return;
  const section = $('.post-detail__stats');
  if (!section) return;

  // If stats are already rendered server-side, skip
  if (section.dataset.enhanced) return;
  section.dataset.enhanced = 'true';

  const { likes, comments, forwards, views } = detail.stats;

  // Update any existing stat elements, or create them if missing
  const statItems = [
    { key: 'likes', label: '点赞', value: likes },
    { key: 'comments', label: '评论', value: comments },
    { key: 'forwards', label: '转发', value: forwards },
    { key: 'views', label: '浏览', value: views },
  ];

  for (const item of statItems) {
    const el = $(`.post-detail__stat--${item.key}`, section);
    if (el && item.value != null) {
      const numEl = $('.post-detail__stat-value', el) || el;
      numEl.textContent = formatNumber(item.value);
    }
  }
}

// ── Feature: Tags Enhancement ──────────────────────────────────────────────

/**
 * Enhance the tags section with links from the JSON.
 * @param {Object} detail
 */
function enhanceTags(detail) {
  if (!detail.tags || detail.tags.length === 0) return;
  const section = $('.post-detail__tags');
  if (!section) return;

  // If already rendered, skip
  if (section.dataset.enhanced) return;
  section.dataset.enhanced = 'true';

  // Clear and rebuild
  section.innerHTML = '';

  for (const tag of detail.tags) {
    const link = createElement('a', {
      class: 'post-detail__tag',
      href: `/tag/${tag.slug}/`,
      style: tag.color ? { borderColor: tag.color, color: tag.color } : {},
    }, [`#${tag.name}`]);
    section.appendChild(link);
  }
}

// ── Main ───────────────────────────────────────────────────────────────────

/**
 * Initialize the detail page enhancements.
 * Exported for completeness; the module self-executes on import.
 */
export async function initPostDetail() {
  // Set up navbar active state
  initRouter();

  // Extract the UUID from the DOM to fetch the detail JSON
  const uuid = extractUUIDFromDOM();

  if (!uuid) {
    console.warn('[post-detail] Could not find UUID in DOM. Skipping enhancements.');
    return;
  }

  // Fetch the detail JSON
  const detail = await fetchJSON(`${API_BASE}/detail/${uuid}.json`);

  if (!detail) {
    console.warn('[post-detail] Failed to fetch detail JSON. Page works from HTML stub only.');
    return;
  }

  // Apply enhancements — each is independent and wrapped in try/catch
  try { enhanceImages(detail); } catch (e) { console.warn('[post-detail] Image enhancement failed:', e); }
  try { addSharePanel(detail); } catch (e) { console.warn('[post-detail] Share panel failed:', e); }
  try { enhanceStats(detail); } catch (e) { console.warn('[post-detail] Stats enhancement failed:', e); }
  try { enhanceTags(detail); } catch (e) { console.warn('[post-detail] Tags enhancement failed:', e); }

  // Prev/next is async — don't block on it
  addPrevNextNav(detail).catch((e) => {
    console.warn('[post-detail] Prev/next nav failed:', e);
  });
}

// ── Auto-init ──────────────────────────────────────────────────────────────

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', initPostDetail);
} else {
  initPostDetail();
}
