/**
 * Stats page for SUI Archive.
 *
 * Renders overview cards with animated count-up, a GitHub-style activity
 * heatmap (SVG), a monthly post trend bar chart (Canvas), and an engagement
 * summary chart (Canvas).  All charts are drawn with native APIs -- no
 * external chart libraries.
 */

import { $, createElement, formatNumber } from './dom.js';
import { fetchStats } from './api.js';

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const COUNT_UP_DURATION = 1000; // ms
const HEATMAP_DAYS = 365;
const DAY_LABELS = ['一', '二', '三', '四', '五', '六', '日'];
const MONTH_LABELS = [
  '1月', '2月', '3月', '4月', '5月', '6月',
  '7月', '8月', '9月', '10月', '11月', '12月',
];

/**
 * Registry of canvas chart renderers for resize handling.
 * Each entry: { canvas, container, draw, barRects, colors }
 * @type {Map<HTMLCanvasElement, Object>}
 */
const chartRegistry = new Map();

// ---------------------------------------------------------------------------
// Color helpers
// ---------------------------------------------------------------------------

/**
 * Read a CSS custom property from the document root.
 * @param {string} prop - e.g. '--primary'
 * @param {string} fallback
 * @returns {string}
 */
function cssVar(prop, fallback = '') {
  return getComputedStyle(document.documentElement).getPropertyValue(prop).trim() || fallback;
}

/**
 * Return the current palette, reflecting the active color scheme.
 */
function getColors() {
  return {
    primary: cssVar('--primary', '#5D7052'),
    secondary: cssVar('--secondary', '#C18C5D'),
    accent: cssVar('--accent', '#E6DCCD'),
    background: cssVar('--background', '#FDFCF8'),
    foreground: cssVar('--foreground', '#2C2C24'),
    border: cssVar('--border', '#E0D5C4'),
  };
}

/**
 * Return heatmap fill color for a given activity level (0-4).
 * Appends hex alpha to the base color for translucency.
 */
function heatColor(level, colors) {
  if (level === 0) return colors.accent + '30';
  if (level === 1) return colors.primary + '55';
  if (level === 2) return colors.primary + '88';
  if (level === 3) return colors.primary + 'BB';
  return colors.primary;
}

/**
 * Map a raw post count to an activity level 0-4.
 */
function activityLevel(count) {
  if (count <= 0) return 0;
  if (count === 1) return 1;
  if (count <= 3) return 2;
  if (count <= 5) return 3;
  return 4;
}

// ---------------------------------------------------------------------------
// Entry point
// ---------------------------------------------------------------------------

/**
 * Initialise the stats page.  Called by app.js when the /stats route loads.
 */
export async function initStats() {
  const stats = await fetchStats();
  if (!stats) {
    showError();
    return;
  }

  renderOverviewCards(stats);
  renderHeatmap(stats);
  renderPostChart(stats);
  renderEngagementChart(stats);

  // Redraw charts when color scheme changes
  const mq = window.matchMedia('(prefers-color-scheme: dark)');
  mq.addEventListener('change', () => {
    renderHeatmap(stats);
    renderPostChart(stats);
    renderEngagementChart(stats);
  });
}

// ---------------------------------------------------------------------------
// Error display
// ---------------------------------------------------------------------------

function showError() {
  const main = $('#main-content') || document.body;
  const el = createElement('div', {
    role: 'alert',
    style: { textAlign: 'center', padding: '2rem 1rem', color: 'var(--muted-foreground, #666)' },
  }, [
    createElement('p', {}, ['无法加载统计数据']),
  ]);
  main.appendChild(el);
}

// ---------------------------------------------------------------------------
// 1. Overview cards -- animated count-up
// ---------------------------------------------------------------------------

function renderOverviewCards(stats) {
  const { overview, engagement } = stats;

  const cards = [
    { id: 'stat-total-posts', value: overview.total_posts },
    { id: 'stat-total-images', value: overview.total_images },
    { id: 'stat-total-likes', value: engagement?.total_likes ?? 0 },
    { id: 'stat-total-reposts', value: engagement?.total_forwards ?? 0 },
  ];

  for (const card of cards) {
    const el = $(`#${card.id}`);
    if (!el) continue;
    animateCount(el, card.value);
  }
}

