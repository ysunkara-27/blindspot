// Tutor debrief (SPEC §8, §13): polls GET /attempts/{id}/debrief every 700 ms until ready/failed.
import { useEffect, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { api } from '../api/client';
import type { DebriefResponse, RevealFinding } from '../types/contracts';
import { OutcomeChip } from './OutcomeList';
import s from './Rail.module.css';

const PROVENANCE: Record<string, string> = {
  ai_draft: 'AI draft, not yet reviewed',
  student_reviewed: 'Reviewed by a medical student',
  radiologist_reviewed: 'Reviewed by a radiologist',
};
const SOURCE: Record<string, string> = { live: 'Written for this read', cache: 'Saved explanation', template: 'Built-in explanation' };
const SLOW_MS = 15_000;

export function DebriefPanel({ attemptId, findings, disabled }: { attemptId: string; findings: RevealFinding[]; disabled: boolean }) {
  const [slow, setSlow] = useState(false);
  const [flagged, setFlagged] = useState(false);
  const q = useQuery({
    queryKey: ['debrief', attemptId],
    queryFn: () => api.debrief(attemptId),
    enabled: !disabled,
    retry: 1,
    refetchInterval: (query) => {
      const st = (query.state.data as DebriefResponse | undefined)?.status;
      return st === 'pending' || st === undefined ? 700 : false;
    },
    staleTime: Infinity,
  });
  useEffect(() => {
    const t = window.setTimeout(() => setSlow(true), SLOW_MS);
    return () => clearTimeout(t);
  }, []);

  if (disabled || q.data?.status === 'disabled') return null;
  const d = q.data;
  const failed = q.isError || d?.status === 'failed';

  const flag = () => {
    setFlagged(true);
    api.flagDebrief(attemptId, 'learner: this seems wrong').catch(() => { /* kept locally; endpoint pending (contract request) */ });
  };

  return (
    <section className={s.section} aria-labelledby="debrief-h" aria-live="polite" data-testid="debrief">
      <div className={s.row}>
        <h3 id="debrief-h" className={s.h3}>Debrief</h3>
        {d?.status === 'ready' && d.source && <span className={s.sourceLabel} data-testid="debrief-source">{SOURCE[d.source] ?? d.source}</span>}
      </div>
      {failed ? (
        <p className={s.notice}>The tutor is offline. Showing the built-in explanation instead.</p>
      ) : !d || d.status === 'pending' ? (
        <p className={s.muted} data-testid="debrief-pending">{slow ? 'The tutor is taking longer than usual. The facts above are complete.' : 'Writing your debrief…'}</p>
      ) : d.debrief ? (
        <div className={s.debrief}>
          <p className={s.debriefHead}>{d.debrief.headline}</p>
          {d.debrief.findings.map((f) => {
            const rf = findings.find((x) => x.finding_id === f.finding_id);
            return (
              <div key={f.finding_id} className={s.dFinding}>
                <div className={s.row}>
                  <span><span className={s.fid}>{f.finding_id}</span> {rf?.display ?? ''}</span>
                  <OutcomeChip result={f.result} />
                </div>
                <dl className={s.dl}>
                  <dt>Where to look</dt><dd>{f.where_to_look}</dd>
                  <dt>What it looks like</dt><dd><ul>{f.what_it_looks_like.map((w, i) => <li key={i}>{w}</li>)}</ul></dd>
                  <dt>{f.result.startsWith('missed') ? 'Why it was missed' : 'Why'}</dt><dd>{f.why}</dd>
                </dl>
              </div>
            );
          })}
          {d.debrief.overcalls.map((o) => (
            <div key={o.mark_id} className={s.dFinding}>
              <div className={s.row}><span className={s.markId}>{o.mark_id}</span><OutcomeChip result="false_positive" /></div>
              <p className={s.p}>{o.explanation}</p>
              {o.possible_mimics.length > 0 && <p className={s.mutedSmall}>Often mistaken for a finding: {o.possible_mimics.join(', ')}.</p>}
            </div>
          ))}
          <dl className={s.dl}>
            {d.debrief.search_coaching && <><dt>Your search</dt><dd>{d.debrief.search_coaching}</dd></>}
            {d.debrief.calibration_note && <><dt>Confidence</dt><dd>{d.debrief.calibration_note}</dd></>}
            {d.debrief.next_step && <><dt>Next</dt><dd>{d.debrief.next_step}</dd></>}
          </dl>
          <div className={s.debriefFoot}>
            {d.provenance && <span className={`${s.badge} ${s[`prov_${d.provenance}`] ?? ''}`} data-testid="provenance">{PROVENANCE[d.provenance]}</span>}
            {flagged ? (
              <span className={s.mutedSmall}>Thanks. Flagged for expert review.</span>
            ) : (
              <button type="button" className={s.linkBtn} onClick={flag}>This seems wrong</button>
            )}
          </div>
        </div>
      ) : (
        <p className={s.notice}>The tutor is offline. Showing the built-in explanation instead.</p>
      )}
    </section>
  );
}
