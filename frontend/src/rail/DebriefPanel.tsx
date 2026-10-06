// Tutor debrief (SPEC §8, §13): polls GET /attempts/{id}/debrief every 700 ms until ready/failed.
import { useEffect, useRef, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from '../api/client';
import { track } from '../analytics';
import { debriefErrorText, debriefHadError } from '../tutor/status';
import type { DebriefResponse, RevealFinding } from '../types/contracts';
import { openReference } from '../reference/store';
import { plainText } from './copy';
import { PROVENANCE, SOURCE, SOURCE_TITLE } from './debriefCopy';
import s from './Rail.module.css';

const SLOW_MS = 15_000;

export function DebriefPanel({ attemptId, findings, disabled }: { attemptId: string; findings: RevealFinding[]; disabled: boolean }) {
  const qc = useQueryClient();
  const [slow, setSlow] = useState(false);
  const [flagged, setFlagged] = useState(false);
  const counted = useRef(false);
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

  const d = q.data;
  const failed = q.isError || d?.status === 'failed';
  const settled = failed || d?.status === 'ready';
  // Once the debrief settles: count which kind arrived, and after a tutor problem re-check the tutor status so the
  // banner catches up without waiting for the next poll.
  useEffect(() => {
    if (!settled || counted.current || disabled) return;
    counted.current = true;
    if (d?.status === 'ready' && d.debrief) track(d.source === 'template' ? 'debrief_template' : 'debrief_live');
    if (debriefHadError(d, failed)) qc.invalidateQueries({ queryKey: ['health'] });
  }, [settled, d, failed, disabled, qc]);

  if (disabled || d?.status === 'disabled') return null;
  // Not the live tutor's words: say why in one plain sentence, and still show any built-in explanation the server sent.
  const problem = settled ? debriefErrorText(d, failed) : null;

  const flag = () => {
    setFlagged(true);
    api.flagDebrief(attemptId, 'learner: this seems wrong').catch(() => { /* kept locally; endpoint pending (contract request) */ });
  };

  return (
    <section className={`${s.section} ${s.settle}`} aria-labelledby="debrief-h" aria-live="polite" data-testid="debrief">
      <div className={s.row}>
        <h3 id="debrief-h" className={s.h3}>Tutor debrief</h3>
        {d?.status === 'ready' && d.source && (
          <span className={`${s.sourceTag} ${d.source === 'template' ? '' : s.sourceClaude}`} title={SOURCE_TITLE[d.source]} data-testid="debrief-source">
            {SOURCE[d.source] ?? d.source}
          </span>
        )}
      </div>
      {problem && <p className={s.notice} data-testid="debrief-busy">{problem}</p>}
      {failed && !d?.debrief ? null : !d || d.status === 'pending' ? (
        <p className={s.muted} data-testid="debrief-pending">{slow ? 'The tutor is taking longer than usual. The facts above are complete.' : 'Writing your debrief…'}</p>
      ) : d.debrief ? (
        <div className={s.debrief}>
          <p className={s.debriefHead}>{plainText(d.debrief.headline)}</p>
          {d.debrief.findings.map((f) => {
            const rf = findings.find((x) => x.finding_id === f.finding_id);
            return (
              <div key={f.finding_id} className={s.dFinding}>
                <div className={s.row}>
                  <span><span className={s.fid}>{f.finding_id}</span> {rf?.display ?? ''}</span>
                  {rf && (
                    <button type="button" className={s.linkBtn} onClick={() => openReference(rf.label)} data-testid={`see-examples-${f.finding_id}`}>
                      See examples
                    </button>
                  )}
                </div>
                <dl className={s.dl}>
                  <dt>Where to look</dt><dd>{plainText(f.where_to_look)}</dd>
                  <dt>What it looks like</dt><dd><ul>{f.what_it_looks_like.map((w, i) => <li key={i}>{plainText(w)}</li>)}</ul></dd>
                  <dt>{f.result.startsWith('missed') ? 'Why it was missed' : 'Why'}</dt><dd>{plainText(f.why)}</dd>
                </dl>
              </div>
            );
          })}
          {d.debrief.overcalls.map((o) => (
            <div key={o.mark_id} className={s.dFinding}>
              <div className={s.row}><span><span className={s.markId}>{o.mark_id}</span> Your mark</span></div>
              <p className={s.p}>{plainText(o.explanation)}</p>
              {o.possible_mimics.length > 0 && <p className={s.mutedSmall}>Often mistaken for a finding: {o.possible_mimics.join(', ')}.</p>}
            </div>
          ))}
          <dl className={s.dl}>
            {d.debrief.search_coaching && <><dt>Search coaching</dt><dd>{plainText(d.debrief.search_coaching)}</dd></>}
            {d.debrief.calibration_note && <><dt>Confidence</dt><dd>{plainText(d.debrief.calibration_note)}</dd></>}
            {d.debrief.next_step && <><dt>Next</dt><dd>{plainText(d.debrief.next_step)}</dd></>}
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
      ) : problem ? null : (
        <p className={s.notice} data-testid="debrief-busy">{debriefErrorText({ status: 'failed' }, true)}</p>
      )}
    </section>
  );
}
