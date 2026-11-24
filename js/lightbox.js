/**
 * Full-screen lightbox image viewer for SUI Archive detail pages.
 *
 * Provides zoom, keyboard/touch navigation, focus trapping,
 * body scroll lock, and progressive image loading (w1200 -> original).
 */

import { createElement } from './dom.js';

// ── State ──────────────────────────────────────────────────────────────────

/** @type {{src: string, width: number, height: number, alt: string}[]} */
let images = [];
let currentIndex = 0;
let isOpen = false;
let isZoomed = false;

// Panning state when zoomed
let panX = 0;
let panY = 0;
let dragStartX = 0;
let dragStartY = 0;
let isDragging = false;

// Touch swipe state
let touchStartX = 0;
let touchStartY = 0;
let touchStartTime = 0;

// Focus trap: element that had focus before lightbox opened
let previousFocus = null;

// ── DOM refs (created lazily) ──────────────────────────────────────────────

let overlay = null;
let imgEl = null;
let counterEl = null;
let prevBtn = null;
let nextBtn = null;
let closeBtn = null;

// ── Image URL helpers ──────────────────────────────────────────────────────

/**
 * Derive the w1200 thumbnail URL from an original or w1200 filename.
 * Inserts _w1200 before the extension and switches to .webp.
 * @param {string} src
 * @returns {string}
 */
function toW1200(src) {
  // If already a w1200 variant, return as-is
  if (/_w1200\./.test(src)) return src;
  return src.replace(/(\.[^.]+)$/, '_w1200.webp');
}

// ── DOM construction ───────────────────────────────────────────────────────

/**
 * Build the lightbox DOM structure and append to <body>.
 * Called once on first open.
 */
function buildDOM() {
  if (overlay) return;

  closeBtn = createElement('button', {
    class: 'lightbox__close',
    'aria-label': '关闭',
  }, ['✕']);

  prevBtn = createElement('button', {
    class: 'lightbox__nav lightbox__nav--prev',
    'aria-label': '上一张',
  }, ['‹']);

  nextBtn = createElement('button', {
    class: 'lightbox__nav lightbox__nav--next',
    'aria-label': '下一张',
  }, ['›']);

  imgEl = createElement('img', {
    class: 'lightbox__img',
    src: '',
    alt: '',
  });

  counterEl = createElement('div', {
    class: 'lightbox__counter',
  });

  overlay = createElement('div', {
    class: 'lightbox',
    role: 'dialog',
    'aria-modal': 'true',
    'aria-label': '图片查看器',
  }, [closeBtn, prevBtn, imgEl, nextBtn, counterEl]);

  // Start hidden for fade-in transition
  overlay.style.opacity = '0';
  overlay.style.transition = 'opacity 0.25s ease';

  document.body.appendChild(overlay);
  attachEvents();
}

// ── Rendering ──────────────────────────────────────────────────────────────

/**
 * Display the image at the given index.
 * Loads w1200 first, then upgrades to original in the background.
 * @param {number} index
 */
function showImage(index) {
  if (index < 0 || index >= images.length) return;
  currentIndex = index;

  const item = images[index];
  const w1200Src = toW1200(item.src);
  const originalSrc = item.src;

  // Reset zoom and pan
  resetZoom();

  // Show loading state
  imgEl.style.opacity = '0.5';
  imgEl.src = w1200Src;
  imgEl.alt = item.alt || `图片 ${index + 1}/${images.length}`;

  // Update counter
  counterEl.textContent = `${index + 1}/${images.length}`;

  // Update nav button visibility
  prevBtn.style.visibility = images.length > 1 ? 'visible' : 'hidden';
  nextBtn.style.visibility = images.length > 1 ? 'visible' : 'hidden';

  // Fade in once loaded
  imgEl.onload = () => {
    imgEl.style.opacity = '1';

    // Preload the original in the background and swap if it loads
    if (originalSrc !== w1200Src) {
      const upgrade = new Image();
      upgrade.onload = () => {
        // Only swap if still viewing the same image
        if (currentIndex === index && imgEl.src !== originalSrc) {
          imgEl.src = originalSrc;
        }
      };
      upgrade.src = originalSrc;
    }
  };
}

