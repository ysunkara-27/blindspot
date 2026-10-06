// Deterministic facts card from the submit response: shown instantly, before the tutor answers.
import type { SubmitResult } from '../types/contracts';
import s from './Rail.module.css';

export function FactsCard({ card }: { card: SubmitResult['facts_card'] }) {
  return (
    <section className={s.section} aria-labelledby="facts-h" data-testid="facts-card">
      <h3 id="facts-h" className={s.h3}>The facts</h3>
      <p className={s.factsHead}>{card.headline}</p>
      <ul className={s.factsList}>
        {card.lines.map((l, i) => <li key={i}>{l}</li>)}
      </ul>
    </section>
  );
}
