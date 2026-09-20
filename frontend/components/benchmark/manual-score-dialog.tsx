'use client';

import { useEffect, useState } from 'react';
import { Button } from '@/components/ui/button';
import { ErrorState } from '@/components/ui/feedback';
import { Field, Input, Slider, Textarea } from '@/components/ui/input';
import { useAction } from '@/hooks/use-async';
import { api } from '@/lib/api';
import type { ModelResult } from '@/types';

const CRITERIA = ['relevance', 'correctness', 'conciseness', 'clarity'] as const;
type Criterion = (typeof CRITERIA)[number];

export function ManualScoreDialog({
  result,
  onClose,
  onSaved,
}: {
  result: ModelResult | null;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [scores, setScores] = useState<Record<Criterion, number>>({
    relevance: 5,
    correctness: 5,
    conciseness: 5,
    clarity: 5,
  });
  const [reasoning, setReasoning] = useState('');
  const [reviewer, setReviewer] = useState('');

  useEffect(() => {
    if (!result) return;
    const existing = result.evaluation;
    setScores({
      relevance: existing?.relevance ?? 5,
      correctness: existing?.correctness ?? 5,
      conciseness: existing?.conciseness ?? 5,
      clarity: existing?.clarity ?? 5,
    });
    setReasoning(existing?.reasoning ?? '');
  }, [result]);

  const save = useAction(async () => {
    if (!result) return;
    await api.evaluateResult(result.id, 'manual', {
      scores: { ...scores, reasoning: reasoning.trim() || null },
      reviewer: reviewer.trim() || undefined,
    });
    onSaved();
    onClose();
  });

  useEffect(() => {
    if (!result) return;
    const handler = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [result, onClose]);

  if (!result) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4"
      role="dialog"
      aria-modal="true"
      aria-label="Score this response manually"
      onClick={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <div className="panel max-h-[90vh] w-full max-w-lg overflow-y-auto">
        <header className="flex items-start justify-between gap-3 border-b border-line px-4 py-3">
          <div className="min-w-0">
            <h2 className="text-sm font-semibold text-fg">Manual score</h2>
            <p className="truncate font-mono text-xs text-fg-subtle">
              {result.provider} / {result.model}
            </p>
          </div>
          <Button size="icon" variant="ghost" onClick={onClose} aria-label="Close">
            ×
          </Button>
        </header>

        <div className="space-y-4 p-4">
          {save.error && <ErrorState message={save.error} />}

          {CRITERIA.map((criterion) => (
            <Field key={criterion} label={criterion[0]!.toUpperCase() + criterion.slice(1)}>
              <Slider
                min={0}
                max={10}
                step={0.5}
                value={scores[criterion]}
                displayValue={scores[criterion].toFixed(1)}
                onChange={(event) =>
                  setScores((current) => ({ ...current, [criterion]: Number(event.target.value) }))
                }
              />
            </Field>
          ))}

          <Field label="Notes" hint="Optional. Stored alongside the score.">
            <Textarea
              value={reasoning}
              onChange={(event) => setReasoning(event.target.value)}
              rows={3}
              maxLength={4000}
              placeholder="Accurate, but buries the answer in the third paragraph."
            />
          </Field>

          <Field label="Reviewer" hint="Optional. Recorded as the evaluator.">
            <Input
              value={reviewer}
              onChange={(event) => setReviewer(event.target.value)}
              maxLength={80}
              placeholder="your-name"
            />
          </Field>
        </div>

        <footer className="flex justify-end gap-2 border-t border-line px-4 py-3">
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button variant="primary" loading={save.pending} onClick={() => void save.run()}>
            Save score
          </Button>
        </footer>
      </div>
    </div>
  );
}
