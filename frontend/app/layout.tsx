import type { Metadata, Viewport } from 'next';
import { Sidebar } from '@/components/layout/sidebar';
import { ToastProvider } from '@/components/ui/toast';
import './globals.css';

export const metadata: Metadata = {
  title: {
    default: 'PromptBench',
    template: '%s · PromptBench',
  },
  description: 'Benchmark LLMs. Compare quality, speed and cost.',
  applicationName: 'PromptBench',
  robots: { index: false, follow: false },
};

export const viewport: Viewport = {
  themeColor: '#0a0a0b',
  width: 'device-width',
  initialScale: 1,
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="min-h-screen bg-bg text-fg antialiased">
        <ToastProvider>
          <a
            href="#main"
            className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:z-50 focus:rounded focus:bg-accent focus:px-3 focus:py-2 focus:text-accent-fg"
          >
            Skip to content
          </a>
          <Sidebar />
          <main id="main" className="min-h-screen lg:pl-60">
            <div className="mx-auto max-w-[1600px] space-y-6 px-4 py-6 pt-16 sm:px-6 lg:pt-6">
              {children}
            </div>
          </main>
        </ToastProvider>
      </body>
    </html>
  );
}
