// Access gates. The server keeps the decision (an httpOnly cookie set by POST /api/access or
// /api/review/access); the client never stores the code. Copy follows SPEC §14.4: say what happened and how to fix it.
import { useState, type FormEvent, type ReactNode } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { Link, useLocation } from 'react-router-dom';
import { submitCode } from '../api/client';
import { useGate, type GateKind } from '../api/access';
import { LandingHero } from '../pages/LandingHero';
import { BrandMark } from './BrandMark';
import { DISCLAIMER } from './Shell';
import { useTitle } from './useTitle';
import g from './Gate.module.css';

function failureText(status: number): string {
  if (status === 401 || status === 403 || status === 400 || status === 422) return 'That code did not work. Check it and try again.';
  if (status === 429) return 'Too many tries. Wait a minute, then try again.';
  return 'The server did not answer. Try again in a moment.';
}

/** The code form. `onDone` runs after the server accepts the code (its cookie is set by then). */
export function CodeForm({ kind, onDone, button }: { kind: GateKind; onDone: () => void; button: string }) {
  const [code, setCode] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (!code.trim() || busy) return;
    setBusy(true);
    setError(null);
    try {
      const r = await submitCode(kind, code.trim());
      if (r.ok) onDone();
      else setError(failureText(r.status));
    } catch {
      setError(failureText(0));
    } finally {
      setBusy(false);
    }
  };
  return (
    <form onSubmit={submit} data-testid={`${kind}-gate-form`}>
      <div className={g.form}>
        <label className={g.field}>
          <span>{kind === 'access' ? 'Access code' : 'Reviewer code'}</span>
          <input className={g.input} value={code} onChange={(e) => setCode(e.target.value)} autoFocus autoComplete="off"
            autoCapitalize="off" spellCheck={false} maxLength={80} data-testid={`${kind}-code`} />
        </label>
        <button type="submit" className={g.button} disabled={!code.trim() || busy} data-testid={`${kind}-submit`}>
          {busy ? 'Checking…' : button}
        </button>
      </div>
      {error && <p className={g.error} role="alert" data-testid={`${kind}-error`}>{error}</p>}
    </form>
  );
}

/** App-wide gate: replaces every page until the access code is accepted, then refetches what failed. */
export function AccessGate({ children }: { children: ReactNode }) {
  const need = useGate((st) => st.need);
  const clear = useGate((st) => st.clear);
  const qc = useQueryClient();
  const { pathname } = useLocation();
  // About is public (its API route is open), so the gate page can link to it.
  if (need !== 'access' || pathname.replace(/\/+$/, '') === '/about') return <>{children}</>;
  const done = () => {
    clear();
    qc.resetQueries();
  };
  return <AccessPage onDone={done} />;
}

function AccessPage({ onDone }: { onDone: () => void }) {
  useTitle(null);
  return (
    <div className={g.page} data-testid="access-gate">
      <header className={g.head}><span className={g.brand}><BrandMark size={22} className={g.headMark} />Blindspot</span></header>
      {/* Someone without a code still sees what this is: the same hero as the landing. */}
      <LandingHero headingId="gate-h" />
      <main className={g.gateMain}>
        <h2 className={g.gateTitle}>Enter your access code to start reading</h2>
        <CodeForm kind="access" onDone={onDone} button="Open Blindspot" />
        <p className={g.note} data-testid="request-access">
          No code? Ask the person who shared this link for the code. You can <Link to="/about">read about Blindspot</Link> without one.
        </p>
      </main>
      <footer className={g.gateFoot} data-testid="disclaimer">{DISCLAIMER}</footer>
    </div>
  );
}

/** Reviewer prompt for /review and /cohort, shown inside the page when the API asks for the reviewer code. */
export function ReviewerGate({ what, onDone }: { what: 'review' | 'cohort'; onDone: () => void }) {
  return (
    <section className={g.inline} data-testid="reviewer-gate">
      <h2 className={g.title}>{what === 'review' ? 'Expert review is for reviewers.' : 'The cohort view is for instructors.'}</h2>
      <p className={g.lede}>Enter the reviewer code. Learners can open their own <Link to="/progress">reading log</Link> instead.</p>
      <CodeForm kind="reviewer" onDone={onDone} button={what === 'review' ? 'Open review' : 'Open cohort'} />
    </section>
  );
}
