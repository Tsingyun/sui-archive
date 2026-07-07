/**
 * Cloudflare Worker — Image Proxy for SUI Archive
 *
 * Intercepts requests to /images/* and serves images from Cloudflare R2.
 * Falls back to a 404 SVG placeholder if the requested file doesn't exist.
 *
 * Features:
 *   - Serves images from R2 bucket (env.IMAGE_BUCKET)
 *   - Long-term caching (1 year) for immutable image assets
 *   - CORS headers for cross-origin image loading
 *   - Conditional requests via If-None-Match / ETag
 *   - Range requests for partial content (large images)
 *   - SVG placeholder for missing images
 */

// MIME type map for common image formats
const MIME_TYPES = {
  '.jpg':  'image/jpeg',
  '.jpeg': 'image/jpeg',
  '.png':  'image/png',
  '.gif':  'image/gif',
  '.webp': 'image/webp',
  '.avif': 'image/avif',
  '.svg':  'image/svg+xml',
  '.ico':  'image/x-icon',
  '.bmp':  'image/bmp',
  '.tiff': 'image/tiff',
  '.tif':  'image/tiff',
};

// Cache-Control: 1 year (images are immutable once uploaded)
const CACHE_MAX_AGE = 31536000;

// SVG placeholder for 404 images
const PLACEHOLDER_SVG = `<svg xmlns="http://www.w3.org/2000/svg" width="400" height="300" viewBox="0 0 400 300">
  <rect width="400" height="300" fill="#1a1a2e"/>
  <text x="200" y="140" font-family="sans-serif" font-size="16" fill="#666" text-anchor="middle">Image Not Found</text>
  <text x="200" y="170" font-family="sans-serif" font-size="12" fill="#444" text-anchor="middle">archive.suijisui.uk</text>
</svg>`;

/**
 * Get MIME type from file path extension.
 */
function getContentType(path) {
  const ext = path.toLowerCase().match(/\.[^.]+$/);
  if (ext && MIME_TYPES[ext[0]]) {
    return MIME_TYPES[ext[0]];
  }
  return 'application/octet-stream';
}

/**
 * Build CORS headers.
 */
function corsHeaders(origin) {
  return {
    'Access-Control-Allow-Origin': origin || '*',
    'Access-Control-Allow-Methods': 'GET, HEAD, OPTIONS',
    'Access-Control-Allow-Headers': 'Content-Type, Range, If-None-Match',
    'Access-Control-Expose-Headers': 'Content-Length, Content-Range, ETag',
    'Access-Control-Max-Age': '86400',
  };
}

/**
 * Handle the incoming request.
 */
async function handleRequest(request, env) {
  const url = new URL(request.url);
  const origin = request.headers.get('Origin') || '*';

  // Handle CORS preflight
  if (request.method === 'OPTIONS') {
    return new Response(null, {
      status: 204,
      headers: corsHeaders(origin),
    });
  }

  // Only allow GET and HEAD
  if (request.method !== 'GET' && request.method !== 'HEAD') {
    return new Response('Method not allowed', {
      status: 405,
      headers: { ...corsHeaders(origin), 'Content-Type': 'text/plain' },
    });
  }

  // Extract path from URL: /images/{path} or /thumbs/{path}
  let imagePath = url.pathname;
  if (imagePath.startsWith('/images/')) {
    imagePath = imagePath.slice('/images/'.length);
  } else if (imagePath.startsWith('/thumbs/')) {
    // Thumbnails are stored in R2 with thumbs/ prefix
    imagePath = 'thumbs/' + imagePath.slice('/thumbs/'.length);
  } else if (imagePath === '/images' || imagePath === '/thumbs' ||
             imagePath === '/images/' || imagePath === '/thumbs/') {
    return new Response('Image path required', {
      status: 400,
      headers: { ...corsHeaders(origin), 'Content-Type': 'text/plain' },
    });
  }

  // Decode and sanitize path
  imagePath = decodeURIComponent(imagePath);

  // Prevent directory traversal
  if (imagePath.includes('..') || imagePath.startsWith('/')) {
    return new Response('Invalid path', {
      status: 400,
      headers: { ...corsHeaders(origin), 'Content-Type': 'text/plain' },
    });
  }

  // Log request (useful for debugging via wrangler tail)
  console.log(`[IMG] ${request.method} /images/${imagePath}`);

  // Fetch from R2
  let object;
  try {
    const rangeHeader = request.headers.get('Range');
    const options = {};

    if (rangeHeader) {
      options.range = rangeHeader;
    }

    object = await env.IMAGE_BUCKET.get(imagePath, options);
  } catch (err) {
    console.error(`[IMG] R2 error for ${imagePath}:`, err.message);
    return returnPlaceholder(origin);
  }

  // Object not found in R2 — try fallback to thumbs/ prefix
  // This handles thumbnail requests arriving on the /images/* route
  // (config.js may use /images as THUMB_BASE, but thumbs live under thumbs/ in R2)
  if (!object && !imagePath.startsWith('thumbs/')) {
    const thumbsPath = 'thumbs/' + imagePath;
    try {
      const rangeHeader = request.headers.get('Range');
      const options = rangeHeader ? { range: rangeHeader } : {};
      object = await env.IMAGE_BUCKET.get(thumbsPath, options);
      if (object) {
        imagePath = thumbsPath; // Update for content-type detection
      }
    } catch (err) {
      // Ignore — fall through to 404
    }
  }

  if (!object) {
    console.log(`[IMG] 404: ${imagePath}`);
    return returnPlaceholder(origin);
  }

  // Build response headers
  const headers = {
    ...corsHeaders(origin),
    'Content-Type': object.httpMetadata?.contentType || getContentType(imagePath),
    'Cache-Control': `public, max-age=${CACHE_MAX_AGE}, immutable`,
    'Accept-Ranges': 'bytes',
  };

  // Set ETag from R2 object
  if (object.httpEtag) {
    headers['ETag'] = object.httpEtag;
  }

  // Set Content-Length
  if (object.size !== undefined) {
    headers['Content-Length'] = String(object.size);
  }

  // Handle conditional request (If-None-Match)
  const ifNoneMatch = request.headers.get('If-None-Match');
  if (ifNoneMatch && object.httpEtag && ifNoneMatch === object.httpEtag) {
    return new Response(null, {
      status: 304,
      headers,
    });
  }

  // Handle range request (206 Partial Content)
  const rangeHeader = request.headers.get('Range');
  if (rangeHeader && object.range) {
    headers['Content-Range'] = `bytes ${object.range.offset}-${object.range.offset + object.range.length - 1}/${object.size}`;
    headers['Content-Length'] = String(object.range.length);

    return new Response(request.method === 'HEAD' ? null : object.body, {
      status: 206,
      headers,
    });
  }

  // Normal response
  return new Response(request.method === 'HEAD' ? null : object.body, {
    status: 200,
    headers,
  });
}

/**
 * Return SVG placeholder for missing images.
 */
function returnPlaceholder(origin) {
  return new Response(PLACEHOLDER_SVG, {
    status: 404,
    headers: {
      ...corsHeaders(origin),
      'Content-Type': 'image/svg+xml',
      'Cache-Control': 'public, max-age=300', // Cache 404s for 5 minutes
    },
  });
}

// ---------------------------------------------------------------------------
// Worker entry point
// ---------------------------------------------------------------------------

export default {
  async fetch(request, env, ctx) {
    try {
      return await handleRequest(request, env);
    } catch (err) {
      console.error('[IMG] Unhandled error:', err);
      return new Response('Internal server error', {
        status: 500,
        headers: { 'Content-Type': 'text/plain' },
      });
    }
  },
};
