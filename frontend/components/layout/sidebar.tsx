'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { useEffect, useState } from 'react';
import { api } from '@/lib/api';
import { cn } from '@/lib/utils';
import type { HealthResponse } from '@/types';

const NAV = [
  { href: '/', label: 'Dashboard', glyph: '▤' },
  { href: '/benchmarks/new', label: 'New Benchmark', glyph: '＋' },
  { href: '/history', label: 'History', glyph: '≡' },
  { href: '/models', label: 'Models', glyph: '◇' },
  { href: '/analytics', label: 'Analytics', glyph: '◫' },
  { href: '/settings', label: 'Settings', glyph: '⚙' },
] as const;

function isActive(pathname: string, href: string): boolean {
  if (href === '/') return pathname === '/';
  if (href === '/benchmarks/new') return pathname === '/benchmarks/new';
  return pathname.startsWith(href);
}

export function Sidebar() {
  const pathname = usePathname();
  const [open, setOpen] = useState(false);

  useEffect(() => {
    setOpen(false);
  }, [pathname]);

  return (
    <>
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        aria-label="Toggle navigation"
        aria-expanded={open}
        className="fixed left-3 top-3 z-50 flex h-9 w-9 items-center justify-center rounded-md border border-line bg-surface text-fg-muted lg:hidden"
      >
        <span aria-hidden="true">{open ? '×' : '☰'}</span>
      </button>

      {open && (
        <div
          className="fixed inset-0 z-30 bg-black/60 lg:hidden"
          onClick={() => setOpen(false)}
          aria-hidden="true"
        />
      )}

      <aside
        className={cn(
          'fixed inset-y-0 left-0 z-40 flex w-60 shrink-0 flex-col border-r border-line bg-surface',
          'transition-transform duration-150 lg:translate-x-0',
          open ? 'translate-x-0' : '-translate-x-full'
        )}
      >
        <div className="flex h-14 items-center gap-2.5 border-b border-line px-4">
          <span
            aria-hidden="true"
            className="flex h-6 w-6 items-center justify-center rounded bg-accent text-[13px] font-bold text-accent-fg"
          >
            P
          </span>
          <div className="min-w-0">
            <p className="truncate text-sm font-semibold leading-tight">PromptBench</p>
            <p className="truncate text-[10px] leading-tight text-fg-subtle">Benchmark LLMs</p>
          </div>
        </div>

        <nav className="flex-1 space-y-0.5 overflow-y-auto p-2" aria-label="Main">
          {NAV.map((item) => {
            const active = isActive(pathname, item.href);
            return (
              <Link
                key={item.href}
                href={item.href}
                aria-current={active ? 'page' : undefined}
                className={cn(
                  'flex items-center gap-2.5 rounded-md px-2.5 py-2 text-sm transition-colors',
                  active
                    ? 'bg-elevated font-medium text-fg'
                    : 'text-fg-muted hover:bg-surface-2 hover:text-fg'
                )}
              >
                <span aria-hidden="true" className="w-4 text-center text-xs text-fg-subtle">
                  {item.glyph}
                </span>
                {item.label}
              </Link>
            );
          })}
        </nav>

        <HealthFooter />
      </aside>
    </>
  );
}

function HealthFooter() {
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let cancelled = false;
    const load = () =>
      api
        .health()
        .then((value) => {
          if (!cancelled) {
            setHealth(value);
            setFailed(false);
          }
        })
        .catch(() => {
          if (!cancelled) setFailed(true);
        });
    void load();
    const timer = setInterval(load, 30_000);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, []);

  const configured = health ? Object.values(health.providers).filter(Boolean).length : 0;
  const total = health ? Object.keys(health.providers).length : 0;

  return (
    <div className="border-t border-line px-4 py-3 text-[11px]">
      {failed ? (
        <p className="text-[#f18e8e]">
          <span aria-hidden="true">✕</span> API unreachable
        </p>
      ) : health ? (
        <>
          <p className="flex items-center gap-1.5 text-fg-muted">
            <span aria-hidden="true" className="text-[#5fd08a]">
              ●
            </span>
            API {health.status} · v{health.version}
          </p>
          <p className="mt-0.5 text-fg-subtle">
            {configured}/{total} providers configured
          </p>
        </>
      ) : (
        <p className="text-fg-subtle">Checking API…</p>
      )}
    </div>
  );
}