/**
 * Animate a number from 0 to `target` inside `el` over COUNT_UP_DURATION ms.
 * Uses requestAnimationFrame with an ease-out cubic curve.
 */
function animateCount(el, target) {
  if (target === 0) {
    el.textContent = formatNumber(0);
    return;
  }

  const start = performance.now();

  function tick(now) {
    const elapsed = now - start;
    const progress = Math.min(elapsed / COUNT_UP_DURATION, 1);
    const eased = 1 - Math.pow(1 - progress, 3);
    const current = Math.round(eased * target);
    el.textContent = formatNumber(current);

    if (progress < 1) {
      requestAnimationFrame(tick);
    }
  }

  requestAnimationFrame(tick);
}

// ---------------------------------------------------------------------------
// 2. Activity heatmap (SVG)
// ---------------------------------------------------------------------------

function renderHeatmap(stats) {
  const container = $('#heatmap');
  if (!container) return;
  container.innerHTML = '';

  const colors = getColors();
  const heatmapData = stats.activity_heatmap || {};

  const days = buildHeatmapDays(heatmapData);
  const weeks = groupIntoWeeks(days);

  // SVG layout constants
  const cellSize = 13;
  const cellGap = 3;
  const step = cellSize + cellGap;
  const labelWidth = 28;
  const labelHeight = 20;
  const cols = weeks.length;
  const rows = 7;

  const svgWidth = labelWidth + cols * step;
  const svgHeight = labelHeight + rows * step;

  const ns = 'http://www.w3.org/2000/svg';
  const svg = document.createElementNS(ns, 'svg');
  svg.setAttribute('viewBox', `0 0 ${svgWidth} ${svgHeight}`);
  svg.setAttribute('width', '100%');
  svg.setAttribute('height', 'auto');
  svg.setAttribute('role', 'img');
  svg.setAttribute('aria-label', '发布活动热力图');
  svg.style.display = 'block';
  svg.style.maxWidth = `${svgWidth}px`;

  // Month labels along the top
  const monthLabels = computeMonthLabels(weeks, labelWidth, step);
  for (const ml of monthLabels) {
    const text = document.createElementNS(ns, 'text');
    text.setAttribute('x', ml.x);
    text.setAttribute('y', labelHeight - 6);
    text.setAttribute('font-size', '10');
    text.setAttribute('fill', colors.foreground);
    text.setAttribute('opacity', '0.6');
    text.textContent = ml.label;
    svg.appendChild(text);
  }

  // Day-of-week labels on the left (show Mon, Wed, Fri)
  for (const rowIdx of [0, 2, 4]) {
    const text = document.createElementNS(ns, 'text');
    text.setAttribute('x', 0);
    text.setAttribute('y', labelHeight + rowIdx * step + cellSize - 2);
    text.setAttribute('font-size', '10');
    text.setAttribute('fill', colors.foreground);
    text.setAttribute('opacity', '0.6');
    text.textContent = DAY_LABELS[rowIdx];
    svg.appendChild(text);
  }

  // Day cells
  for (let col = 0; col < weeks.length; col++) {
    const week = weeks[col];
    for (let row = 0; row < 7; row++) {
      const day = week[row];
      if (!day) continue;

      const x = labelWidth + col * step;
      const y = labelHeight + row * step;
      const level = activityLevel(day.count);

      const rect = document.createElementNS(ns, 'rect');
      rect.setAttribute('x', x);
      rect.setAttribute('y', y);
      rect.setAttribute('width', cellSize);
      rect.setAttribute('height', cellSize);
      rect.setAttribute('rx', '2');
      rect.setAttribute('ry', '2');
      rect.setAttribute('fill', heatColor(level, colors));

      // Native tooltip via <title>
      const title = document.createElementNS(ns, 'title');
      title.textContent = `${day.dateStr}: ${day.count}条动态`;
      rect.appendChild(title);

      svg.appendChild(rect);
    }
  }

  container.appendChild(svg);
}

/**
 * Build day entries for the last HEATMAP_DAYS days from the heatmap data map.
 * Each entry: { date, dateStr, count, dayOfWeek } where dayOfWeek 0=Mon..6=Sun.
 */
