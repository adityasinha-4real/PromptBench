'use client';

import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import {
  BAR_RADIUS,
  CHART_INK,
  LINE_PROPS,
  SERIES_COLORS,
  axisProps,
  colorAt,
  gridProps,
} from '@/lib/chart-theme';
import { cn } from '@/lib/utils';

/* -------------------------------------------------------------------------- */
/* Shared chrome                                                               */
/* -------------------------------------------------------------------------- */

export function ChartFrame({
  title,
  subtitle,
  children,
  height = 240,
  footnote,
  className,
}: {
  title: string;
  subtitle?: string;
  children: React.ReactNode;
  height?: number;
  footnote?: React.ReactNode;
  className?: string;
}) {
  return (
    <figure className={cn('panel flex flex-col p-4', className)}>
      <figcaption className="mb-3">
        <h3 className="text-sm font-medium text-fg">{title}</h3>
        {subtitle && <p className="mt-0.5 text-xs text-fg-subtle">{subtitle}</p>}
      </figcaption>
      <div style={{ height }} className="w-full">
        {children}
      </div>
      {footnote && <p className="mt-3 text-[11px] text-fg-subtle">{footnote}</p>}
    </figure>
  );
}

interface TooltipRow {
  name?: string | number;
  value?: number | string | null;
  color?: string;
  dataKey?: string | number;
}

function ChartTooltip({
  active,
  payload,
  label,
  formatter,
}: {
  active?: boolean;
  payload?: TooltipRow[];
  label?: string | number;
  formatter: (value: number | null) => string;
}) {
  if (!active || !payload || payload.length === 0) return null;
  return (
    <div className="rounded-md border border-line-strong bg-elevated px-2.5 py-2 text-xs shadow-xl">
      <p className="mb-1 font-medium text-fg">{label}</p>
      {payload.map((row, index) => (
        <p key={index} className="flex items-center gap-2 text-fg-muted">
          <span
            aria-hidden="true"
            className="h-2 w-2 shrink-0 rounded-[2px]"
            style={{ background: row.color }}
          />
          <span className="flex-1">{row.name}</span>
          <span className="tabular font-medium text-fg">
            {formatter(typeof row.value === 'number' ? row.value : null)}
          </span>
        </p>
      ))}
    </div>
  );
}

const legendStyle = { fontSize: 11, color: CHART_INK.secondary, paddingTop: 8 };

