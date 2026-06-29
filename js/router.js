/**
 * Lightweight client-side router for SUI Archive.
 *
 * This router enhances navigation between real HTML pages served by
 * GitHub Pages (or any static host) by:
 *   - Intercepting navbar link clicks to avoid full page reloads
 *   - Using history.pushState and fetch to swap <main> content
 *   - Managing the active nav link indicator
 *   - Handling the mobile menu toggle
 *   - Supporting browser back/forward via popstate
 */

import { $ } from './dom.js';

/**
 * Map of URL path prefixes/patterns to page identifiers.
 * Order matters: more specific patterns are matched first.
 */
const ROUTES = [
  { pattern: /^\/d\//,    page: 'detail' },
  { pattern: /^\/tag\//,  page: 'tag-detail' },
  { pattern: /^\/timeline/, page: 'timeline' },
  { pattern: /^\/gallery/,  page: 'gallery' },
  { pattern: /^\/search/,   page: 'search' },
  { pattern: /^\/stats/,    page: 'stats' },
  { pattern: /^\/tags/,     page: 'tags' },
  { pattern: /^\/about/,    page: 'about' },
  { pattern: /^\/?$/,       page: 'home' },
];

/**
 * Custom event dispatched on <main> after a successful page swap.
 * Page-specific scripts can listen for this to re-initialize.
 * @type {string}
 */
export const PAGE_LOADED_EVENT = 'sui:page-loaded';

/**
 * Determine the current page name from the URL pathname.
 *
 * @returns {string} one of 'home', 'timeline', 'gallery', 'search',
 *   'stats', 'tags', 'about', 'detail', 'tag-detail', or '404'
 */
export function getCurrentPage() {
  const path = window.location.pathname;
  for (const { pattern, page } of ROUTES) {
    if (pattern.test(path)) return page;
  }
  return '404';
}

/**
 * Mark the correct navbar link as active based on the current page.
 */
function updateActiveNav() {
  const page = getCurrentPage();
  const links = document.querySelectorAll('.navbar__link');

  links.forEach((link) => {
    const linkPage = link.dataset.page;
    if (linkPage === page || (page === 'home' && linkPage === 'home')) {
      link.classList.add('active');
      link.setAttribute('aria-current', 'page');
    } else {
      link.classList.remove('active');
      link.removeAttribute('aria-current');
    }
  });
}

/**
 * Close the mobile menu if it is open.
 */
function closeMobileMenu() {
  const mobile = $('.navbar__mobile');
  const toggle = $('.navbar__toggle');
  if (mobile) mobile.setAttribute('hidden', '');
  if (toggle) toggle.setAttribute('aria-expanded', 'false');
}

/**
 * Set up the mobile menu toggle (hamburger button).
 */
function setupMobileMenu() {
  const toggle = $('.navbar__toggle');
  const mobile = $('.navbar__mobile');
  if (!toggle || !mobile) return;

  toggle.addEventListener('click', () => {
    const isHidden = mobile.hasAttribute('hidden');
    if (isHidden) {
      mobile.removeAttribute('hidden');
      toggle.setAttribute('aria-expanded', 'true');
    } else {
      mobile.setAttribute('hidden', '');
      toggle.setAttribute('aria-expanded', 'false');
    }
  });
}

/**
 * Fetch an HTML page, extract its <main> content, and swap it into the DOM.
 *
 * @param {string} path - the URL path to fetch
 * @returns {Promise<boolean>} true on success, false on failure
 */
async function swapContent(path) {
  try {
    const res = await fetch(path, {
      headers: { 'X-Requested-With': 'XMLHttpRequest' },
    });
    if (!res.ok) return false;

    const html = await res.text();

    // Parse the fetched document and extract <main>
    const parser = new DOMParser();
    const doc = parser.parseFromString(html, 'text/html');
    const newMain = doc.querySelector('main');
    const currentMain = $('main');

    if (!newMain || !currentMain) return false;

    // Swap content and preserve any data attributes on <main>
    currentMain.innerHTML = newMain.innerHTML;
    for (const attr of newMain.attributes) {
      currentMain.setAttribute(attr.name, attr.value);
    }

    // Update document title
    const newTitle = doc.querySelector('title');
    if (newTitle) document.title = newTitle.textContent;

    return true;
  } catch (err) {
    console.warn('[router] Failed to fetch page:', path, err);
    return false;
  }
}

/**
 * Navigate to a new path programmatically.
 *
 * @param {string} path - the target URL path (e.g. '/timeline')
 * @param {boolean} [replace=false] - use replaceState instead of pushState
 */
export async function navigate(path, replace = false) {
  if (replace) {
    history.replaceState({ path }, '', path);
  } else {
    history.pushState({ path }, '', path);
  }

  const ok = await swapContent(path);
  if (!ok) {
    // Fall back to a real navigation on failure
    window.location.href = path;
    return;
  }

  updateActiveNav();
  window.scrollTo({ top: 0 });

  // Notify page scripts that content has changed
  document.dispatchEvent(new CustomEvent(PAGE_LOADED_EVENT, {
    detail: { page: getCurrentPage(), path },
  }));
}

/**
 * Handle clicks on navbar links for SPA-like navigation.
 */
function setupNavInterception() {
  document.addEventListener('click', async (e) => {
    const link = e.target.closest('.navbar__link[data-page]');
    if (!link) return;

    const href = link.getAttribute('href');
    if (!href || href.startsWith('http') || href.startsWith('//')) return;

    e.preventDefault();

    // Close mobile menu before navigating
    closeMobileMenu();

    // Skip navigation if already on the same page
    if (window.location.pathname === href) return;

    await navigate(href);
  });
}

/**
 * Handle browser back/forward buttons.
 */
function setupPopState() {
  window.addEventListener('popstate', async (e) => {
    const path = e.state?.path || window.location.pathname;
    const ok = await swapContent(path);
    if (!ok) {
      window.location.reload();
      return;
    }

    updateActiveNav();

    document.dispatchEvent(new CustomEvent(PAGE_LOADED_EVENT, {
      detail: { page: getCurrentPage(), path },
    }));
  });
}

/**
 * Initialize the router.
 *
 * Call this once on DOMContentLoaded. It will:
 *   1. Detect the current page and mark the active nav link
 *   2. Set up navbar click interception for smooth transitions
 *   3. Set up mobile menu toggle
 *   4. Set up popstate handling for back/forward
 *   5. Replace the initial history state so popstate works correctly
 */
export function initRouter() {
  // Store the initial path in history state for popstate support
  history.replaceState({ path: window.location.pathname }, '');

  updateActiveNav();
  setupNavInterception();
  setupMobileMenu();
  setupPopState();
}
