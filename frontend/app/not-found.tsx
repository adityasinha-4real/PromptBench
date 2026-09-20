import Link from 'next/link';
import { EmptyState } from '@/components/ui/feedback';

export default function NotFound() {
  return (
    <EmptyState
      title="Page not found"
      description="That route does not exist in PromptBench."
      action={
        <Link href="/" className="text-sm text-accent hover:underline">
          Back to the dashboard
        </Link>
      }
    />
  );
}
