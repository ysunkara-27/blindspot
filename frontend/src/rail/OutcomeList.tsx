// Outcome chip (SPEC §14.3 step 4). Truth-side chips are cyan; learner overcalls are amber. Never red/green.
import { OUTCOME_COPY } from '../api/labels';
import { PROXY_NOTE } from './copy';
import s from './Rail.module.css';

export function OutcomeChip({ result }: { result: keyof typeof OUTCOME_COPY }) {
  const c = OUTCOME_COPY[result];
  const proxy = c.missType && c.missType !== 'interpretation' && c.missType !== 'overcall';
  const cls = c.tone === 'found' ? s.oFound : c.tone === 'missed' ? s.oMissed : c.tone === 'overcall' ? s.oOvercall : s.oNeutral;
  return (
    <span className={`${s.oChip} ${cls}`} title={proxy ? PROXY_NOTE : undefined} data-result={result}>
      {c.tone === 'missed' && result !== 'mislabeled' && <span className={s.oTag}>missed</span>}
      {c.text}
    </span>
  );
}