function buildHeatmapDays(heatmapData) {
  const today = new Date();
  today.setHours(0, 0, 0, 0);

  const days = [];
  for (let i = HEATMAP_DAYS - 1; i >= 0; i--) {
    const d = new Date(today);
    d.setDate(d.getDate() - i);

    const yyyy = d.getFullYear();
    const mm = String(d.getMonth() + 1).padStart(2, '0');
    const dd = String(d.getDate()).padStart(2, '0');
    const dateStr = `${yyyy}-${mm}-${dd}`;

    // JS getDay: 0=Sun..6=Sat -> convert to 0=Mon..6=Sun
    const dayOfWeek = (d.getDay() + 6) % 7;

    days.push({
      date: d,
      dateStr,
      count: heatmapData[dateStr] || 0,
      dayOfWeek,
    });
  }

  return days;
}

/**
 * Group day entries into week columns (index 0 = Monday).
 * Days before the first entry's weekday are null.
 */
function groupIntoWeeks(days) {
  const weeks = [];
  let currentWeek = [];

  for (const day of days) {
    if (day.dayOfWeek === 0 && currentWeek.length > 0) {
      weeks.push(currentWeek);
      currentWeek = [];
    }

    // Pad the first week with nulls for days before the start day
    if (weeks.length === 0 && currentWeek.length === 0) {
      for (let i = 0; i < day.dayOfWeek; i++) {
        currentWeek.push(null);
      }
    }

    currentWeek[day.dayOfWeek] = day;
  }

  if (currentWeek.length > 0) {
    weeks.push(currentWeek);
  }

  return weeks;
}

/**
 * Compute month label positions for the heatmap SVG.
 * Emits a label at the first week column where a new month begins.
 */
function computeMonthLabels(weeks, labelWidth, step) {
  const labels = [];
  let lastMonth = -1;

  for (let col = 0; col < weeks.length; col++) {
    const firstDay = weeks[col].find((d) => d != null);
    if (!firstDay) continue;

    const month = firstDay.date.getMonth();
    if (month !== lastMonth) {
      labels.push({
        x: labelWidth + col * step,
        label: MONTH_LABELS[month],
      });
      lastMonth = month;
    }
  }

  return labels;
}

// ---------------------------------------------------------------------------
// 3. Post trend chart -- Canvas bar chart by month
// ---------------------------------------------------------------------------

function renderPostChart(stats) {
  const container = $('#chart-posts');
  if (!container) return;
  container.innerHTML = '';

  const colors = getColors();
  const byMonth = stats.by_month || {};

  const values = [];
  for (let m = 1; m <= 12; m++) {
    values.push(byMonth[String(m)] || 0);
  }

  const cssWidth = container.clientWidth || 600;
  const cssHeight = 300;
  const { canvas, ctx } = createHiDPICanvas(container, cssWidth, cssHeight);

  const pad = { top: 40, right: 20, bottom: 40, left: 50 };
  const chartW = cssWidth - pad.left - pad.right;
  const chartH = cssHeight - pad.top - pad.bottom;
  const maxVal = Math.max(1, ...values);

  // Title
  ctx.fillStyle = colors.foreground;
  ctx.font = 'bold 14px system-ui, sans-serif';
  ctx.textAlign = 'center';
  ctx.fillText('每月发布数量', cssWidth / 2, 22);

  // Y-axis gridlines and labels
  const yTicks = niceScale(0, maxVal, 5);
  ctx.font = '11px system-ui, sans-serif';
  ctx.textAlign = 'right';
  ctx.textBaseline = 'middle';

  for (const tick of yTicks) {
    const y = pad.top + chartH - (tick / maxVal) * chartH;
    ctx.strokeStyle = colors.border;
    ctx.lineWidth = 0.5;
    ctx.beginPath();
    ctx.moveTo(pad.left, y);
    ctx.lineTo(pad.left + chartW, y);
    ctx.stroke();

    ctx.fillStyle = colors.foreground;
    ctx.globalAlpha = 0.6;
    ctx.fillText(String(tick), pad.left - 8, y);
    ctx.globalAlpha = 1;
  }

  // Bars
  const barGap = 6;
  const barWidth = (chartW - barGap * 13) / 12;
  const barRects = [];

  for (let i = 0; i < 12; i++) {
    const x = pad.left + barGap + i * (barWidth + barGap);
    const barH = (values[i] / maxVal) * chartH;
    const y = pad.top + chartH - barH;

    ctx.fillStyle = colors.primary;
    roundedRect(ctx, x, y, barWidth, barH, 3);
    ctx.fill();

    barRects.push({ x, y, w: barWidth, h: barH, value: values[i], label: MONTH_LABELS[i] });

    // X-axis label
    ctx.fillStyle = colors.foreground;
    ctx.globalAlpha = 0.6;
    ctx.font = '11px system-ui, sans-serif';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'top';
    ctx.fillText(MONTH_LABELS[i], x + barWidth / 2, pad.top + chartH + 8);
    ctx.globalAlpha = 1;
  }

  // Register for tooltip and resize handling
  const drawFn = () => renderPostChart(stats);
  registerChart(canvas, container, drawFn, barRects, colors, (bar) => {
    return `${bar.label}: ${formatNumber(bar.value)}`;
  });
}

