// One quiet line about the film library. It only gets loud when something is wrong, and then says what to do.
// (The tutor's own state is the TutorNotice banner above the form.)
import { apiMode } from '../api/client';
import { useHealth } from '../tutor/health';

export function ServerLine({ className }: { className?: string }) {
  const health = useHealth();
  const mock = apiMode().mode === 'mock';
  return (
    <p className={className} data-testid="health">
      {health.isPending ? 'Checking the film library…'
        : mock ? 'The film library is not reachable, so you are seeing synthetic practice shapes, not radiographs. Reload the page to try the library again.'
        : health.data?.ok
          ? `Library: ${health.data.cases.toLocaleString()} chest films with radiologist outlines.`
          : 'The film library is not answering. Check your connection, then reload the page.'}
    </p>
  );
}
