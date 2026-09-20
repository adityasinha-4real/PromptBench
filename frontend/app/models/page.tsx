'use client';

import { useState } from 'react';
import { PageHeader } from '@/components/layout/page-header';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { ErrorState, InlineNote, LoadingPanel } from '@/components/ui/feedback';
import { TBody, TD, TH, THead, TR, Table } from '@/components/ui/table';
import { useAction, useAsync } from '@/hooks/use-async';
import { api } from '@/lib/api';
import { formatCost } from '@/lib/format';
import { cn } from '@/lib/utils';
import type { TestConnectionResponse } from '@/types';

export default function ModelsPage() {
  const models = useAsync(() => api.models(true), []);
  const [probes, setProbes] = useState<Record<string, TestConnectionResponse>>({});
  const [probing, setProbing] = useState<string | null>(null);

  const test = useAction(async (provider: string, model?: string) => {
    const key = model ? `${provider}:${model}` : provider;
    setProbing(key);
    try {
      const response = await api.testConnection(provider, model);
      setProbes((current) => ({ ...current, [key]: response }));
      return response;
    } finally {
      setProbing(null);
    }
  });

  return (
    <>
      <PageHeader
        title="Models"
        description="Providers PromptBench can reach, the models they serve, and their configured pricing."
        actions={
          <Button onClick={models.reload} loading={models.loading}>
            <span aria-hidden="true">↻</span> Refresh
          </Button>
        }
      />

      <InlineNote>
        API keys are read from backend environment variables and are never sent to the browser. This
        page shows only whether a credential is present.
      </InlineNote>

      {models.error && <ErrorState message={models.error} onRetry={models.reload} />}
      {test.error && <ErrorState title="Connection test failed" message={test.error} />}

      {models.loading && !models.data ? (
        <LoadingPanel rows={8} />
      ) : (
        <div className="space-y-4">
          {models.data?.providers.map((provider) => {
            const probe = probes[provider.id];
            return (
              <Card key={provider.id}>
                <CardHeader>
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <CardTitle>{provider.label}</CardTitle>
                      <Badge tone={provider.available ? 'ok' : 'muted'}>
                        <span aria-hidden="true">{provider.available ? '✓' : '○'}</span>
                        {provider.available ? 'Available' : 'Unavailable'}
                      </Badge>
                      {provider.is_local && <Badge tone="accent">Local · no API key</Badge>}
                      {provider.configured && !provider.is_local && (
                        <Badge tone="neutral">Credential present</Badge>
                      )}
                    </div>
                    <p className="mt-1 text-xs text-fg-muted">
                      {probe?.detail ?? provider.status_detail}
                    </p>
                    {provider.api_key_env && !provider.configured && (
                      <p className="mt-1 font-mono text-xs text-fg-subtle">
                        Set {provider.api_key_env} in your .env to enable this provider.
                      </p>
                    )}
                  </div>
                  <Button
                    size="sm"
                    loading={probing === provider.id}
                    onClick={() => void test.run(provider.id)}
                  >
                    Test connection
                  </Button>
                </CardHeader>

                <CardContent className="p-0">
                  {provider.models.length === 0 ? (
                    <p className="px-4 py-4 text-xs text-fg-subtle">
                      {provider.is_local
                        ? 'No local models found. Pull one with `ollama pull llama3.2`, then refresh.'
                        : 'No models listed for this provider.'}
                    </p>
                  ) : (
                    <Table>
                      <THead>
                        <TR>
                          <TH>Model</TH>
                          <TH>Context</TH>
                          <TH numeric>Input / 1M</TH>
                          <TH numeric>Output / 1M</TH>
                          <TH>Status</TH>
                          <TH>
                            <span className="sr-only">Actions</span>
                          </TH>
                        </TR>
                      </THead>
                      <TBody>
                        {provider.models.map((model) => {
                          const key = `${provider.id}:${model.id}`;
                          const modelProbe = probes[key];
                          return (
                            <TR key={model.id}>
                              <TD>
                                <span className="font-mono text-xs text-fg">{model.id}</span>
                                {model.description && (
                                  <p className="mt-0.5 text-[11px] text-fg-subtle">
                                    {model.description}
                                  </p>
                                )}
                              </TD>
                              <TD className="text-xs text-fg-muted">
                                {model.context_window
                                  ? `${(model.context_window / 1000).toFixed(0)}K`
                                  : '—'}
                              </TD>
                              <TD numeric className="text-xs">
                                {model.pricing ? (
                                  `$${model.pricing.input_per_1m.toFixed(2)}`
                                ) : (
                                  <span className="text-fg-subtle">Pricing unavailable</span>
                                )}
                              </TD>
                              <TD numeric className="text-xs">
                                {model.pricing ? `$${model.pricing.output_per_1m.toFixed(2)}` : '—'}
                              </TD>
                              <TD>
                                {modelProbe ? (
                                  <Badge tone={modelProbe.generation_ok ? 'ok' : 'danger'}>
                                    {modelProbe.generation_ok
                                      ? `OK · ${modelProbe.latency_ms ?? 0} ms`
                                      : 'Failed'}
                                  </Badge>
                                ) : (
                                  <Badge tone={model.available ? 'neutral' : 'muted'}>
                                    {model.available ? 'Ready' : 'Unavailable'}
                                  </Badge>
                                )}
                              </TD>
                              <TD>
                                <div className="flex justify-end">
                                  <Button
                                    size="sm"
                                    variant="ghost"
                                    disabled={!provider.available}
                                    loading={probing === key}
                                    onClick={() => void test.run(provider.id, model.id)}
                                  >
                                    Test
                                  </Button>
                                </div>
                              </TD>
                            </TR>
                          );
                        })}
                      </TBody>
                    </Table>
                  )}
                  {probes[provider.id]?.available === false && (
                    <p className={cn('border-t border-line px-4 py-2 text-xs', 'text-[#f18e8e]')}>
                      {probes[provider.id]?.detail}
                    </p>
                  )}
                </CardContent>
              </Card>
            );
          })}

          {models.data && (
            <Card>
              <CardHeader>
                <CardTitle>Pricing source</CardTitle>
              </CardHeader>
              <CardContent className="space-y-1.5 text-xs text-fg-muted">
                <p>{models.data.pricing.disclaimer}</p>
                <p>
                  Table dated <span className="font-mono text-fg">{models.data.pricing.as_of}</span>
                  , in {models.data.pricing.currency} {models.data.pricing.unit.replace(/_/g, ' ')}.
                </p>
                <ul className="mt-2 space-y-0.5">
                  {Object.entries(models.data.pricing.sources).map(([provider, source]) => (
                    <li key={provider}>
                      <span className="text-fg-subtle">{provider}:</span>{' '}
                      <span className="font-mono">{source}</span>
                    </li>
                  ))}
                </ul>
                <p className="pt-1 text-fg-subtle">
                  A model with no entry shows “{formatCost(null)}” rather than a guessed number.
                </p>
              </CardContent>
            </Card>
          )}
        </div>
      )}
    </>
  );
}
