// /dev/case/:id — clinical QA overlays rendered by the API (dev only).
import { useState } from 'react';
import { useParams } from 'react-router-dom';
import { api, apiMode } from '../api/client';
import { PageShell } from '../app/Shell';
import { useTitle } from '../app/useTitle';
import s from './Pages.module.css';

const LAYERS = ['anatomy', 'zones', 'findings'] as const;

export function DevCasePage() {
  const { id = '' } = useParams();
  useTitle(`Case ${id} · Clinical QA`);
  const [on, setOn] = useState<Record<string, boolean>>({ anatomy: true, zones: true, findings: true });
  const layers = LAYERS.filter((l) => on[l]).join(',');
  return (
    <PageShell wide>
      <h1 className={s.h1}>Case {id}</h1>
      <p className={s.mutedSmall}>Dev overlay for clinical QA. Patient right is on the image left.</p>
      <div className={s.row}>
        {LAYERS.map((l) => (
          <label key={l} className={s.inline}>
            <input type="checkbox" checked={on[l]} onChange={() => setOn({ ...on, [l]: !on[l] })} /> {l}
          </label>
        ))}
      </div>
      {apiMode().mode === 'mock' ? (
        <p className={s.notice}>Dev overlays are drawn by the API. Start it with <code>make api</code>.</p>
      ) : (
        <div className={s.devGrid}>
          <img src={api.imageUrl(id)} alt={`Case ${id}`} className={s.devImg} />
          <img src={api.devOverlayUrl(id, layers || 'none')} alt={`Overlay for ${id}: ${layers}`} className={s.devImg} />
        </div>
      )}
    </PageShell>
  );
}
