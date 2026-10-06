import type { Confidence } from '../types/contracts';
import s from './Rail.module.css';

const LEVELS: Confidence[] = [1, 2, 3, 4, 5];

/** 1 = a guess, 5 = certain. A radio group of five small chips. */
export function ConfidenceChips({ value, onChange, name, dark = false, disabled = false }: {
  value: Confidence | undefined; onChange: (c: Confidence) => void; name: string; dark?: boolean; disabled?: boolean;
}) {
  return (
    <span className={`${s.chips} ${dark ? s.chipsDark : ''}`} role="radiogroup" aria-label="Confidence, 1 = a guess, 5 = certain" data-testid={`confidence-${name}`}>
      {LEVELS.map((c) => (
        <button
          key={c}
          type="button"
          role="radio"
          aria-checked={value === c}
          aria-label={`Confidence ${c} of 5`}
          disabled={disabled}
          className={`${s.chip} ${value === c ? s.chipOn : ''}`}
          onClick={() => onChange(c)}
        >
          {c}
        </button>
      ))}
    </span>
  );
}
