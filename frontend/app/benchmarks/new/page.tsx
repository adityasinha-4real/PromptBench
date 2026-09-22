'use client';

import { useRouter } from 'next/navigation';
import { useEffect, useMemo, useRef, useState } from 'react';
import { ModelPicker } from '@/components/benchmark/model-picker';
import { PageHeader } from '@/components/layout/page-header';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { ErrorState, InlineNote, LoadingPanel } from '@/components/ui/feedback';
import { Checkbox, Field, Input, Select, Slider, Textarea } from '@/components/ui/input';
import { useToast } from '@/components/ui/toast';
import { useAction, useAsync } from '@/hooks/use-async';
import { api } from '@/lib/api';
import { evaluationModeLabel } from '@/lib/format';
import type { BenchmarkCreatePayload, EvaluationMode, ModelSelection } from '@/types';

interface VariantDraft {
  id: string;
  name: string;
  prompt: string;
}

const EXAMPLE_PROMPT = 'Explain why TCP uses a three-way handshake.';

export default function NewBenchmarkPage() {
  const router = useRouter();
  const { toast } = useToast();

  const models = useAsync(() => api.models(true), []);
  const modes = useAsync(() => api.evaluationModes(), []);
  const settings = useAsync(() => api.settings(), []);

  const [name, setName] = useState('');
  const [prompt, setPrompt] = useState('');
  const [systemPrompt, setSystemPrompt] = useState('');
  const [temperature, setTemperature] = useState(0.7);
  const [maxTokens, setMaxTokens] = useState(1024);
  const [selected, setSelected] = useState<ModelSelection[]>([]);
  const [evaluationMode, setEvaluationMode] = useState<EvaluationMode>('heuristic');
  const [judgeProvider, setJudgeProvider] = useState('');
  const [judgeModel, setJudgeModel] = useState('');
  const [tags, setTags] = useState('');
  const [variants, setVariants] = useState<VariantDraft[]>([]);
  const [runNow, setRunNow] = useState(true);
  const [touched, setTouched] = useState(false);

  // Start from the server's EVALUATION_DEFAULT_MODE and JUDGE_PROVIDER /
  // JUDGE_MODEL — once, and never over a choice the user has already made.
  const defaultsApplied = useRef(false);
  const evaluationTouched = useRef(false);
  useEffect(() => {
    const evaluation = settings.data?.evaluation;
    if (!evaluation || defaultsApplied.current) return;
    defaultsApplied.current = true;
    if (evaluationTouched.current) return;
    setEvaluationMode(evaluation.default_mode);
    if (evaluation.judge_provider && evaluation.judge_model) {
      setJudgeProvider(evaluation.judge_provider);
      setJudgeModel(evaluation.judge_model);
    }
  }, [settings.data]);

  const limits = settings.data?.limits;
  const maxModels = limits?.max_models_per_benchmark ?? 12;
  const maxVariants = limits?.max_variants_per_benchmark ?? 10;
  const maxPromptChars = limits?.max_prompt_chars ?? 32000;
  const maxOutputTokens = limits?.max_output_tokens ?? 8192;

  const availableProviders = useMemo(
    () => models.data?.providers.filter((p) => p.available) ?? [],
    [models.data]
  );

  const errors = useMemo(() => {
    const found: Record<string, string> = {};
    if (!name.trim()) found.name = 'Give the benchmark a name so you can find it later.';
    if (!prompt.trim()) found.prompt = 'A prompt is required.';
    else if (prompt.length > maxPromptChars)
      found.prompt = `Prompt is ${prompt.length} characters; the limit is ${maxPromptChars}.`;
    if (selected.length === 0) found.models = 'Select at least one model.';
    if (maxTokens < 1 || maxTokens > maxOutputTokens)
      found.maxTokens = `Must be between 1 and ${maxOutputTokens}.`;
    if (evaluationMode === 'llm_judge' && (!judgeProvider || !judgeModel))
      found.judge = 'LLM-judge mode needs a judge provider and model.';
    variants.forEach((variant) => {
      if (!variant.name.trim() || !variant.prompt.trim())
        found.variants = 'Every prompt variant needs a name and a prompt.';
    });
    return found;
  }, [
    name,
    prompt,
    selected,
    maxTokens,
    evaluationMode,
    judgeProvider,
    judgeModel,
    variants,
    maxPromptChars,
    maxOutputTokens,
  ]);

  const valid = Object.keys(errors).length === 0;

  const submit = useAction(async () => {
    const payload: BenchmarkCreatePayload = {
      name: name.trim(),
      prompt: prompt.trim(),
      system_prompt: systemPrompt.trim() || null,
      temperature,
      max_tokens: maxTokens,
      evaluation_enabled: evaluationMode !== 'disabled',
      evaluation_mode: evaluationMode,
      judge_provider: evaluationMode === 'llm_judge' ? judgeProvider : null,
      judge_model: evaluationMode === 'llm_judge' ? judgeModel : null,
      models: selected,
      variants: variants.map((variant) => ({
        name: variant.name.trim(),
        prompt: variant.prompt.trim(),
      })),
      tags: tags
        .split(',')
        .map((tag) => tag.trim())
        .filter(Boolean),
      run_immediately: false,
    };

    const created = await api.createBenchmark(payload);
    if (runNow) {
      const progress = await api.runBenchmark(created.id);
      router.push(`/benchmarks/${created.id}?run=${progress.run_id}`);
    } else {
      toast(`Benchmark "${created.name}" saved.`, 'success');
      router.push(`/benchmarks/${created.id}`);
    }
    return created;
  });

  const handleSubmit = (event: React.FormEvent) => {
    event.preventDefault();
    setTouched(true);
    if (!valid) return;
    void submit.run();
  };

  const judgeProviderOptions = availableProviders;
  const judgeModelOptions = judgeProviderOptions.find((p) => p.id === judgeProvider)?.models ?? [];
  // A configured judge may be down or not listed (e.g. an Ollama model that
  // was never pulled). Show it rather than letting the select read "Select…".
  const judgeProviderMissing =
    judgeProvider !== '' && !judgeProviderOptions.some((p) => p.id === judgeProvider);
  const judgeModelMissing =
    judgeModel !== '' && !judgeModelOptions.some((m) => m.id === judgeModel);

  const totalExecutions = selected.length * Math.max(variants.length, 1);

  return (
    <form onSubmit={handleSubmit} noValidate>
      <PageHeader
        title="New benchmark"
        description="One prompt, many models. Results are saved so you can compare and re-run later."
        actions={
          <>
            <Button type="button" variant="ghost" onClick={() => router.back()}>
              Cancel
            </Button>
            <Button type="submit" variant="primary" loading={submit.pending}>
              {runNow ? 'Save & run benchmark' : 'Save benchmark'}
            </Button>
          </>
        }
      />

      {submit.error && (
        <ErrorState
          title="Could not create the benchmark"
          message={submit.error}
          className="mt-4"
        />
      )}

      <div className="mt-4 grid gap-4 xl:grid-cols-[1.3fr_1fr]">
        {/* ---------------- Prompt ---------------- */}
        <div className="space-y-4">
          <Card>
            <CardHeader>
              <CardTitle>Prompt</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <Field
                label="Benchmark name"
                required
                error={touched ? errors.name : null}
                hint="For example: “TCP handshake explanation”."
              >
                <Input
                  value={name}
                  onChange={(event) => setName(event.target.value)}
                  placeholder="TCP handshake explanation"
                  maxLength={200}
                  aria-invalid={touched && Boolean(errors.name)}
                />
              </Field>

              <Field
                label="Prompt"
                required
                error={touched ? errors.prompt : null}
                hint={`${prompt.length.toLocaleString()} / ${maxPromptChars.toLocaleString()} characters`}
              >
                <Textarea
                  value={prompt}
                  onChange={(event) => setPrompt(event.target.value)}
                  rows={8}
                  placeholder={EXAMPLE_PROMPT}
                  aria-invalid={touched && Boolean(errors.prompt)}
                />
              </Field>

              {!prompt && (
                <Button
                  type="button"
                  size="sm"
                  variant="ghost"
                  onClick={() => {
                    setPrompt(EXAMPLE_PROMPT);
                    if (!name) setName('TCP handshake explanation');
                  }}
                >
                  Use the example prompt
                </Button>
              )}

              <Field label="System prompt" hint="Optional. Sent to every model that supports one.">
                <Textarea
                  value={systemPrompt}
                  onChange={(event) => setSystemPrompt(event.target.value)}
                  rows={3}
                  placeholder="You are a concise systems engineer."
                />
              </Field>

              <Field label="Tags" hint="Comma separated, used for filtering in history.">
                <Input
                  value={tags}
                  onChange={(event) => setTags(event.target.value)}
                  placeholder="networking, docs"
                />
              </Field>
            </CardContent>
          </Card>

          {/* ---------------- Variants ---------------- */}
          <Card>
            <CardHeader>
              <div>
                <CardTitle>Prompt variants</CardTitle>
                <p className="mt-0.5 text-xs text-fg-subtle">
                  Optional. Each variant runs against every selected model, producing a model ×
                  variant matrix.
                </p>
              </div>
              <Button
                type="button"
                size="sm"
                disabled={variants.length >= maxVariants}
                onClick={() =>
                  setVariants((current) => [
                    ...current,
                    {
                      id: `v${Date.now()}`,
                      name: `Variant ${String.fromCharCode(65 + current.length)}`,
                      prompt: '',
                    },
                  ])
                }
              >
                Add variant
              </Button>
            </CardHeader>
            <CardContent className="space-y-3">
              {variants.length === 0 ? (
                <InlineNote>With no variants the base prompt above runs once per model.</InlineNote>
              ) : (
                variants.map((variant, index) => (
                  <div key={variant.id} className="space-y-2 rounded-md border border-line p-3">
                    <div className="flex items-center gap-2">
                      <Input
                        value={variant.name}
                        onChange={(event) =>
                          setVariants((current) =>
                            current.map((item) =>
                              item.id === variant.id ? { ...item, name: event.target.value } : item
                            )
                          )
                        }
                        className="h-8 max-w-[220px] text-xs"
                        aria-label={`Variant ${index + 1} name`}
                        maxLength={120}
                      />
                      <Button
                        type="button"
                        size="sm"
                        variant="ghost"
                        className="ml-auto"
                        onClick={() =>
                          setVariants((current) => current.filter((item) => item.id !== variant.id))
                        }
                      >
                        Remove
                      </Button>
                    </div>
                    <Textarea
                      value={variant.prompt}
                      onChange={(event) =>
                        setVariants((current) =>
                          current.map((item) =>
                            item.id === variant.id ? { ...item, prompt: event.target.value } : item
                          )
                        )
                      }
                      rows={3}
                      placeholder="Explain TCP to a beginner using an analogy."
                      aria-label={`Variant ${index + 1} prompt`}
                    />
                  </div>
                ))
              )}
              {touched && errors.variants && (
                <p className="text-xs text-[#f18e8e]" role="alert">
                  {errors.variants}
                </p>
              )}
            </CardContent>
          </Card>
        </div>

        {/* ---------------- Configuration ---------------- */}
        <div className="space-y-4">
          <Card>
            <CardHeader>
              <CardTitle>Models</CardTitle>
              {touched && errors.models && (
                <span className="text-xs text-[#f18e8e]">{errors.models}</span>
              )}
            </CardHeader>
            <CardContent>
              {models.loading && !models.data ? (
                <LoadingPanel rows={5} />
              ) : models.error ? (
                <ErrorState message={models.error} onRetry={models.reload} />
              ) : (
                <ModelPicker
                  providers={models.data?.providers ?? []}
                  selected={selected}
                  onChange={setSelected}
                  max={maxModels}
                  disabled={submit.pending}
                />
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Generation parameters</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <Field
                label="Temperature"
                hint="0 is deterministic; higher values increase variation."
              >
                <Slider
                  min={0}
                  max={2}
                  step={0.1}
                  value={temperature}
                  displayValue={temperature.toFixed(1)}
                  onChange={(event) => setTemperature(Number(event.target.value))}
                />
              </Field>

              <Field
                label="Max output tokens"
                error={touched ? errors.maxTokens : null}
                hint={`Upper bound: ${maxOutputTokens.toLocaleString()}.`}
              >
                <Input
                  type="number"
                  min={1}
                  max={maxOutputTokens}
                  value={maxTokens}
                  onChange={(event) => setMaxTokens(Number(event.target.value))}
                  aria-invalid={touched && Boolean(errors.maxTokens)}
                />
              </Field>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Evaluation</CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              <Field label="Mode" error={touched ? errors.judge : null}>
                <Select
                  value={evaluationMode}
                  onChange={(event) => {
                    evaluationTouched.current = true;
                    setEvaluationMode(event.target.value as EvaluationMode);
                  }}
                >
                  {(modes.data?.modes ?? []).map((mode) => (
                    <option key={mode.id} value={mode.id}>
                      {mode.label}
                    </option>
                  ))}
                  {!modes.data && (
                    <option value={evaluationMode}>{evaluationModeLabel(evaluationMode)}</option>
                  )}
                </Select>
              </Field>

              <p className="text-xs text-fg-subtle">
                {modes.data?.modes.find((mode) => mode.id === evaluationMode)?.description ??
                  'Scores each response on relevance, correctness, conciseness and clarity.'}
              </p>

              {evaluationMode === 'llm_judge' && (
                <div className="grid gap-3 sm:grid-cols-2">
                  <Field label="Judge provider" required>
                    <Select
                      value={judgeProvider}
                      onChange={(event) => {
                        evaluationTouched.current = true;
                        setJudgeProvider(event.target.value);
                        setJudgeModel('');
                      }}
                    >
                      <option value="">Select…</option>
                      {judgeProviderMissing && (
                        <option value={judgeProvider}>{judgeProvider} (unavailable)</option>
                      )}
                      {judgeProviderOptions.map((provider) => (
                        <option key={provider.id} value={provider.id}>
                          {provider.label}
                        </option>
                      ))}
                    </Select>
                  </Field>
                  <Field label="Judge model" required>
                    <Select
                      value={judgeModel}
                      onChange={(event) => {
                        evaluationTouched.current = true;
                        setJudgeModel(event.target.value);
                      }}
                      disabled={!judgeProvider}
                    >
                      <option value="">Select…</option>
                      {judgeModelMissing && <option value={judgeModel}>{judgeModel}</option>}
                      {judgeModelOptions.map((model) => (
                        <option key={model.id} value={model.id}>
                          {model.id}
                        </option>
                      ))}
                    </Select>
                  </Field>
                </div>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardContent className="space-y-3">
              <Checkbox
                label="Run immediately after saving"
                description="Models execute concurrently; you can watch progress per model."
                checked={runNow}
                onChange={(event) => setRunNow(event.target.checked)}
              />
              <div className="rounded-md border border-line bg-surface-2 px-3 py-2 text-xs text-fg-muted">
                This run will make{' '}
                <span className="tabular font-medium text-fg">{totalExecutions}</span> model call
                {totalExecutions === 1 ? '' : 's'}
                {variants.length > 0 &&
                  ` (${selected.length} model${selected.length === 1 ? '' : 's'} × ${variants.length} variant${variants.length === 1 ? '' : 's'})`}
                .
              </div>
            </CardContent>
          </Card>
        </div>
      </div>
    </form>
  );
}