// ---------------------------------------------------------------------------
// 4. Engagement chart -- Canvas grouped bar chart
// ---------------------------------------------------------------------------

function renderEngagementChart(stats) {
  const container = $('#chart-engagement');
  if (!container) return;
  container.innerHTML = '';

  const colors = getColors();
  const engagement = stats.engagement || {};

  const groups = [
    { label: '点赞', value: engagement.total_likes || 0, color: colors.primary },
    { label: '评论', value: engagement.total_comments || 0, color: colors.secondary },
    { label: '转发', value: engagement.total_forwards || 0, color: colors.accent },
  ];

  const cssWidth = container.clientWidth || 600;
  const cssHeight = 300;
  const { canvas, ctx } = createHiDPICanvas(container, cssWidth, cssHeight);

  const pad = { top: 40, right: 20, bottom: 40, left: 70 };
  const chartW = cssWidth - pad.left - pad.right;
  const chartH = cssHeight - pad.top - pad.bottom;
  const maxVal = Math.max(1, ...groups.map((g) => g.value));

  // Title
  ctx.fillStyle = colors.foreground;
  ctx.font = 'bold 14px system-ui, sans-serif';
  ctx.textAlign = 'center';
  ctx.fillText('互动数据总览', cssWidth / 2, 22);

  // Y-axis gridlines and labels
  const yTicks = niceScale(0, maxVal, 5);
  ctx.font = '11px system-ui, sans-serif';
  ctx.textAlign = 'right';
  ctx.textBaseline = 'middle';

  for (const tick of yTicks) {
    const y = pad.top + chartH - (tick / maxVal) * chartH;
    ctx.strokeStyle = colors.border;
    ctx.lineWidth = 0.5;
    ctx.beginPath();
    ctx.moveTo(pad.left, y);
    ctx.lineTo(pad.left + chartW, y);
    ctx.stroke();

    ctx.fillStyle = colors.foreground;
    ctx.globalAlpha = 0.6;
    ctx.fillText(formatCompact(tick), pad.left - 8, y);
    ctx.globalAlpha = 1;
  }

  // Bars -- centered with even spacing
  const barGap = 20;
  const totalGaps = barGap * (groups.length + 1);
  const barWidth = Math.min(80, (chartW - totalGaps) / groups.length);
  const totalBarWidth = groups.length * barWidth + (groups.length - 1) * barGap;
  const startX = pad.left + (chartW - totalBarWidth) / 2;

  const barRects = [];

  for (let i = 0; i < groups.length; i++) {
    const g = groups[i];
    const x = startX + i * (barWidth + barGap);
    const barH = (g.value / maxVal) * chartH;
    const y = pad.top + chartH - barH;

    ctx.fillStyle = g.color;
    roundedRect(ctx, x, y, barWidth, barH, 4);
    ctx.fill();

    barRects.push({ x, y, w: barWidth, h: barH, value: g.value, label: g.label });

    // X-axis label
    ctx.fillStyle = colors.foreground;
    ctx.font = '12px system-ui, sans-serif';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'top';
    ctx.fillText(g.label, x + barWidth / 2, pad.top + chartH + 10);

    // Value on top of bar
    ctx.fillStyle = colors.foreground;
    ctx.globalAlpha = 0.7;
    ctx.font = '11px system-ui, sans-serif';
    ctx.textBaseline = 'bottom';
    ctx.fillText(formatCompact(g.value), x + barWidth / 2, y - 4);
    ctx.globalAlpha = 1;
  }

  // Register for tooltip and resize handling
  const drawFn = () => renderEngagementChart(stats);
  registerChart(canvas, container, drawFn, barRects, colors, (bar) => {
    return `${bar.label}: ${formatNumber(bar.value)}`;
  });
}

