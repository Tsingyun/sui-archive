/**
 * Share panel for SUI Archive detail pages.
 *
 * Provides clipboard copy, Weibo/Twitter share links,
 * and native Web Share API support when available.
 */

import { createElement } from './dom.js';

/**
 * Copy a URL string to the clipboard.
 *
 * @param {string} url - the URL to copy
 * @returns {Promise<boolean>} true on success
 */
export async function shareToClipboard(url) {
  try {
    await navigator.clipboard.writeText(url);
    return true;
  } catch {
    // Fallback for older browsers or insecure contexts
    const textarea = document.createElement('textarea');
    textarea.value = url;
    textarea.style.position = 'fixed';
    textarea.style.opacity = '0';
    document.body.appendChild(textarea);
    textarea.select();
    let ok = false;
    try {
      ok = document.execCommand('copy');
    } catch {
      ok = false;
    }
    document.body.removeChild(textarea);
    return ok;
  }
}

/**
 * Create a share panel DOM element with share buttons.
 *
 * @param {string} url   - the URL to share (typically the current page)
 * @param {string} title - the page title for social share links
 * @param {string} [text] - optional descriptive text (unused by current templates)
 * @returns {HTMLElement} the share panel element
 */
export function createSharePanel(url, title, text) {
  const encodedUrl = encodeURIComponent(url);
  const encodedTitle = encodeURIComponent(title);

  // Weibo share URL
  const weiboUrl = `https://service.weibo.com/share/share.php?url=${encodedUrl}&title=${encodedTitle}`;

  // Twitter/X share URL
  const twitterUrl = `https://twitter.com/intent/tweet?url=${encodedUrl}&text=${encodedTitle}`;

  // Copy button with feedback
  const copyBtn = createElement('button', {
    class: 'btn btn--ghost btn--sm',
    'aria-label': '复制链接',
    onclick: async () => {
      const ok = await shareToClipboard(url);
      const original = copyBtn.textContent;
      copyBtn.textContent = ok ? '已复制!' : '复制失败';
      copyBtn.disabled = true;
      setTimeout(() => {
        copyBtn.textContent = original;
        copyBtn.disabled = false;
      }, 1500);
    },
  }, ['复制链接']);

  // Weibo share link
  const weiboBtn = createElement('a', {
    class: 'btn btn--ghost btn--sm',
    href: weiboUrl,
    target: '_blank',
    rel: 'noopener noreferrer',
    'aria-label': '分享到微博',
  }, ['微博']);

  // Twitter/X share link
  const twitterBtn = createElement('a', {
    class: 'btn btn--ghost btn--sm',
    href: twitterUrl,
    target: '_blank',
    rel: 'noopener noreferrer',
    'aria-label': '分享到Twitter/X',
  }, ['X']);

  const children = [copyBtn, weiboBtn, twitterBtn];

  // Native Web Share API button (only if supported)
  if (typeof navigator !== 'undefined' && navigator.share) {
    const nativeBtn = createElement('button', {
      class: 'btn btn--ghost btn--sm',
      'aria-label': '分享',
      onclick: async () => {
        try {
          await navigator.share({ url, title, text: text || title });
        } catch {
          // User cancelled or share failed — silently ignore
        }
      },
    }, ['分享']);
    children.push(nativeBtn);
  }

  // Assemble the panel
  const panel = createElement('div', {
    class: 'share-panel',
    style: {
      display: 'flex',
      gap: '0.5rem',
      alignItems: 'center',
      flexWrap: 'wrap',
      margin: '1rem 0',
    },
  }, [
    createElement('span', {
      style: { fontSize: '0.85rem', opacity: '0.7' },
    }, ['分享:']),
    ...children,
  ]);

  return panel;
}
