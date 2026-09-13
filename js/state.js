/**
 * Global application state with a lightweight publish-subscribe pattern.
 *
 * Components subscribe to individual keys and are notified only when
 * the value they care about actually changes.
 */

const DEFAULTS = {
  currentYear: null,     // null = all years or latest
  currentFilter: '',     // '' | 'image' | 'text' | 'repost'
  searchQuery: '',
  currentPage: 0,        // pagination offset
  isLoading: false,
  posts: [],             // currently loaded posts
  indexData: null,       // dynamics-index.json data
};

/** @type {Object} live state object */
const state = { ...DEFAULTS };

/**
 * Map of state key -> Set of listener callbacks.
 * Listeners are called with (newValue, oldValue, key) when the
 * corresponding key changes via setState().
 * @type {Map<string, Set<Function>>}
 */
const listeners = new Map();

/**
 * Return a shallow copy of the current state.
 * @returns {Object}
 */
export function getState() {
  return { ...state };
}

/**
 * Merge partial updates into the state and notify subscribers of changed keys.
 *
 * Only keys whose value has actually changed (strict inequality) trigger
 * notifications. Array and object values always trigger because reference
 * identity is compared.
 *
 * @param {Object} updates - partial state object
 */
export function setState(updates) {
  const changedKeys = [];

  for (const [key, value] of Object.entries(updates)) {
    if (!(key in state)) {
      console.warn(`[state] Unknown state key "${key}" ignored.`);
      continue;
    }
    if (state[key] !== value) {
      const old = state[key];
      state[key] = value;
      changedKeys.push({ key, value, old });
    }
  }

  for (const { key, value, old } of changedKeys) {
    const subs = listeners.get(key);
    if (subs) {
      for (const cb of subs) {
        try {
          cb(value, old, key);
        } catch (err) {
          console.error(`[state] Subscriber error for key "${key}":`, err);
        }
      }
    }
  }
}

/**
 * Subscribe to changes on a specific state key.
 *
 * The callback is invoked immediately is not called; it fires only on
 * subsequent setState() calls that change the key.
 *
 * @param {string} key - state key to observe
 * @param {Function} callback - called with (newValue, oldValue, key)
 * @returns {Function} unsubscribe function
 */
export function subscribe(key, callback) {
  if (!listeners.has(key)) {
    listeners.set(key, new Set());
  }
  listeners.get(key).add(callback);

  return () => {
    const subs = listeners.get(key);
    if (subs) {
      subs.delete(callback);
      if (subs.size === 0) listeners.delete(key);
    }
  };
}

/**
 * Reset all state keys to their default values and notify subscribers.
 */
export function resetState() {
  setState({ ...DEFAULTS });
}
