/**
 * Chart design tokens.
 *
 * The categorical slots are the validated dark-mode steps from the reference
 * palette, checked against this app's chart surface (#131316) with
 * `validate_palette.js`: lightness band, chroma floor, CVD separation
 * (worst adjacent ΔE 8.4), normal-vision floor (19.8) and ≥3:1 contrast all pass.
 *
 * Rules enforced by the chart components that consume these:
 *  - categorical hues are assigned in fixed order and never cycled;
 *  - colour follows the entity, so filtering a series never repaints the rest;
 *  - no chart has two y-axes;
 *  - axes and gridlines stay recessive; values wear text tokens, not series colour.
 */

/** Fixed categorical order — index 0 is always the first series. */
export const SERIES_COLORS = ['#3987e5', '#d95926', '#199e70', '#c98500'] as const;

/** Single-hue accent used by one-series charts (magnitude, not identity). */
export const ACCENT = SERIES_COLORS[0];

export const CHART_INK = {
  surface: '#131316',
  grid: '#23232a',
  axis: '#33333c',
  muted: '#8b8b95',
  secondary: '#c3c2b7',
  primary: '#e7e7ea',
} as const;

export const STATUS_COLORS = {
  good: '#0ca30c',
  warning: '#fab219',
  serious: '#ec835a',
  critical: '#d03b3b',
} as const;

/**
 * Stable colour for a named entity.
 *
 * Keyed on the entity (provider:model), not its position in a filtered list, so
 * a model keeps its colour across every chart and every filter change.
 */
export function seriesColor(key: string, order: readonly string[]): string {
  const index = order.indexOf(key);
  if (index < 0) return CHART_INK.muted;
  return SERIES_COLORS[index % SERIES_COLORS.length] as string;
}

export function colorAt(index: number): string {
  return SERIES_COLORS[index % SERIES_COLORS.length] as string;
}

/** Shared Recharts axis styling — recessive by design. */
export const axisProps = {
  stroke: CHART_INK.axis,
  tick: { fill: CHART_INK.muted, fontSize: 11 },
  tickLine: false,
  axisLine: { stroke: CHART_INK.axis },
} as const;

export const gridProps = {
  stroke: CHART_INK.grid,
  strokeDasharray: '0',
  vertical: false,
} as const;

/** 4px rounded data-end anchored to the baseline. */
export const BAR_RADIUS: [number, number, number, number] = [4, 4, 0, 0];
export const BAR_RADIUS_HORIZONTAL: [number, number, number, number] = [0, 4, 4, 0];

/** 2px stroke, ≥8px active marker. */
export const LINE_PROPS = {
  strokeWidth: 2,
  dot: false,
  activeDot: { r: 4, strokeWidth: 2, stroke: CHART_INK.surface },
} as const;
