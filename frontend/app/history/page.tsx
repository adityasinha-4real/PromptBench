'use client';

import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useEffect, useMemo, useState } from 'react';
import { PageHeader } from '@/components/layout/page-header';
import { Badge, StatusBadge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { EmptyState, ErrorState, LoadingPanel } from '@/components/ui/feedback';
import { Input, Select } from '@/components/ui/input';
import { ConfirmButton } from '@/components/ui/misc';
import { TBody, TD, TH, THead, TR, Table } from '@/components/ui/table';
import { useToast } from '@/components/ui/toast';
import { useAction, useAsync } from '@/hooks/use-async';
import { api } from '@/lib/api';
import { formatCost, formatRelative, formatScore, evaluationModeLabel } from '@/lib/format';

const PAGE_SIZE = 20;

export default function HistoryPage() {
  const router = useRouter();
  const { toast } = useToast();

  const [searchInput, setSearchInput] = useState('');
  const [search, setSearch] = useState('');
  const [provider, setProvider] = useState('');
  const [status, setStatus] = useState('');
  const [sort, setSort] = useState<'created_at' | 'name'>('created_at');
  const [order, setOrder] = useState<'asc' | 'desc'>('desc');
  const [offset, setOffset] = useState(0);

  // Debounce so typing does not fire a request per keystroke.
  useEffect(() => {
    const timer = setTimeout(() => {
      setSearch(searchInput.trim());
      setOffset(0);
    }, 300);
    return () => clearTimeout(timer);
  }, [searchInput]);

  const providers = useAsync(() => api.models(false), []);

  const list = useAsync(
    () =>
      api.listBenchmarks({
        search: search || undefined,
        provider: provider || undefined,
        status: status || undefined,
        sort,
        order,
        limit: PAGE_SIZE,
        offset,
      }),
    [search, provider, status, sort, order, offset]
  );

  const remove = useAction(async (id: number) => {
    await api.deleteBenchmark(id);
    toast('Benchmark deleted.', 'info');
    list.reload();
  });

  const rerun = useAction(async (id: number) => {
    const started = await api.rerunBenchmark(id);
    router.push(`/benchmarks/${id}?run=${started.run_id}`);
  });

  const total = list.data?.total ?? 0;
  const items = useMemo(() => list.data?.items ?? [], [list.data]);
  const showingTo = Math.min(offset + PAGE_SIZE, total);
  const filtered = Boolean(search || provider || status);

  return (
    <>
      <PageHeader
        title="History"
        description="Every saved benchmark, with the results of its most recent run."
        actions={
          <Link href="/benchmarks/new">
            <Button variant="primary">
              <span aria-hidden="true">＋</span> New Benchmark
            </Button>
          </Link>
        }
      />

      <section className="flex flex-wrap items-end gap-2" aria-label="Filters">
        <div className="min-w-[220px] flex-1">
          <label htmlFor="search" className="label-caps mb-1 block">
            Search
          </label>
          <Input
            id="search"
            value={searchInput}
            onChange={(event) => setSearchInput(event.target.value)}
            placeholder="Name, prompt or description…"
            type="search"
          />
        </div>

        <div>
          <label htmlFor="provider" className="label-caps mb-1 block">
            Provider
          </label>
          <Select
            id="provider"
            value={provider}
            onChange={(event) => {
              setProvider(event.target.value);
              setOffset(0);
            }}
            className="w-40"
          >
            <option value="">All providers</option>
            {providers.data?.providers.map((item) => (
              <option key={item.id} value={item.id}>
                {item.label}
              </option>
            ))}
          </Select>
        </div>

        <div>
          <label htmlFor="status" className="label-caps mb-1 block">
            Run status
          </label>
          <Select
            id="status"
            value={status}
            onChange={(event) => {
              setStatus(event.target.value);
              setOffset(0);
            }}
            className="w-36"
          >
            <option value="">Any status</option>
            <option value="completed">Completed</option>
            <option value="failed">Failed</option>
            <option value="cancelled">Cancelled</option>
            <option value="running">Running</option>
          </Select>
        </div>

        <div>
          <label htmlFor="sort" className="label-caps mb-1 block">
            Sort
          </label>
          <Select
            id="sort"
            value={`${sort}:${order}`}
            onChange={(event) => {
              const [nextSort, nextOrder] = event.target.value.split(':');
              setSort(nextSort as 'created_at' | 'name');
              setOrder(nextOrder as 'asc' | 'desc');
              setOffset(0);
            }}
            className="w-44"
          >
            <option value="created_at:desc">Newest first</option>
            <option value="created_at:asc">Oldest first</option>
            <option value="name:asc">Name A–Z</option>
            <option value="name:desc">Name Z–A</option>
          </Select>
        </div>

        {filtered && (
          <Button
            variant="ghost"
            onClick={() => {
              setSearchInput('');
              setProvider('');
              setStatus('');
              setOffset(0);
            }}
          >
            Clear filters
          </Button>
        )}
      </section>

      {list.error && <ErrorState message={list.error} onRetry={list.reload} />}
      {remove.error && <ErrorState title="Could not delete" message={remove.error} />}
      {rerun.error && <ErrorState title="Could not re-run" message={rerun.error} />}

      {list.loading && !list.data ? (
        <LoadingPanel rows={8} />
      ) : items.length === 0 ? (
        <EmptyState
          title={filtered ? 'No benchmarks match those filters' : 'No benchmarks yet'}
          description={
            filtered
              ? 'Try a different search term or clear the filters.'
              : 'Create a benchmark to start comparing models on the same prompt.'
          }
          action={
            filtered ? null : (
              <Link href="/benchmarks/new">
                <Button variant="primary" size="sm">
                  New Benchmark
                </Button>
              </Link>
            )
          }
        />
      ) : (
        <>
          <div className="panel">
            <Table>
              <THead>
                <TR>
                  <TH>Benchmark</TH>
                  <TH>Tags</TH>
                  <TH numeric>Models</TH>
                  <TH numeric>Runs</TH>
                  <TH numeric>Quality</TH>
                  <TH numeric>Cost</TH>
                  <TH>Last run</TH>
                  <TH>
                    <span className="sr-only">Actions</span>
                  </TH>
                </TR>
              </THead>
              <TBody>
                {items.map((item) => (
                  <TR key={item.id}>
                    <TD>
                      <Link
                        href={`/benchmarks/${item.id}`}
                        className="font-medium text-fg hover:text-accent"
                      >
                        {item.name}
                      </Link>
                      <p className="mt-0.5 line-clamp-1 max-w-md text-xs text-fg-subtle">
                        {item.prompt_excerpt}
                      </p>
                      <p className="mt-0.5 text-[11px] text-fg-subtle">
                        {evaluationModeLabel(item.evaluation_mode)}
                        {item.variant_count > 0 && ` · ${item.variant_count} variants`}
                      </p>
                    </TD>
                    <TD>
                      <div className="flex flex-wrap gap-1">
                        {item.tags.length === 0 ? (
                          <span className="text-xs text-fg-subtle">—</span>
                        ) : (
                          item.tags.map((tag) => (
                            <Badge key={tag} tone="muted">
                              {tag}
                            </Badge>
                          ))
                        )}
                      </div>
                    </TD>
                    <TD numeric>{item.model_count}</TD>
                    <TD numeric>{item.run_count}</TD>
                    <TD numeric>{formatScore(item.avg_quality)}</TD>
                    <TD numeric>{formatCost(item.total_cost)}</TD>
                    <TD>
                      {item.last_run_at ? (
                        <div className="flex flex-col gap-1">
                          <span className="whitespace-nowrap text-xs text-fg-muted">
                            {formatRelative(item.last_run_at)}
                          </span>
                          {item.last_run_status && <StatusBadge status={item.last_run_status} />}
                        </div>
                      ) : (
                        <span className="text-xs text-fg-subtle">Never run</span>
                      )}
                    </TD>
                    <TD>
                      <div className="flex items-center justify-end gap-1">
                        <Button
                          size="sm"
                          variant="ghost"
                          loading={rerun.pending}
                          onClick={() => void rerun.run(item.id)}
                        >
                          Re-run
                        </Button>
                        <ConfirmButton
                          variant="ghost"
                          onConfirm={() => void remove.run(item.id)}
                          confirmLabel="Delete?"
                        >
                          Delete
                        </ConfirmButton>
                      </div>
                    </TD>
                  </TR>
                ))}
              </TBody>
            </Table>
          </div>

          <div className="flex items-center justify-between text-xs text-fg-subtle">
            <span>
              Showing {offset + 1}–{showingTo} of {total}
            </span>
            <div className="flex gap-2">
              <Button
                size="sm"
                variant="outline"
                disabled={offset === 0}
                onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
              >
                Previous
              </Button>
              <Button
                size="sm"
                variant="outline"
                disabled={showingTo >= total}
                onClick={() => setOffset(offset + PAGE_SIZE)}
              >
                Next
              </Button>
            </div>
          </div>
        </>
      )}
    </>
  );
}
