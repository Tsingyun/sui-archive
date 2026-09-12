/**
 * DOM manipulation utilities for SUI Archive.
 */

/**
 * querySelector wrapper.
 * @param {string} selector - CSS selector
 * @param {Element|Document} [parent=document] - scope
 * @returns {Element|null}
 */
export function $(selector, parent = document) {
  return parent.querySelector(selector);
}

/**
 * querySelectorAll returning a real array.
 * @param {string} selector - CSS selector
 * @param {Element|Document} [parent=document] - scope
 * @returns {Element[]}
 */
export function $$(selector, parent = document) {
  return Array.from(parent.querySelectorAll(selector));
}

/**
 * Create an element with attributes and children.
 *
 * attrs may include:
 *   class (string or array), id, data-*, aria-*, and any standard attribute.
 *   Event listeners via on* keys (e.g. onclick) are attached as properties.
 *
 * children may be:
 *   - string  -> text node
 *   - Element -> appended directly
 *   - array   -> flattened recursively
 *   - null/undefined -> skipped
 *
 * @param {string} tag - HTML tag name
 * @param {Object} [attrs={}] - attributes / properties
 * @param {Array} [children=[]] - child nodes
 * @returns {HTMLElement}
 */
export function createElement(tag, attrs = {}, children = []) {
  const el = document.createElement(tag);

  for (const [key, value] of Object.entries(attrs)) {
    if (key === 'class') {
      if (Array.isArray(value)) {
        el.classList.add(...value.filter(Boolean));
      } else if (value) {
        el.className = value;
      }
    } else if (key === 'style' && typeof value === 'object') {
      Object.assign(el.style, value);
    } else if (key.startsWith('on') && typeof value === 'function') {
      // Event listener properties like onclick, onmouseenter
      el[key] = value;
    } else if (key === 'dataset' && typeof value === 'object') {
      for (const [dk, dv] of Object.entries(value)) {
        if (dv != null) el.dataset[dk] = String(dv);
      }
    } else if (value === true) {
      el.setAttribute(key, '');
    } else if (value === false || value == null) {
      // Skip false/null/undefined attributes
    } else {
      el.setAttribute(key, String(value));
    }
  }

  appendChildren(el, children);
  return el;
}

/**
 * Recursively append children to a parent element.
 * @param {Element} parent
 * @param {Array} children
 */
function appendChildren(parent, children) {
  for (const child of children) {
    if (child == null || child === false) continue;
    if (Array.isArray(child)) {
      appendChildren(parent, child);
    } else if (typeof child === 'string' || typeof child === 'number') {
      parent.appendChild(document.createTextNode(String(child)));
    } else if (child instanceof Node) {
      parent.appendChild(child);
    }
  }
}

/**
 * Event delegation: attach a single listener for a selector on a parent.
 * @param {Element} parent - delegation root
 * @param {string} event - event type (e.g. 'click')
 * @param {string} selector - CSS selector to match against
 * @param {Function} handler - called with (event, matchedElement)
 * @returns {Function} cleanup function that removes the listener
 */
export function delegate(parent, event, selector, handler) {
  const listener = (e) => {
    const target = e.target.closest(selector);
    if (target && parent.contains(target)) {
      handler(e, target);
    }
  };
  parent.addEventListener(event, listener);
  return () => parent.removeEventListener(event, listener);
}

/**
 * Safe innerHTML setter.
 * @param {Element} el - target element
 * @param {string} html - HTML string
 */
export function setHTML(el, html) {
  el.innerHTML = html;
}

/**
 * Show an element by removing inline display:none.
 * @param {Element} el
 */
export function show(el) {
  if (el) el.style.display = '';
}

/**
 * Hide an element with display:none.
 * @param {Element} el
 */
export function hide(el) {
  if (el) el.style.display = 'none';
}

/**
 * Scroll to the top of the page.
 * @param {boolean} [smooth=true] - use smooth scrolling
 */
export function scrollToTop(smooth = true) {
  window.scrollTo({ top: 0, behavior: smooth ? 'smooth' : 'auto' });
}

/**
 * Format a number with comma separators (e.g. 1234 -> "1,234").
 * @param {number} n
 * @returns {string}
 */
export function formatNumber(n) {
  return Number(n).toLocaleString('en-US');
}

/**
 * Format an ISO date string to Chinese full date "YYYY年M月D日".
 * @param {string} isoStr - ISO-8601 date string
 * @returns {string}
 */
export function formatDate(isoStr) {
  const d = new Date(isoStr);
  return `${d.getFullYear()}年${d.getMonth() + 1}月${d.getDate()}日`;
}

/**
 * Format an ISO date string to Chinese short date "M月D日".
 * @param {string} isoStr - ISO-8601 date string
 * @returns {string}
 */
export function formatDateShort(isoStr) {
  const d = new Date(isoStr);
  return `${d.getMonth() + 1}月${d.getDate()}日`;
}

/**
 * Return a human-readable relative time string in Chinese.
 * Examples: "刚刚", "5分钟前", "3小时前", "2天前", "3个月前", "1年前"
 * @param {string} isoStr - ISO-8601 date string
 * @returns {string}
 */
export function timeAgo(isoStr) {
  const now = Date.now();
  const then = new Date(isoStr).getTime();
  const diff = Math.max(0, now - then);

  const seconds = Math.floor(diff / 1000);
  const minutes = Math.floor(seconds / 60);
  const hours = Math.floor(minutes / 60);
  const days = Math.floor(hours / 24);
  const months = Math.floor(days / 30);
  const years = Math.floor(days / 365);

  if (seconds < 60) return '刚刚';
  if (minutes < 60) return `${minutes}分钟前`;
  if (hours < 24) return `${hours}小时前`;
  if (days < 30) return `${days}天前`;
  if (months < 12) return `${months}个月前`;
  return `${years}年前`;
}

/**
 * Create a debounced version of a function.
 * @param {Function} fn - function to debounce
 * @param {number} ms - debounce delay in milliseconds
 * @returns {Function}
 */
export function debounce(fn, ms) {
  let timer = null;
  const debounced = function (...args) {
    clearTimeout(timer);
    timer = setTimeout(() => fn.apply(this, args), ms);
  };
  debounced.cancel = () => clearTimeout(timer);
  return debounced;
}

/**
 * Create a throttled version of a function.
 * Fires immediately on the leading edge, then at most once per ms interval.
 * @param {Function} fn - function to throttle
 * @param {number} ms - throttle interval in milliseconds
 * @returns {Function}
 */
export function throttle(fn, ms) {
  let lastCall = 0;
  let timer = null;

  const throttled = function (...args) {
    const now = Date.now();
    const remaining = ms - (now - lastCall);

    if (remaining <= 0) {
      clearTimeout(timer);
      timer = null;
      lastCall = now;
      fn.apply(this, args);
    } else if (!timer) {
      // Trailing edge call
      timer = setTimeout(() => {
        lastCall = Date.now();
        timer = null;
        fn.apply(this, args);
      }, remaining);
    }
  };

  throttled.cancel = () => clearTimeout(timer);
  return throttled;
}
