'use client';

import { useMemo, useState } from 'react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { cn } from '@/lib/utils';
import type { ModelSelection, ProviderInfo } from '@/types';

function keyOf(selection: ModelSelection): string {
  return `${selection.provider}:${selection.model}`;
}

export interface ModelPickerProps {
  providers: ProviderInfo[];
  selected: ModelSelection[];
  onChange: (selection: ModelSelection[]) => void;
  max: number;
  disabled?: boolean;
}

/**
 * Multi-select over every configured provider.
 *
 * Unavailable providers stay visible but disabled, with the reason shown —
 * that is more useful than hiding them, because the reason is usually a
 * missing environment variable the user can go and set.
 */
export function ModelPicker({ providers, selected, onChange, max, disabled }: ModelPickerProps) {
  const [custom, setCustom] = useState<Record<string, string>>({});
  const selectedKeys = useMemo(() => new Set(selected.map(keyOf)), [selected]);
  const atLimit = selected.length >= max;

  const toggle = (selection: ModelSelection) => {
    const key = keyOf(selection);
    if (selectedKeys.has(key)) {
      onChange(selected.filter((item) => keyOf(item) !== key));
    } else if (!atLimit) {
      onChange([...selected, selection]);
    }
  };

  const addCustom = (providerId: string) => {
    const model = (custom[providerId] ?? '').trim();
    if (!model || atLimit) return;
    const selection = { provider: providerId, model };
    if (!selectedKeys.has(keyOf(selection))) onChange([...selected, selection]);
    setCustom((current) => ({ ...current, [providerId]: '' }));
  };

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <p className="text-xs text-fg-muted">
          {selected.length} of {max} selected
        </p>
        {selected.length > 0 && (
          <Button size="sm" variant="ghost" onClick={() => onChange([])} disabled={disabled}>
            Clear
          </Button>
        )}
      </div>

      <div className="space-y-2">
        {providers.map((provider) => (
          <div key={provider.id} className="rounded-md border border-line">
            <div className="flex flex-wrap items-center justify-between gap-2 border-b border-line px-3 py-2">
              <div className="flex items-center gap-2">
                <span className="text-sm font-medium text-fg">{provider.label}</span>
                {provider.is_local && <Badge tone="accent">Local · free</Badge>}
                <Badge tone={provider.available ? 'ok' : 'muted'}>
                  <span aria-hidden="true">{provider.available ? '✓' : '○'}</span>
                  {provider.available ? 'Available' : 'Unavailable'}
                </Badge>
              </div>
              {!provider.available && (
                <p className="text-xs text-fg-subtle">{provider.status_detail}</p>
              )}
            </div>

            <div className="p-2">
              {provider.models.length === 0 ? (
                <p className="px-1 py-1.5 text-xs text-fg-subtle">
                  {provider.available
                    ? 'No models reported by this provider.'
                    : 'Configure this provider to list its models.'}
                </p>
              ) : (
                <div className="grid gap-1.5 sm:grid-cols-2 xl:grid-cols-3">
                  {provider.models.map((model) => {
                    const selection = { provider: provider.id, model: model.id };
                    const isSelected = selectedKeys.has(keyOf(selection));
                    const blocked = !provider.available || (atLimit && !isSelected) || disabled;
                    return (
                      <button
                        key={model.id}
                        type="button"
                        onClick={() => toggle(selection)}
                        disabled={blocked}
                        aria-pressed={isSelected}
                        className={cn(
                          'flex flex-col gap-0.5 rounded-md border px-2.5 py-2 text-left transition-colors',
                          isSelected
                            ? 'border-accent bg-accent-soft'
                            : 'border-line hover:border-line-strong hover:bg-surface-2',
                          blocked &&
                            'cursor-not-allowed opacity-45 hover:border-line hover:bg-transparent'
                        )}
                      >
                        <span className="flex items-center gap-1.5">
                          <span
                            aria-hidden="true"
                            className={cn(
                              'text-[11px]',
                              isSelected ? 'text-accent' : 'text-fg-subtle'
                            )}
                          >
                            {isSelected ? '☑' : '☐'}
                          </span>
                          <span className="truncate font-mono text-xs text-fg">{model.id}</span>
                        </span>
                        <span className="truncate pl-4 text-[11px] text-fg-subtle">
                          {model.pricing
                            ? `$${model.pricing.input_per_1m.toFixed(2)} in · $${model.pricing.output_per_1m.toFixed(2)} out · per 1M tokens`
                            : 'Pricing unavailable'}
                        </span>
                      </button>
                    );
                  })}
                </div>
              )}

              {provider.available && (
                <div className="mt-2 flex gap-1.5 border-t border-line pt-2">
                  <Input
                    value={custom[provider.id] ?? ''}
                    onChange={(event) =>
                      setCustom((current) => ({ ...current, [provider.id]: event.target.value }))
                    }
                    onKeyDown={(event) => {
                      if (event.key === 'Enter') {
                        event.preventDefault();
                        addCustom(provider.id);
                      }
                    }}
                    placeholder={`Any other ${provider.label} model id…`}
                    className="h-8 text-xs"
                    disabled={disabled || atLimit}
                    aria-label={`Add a custom ${provider.label} model`}
                  />
                  <Button
                    size="sm"
                    onClick={() => addCustom(provider.id)}
                    disabled={disabled || atLimit || !(custom[provider.id] ?? '').trim()}
                  >
                    Add
                  </Button>
                </div>
              )}
            </div>
          </div>
        ))}
      </div>

      {selected.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {selected.map((selection) => (
            <button
              key={keyOf(selection)}
              type="button"
              onClick={() => toggle(selection)}
              disabled={disabled}
              className="inline-flex items-center gap-1.5 rounded border border-accent bg-accent-soft px-2 py-1 text-xs text-[#9cc4f7] hover:bg-[#1a2f4d]"
            >
              <span className="font-mono">{selection.model}</span>
              <span className="text-fg-subtle">{selection.provider}</span>
              <span aria-hidden="true">×</span>
              <span className="sr-only">Remove {keyOf(selection)}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
