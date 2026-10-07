// After submit: ONE list of what was there (name · location · outcome · one-line why), then the search summary.
// Everything here is built from the computed SubmitResult (deterministic, instant); the tutor debrief follows below.
// Replaces the separate outcome list + facts card, which repeated each other (round 3 audit).
import { useState } from 'react';
import { labelDisplay, OUTCOME_COPY, zoneDisplay } from '../api/labels';
import { InfoButton } from '../reference/ReferenceDrawer';
import type { Outcome, SubmitResult } from '../types/contracts';
import { OutcomeChip } from './OutcomeList';
import { PROXY_NOTE, scoreSentence, searchLines, whyLine } from './copy';
import { sizeVerdictText } from '../viewer/volume/dwell';
import s from './Rail.module.css';

type MarkResult = SubmitResult['reveal']['marks'][number]['result'] | 'unmatched';

export function ResultSummary({ result, settle = true }: { result: SubmitResult; settle?: boolean }) {
  const [info, setInfo] = useState(false);
  const findings = result.reveal.findings;
  const byTarget = new Map<string, Outcome>(result.outcomes.map((o) => [o.target, o]));
  // CT / MR: `unmatched` marks (the reference does not label that spot) are listed too, neutrally.
  const fps = result.reveal.marks.filter((m) => m.result === 'false_positive' || m.result === 'duplicate' || (m.result as MarkResult) === 'unmatched');
  const volumetric = result.reveal.modality === 'ct' || result.reveal.modality === 'mr';
  const patternFalse = result.outcomes.filter((o) => o.result === 'pattern_false');
  const tn = result.outcomes.find((o) => o.result === 'true_negative');
  const anyProxy = result.outcomes.some((o) => { const t = OUTCOME_COPY[o.result]?.missType; return t === 'search' || t === 'recognition' || t === 'decision'; });
  const search = searchLines(result.reveal.search, volumetric);
  const anim = settle ? s.settle : '';
  return (
    <>
      <section className={`${s.section} ${anim}`} aria-labelledby="outcomes-h" data-testid="outcomes">
        <div className={s.row}>
          <h3 id="outcomes-h" className={s.h3}>What was there</h3>
          <span className={s.score} data-testid="score">
            Score <strong>{Math.round(result.score)}</strong> / 100
            <button type="button" className={s.scoreInfo} aria-label="How the score is worked out" aria-expanded={info} aria-controls="score-info"
              onClick={() => setInfo((v) => !v)} data-testid="score-info-btn">i</button>
          </span>
        </div>
        {info && <p className={s.scoreNote} id="score-info" data-testid="score-info">{scoreSentence(result.reveal.is_normal)}</p>}
        <p className={s.factsHead} data-testid="facts-headline">{result.facts_card.headline}</p>
        <ul className={s.outcomeList}>
          {findings.map((f) => {
            const o = byTarget.get(f.finding_id);
            const res = f.result ?? o?.result;
            const where = f.relative_location ?? zoneDisplay(f.primary_zone);
            return (
              <li key={f.finding_id} className={s.outcomeRow} data-testid={`outcome-${f.finding_id}`}>
                <span className={s.fid}>{f.finding_id}</span>
                <span className={s.outcomeWhat}>
                  {f.display}
                  {where ? <span className={s.muted}> · {where}</span> : null}
                </span>
                <InfoButton label={f.label} display={f.display} />
                {res && <span className={s.outcomeChipCell}><OutcomeChip result={res} /></span>}
                {res && <span className={s.why}>{whyLine(res, { dwell_ms: o?.dwell_ms ?? f.dwell_ms, learner_label: o?.learner_label, matched: o?.matched })}</span>}
                {f.size_verdict && (
                  <span className={s.sizeVerdict} data-testid={`size-verdict-${f.finding_id}`} data-ok={f.size_verdict.ok ? '1' : '0'}>{sizeVerdictText(f.size_verdict)}</span>
                )}
              </li>
            );
          })}
          {fps.map((m) => {
            const o = byTarget.get(m.mark_id);
            return (
              <li key={m.mark_id} className={s.outcomeRow} data-testid={`outcome-${m.mark_id}`}>
                <span className={s.markId}>{m.mark_id}</span>
                <span className={s.outcomeWhat}>Your mark{m.zone ? <span className={s.muted}> · {zoneDisplay(m.zone)}</span> : null}</span>
                <span />
                <span className={s.outcomeChipCell}><OutcomeChip result={m.result as MarkResult} /></span>
                <span className={s.why}>{whyLine(m.result as MarkResult, { learner_label: o?.learner_label, matched: m.matched_finding ?? o?.matched })}</span>
              </li>
            );
          })}
          {patternFalse.map((o) => (
            <li key={o.target} className={s.outcomeRow} data-testid={`outcome-${o.target}`}>
              <span className={s.markId}>—</span>
              <span className={s.outcomeWhat}>{labelDisplay(o.learner_label ?? o.target)}<span className={s.muted}> · whole film</span></span>
              <span />
              <span className={s.outcomeChipCell}><OutcomeChip result="pattern_false" /></span>
              <span className={s.why}>{whyLine('pattern_false')}</span>
            </li>
          ))}
          {tn && (
            <li className={s.outcomeRow} data-testid="outcome-normal">
              <span className={s.fid}>—</span>
              <span className={s.outcomeWhat}>Normal film</span>
              <span />
              <span className={s.outcomeChipCell}><OutcomeChip result="true_negative" /></span>
              <span className={s.why}>{whyLine('true_negative')}</span>
            </li>
          )}
          {findings.length === 0 && !tn && fps.length === 0 && patternFalse.length === 0 && <li className={s.muted}>This film is normal.</li>}
        </ul>
      </section>

      <section className={`${s.section} ${anim}`} aria-labelledby="search-h" data-testid="facts-card">
        <h3 id="search-h" className={s.h3}>Your search</h3>
        <ul className={s.factsList}>
          <li>{search.coverage}</li>
          <li data-testid="search-areas">{search.areas}</li>
        </ul>
        <p className={s.proxy} data-testid="proxy-note">{PROXY_NOTE}{anyProxy ? ' “Never looked there”, “Looked past it” and “Looked, judged it normal” come from it.' : ''}</p>
      </section>
    </>
  );
}
