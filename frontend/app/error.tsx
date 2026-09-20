'use client';

import { useEffect } from 'react';
import { Button } from '@/components/ui/button';
import { ErrorState } from '@/components/ui/feedback';

export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    console.error(error);
  }, [error]);

  return (
    <div className="mx-auto max-w-2xl py-12">
      <ErrorState
        title="This page failed to render"
        message={error.message || 'An unexpected client error occurred.'}
        hint={error.digest ? `Digest: ${error.digest}` : undefined}
      />
      <div className="mt-4">
        <Button variant="primary" onClick={reset}>
          Try again
        </Button>
      </div>
    </div>
  );
}