// ── Zoom & Pan ─────────────────────────────────────────────────────────────

function resetZoom() {
  isZoomed = false;
  panX = 0;
  panY = 0;
  imgEl.style.transform = '';
  imgEl.style.cursor = 'zoom-in';
}

function toggleZoom(e) {
  if (isZoomed) {
    resetZoom();
  } else {
    isZoomed = true;
    imgEl.style.cursor = 'grab';

    // Zoom toward the click point
    if (e) {
      const rect = imgEl.getBoundingClientRect();
      const cx = rect.left + rect.width / 2;
      const cy = rect.top + rect.height / 2;
      panX = (cx - e.clientX) * 1;
      panY = (cy - e.clientY) * 1;
    }

    applyTransform();
  }
}

function applyTransform() {
  imgEl.style.transform = `scale(2) translate(${panX / 2}px, ${panY / 2}px)`;
}

function clampPan() {
  const rect = imgEl.getBoundingClientRect();
  const maxPanX = Math.max(0, (rect.width - window.innerWidth) / 2);
  const maxPanY = Math.max(0, (rect.height - window.innerHeight) / 2);
  panX = Math.max(-maxPanX, Math.min(maxPanX, panX));
  panY = Math.max(-maxPanY, Math.min(maxPanY, panY));
}

// ── Navigation ─────────────────────────────────────────────────────────────

function goNext() {
  if (images.length <= 1) return;
  showImage((currentIndex + 1) % images.length);
}

function goPrev() {
  if (images.length <= 1) return;
  showImage((currentIndex - 1 + images.length) % images.length);
}

// ── Focus trap ─────────────────────────────────────────────────────────────

const FOCUSABLE = 'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])';

function trapFocus(e) {
  if (!overlay) return;
  const focusableEls = overlay.querySelectorAll(FOCUSABLE);
  if (focusableEls.length === 0) return;

  const first = focusableEls[0];
  const last = focusableEls[focusableEls.length - 1];

  if (e.shiftKey && document.activeElement === first) {
    e.preventDefault();
    last.focus();
  } else if (!e.shiftKey && document.activeElement === last) {
    e.preventDefault();
    first.focus();
  }
}

// ── Events ─────────────────────────────────────────────────────────────────

function onKeyDown(e) {
  switch (e.key) {
    case 'Escape':
      closeLightbox();
      break;
    case 'ArrowLeft':
      e.preventDefault();
      goPrev();
      break;
    case 'ArrowRight':
      e.preventDefault();
      goNext();
      break;
    case 'Tab':
      trapFocus(e);
      break;
  }
}

function onBackdropClick(e) {
  // Close when clicking the overlay background, not the image or buttons
  if (e.target === overlay) {
    closeLightbox();
  }
}

function onImageClick(e) {
  e.stopPropagation();
  toggleZoom(e);
}

function onMouseDown(e) {
  if (!isZoomed) return;
  isDragging = true;
  dragStartX = e.clientX - panX;
  dragStartY = e.clientY - panY;
  imgEl.style.cursor = 'grabbing';
  e.preventDefault();
}

function onMouseMove(e) {
  if (!isDragging) return;
  panX = e.clientX - dragStartX;
  panY = e.clientY - dragStartY;
  applyTransform();
}

function onMouseUp() {
  if (!isDragging) return;
  isDragging = false;
  clampPan();
  applyTransform();
  imgEl.style.cursor = isZoomed ? 'grab' : 'zoom-in';
}

function onTouchStart(e) {
  if (e.touches.length !== 1) return;
  touchStartX = e.touches[0].clientX;
  touchStartY = e.touches[0].clientY;
  touchStartTime = Date.now();

  if (isZoomed) {
    isDragging = true;
    dragStartX = touchStartX - panX;
    dragStartY = touchStartY - panY;
  }
}