export function EmptyChart({ message }: { message: string }) {
  return (
    <div className="flex h-full items-center justify-center rounded border border-dashed border-line text-xs text-fg-subtle">
      {message}
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* Single-series bar comparison                                                */
/* -------------------------------------------------------------------------- */

export interface CategoryDatum {
  label: string;
  value: number | null;
}

/**
 * One measure across models. A single series, so there is no legend and no
 * second y-axis; the title names what is being measured.
 *
 * Rows with `value === null` (e.g. unpriced models) are dropped rather than
 * plotted as zero, and the count is reported in the footnote by the caller.
 */
export function CategoryBars({
  data,
  format,
  height = 240,
  horizontal = false,
  colorByIndex = false,
  domain,
}: {
  data: CategoryDatum[];
  format: (value: number | null) => string;
  height?: number;
  horizontal?: boolean;
  colorByIndex?: boolean;
  domain?: [number, number];
}) {
  const rows = data.filter((row): row is { label: string; value: number } => row.value !== null);
  if (rows.length === 0) return <EmptyChart message="No data for this metric yet." />;

  return (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart
        data={rows}
        layout={horizontal ? 'vertical' : 'horizontal'}
        margin={{ top: 4, right: 12, bottom: 4, left: horizontal ? 8 : 0 }}
        barCategoryGap="22%"
      >
        <CartesianGrid {...gridProps} vertical={horizontal} horizontal={!horizontal} />
        {horizontal ? (
          <>
            <XAxis
              type="number"
              domain={domain}
              {...axisProps}
              tickFormatter={(v) => format(Number(v))}
            />
            <YAxis type="category" dataKey="label" width={130} {...axisProps} />
          </>
        ) : (
          <>
            <XAxis dataKey="label" {...axisProps} interval={0} angle={0} height={34} />
            <YAxis
              {...axisProps}
              domain={domain}
              tickFormatter={(v) => format(Number(v))}
              width={64}
            />
          </>
        )}
        <Tooltip
          cursor={{ fill: 'rgba(255,255,255,0.04)' }}
          content={<ChartTooltip formatter={format} />}
        />
        <Bar
          dataKey="value"
          name="Value"
          radius={horizontal ? [0, 4, 4, 0] : BAR_RADIUS}
          maxBarSize={44}
        >
          {rows.map((row, index) => (
            <Cell
              key={row.label}
              fill={colorByIndex ? colorAt(index) : SERIES_COLORS[0]}
              stroke={CHART_INK.surface}
              strokeWidth={2}
            />
          ))}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}

/* -------------------------------------------------------------------------- */
/* Grouped bars (multi-series)                                                 */
/* -------------------------------------------------------------------------- */

export interface SeriesSpec {
  key: string;
  label: string;
}

/**
 * Several measures on the *same* 0–10 scale across models (the evaluation
 * criteria). Same scale is what makes one axis legitimate here.
 */
export function GroupedBars<T extends object>({
  data,
  series,
  format,
  height = 260,
  domain,
}: {
  data: readonly T[];
  series: SeriesSpec[];
  format: (value: number | null) => string;
  height?: number;
  domain?: [number, number];
}) {
  if (data.length === 0) return <EmptyChart message="No scored results yet." />;

  return (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart
        data={[...data]}
        margin={{ top: 4, right: 12, bottom: 4, left: 0 }}
        barCategoryGap="22%"
      >
        <CartesianGrid {...gridProps} />
        <XAxis dataKey="label" {...axisProps} interval={0} height={34} />
        <YAxis {...axisProps} domain={domain} width={44} tickFormatter={(v) => format(Number(v))} />
        <Tooltip
          cursor={{ fill: 'rgba(255,255,255,0.04)' }}
          content={<ChartTooltip formatter={format} />}
        />
        <Legend wrapperStyle={legendStyle} iconType="square" iconSize={9} />
        {series.map((spec, index) => (
          <Bar
            key={spec.key}
            dataKey={spec.key}
            name={spec.label}
            fill={colorAt(index)}
            radius={BAR_RADIUS}
            maxBarSize={26}
            stroke={CHART_INK.surface}
            strokeWidth={2}
          />
        ))}
      </BarChart>
    </ResponsiveContainer>
  );
}

/* -------------------------------------------------------------------------- */
/* Trend line                                                                  */
/* -------------------------------------------------------------------------- */

/**
 * One measure over time. Deliberately single-series with one y-axis — two
 * measures of different scale get two charts, never a second axis.
 */
export function TrendLine<T extends object>({
  data,
  dataKey,
  label,
  format,
  height = 220,
  colorIndex = 0,
}: {
  data: readonly T[];
  dataKey: string;
  label: string;
  format: (value: number | null) => string;
  height?: number;
  colorIndex?: number;
}) {
  const points = data.filter((row) => (row as Record<string, unknown>)[dataKey] != null);
  if (points.length === 0) return <EmptyChart message="No history for this range yet." />;

  return (
    <ResponsiveContainer width="100%" height={height}>
      <LineChart data={[...points]} margin={{ top: 4, right: 12, bottom: 4, left: 0 }}>
        <CartesianGrid {...gridProps} />
        <XAxis dataKey="date" {...axisProps} minTickGap={24} />
        <YAxis {...axisProps} width={64} tickFormatter={(v) => format(Number(v))} />
        <Tooltip
          cursor={{ stroke: CHART_INK.axis, strokeWidth: 1 }}
          content={<ChartTooltip formatter={format} />}
        />
        <Line
          type="monotone"
          dataKey={dataKey}
          name={label}
          stroke={colorAt(colorIndex)}
          {...LINE_PROPS}
        />
      </LineChart>
    </ResponsiveContainer>
  );
}
