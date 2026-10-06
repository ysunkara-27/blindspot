import type { Confidence } from '../types/contracts';
import s from './Rail.module.css';

const LEVELS: Confidence[] = [1, 2, 3, 4, 5];

/** "How sure are you?" — five chips, 1 = guessing … 5 = certain. Nothing is preselected: `value` is null until the
 *  learner chooses. `captions` writes the two ends out beside the chips; `needed` marks a still-empty answer. */
export function ConfidenceChips({ value, onChange, name, dark = false, disabled = false, captions = false, needed = false }: {
  value: Confidence | null | undefined; onChange: (c: Confidence) => void; name: string; dark?: boolean; disabled?: boolean;
  captions?: boolean; needed?: boolean;
}) {
  const group = (
    <span
      className={`${s.chips} ${dark ? s.chipsDark : ''} ${needed && value == null ? s.chipsNeeded : ''}`}
      role="radiogroup"
      aria-label="How sure are you? 1 = guessing, 5 = certain"
      data-testid={`confidence-${name}`}
      data-value={value ?? ''}
    >
      {LEVELS.map((c) => (
        <button
          key={c}
          type="button"
          role="radio"
          aria-checked={value === c}
          aria-label={`Confidence ${c} of 5`}
          title={c === 1 ? '1 = guessing' : c === 5 ? '5 = certain' : undefined}
          disabled={disabled}
          className={`${s.chip} ${value === c ? s.chipOn : ''}`}
          onClick={() => onChange(c)}
        >
          {c}
        </button>
      ))}
    </span>
  );
  if (!captions) return group;
  return (
    <span className={s.chipsCaptioned}>
      <span className={s.chipCap} aria-hidden="true">guessing</span>
      {group}
      <span className={s.chipCap} aria-hidden="true">certain</span>
    </span>
  );
}
