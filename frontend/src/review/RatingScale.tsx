// 1–5 rating as a radio group of buttons. Number keys are handled by the parent form.
import r from './Review.module.css';

export function RatingScale({ name, label, value, onChange, active, onFocus, low, high }: {
  name: string; label: string; value: number | null; onChange: (v: number) => void; active: boolean; onFocus: () => void; low: string; high: string;
}) {
  return (
    <fieldset className={`${r.scale} ${active ? r.scaleActive : ''}`} data-testid={`scale-${name}`} onFocus={onFocus}>
      <legend className={r.scaleLegend}>{label}{active && <span className={r.keyHint}> · keys 1–5</span>}</legend>
      <div className={r.scaleRow} role="radiogroup" aria-label={label}>
        {[1, 2, 3, 4, 5].map((v) => (
          <button key={v} type="button" role="radio" aria-checked={value === v} className={`${r.scaleBtn} ${value === v ? r.scaleOn : ''}`}
            onClick={() => { onFocus(); onChange(v); }} data-testid={`${name}-${v}`}>
            {v}
          </button>
        ))}
      </div>
      <div className={r.scaleEnds}><span>{low}</span><span>{high}</span></div>
    </fieldset>
  );
}
