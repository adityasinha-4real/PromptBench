/**
 * Display formatters.
 *
 * The important rule: a `null` cost means the model has no configured price.
 * It must render as "Pricing unavailable", never as `$0.00`.
 */

export const PRICING_UNAVAILABLE = 'Pricing unavailable';

export function formatLatency(ms: number | null | undefined): string {
  if (ms === null || ms === undefined) return '—';
  if (ms < 1000) return `${Math.round(ms)} ms`;
  if (ms < 60_000) return `${(ms / 1000).toFixed(2)} s`;
  const minutes = Math.floor(ms / 60_000);
  return `${minutes}m ${Math.round((ms % 60_000) / 1000)}s`;
}

/** Drop trailing zeros so `$0.002100` reads as `$0.0021`. */
function trimZeros(value: string): string {
  return value.includes('.') ? value.replace(/0+$/, '').replace(/\.$/, '') : value;
}

export function formatCost(cost: number | null | undefined): string {
  if (cost === null || cost === undefined) return PRICING_UNAVAILABLE;
  if (cost === 0) return '$0.00';
  if (cost < 0.000001) return '<$0.000001';
  if (cost < 0.01) return `$${trimZeros(cost.toFixed(6))}`;
  if (cost < 1) return `$${trimZeros(cost.toFixed(4))}`;
  return `$${cost.toFixed(2)}`;
}

export function formatCostPer1k(cost: number | null | undefined): string {
  if (cost === null || cost === undefined) return PRICING_UNAVAILABLE;
  return `${formatCost(cost)} / 1K`;
}

export function formatNumber(value: number | null | undefined, digits = 0): string {
  if (value === null || value === undefined) return '—';
  return value.toLocaleString('en-US', {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

export function formatTokens(value: number | null | undefined): string {
  if (value === null || value === undefined) return '—';
  if (value >= 1_000_000) return `${(value / 1_000_000).toFixed(2)}M`;
  if (value >= 10_000) return `${(value / 1000).toFixed(1)}K`;
  return value.toLocaleString('en-US');
}

export function formatScore(value: number | null | undefined): string {
  if (value === null || value === undefined) return '—';
  return value.toFixed(1);
}

export function formatPercent(value: number | null | undefined, digits = 0): string {
  if (value === null || value === undefined) return '—';
  return `${(value * 100).toFixed(digits)}%`;
}

export function formatThroughput(value: number | null | undefined): string {
  if (value === null || value === undefined || value === 0) return '—';
  return `${value.toFixed(1)} tok/s`;
}

export function formatDate(iso: string | null | undefined): string {
  if (!iso) return '—';
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return '—';
  return date.toLocaleString('en-US', {
    year: 'numeric',
    month: 'short',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  });
}

export function formatRelative(iso: string | null | undefined): string {
  if (!iso) return '—';
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return '—';
  const seconds = Math.round((Date.now() - date.getTime()) / 1000);
  if (seconds < 45) return 'just now';
  if (seconds < 90) return '1 minute ago';
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes} minutes ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours} hour${hours === 1 ? '' : 's'} ago`;
  const days = Math.round(hours / 24);
  if (days < 30) return `${days} day${days === 1 ? '' : 's'} ago`;
  return formatDate(iso);
}

export function providerLabel(provider: string): string {
  const labels: Record<string, string> = {
    openai: 'OpenAI',
    anthropic: 'Anthropic',
    gemini: 'Gemini',
    ollama: 'Ollama',
  };
  return labels[provider] ?? provider.charAt(0).toUpperCase() + provider.slice(1);
}

export function errorLabel(code: string | null | undefined): string {
  const labels: Record<string, string> = {
    timeout: 'Timed out',
    rate_limit: 'Rate limited',
    authentication: 'Auth failed',
    provider_unavailable: 'Unavailable',
    invalid_request: 'Invalid request',
    content_filter: 'Content blocked',
    cancelled: 'Cancelled',
    not_found: 'Not found',
    unknown: 'Failed',
  };
  if (!code) return 'Failed';
  return labels[code] ?? code.replace(/_/g, ' ');
}

export function evaluationModeLabel(mode: string): string {
  const labels: Record<string, string> = {
    disabled: 'No evaluation',
    heuristic: 'Heuristic',
    llm_judge: 'LLM judge',
    manual: 'Manual',
  };
  return labels[mode] ?? mode;
}
