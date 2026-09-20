import { describe, expect, it } from 'vitest';
import {
  PRICING_UNAVAILABLE,
  errorLabel,
  evaluationModeLabel,
  formatCost,
  formatCostPer1k,
  formatLatency,
  formatNumber,
  formatPercent,
  formatScore,
  formatThroughput,
  formatTokens,
  providerLabel,
} from '@/lib/format';

describe('formatCost', () => {
  it('renders "Pricing unavailable" for null rather than a zero', () => {
    // A model with no configured price must never look free.
    expect(formatCost(null)).toBe(PRICING_UNAVAILABLE);
    expect(formatCost(undefined)).toBe(PRICING_UNAVAILABLE);
  });

  it('renders a genuine zero as $0.00', () => {
    expect(formatCost(0)).toBe('$0.00');
  });

  it('keeps enough precision for sub-cent amounts', () => {
    expect(formatCost(0.000123)).toBe('$0.000123');
    expect(formatCost(0.0021)).toBe('$0.0021');
    expect(formatCost(0.0234)).toBe('$0.0234');
    expect(formatCost(1.5)).toBe('$1.50');
  });

  it('floors unrepresentably small costs instead of showing $0.00', () => {
    expect(formatCost(0.0000001)).toBe('<$0.000001');
  });

  it('propagates unavailability through the per-1K helper', () => {
    expect(formatCostPer1k(null)).toBe(PRICING_UNAVAILABLE);
    expect(formatCostPer1k(0.002)).toBe('$0.002 / 1K');
  });
});

describe('formatLatency', () => {
  it.each([
    [null, '—'],
    [0, '0 ms'],
    [820, '820 ms'],
    [1234, '1.23 s'],
    [65000, '1m 5s'],
  ])('formats %s as %s', (input, expected) => {
    expect(formatLatency(input as number | null)).toBe(expected);
  });
});

describe('formatTokens', () => {
  it.each([
    [null, '—'],
    [0, '0'],
    [950, '950'],
    [12500, '12.5K'],
    [2_500_000, '2.50M'],
  ])('formats %s as %s', (input, expected) => {
    expect(formatTokens(input as number | null)).toBe(expected);
  });
});

describe('score and percentage helpers', () => {
  it('shows an em dash rather than 0.0 for a missing score', () => {
    expect(formatScore(null)).toBe('—');
    expect(formatScore(8.42)).toBe('8.4');
    expect(formatScore(0)).toBe('0.0');
  });

  it('formats percentages', () => {
    expect(formatPercent(null)).toBe('—');
    expect(formatPercent(1)).toBe('100%');
    expect(formatPercent(0.5)).toBe('50%');
  });

  it('formats throughput and treats zero as unknown', () => {
    expect(formatThroughput(null)).toBe('—');
    expect(formatThroughput(0)).toBe('—');
    expect(formatThroughput(73.24)).toBe('73.2 tok/s');
  });

  it('formats plain numbers', () => {
    expect(formatNumber(null)).toBe('—');
    expect(formatNumber(1234)).toBe('1,234');
    expect(formatNumber(12.345, 2)).toBe('12.35');
  });
});

describe('labels', () => {
  it('maps provider ids to display names', () => {
    expect(providerLabel('openai')).toBe('OpenAI');
    expect(providerLabel('ollama')).toBe('Ollama');
    expect(providerLabel('mystery')).toBe('Mystery');
  });

  it('maps error codes to readable labels', () => {
    expect(errorLabel('rate_limit')).toBe('Rate limited');
    expect(errorLabel('authentication')).toBe('Auth failed');
    expect(errorLabel(null)).toBe('Failed');
    expect(errorLabel('weird_code')).toBe('weird code');
  });

  it('maps evaluation modes', () => {
    expect(evaluationModeLabel('llm_judge')).toBe('LLM judge');
    expect(evaluationModeLabel('disabled')).toBe('No evaluation');
  });
});
