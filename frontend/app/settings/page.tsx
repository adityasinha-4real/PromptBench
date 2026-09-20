'use client';

import { PageHeader } from '@/components/layout/page-header';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { ErrorState, InlineNote, LoadingPanel } from '@/components/ui/feedback';
import { CopyButton } from '@/components/ui/misc';
import { TBody, TD, TH, THead, TR, Table } from '@/components/ui/table';
import { useToast } from '@/components/ui/toast';
import { useAction, useAsync } from '@/hooks/use-async';
import { api } from '@/lib/api';

const ENV_TEMPLATE = `# Provider credentials — leave blank to run without that provider.
OPENAI_API_KEY=
ANTHROPIC_API_KEY=
GEMINI_API_KEY=

# Ollama needs no key; point this at your local daemon.
OLLAMA_BASE_URL=http://localhost:11434`;

export default function SettingsPage() {
  const { toast } = useToast();
  const settings = useAsync(() => api.settings(), []);

  const reload = useAction(async () => {
    const response = await api.reloadPricing();
    toast(`Pricing reloaded — ${response.models_priced} models priced.`, 'success');
    settings.reload();
  });

  if (settings.loading && !settings.data) return <LoadingPanel rows={10} />;
  if (settings.error || !settings.data) {
    return (
      <ErrorState
        title="Could not load settings"
        message={settings.error ?? 'No data.'}
        onRetry={settings.reload}
      />
    );
  }

  const data = settings.data;

  return (
    <>
      <PageHeader
        title="Settings"
        description="Effective backend configuration. Credentials are read from environment variables and are never returned to the browser."
      />

      {/* ---------------- Providers ---------------- */}
      <Card>
        <CardHeader>
          <div>
            <CardTitle>Provider configuration</CardTitle>
            <p className="mt-0.5 text-xs text-fg-subtle">
              PromptBench reports only whether each variable is set, never its value.
            </p>
          </div>
        </CardHeader>
        <CardContent className="p-0">
          <Table>
            <THead>
              <TR>
                <TH>Provider</TH>
                <TH>Environment variable</TH>
                <TH>Credential</TH>
                <TH>Base URL</TH>
              </TR>
            </THead>
            <TBody>
              {data.providers.map((provider) => (
                <TR key={provider.id}>
                  <TD>
                    <span className="text-fg">{provider.label}</span>
                    {provider.is_local && (
                      <Badge tone="accent" className="ml-2">
                        Local
                      </Badge>
                    )}
                  </TD>
                  <TD className="font-mono text-xs text-fg-muted">
                    {provider.api_key_env ?? <span className="text-fg-subtle">none required</span>}
                  </TD>
                  <TD>
                    {provider.is_local ? (
                      <Badge tone="ok">Not required</Badge>
                    ) : provider.credential_present ? (
                      <Badge tone="ok">
                        <span aria-hidden="true">✓</span> Set
                      </Badge>
                    ) : (
                      <Badge tone="muted">
                        <span aria-hidden="true">○</span> Not set
                      </Badge>
                    )}
                  </TD>
                  <TD className="font-mono text-xs text-fg-subtle">{provider.base_url ?? '—'}</TD>
                </TR>
              ))}
            </TBody>
          </Table>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Setting API keys</CardTitle>
          <CopyButton value={ENV_TEMPLATE} label="Copy template" />
        </CardHeader>
        <CardContent className="space-y-3">
          <p className="text-xs text-fg-muted">
            Add the keys to <span className="font-mono text-fg">.env</span> in the project root and
            restart the backend. Keys are never written to the database and never leave the server.
          </p>
          <pre className="overflow-x-auto rounded border border-line bg-bg p-3 font-mono text-xs leading-relaxed text-fg-muted">
            {ENV_TEMPLATE}
          </pre>
          <InlineNote>
            PromptBench runs with none of these set — Ollama covers local models for free, and any
            provider without a credential simply shows as unavailable.
          </InlineNote>
        </CardContent>
      </Card>

      {/* ---------------- Evaluation ---------------- */}
      <Card>
        <CardHeader>
          <div>
            <CardTitle>Evaluation</CardTitle>
            <p className="mt-0.5 text-xs text-fg-subtle">
              Default mode: <span className="font-mono">{data.evaluation.default_mode}</span>
              {data.evaluation.judge_model &&
                ` · default judge ${data.evaluation.judge_provider}:${data.evaluation.judge_model}`}
            </p>
          </div>
        </CardHeader>
        <CardContent className="space-y-2">
          {data.evaluation.modes.map((mode) => (
            <div key={mode.id} className="rounded-md border border-line px-3 py-2">
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-sm text-fg">{mode.label}</span>
                <span className="font-mono text-[11px] text-fg-subtle">{mode.id}</span>
                {mode.requires_credentials ? (
                  <Badge tone="warn">Needs a configured provider</Badge>
                ) : (
                  <Badge tone="ok">Works offline</Badge>
                )}
              </div>
              <p className="mt-1 text-xs text-fg-muted">{mode.description}</p>
            </div>
          ))}
        </CardContent>
      </Card>

      {/* ---------------- Pricing ---------------- */}
      <Card>
        <CardHeader>
          <div>
            <CardTitle>Pricing configuration</CardTitle>
            <p className="mt-0.5 text-xs text-fg-subtle">
              {data.pricing.models_priced} models priced · table dated{' '}
              <span className="font-mono">{data.pricing.as_of}</span>
            </p>
          </div>
          <Button size="sm" loading={reload.pending} onClick={() => void reload.run()}>
            Reload from disk
          </Button>
        </CardHeader>
        <CardContent className="space-y-3">
          <InlineNote>{data.pricing.disclaimer}</InlineNote>
          <p className="text-xs text-fg-muted">
            Edit <span className="font-mono text-fg">{data.pricing.file}</span> to use your own
            negotiated rates, then reload — no restart required. A model that is absent renders as
            “Pricing unavailable” rather than as free.
          </p>
          {reload.error && <ErrorState message={reload.error} />}

          <div className="overflow-hidden rounded border border-line">
            <Table>
              <THead>
                <TR>
                  <TH>Provider</TH>
                  <TH>Model</TH>
                  <TH numeric>Input / 1M</TH>
                  <TH numeric>Output / 1M</TH>
                  <TH>Note</TH>
                </TR>
              </THead>
              <TBody>
                {Object.entries(data.pricing.table).flatMap(([provider, models]) =>
                  Object.entries(models).map(([model, price]) => (
                    <TR key={`${provider}:${model}`}>
                      <TD className="text-xs text-fg-muted">{provider}</TD>
                      <TD className="font-mono text-xs">{model}</TD>
                      <TD numeric className="text-xs">
                        ${price.input_per_1m.toFixed(2)}
                      </TD>
                      <TD numeric className="text-xs">
                        ${price.output_per_1m.toFixed(2)}
                      </TD>
                      <TD className="text-xs text-fg-subtle">{price.note ?? '—'}</TD>
                    </TR>
                  ))
                )}
              </TBody>
            </Table>
          </div>
        </CardContent>
      </Card>

      {/* ---------------- Application ---------------- */}
      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>Application</CardTitle>
          </CardHeader>
          <CardContent className="space-y-1.5 text-xs">
            <Row label="Environment" value={data.application.environment} />
            <Row label="Debug" value={String(data.application.debug)} />
            <Row label="Database" value={data.application.database_backend} />
            <Row label="Allowed origins" value={data.application.cors_origins.join(', ')} />
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Limits</CardTitle>
            <p className="mt-0.5 text-xs text-fg-subtle">Set via environment variables.</p>
          </CardHeader>
          <CardContent className="space-y-1.5 text-xs">
            {Object.entries(data.limits).map(([key, value]) => (
              <Row key={key} label={key.replace(/_/g, ' ')} value={String(value)} />
            ))}
          </CardContent>
        </Card>
      </div>
    </>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-baseline justify-between gap-3 border-b border-line pb-1.5 last:border-0">
      <span className="text-fg-subtle">{label}</span>
      <span className="text-right font-mono text-fg">{value}</span>
    </div>
  );
}
