/**
 * SUI Archive -- Post Card Renderer
 *
 * Creates DOM elements for individual post cards in the timeline feed.
 * Each card is a clickable link containing the post header, text preview,
 * image grid, engagement stats, and tags.
 */

import { createElement, formatDate, formatNumber } from './dom.js';
import { IMAGE_BASE, EAGER_LOAD_COUNT } from './config.js';
import { observeImage, loadImage } from './lazy-load.js';

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

/** Maximum number of images shown in a card grid. */
const MAX_VISIBLE_IMAGES = 4;

// ---------------------------------------------------------------------------
// Post card
// ---------------------------------------------------------------------------

/**
 * Create a DOM element representing a single post card.
 *
 * The entire card is wrapped in an `<a>` element linking to the post detail
 * page. Images are rendered with `data-src` for lazy loading and must be
 * activated by calling `observeImage()` afterwards.
 *
 * @param {Object} post  A post object from dynamics-{year}.json.
 * @returns {HTMLAnchorElement}
 */
export function createPostCard(post) {
  const href = `/d/${post.platform_post_id}`;
  const card = createElement('a', {
    class: 'post-card card card--interactive',
    href,
  });

  // -- Header --------------------------------------------------------------
  const header = createElement('div', { class: 'post-card__header' });

  const date = createElement('time', {
    class: 'post-card__date',
    datetime: post.published_at,
  });
  date.textContent = formatDate(post.published_at);

  const typeLabel = TYPE_LABELS[post.post_type] ?? post.post_type ?? '';
  const typeTag = createElement('span', { class: 'post-card__type tag' });
  typeTag.textContent = typeLabel;

  header.appendChild(date);
  header.appendChild(typeTag);
  card.appendChild(header);

  // -- Repost indicator ----------------------------------------------------
  if (post.is_repost && post.repost_author) {
    const repost = createElement('div', { class: 'post-card__repost' });
    repost.textContent = `转发自 @${post.repost_author}`;
    card.appendChild(repost);
  }

  // -- Text preview --------------------------------------------------------
  if (post.text_preview) {
    const text = createElement('div', { class: 'post-card__text' });
    text.textContent = post.text_preview;
    card.appendChild(text);
  }

  // -- Image grid ----------------------------------------------------------
  if (post.has_images && post.images?.length > 0) {
    const visibleImages = post.images.slice(0, MAX_VISIBLE_IMAGES);
    const gridModifier = Math.min(visibleImages.length, MAX_VISIBLE_IMAGES);
    const gridClass = `post-card__images post-card__images--${gridModifier}`;
    const grid = createElement('div', { class: gridClass });

    for (const imgData of visibleImages) {
      const imgSrc = `${IMAGE_BASE}/${imgData.filename}`;

      // Preserve aspect ratio for CLS prevention; fall back to square
      const w = imgData.width ?? 300;
      const h = imgData.height ?? 300;

      const img = createElement('img', {
        class: 'post-card__img',
        'data-src': imgSrc,
        width: String(w),
        height: String(h),
        alt: '动态图片',
        loading: 'lazy',
      });

      grid.appendChild(img);
    }

    card.appendChild(grid);
  }

  // -- Stats ---------------------------------------------------------------
  const stats = post.stats ?? {};
  const statsRow = createElement('div', { class: 'post-card__stats' });

  const likeSpan = createElement('span');
  likeSpan.textContent = `❤ ${formatNumber(stats.likes ?? 0)}`;

  const commentSpan = createElement('span');
  commentSpan.textContent = `💬 ${formatNumber(stats.comments ?? 0)}`;

  const forwardSpan = createElement('span');
  forwardSpan.textContent = `🔄 ${formatNumber(stats.forwards ?? 0)}`;

  statsRow.appendChild(likeSpan);
  statsRow.appendChild(commentSpan);
  statsRow.appendChild(forwardSpan);
  card.appendChild(statsRow);

  // -- Tags ----------------------------------------------------------------
  if (post.tags?.length > 0) {
    const tagsWrap = createElement('div', { class: 'post-card__tags' });

    for (const tagSlug of post.tags) {
      const tagEl = createElement('span', { class: 'tag tag--secondary' });
      tagEl.textContent = tagSlug;
      tagsWrap.appendChild(tagEl);
    }

    card.appendChild(tagsWrap);
  }

  return card;
}

// ---------------------------------------------------------------------------
// Skeleton card
// ---------------------------------------------------------------------------

/**
 * Create a skeleton placeholder card shown during data loading.
 *
 * @returns {HTMLDivElement}
 */
export function createSkeletonCard() {
  const skeleton = createElement('div', { class: 'skeleton--card' });

  // Header row placeholder
  const headerLine = createElement('div', { class: 'skeleton__line skeleton__line--short' });
  skeleton.appendChild(headerLine);

  // Text line placeholders
  for (let i = 0; i < 3; i++) {
    const line = createElement('div', {
      class: `skeleton__line${i === 2 ? ' skeleton__line--medium' : ''}`,
    });
    skeleton.appendChild(line);
  }

  // Image grid placeholder
  const imgPlaceholder = createElement('div', { class: 'skeleton__image-grid' });
  for (let i = 0; i < 2; i++) {
    imgPlaceholder.appendChild(
      createElement('div', { class: 'skeleton__image' }),
    );
  }
  skeleton.appendChild(imgPlaceholder);

  return skeleton;
}

// ---------------------------------------------------------------------------
// Batch renderer
// ---------------------------------------------------------------------------

/**
 * Render a batch of post cards into a container element.
 *
 * After appending, every image inside the new cards is registered for lazy
 * loading. The `startIndex` parameter determines which images are loaded
 * eagerly (first `EAGER_LOAD_COUNT` across the entire feed) versus lazily.
 *
 * @param {HTMLElement} container   The post-list container.
 * @param {Object[]}    posts       Array of post objects.
 * @param {number}      [startIndex=0]  The running image counter offset.
 */
export function renderPostList(container, posts, startIndex = 0) {
  if (!container || !posts?.length) return;

  const fragment = document.createDocumentFragment();
  const newCards = [];

  for (const post of posts) {
    const card = createPostCard(post);
    newCards.push(card);
    fragment.appendChild(card);
  }

  container.appendChild(fragment);

  // Collect only the images from the cards we just appended, in order.
  const newImages = [];
  for (const card of newCards) {
    const imgs = card.querySelectorAll('.post-card__img[data-src]');
    for (const img of imgs) {
      newImages.push(img);
    }
  }

  // Apply eager or lazy loading based on global image index.
  newImages.forEach((img, localIdx) => {
    const globalIdx = startIndex + localIdx;

    if (globalIdx < EAGER_LOAD_COUNT) {
      // Above-the-fold images: load immediately without the observer.
      img.setAttribute('loading', 'eager');
      const src = img.getAttribute('data-src');
      if (src) loadImage(img, src);
    } else {
      // Below-the-fold images: register with the IntersectionObserver.
      img.setAttribute('loading', 'lazy');
      observeImage(img);
    }
  });
}