// ---------------------------------------------------------------------------
// Canvas helpers
// ---------------------------------------------------------------------------

/**
 * Create a <canvas> element scaled for high-DPI displays.
 * Returns the canvas and its 2D context (already scaled by devicePixelRatio).
 *
 * All subsequent drawing on the returned context should use logical (CSS)
 * pixel coordinates -- the dpr scale transform handles the rest.
 *
 * @param {HTMLElement} container - parent element
 * @param {number} cssWidth - desired CSS width in px
 * @param {number} cssHeight - desired CSS height in px
 * @returns {{ canvas: HTMLCanvasElement, ctx: CanvasRenderingContext2D }}
 */
function createHiDPICanvas(container, cssWidth, cssHeight) {
  const dpr = window.devicePixelRatio || 1;
  const canvas = document.createElement('canvas');
  canvas.width = Math.round(cssWidth * dpr);
  canvas.height = Math.round(cssHeight * dpr);
  canvas.style.width = `${cssWidth}px`;
  canvas.style.height = `${cssHeight}px`;
  canvas.style.display = 'block';

  const ctx = canvas.getContext('2d');
  ctx.scale(dpr, dpr);

  container.appendChild(canvas);
  return { canvas, ctx };
}

/**
 * Draw a rounded-top rectangle path (does not fill -- caller fills).
 */
function roundedRect(ctx, x, y, w, h, r) {
  if (h <= 0) { ctx.beginPath(); return; }
  r = Math.min(r, w / 2, h / 2);
  ctx.beginPath();
  ctx.moveTo(x + r, y);
  ctx.lineTo(x + w - r, y);
  ctx.arcTo(x + w, y, x + w, y + r, r);
  ctx.lineTo(x + w, y + h);
  ctx.lineTo(x, y + h);
  ctx.lineTo(x, y + r);
  ctx.arcTo(x, y, x + r, y, r);
  ctx.closePath();
}

/**
 * Compute nice Y-axis tick values from 0 to max.
 */
function niceScale(min, max, targetTicks) {
  if (max <= min) return [0];
  const range = max - min;
  const roughStep = range / targetTicks;
  const mag = Math.pow(10, Math.floor(Math.log10(roughStep)));
  const residual = roughStep / mag;

  let niceStep;
  if (residual <= 1.5) niceStep = mag;
  else if (residual <= 3) niceStep = 2 * mag;
  else if (residual <= 7) niceStep = 5 * mag;
  else niceStep = 10 * mag;

  const ticks = [];
  for (let v = 0; v <= max + niceStep * 0.01; v += niceStep) {
    ticks.push(Math.round(v));
  }
  return ticks;
}

/**
 * Compact number format for axis labels (e.g. 1500 -> "1.5k", 250000 -> "250k").
 */
function formatCompact(n) {
  if (n >= 1_000_000) return (n / 1_000_000).toFixed(1).replace(/\.0$/, '') + 'M';
  if (n >= 10_000) return (n / 1_000).toFixed(0) + 'k';
  if (n >= 1_000) return (n / 1_000).toFixed(1).replace(/\.0$/, '') + 'k';
  return String(n);
}

// ---------------------------------------------------------------------------
// Chart registration, tooltip, and resize handling
// ---------------------------------------------------------------------------

/**
 * Register a canvas chart for interactive tooltips and resize redrawing.
 *
 * After the chart is drawn, this captures the base pixel buffer so that
 * hover overlays can be cleanly composited and removed.  A ResizeObserver
 * watches the container and re-invokes the draw function when the width
 * changes.
 *
 * @param {HTMLCanvasElement} canvas
 * @param {HTMLElement} container
 * @param {Function} redraw - function that fully re-renders the chart
 * @param {Array} barRects - hit-test rects [{ x, y, w, h, value, label }]
 * @param {Object} colors - current palette
 * @param {Function} tooltipText - (bar) => string
 */
