/**
 * SUI Archive -- Application Entry Point
 *
 * Detects the current page, initialises the router, and dynamically imports
 * the appropriate page module. Also preloads the dynamics index in the
 * background for faster first interaction.
 *
 * This module is self-executing on import -- no explicit init call needed.
 */

import { initRouter, getCurrentPage } from './router.js';
import { fetchIndex } from './api.js';
import { setState } from './state.js';

// ---------------------------------------------------------------------------
// Bootstrap
// ---------------------------------------------------------------------------

/**
 * Main initialisation routine.
 *
 * Called once the DOM is ready. Sets up navigation, detects the current page,
 * and loads the matching feature module via dynamic import.
 */
async function bootstrap() {
  // 1. Set up client-side router (popstate handling, link interception)
  try {
    initRouter();
  } catch (err) {
    console.warn('[app] Router initialisation failed:', err);
  }

  // 2. Detect which page we are on
  const page = getCurrentPage();

  // 3. Preload the dynamics index in the background.
  //    This ensures that by the time the timeline module needs it, the
  //    response is already in the browser cache (or already resolved).
  preloadIndex();

  // 4. Route to the matching page module
  try {
    await initPageModule(page);
  } catch (err) {
    console.error(`[app] Failed to initialise page "${page}":`, err);
    showInitError(page, err);
  }
}

// ---------------------------------------------------------------------------
// Page module loader
// ---------------------------------------------------------------------------

/**
 * Dynamically import and initialise the module for the given page.
 *
 * @param {string} page  Page identifier returned by getCurrentPage().
 */
async function initPageModule(page) {
  switch (page) {
    case 'home': {
      const { initTimeline } = await import('./timeline.js');
      await initTimeline();
      break;
    }

    case 'search': {
      const { initSearch } = await import('./search.js');
      await initSearch();
      break;
    }

    case 'gallery': {
      const { initGallery } = await import('./gallery.js');
      await initGallery();
      break;
    }

    case 'timeline': {
      const { initTimelinePage } = await import('./timeline.js');
      await initTimelinePage();
      break;
    }

    case 'stats': {
      const { initStats } = await import('./stats.js');
      await initStats();
      break;
    }

    case 'tags': {
      const { initTagsPage } = await import('./tag-filter.js');
      await initTagsPage();
      break;
    }

    case 'detail': {
      // Detail page loads its own module directly via a <script> tag in
      // the detail HTML template -- nothing to do here.
      break;
    }

    case 'tag-detail': {
      const { initTagDetail } = await import('./tag-filter.js');
      await initTagDetail();
      break;
    }

    case 'about':
    case '404': {
      // Static pages -- no JavaScript needed.
      break;
    }

    default: {
      console.warn(`[app] Unknown page: "${page}"`);
      break;
    }
  }
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/**
 * Preload the dynamics-index.json in the background so it is available
 * immediately when the timeline module requests it.
 */
function preloadIndex() {
  fetchIndex()
    .then((data) => {
      setState({ indexData: data });
    })
    .catch(() => {
      // Silently ignore -- the timeline module will show its own error
      // if the index is truly unavailable.
    });
}

/**
 * Display a user-visible error message when page initialisation fails.
 */
function showInitError(page, _err) {
  const main = document.getElementById('main-content') ?? document.body;
  if (!main) return;

  const errorEl = document.createElement('div');
  errorEl.className = 'app-error';
  errorEl.setAttribute('role', 'alert');
  errorEl.style.cssText =
    'text-align:center;padding:2rem 1rem;color:var(--muted-foreground,#666);';

  const heading = document.createElement('h2');
  heading.textContent = '页面加载失败';
  heading.style.cssText = 'font-size:1.25rem;margin-bottom:0.5rem;';

  const message = document.createElement('p');
  message.textContent = '无法初始化页面功能，请检查网络连接后刷新重试。';

  const retryBtn = document.createElement('button');
  retryBtn.className = 'btn btn--ghost btn--sm';
  retryBtn.textContent = '刷新页面';
  retryBtn.style.marginTop = '1rem';
  retryBtn.addEventListener('click', () => location.reload());

  errorEl.appendChild(heading);
  errorEl.appendChild(message);
  errorEl.appendChild(retryBtn);
  main.appendChild(errorEl);
}

// ---------------------------------------------------------------------------
// DOM ready check
// ---------------------------------------------------------------------------

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', bootstrap);
} else {
  // DOM is already ready (module scripts are deferred by default)
  bootstrap();
}
