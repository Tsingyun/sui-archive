/**
 * SUI Archive -- Infinite Scroll
 *
 * IntersectionObserver-based infinite scroll controller. Monitors a sentinel
 * element and invokes a callback to load more content when the sentinel enters
 * the viewport. Supports pause / resume / destroy lifecycle management.
 */

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

/**
 * @typedef {Object} ScrollController
 * @property {() => void} pause   Temporarily stop triggering the callback.
 * @property {() => void} resume  Resume triggering after a pause.
 * @property {() => void} destroy Permanently disconnect the observer and clean up.
 */

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

/**
 * Set up an IntersectionObserver on a sentinel element.
 *
 * When the sentinel becomes visible, `callback` is invoked. While the callback
 * is running (it may be async), subsequent intersections are suppressed to
 * prevent duplicate loads. When there is no more data to load, call
 * `controller.finish()` or let the callback resolve with `false` to signal
 * exhaustion.
 *
 * @param {HTMLElement}  sentinelEl  The sentinel element to observe.
 * @param {() => (void|boolean|Promise<void|boolean>)} callback
 *   Called when the sentinel is visible. Return `false` (or a promise that
 *   resolves to `false`) to signal that all data has been loaded.
 * @param {Object}  [options]
 * @param {string}  [options.rootMargin='400px']  Look-ahead distance.
 * @param {number}  [options.threshold=0]         Intersection threshold.
 * @returns {ScrollController & { finish: () => void }}
 */
export function initInfiniteScroll(sentinelEl, callback, options = {}) {
  if (!sentinelEl) {
    // Return a no-op controller when the sentinel element is absent
    const noop = () => {};
    return { pause: noop, resume: noop, destroy: noop, finish: noop };
  }

  const {
    rootMargin = '400px',
    threshold = 0,
  } = options;

  let isLoading = false;
  let isPaused = false;
  let isFinished = false;
  let io = null;

  // -----------------------------------------------------------------------
  // Intersection handler
  // -----------------------------------------------------------------------

  async function handleIntersection(entries) {
    for (const entry of entries) {
      if (
        !entry.isIntersecting ||
        isLoading ||
        isPaused ||
        isFinished
      ) {
        continue;
      }

      isLoading = true;

      try {
        const result = await callback();

        // A `false` return value signals that no more data is available
        if (result === false) {
          markFinished();
        }
      } catch (err) {
        console.error('[infinite-scroll] Callback error:', err);
      } finally {
        isLoading = false;
      }
    }
  }

  // -----------------------------------------------------------------------
  // Internal helpers
  // -----------------------------------------------------------------------

  /**
   * Display the "all loaded" message and disconnect the observer.
   */
  function markFinished() {
    isFinished = true;
    destroy();

    sentinelEl.classList.add('scroll-sentinel--done');
    sentinelEl.textContent = '已加载全部';
  }

  /**
   * Disconnect the observer and remove the sentinel content.
   */
  function destroy() {
    if (io) {
      io.disconnect();
      io = null;
    }
  }

  // -----------------------------------------------------------------------
  // Start observing
  // -----------------------------------------------------------------------

  io = new IntersectionObserver(handleIntersection, {
    rootMargin,
    threshold,
  });

  io.observe(sentinelEl);

  // -----------------------------------------------------------------------
  // Return controller handle
  // -----------------------------------------------------------------------

  return {
    /** Temporarily stop triggering (e.g. during year-tab switch). */
    pause() {
      isPaused = true;
    },

    /** Resume after a pause. */
    resume() {
      isPaused = false;
    },

    /** Permanently tear down the observer and clean up the sentinel. */
    destroy() {
      destroy();
      sentinelEl.textContent = '';
      sentinelEl.classList.remove('scroll-sentinel--done');
    },

    /**
     * Explicitly signal that all data has been loaded.
     * Shows "已加载全部" and disconnects the observer.
     */
    finish() {
      markFinished();
    },
  };
}