function registerChart(canvas, container, redraw, barRects, colors, tooltipText) {
  const ctx = canvas.getContext('2d');

  // Capture the base image after the current frame to ensure all draw calls
  // have been flushed to the bitmap.
  let baseImageData = null;
  requestAnimationFrame(() => {
    baseImageData = ctx.getImageData(0, 0, canvas.width, canvas.height);
  });

  // -- Tooltip on hover ----------------------------------------------------

  function handleMouseMove(e) {
    if (!baseImageData) return;

    const rect = canvas.getBoundingClientRect();
    const mx = e.clientX - rect.left;
    const my = e.clientY - rect.top;

    // Restore the clean chart
    ctx.putImageData(baseImageData, 0, 0);

    // Hit-test bar rects (coordinates are in CSS / logical pixels, which
    // matches the offset from getBoundingClientRect).
    let hit = null;
    for (const bar of barRects) {
      if (mx >= bar.x && mx <= bar.x + bar.w && my >= bar.y && my <= bar.y + bar.h) {
        hit = bar;
        break;
      }
    }

    if (!hit) return;

    // After putImageData the dpr scale transform from createHiDPICanvas is
    // still in effect, so all subsequent draws use logical coordinates.
    ctx.save();

    // Highlight overlay on the hovered bar
    ctx.globalAlpha = 0.15;
    ctx.fillStyle = colors.foreground;
    roundedRect(ctx, hit.x, hit.y, hit.w, hit.h, 3);
    ctx.fill();
    ctx.globalAlpha = 1;

    // Tooltip bubble
    const text = tooltipText(hit);
    drawTooltip(ctx, text, mx, my, colors);

    ctx.restore();
  }

  function handleMouseLeave() {
    if (baseImageData) {
      ctx.putImageData(baseImageData, 0, 0);
    }
  }

  canvas.addEventListener('mousemove', handleMouseMove);
  canvas.addEventListener('mouseleave', handleMouseLeave);

  // -- ResizeObserver: redraw at new width ----------------------------------

  if (typeof ResizeObserver !== 'undefined') {
    let lastWidth = container.clientWidth;
    const ro = new ResizeObserver((entries) => {
      const newWidth = entries[0]?.contentRect?.width || container.clientWidth;
      if (Math.abs(newWidth - lastWidth) > 2) {
        lastWidth = newWidth;
        // Clean up old listeners before re-rendering (container.innerHTML
        // is cleared inside the render function, which removes this canvas).
        canvas.removeEventListener('mousemove', handleMouseMove);
        canvas.removeEventListener('mouseleave', handleMouseLeave);
        ro.disconnect();
        chartRegistry.delete(canvas);
        redraw();
      }
    });
    ro.observe(container);
  }

  chartRegistry.set(canvas, { canvas, container, redraw });
}

/**
 * Draw a tooltip bubble positioned above (or below) the cursor.
 * All coordinates are in logical (CSS) pixels -- the ctx dpr transform
 * handles the actual pixel mapping.
 */
function drawTooltip(ctx, text, tx, ty, colors) {
  ctx.font = '12px system-ui, sans-serif';
  const metrics = ctx.measureText(text);
  const pw = 8;
  const ph = 6;
  const tw = metrics.width + pw * 2;
  const th = 20 + ph;

  const canvasW = parseInt(ctx.canvas.style.width, 10);
  let bx = tx - tw / 2;
  let by = ty - th - 8;
  if (bx < 2) bx = 2;
  if (bx + tw > canvasW - 2) bx = canvasW - tw - 2;
  if (by < 2) by = ty + 16;

  // Background pill
  ctx.fillStyle = colors.foreground;
  ctx.globalAlpha = 0.9;
  roundedRect(ctx, bx, by, tw, th, 4);
  ctx.fill();
  ctx.globalAlpha = 1;

  // Text
  ctx.fillStyle = colors.background;
  ctx.textAlign = 'left';
  ctx.textBaseline = 'middle';
  ctx.fillText(text, bx + pw, by + th / 2);
}