function onTouchMove(e) {
  if (isZoomed && isDragging && e.touches.length === 1) {
    panX = e.touches[0].clientX - dragStartX;
    panY = e.touches[0].clientY - dragStartY;
    applyTransform();
    e.preventDefault();
  }
}

function onTouchEnd(e) {
  if (isZoomed && isDragging) {
    isDragging = false;
    clampPan();
    applyTransform();
    return;
  }

  // Swipe detection for navigation
  const dx = e.changedTouches[0].clientX - touchStartX;
  const dy = e.changedTouches[0].clientY - touchStartY;
  const dt = Date.now() - touchStartTime;

  // Require horizontal swipe > 50px, within 300ms, and more horizontal than vertical
  if (Math.abs(dx) > 50 && dt < 300 && Math.abs(dx) > Math.abs(dy)) {
    if (dx > 0) {
      goPrev();
    } else {
      goNext();
    }
  }
}

function attachEvents() {
  // Close button
  closeBtn.addEventListener('click', closeLightbox);

  // Navigation buttons
  prevBtn.addEventListener('click', (e) => { e.stopPropagation(); goPrev(); });
  nextBtn.addEventListener('click', (e) => { e.stopPropagation(); goNext(); });

  // Backdrop click
  overlay.addEventListener('click', onBackdropClick);

  // Image click for zoom
  imgEl.addEventListener('click', onImageClick);

  // Mouse drag for panning when zoomed
  imgEl.addEventListener('mousedown', onMouseDown);
  document.addEventListener('mousemove', onMouseMove);
  document.addEventListener('mouseup', onMouseUp);

  // Touch events for swipe and zoom pan
  overlay.addEventListener('touchstart', onTouchStart, { passive: true });
  overlay.addEventListener('touchmove', onTouchMove, { passive: false });
  overlay.addEventListener('touchend', onTouchEnd);

  // Keyboard
  document.addEventListener('keydown', onKeyDown);
}

function detachEvents() {
  document.removeEventListener('keydown', onKeyDown);
  document.removeEventListener('mousemove', onMouseMove);
  document.removeEventListener('mouseup', onMouseUp);
}

// ── Public API ─────────────────────────────────────────────────────────────

/**
 * Open the lightbox with an array of image objects.
 *
 * @param {{src: string, width: number, height: number, alt: string}[]} imgs
 *   Array of image objects. `src` should be the large/original URL.
 * @param {number} [startIndex=0] - which image to show first
 */
export function openLightbox(imgs, startIndex = 0) {
  if (!imgs || imgs.length === 0) return;

  images = imgs;
  currentIndex = startIndex;

  buildDOM();

  // Save current focus for restoration on close
  previousFocus = document.activeElement;

  // Lock body scroll
  document.body.style.overflow = 'hidden';

  // Show the overlay with fade-in
  overlay.style.display = '';
  // Force reflow before changing opacity for transition
  void overlay.offsetHeight;
  overlay.style.opacity = '1';

  isOpen = true;

  showImage(currentIndex);

  // Move focus into the lightbox
  closeBtn.focus();
}

/**
 * Close the lightbox and restore the page state.
 */
export function closeLightbox() {
  if (!isOpen || !overlay) return;

  isOpen = false;

  // Fade out
  overlay.style.opacity = '0';

  // After transition completes, hide the overlay
  const onEnd = () => {
    overlay.removeEventListener('transitionend', onEnd);
    if (!isOpen) {
      overlay.style.display = 'none';
      imgEl.src = '';
    }
  };
  overlay.addEventListener('transitionend', onEnd);

  // Unlock body scroll
  document.body.style.overflow = '';

  // Detach global listeners
  detachEvents();

  // Restore focus
  if (previousFocus && typeof previousFocus.focus === 'function') {
    previousFocus.focus();
    previousFocus = null;
  }

  resetZoom();
}
