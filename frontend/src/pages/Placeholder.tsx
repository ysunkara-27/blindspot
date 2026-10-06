import { useQuery } from '@tanstack/react-query';
import { api } from '../api/client';

export function Placeholder({ title }: { title: string }) {
  const health = useQuery({ queryKey: ['health'], queryFn: api.health });
  return (
    <main style={{ padding: 24, maxWidth: 720 }}>
      <h1 style={{ fontSize: 'var(--fs-4)', fontWeight: 500, margin: '0 0 8px' }}>{title}</h1>
      <p style={{ color: 'var(--report-ink-muted)' }}>M0 scaffold. The frontend-engineer builds this page (SPEC §14.5).</p>
      <p data-testid="health">
        API: {health.isLoading ? 'checking…' : health.data ? `ok · ${health.data.cases} cases · ${health.data.offline ? 'offline' : 'online'}` : 'unreachable'}
      </p>
      <footer className="footer-disclaimer">For education. Not for clinical use.</footer>
    </main>
  );
}
