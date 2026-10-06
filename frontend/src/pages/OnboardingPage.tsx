// / — onboarding (SPEC §14.5): who you are, your level, the mode. Three lines of explanation, then the film.
import { useState } from 'react';
import { useMutation, useQuery } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import { api, apiMode } from '../api/client';
import { FOCAL_LABELS, LEVELS, MODES } from '../api/labels';
import { PageShell } from '../app/Shell';
import { useSession } from '../state/session';
import type { Level, Mode } from '../types/contracts';
import s from './Pages.module.css';

const looksLikeCode = (v: string) => /^[A-Za-z]{0,4}[-_]?\d{2,6}$/.test(v.trim());

export function OnboardingPage() {
  const navigate = useNavigate();
  const setSession = useSession((st) => st.setSession);
  const projector = useSession((st) => st.projector);
  const [name, setName] = useState('');
  const [level, setLevel] = useState<Level>('MS3');
  const [mode, setMode] = useState<Mode>('practice');
  const [drillLabel, setDrillLabel] = useState('pneumothorax');

  const health = useQuery({ queryKey: ['health'], queryFn: api.health, retry: false });
  const start = useMutation({
    mutationFn: () => {
      const v = name.trim();
      return api.createSession({
        display_name: v,
        level,
        participant_code: looksLikeCode(v) ? v : null,
        mode,
        settings: { projector, ...(mode === 'drill' ? { label: drillLabel } : {}) },
      });
    },
    onSuccess: (r) => {
      setSession({ sessionId: r.session_id, learnerId: r.learner_id, displayName: name.trim(), level, mode, drillLabel: mode === 'drill' ? drillLabel : undefined });
      navigate('/read');
    },
  });

  return (
    <PageShell>
      <h1 className={s.display}>Blindspot</h1>
      <div className={s.intro}>
        <p>Mark what you see. We'll show you how you looked.</p>
        <p>Each chest film has expert outlines behind it. After you submit, your search appears over the film.</p>
        <p>Miss types are based on your cursor, loupe and zoom — a proxy for where you looked.</p>
      </div>
      <form className={s.form} onSubmit={(e) => { e.preventDefault(); if (name.trim()) start.mutate(); }}>
        <label className={s.field}>
          <span>Your name or participant code</span>
          <input className={s.input} value={name} onChange={(e) => setName(e.target.value)} autoFocus required maxLength={60} data-testid="name" />
        </label>
        <label className={s.field}>
          <span>Training level</span>
          <select className={s.input} value={level} onChange={(e) => setLevel(e.target.value as Level)} data-testid="level">
            {LEVELS.map((l) => <option key={l} value={l}>{l}</option>)}
          </select>
        </label>
        <fieldset className={s.modes}>
          <legend>Mode</legend>
          {MODES.map((m) => (
            <label key={m.id} className={`${s.modeRow} ${mode === m.id ? s.modeOn : ''}`}>
              <input type="radio" name="mode" value={m.id} checked={mode === m.id} onChange={() => setMode(m.id)} />
              <span className={s.modeName}>{m.display}</span>
              <span className={s.modeNote}>{m.note}</span>
            </label>
          ))}
        </fieldset>
        {mode === 'drill' && (
          <label className={s.field}>
            <span>Drill on</span>
            <select className={s.input} value={drillLabel} onChange={(e) => setDrillLabel(e.target.value)} data-testid="drill-label">
              {FOCAL_LABELS.map((l) => <option key={l.id} value={l.id}>{l.display}</option>)}
            </select>
          </label>
        )}
        {start.isError && (
          <p className={s.notice}>
            The server did not answer, so no session was started. Start it with <code>make api</code>, or open <code>/?mock=1</code> for the synthetic demo.
          </p>
        )}
        <button type="submit" className={s.primary} disabled={!name.trim() || start.isPending} data-testid="start">
          {start.isPending ? 'Starting…' : 'Start reading'}
        </button>
        <p className={s.mutedSmall} data-testid="health">
          {health.isPending ? 'Checking the server…' : health.data?.ok
            ? apiMode().mode === 'mock'
              ? `Server: ok · synthetic demo, the cases are drawn shapes, not radiographs (${apiMode().reason}).`
              : `Server: ok · ${health.data.cases.toLocaleString()} cases${health.data.offline ? ' · tutor offline: built-in explanations' : ''}.`
            : 'Server: not reachable.'}
        </p>
      </form>
    </PageShell>
  );
}
