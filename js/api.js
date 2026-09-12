/**
 * Data fetching layer with promise-based caching for SUI Archive.
 */

import { INDEX_URL, SEARCH_INDEX_URL, TAG_INDEX_URL, STATS_URL, API_BASE } from './config.js';

/**
 * Internal cache storing in-flight or resolved Promises keyed by URL.
 * Concurrent callers for the same URL share a single fetch.
 * @type {Map<string, Promise<any>>}
 */
const cache = new Map();

/**
 * Fetch JSON from a URL with caching.
 *
 * The cache stores Promises so that simultaneous requests for the same URL
 * are deduplicated into a single network request.
 *
 * @param {string} url - absolute or relative URL to fetch
 * @returns {Promise<any>} parsed JSON, or null on failure
 */
export async function fetchJSON(url) {
  if (cache.has(url)) {
    return cache.get(url);
  }

  const promise = fetch(url)
    .then((res) => {
      if (!res.ok) {
        console.warn(`[api] ${res.status} ${res.statusText} for ${url}`);
        cache.delete(url);
        return null;
      }
      return res.json();
    })
    .catch((err) => {
      console.warn(`[api] Network error fetching ${url}:`, err.message);
      cache.delete(url);
      return null;
    });

  cache.set(url, promise);
  return promise;
}

/**
 * Load the dynamics index (year list, counts, etc.).
 * @returns {Promise<Object|null>}
 */
export async function fetchIndex() {
  return fetchJSON(INDEX_URL);
}

/**
 * Load all dynamics for a given year.
 * @param {number|string} year
 * @returns {Promise<Object|null>}
 */
export async function fetchYearData(year) {
  return fetchJSON(`${API_BASE}/dynamics-${year}.json`);
}

/**
 * Load a single detail page by UUID.
 * @param {string} uuid
 * @returns {Promise<Object|null>}
 */
export async function fetchDetail(uuid) {
  return fetchJSON(`${API_BASE}/detail/${uuid}.json`);
}

/**
 * Load the full-text search index.
 * Intended to be called lazily, only when the search page is visited.
 * @returns {Promise<Object|null>}
 */
export async function fetchSearchIndex() {
  return fetchJSON(SEARCH_INDEX_URL);
}

/**
 * Load the tag index.
 * @returns {Promise<Object|null>}
 */
export async function fetchTagIndex() {
  return fetchJSON(TAG_INDEX_URL);
}

/**
 * Load site-wide statistics.
 * @returns {Promise<Object|null>}
 */
export async function fetchStats() {
  return fetchJSON(STATS_URL);
}

/**
 * Clear the entire request cache.
 * Useful after a data update or when memory pressure is a concern.
 */
export function clearCache() {
  cache.clear();
}
