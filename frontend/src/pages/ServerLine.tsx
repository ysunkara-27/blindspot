// One quiet line about the film library. It only gets loud when something is wrong, and then says what to do.
import { useQuery } from '@tanstack/react-query';
import { api, apiMode } from '../api/client';

export function ServerLine({ className }: { className?: string }) {
  const health = useQuery({ queryKey: ['health'], queryFn: api.health, retry: false });
  const mock = apiMode().mode === 'mock';
  return (
    <p className={className} data-testid="health">
      {health.isPending ? 'Checking the film library…'
        : mock ? 'The film library is not reachable, so you are seeing synthetic practice shapes, not radiographs. Reload the page to try the library again.'
        : health.data?.ok
          ? `Library: ${health.data.cases.toLocaleString()} chest films with radiologist outlines.${health.data.offline ? ' The tutor is offline, so explanations are the built-in ones.' : ''}`
          : 'The film library is not answering. Check your connection, then reload the page.'}
    </p>
  );
}
