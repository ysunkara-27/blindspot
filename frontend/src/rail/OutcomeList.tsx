// Outcome chips (SPEC §14.3 step 4). Truth-side chips are cyan; learner overcalls are amber. Never red/green.
import { labelDisplay, OUTCOME_COPY, PROXY_TOOLTIP, zoneDisplay } from '../api/labels';
import type { SubmitResult } from '../types/contracts';
import s from './Rail.module.css';

export function OutcomeChip({ result }: { result: keyof typeof OUTCOME_COPY }) {
  const c = OUTCOME_COPY[result];
  const proxy = c.missType && c.missType !== 'interpretation' && c.missType !== 'overcall';
  const cls = c.tone === 'found' ? s.oFound : c.tone === 'missed' ? s.oMissed : c.tone === 'overcall' ? s.oOvercall : s.oNeutral;
  return (
    <span className={`${s.oChip} ${cls}`} title={c.missType ? PROXY_TOOLTIP : undefined} data-result={result}>
      {c.tone === 'missed' && result !== 'mislabeled' && <span className={s.oTag}>missed</span>}
      {c.text}
      {proxy && <span className={s.oInfo} aria-hidden="true">?</span>}
    </span>
  );
}

export function OutcomeList({ result }: { result: SubmitResult }) {
  const findings = result.reveal.findings;
  const fps = result.reveal.marks.filter((m) => m.result === 'false_positive' || m.result === 'duplicate');
  const patternFalse = result.outcomes.filter((o) => o.result === 'pattern_false');
  const tn = result.outcomes.find((o) => o.result === 'true_negative');
  const anyMissType = result.outcomes.some((o) => OUTCOME_COPY[o.result]?.missType);
  return (
    <section className={`${s.section} ${s.settle}`} aria-labelledby="outcomes-h" data-testid="outcomes">
      <div className={s.row}>
        <h3 id="outcomes-h" className={s.h3}>What was there</h3>
        <span className={s.score} data-testid="score">Score <strong>{Math.round(result.score)}</strong></span>
      </div>
      <ul className={s.outcomeList}>
        {findings.map((f) => (
          <li key={f.finding_id} className={s.outcomeRow}>
            <span className={s.fid}>{f.finding_id}</span>
            <span className={s.outcomeWhat}>
              {f.display}
              {f.relative_location || f.primary_zone ? <span className={s.muted}> · {f.relative_location ?? zoneDisplay(f.primary_zone)}</span> : null}
            </span>
            {f.result && <OutcomeChip result={f.result} />}
          </li>
        ))}
        {fps.map((m) => (
          <li key={m.mark_id} className={s.outcomeRow}>
            <span className={s.markId}>{m.mark_id}</span>
            <span className={s.outcomeWhat}>{m.zone ? zoneDisplay(m.zone) : 'Your mark'}</span>
            <OutcomeChip result={m.result} />
          </li>
        ))}
        {patternFalse.map((o) => (
          <li key={o.target} className={s.outcomeRow}>
            <span className={s.markId}>—</span>
            <span className={s.outcomeWhat}>{labelDisplay(o.learner_label ?? o.target)}</span>
            <OutcomeChip result="pattern_false" />
          </li>
        ))}
        {tn && (
          <li className={s.outcomeRow}>
            <span className={s.fid}>—</span>
            <span className={s.outcomeWhat}>Normal film</span>
            <OutcomeChip result="true_negative" />
          </li>
        )}
        {findings.length === 0 && !tn && fps.length === 0 && <li className={s.muted}>This film is normal.</li>}
      </ul>
      {anyMissType && <p className={s.mutedSmall}>{PROXY_TOOLTIP}</p>}
    </section>
  );
}
