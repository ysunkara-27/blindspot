// First-run tutorial: a short, skippable coach-mark sequence over the real reading room. Each step rings the real
// control and puts a small card beside it — never a full-screen overlay, so the film and every control stay usable
// while it runs. Next / Back / Skip; ← → and Esc work while the card has focus.
import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { track } from '../analytics';
import { availableSteps, markTutorialDone, placeCard, tourStep, type Rect, type Step } from './steps';
import s from './Tutorial.module.css';

const CARD_W = 320;

const rectOf = (el: Element | null): Rect | null => {
  if (!el) return null;
  const r = el.getBoundingClientRect();
  return r.width > 0 && r.height > 0 ? { left: r.left, top: r.top, width: r.width, height: r.height } : null;
};
const same = (a: Rect | null, b: Rect | null) => a === b || (!!a && !!b && Math.abs(a.left - b.left) < 0.5 && Math.abs(a.top - b.top) < 0.5 && Math.abs(a.width - b.width) < 0.5 && Math.abs(a.height - b.height) < 0.5);

/** `onClose(finished)`: finished = walked to the end; false = skipped. Either way it is remembered as done.
 *  `modality` (round 4): 'ct' | 'mr' adds the slice and measure steps, whose controls the volume viewer marks with
 *  data-tour="slices" and data-tour="measure"; a chest film (or no modality) gets the unchanged X-ray tour. */
export function Tutorial({ onClose, modality }: { onClose: (finished: boolean) => void; modality?: string | null }) {
  const volumetric = modality === 'ct' || modality === 'mr';
  const steps = useMemo<Step[]>(() => availableSteps((sel) => !!document.querySelector(sel), undefined, volumetric), [volumetric]);
  const [i, setI] = useState(0);
  const [target, setTarget] = useState<Rect | null>(null);
  const [film, setFilm] = useState<Rect | null>(null);
  const [cardH, setCardH] = useState(190);
  const cardRef = useRef<HTMLDivElement>(null);
  const nextRef = useRef<HTMLButtonElement>(null);
  const step = steps[i];

  const end = (finished: boolean) => {
    markTutorialDone();
    if (finished) track('tutorial_done');
    onClose(finished);
  };
  const endRef = useRef(end);
  useLayoutEffect(() => { endRef.current = end; });
  // No controls to point at (should not happen): close quietly rather than show an orphan card.
  useEffect(() => { if (steps.length === 0) endRef.current(false); }, [steps.length]);

  // Bring the control into view (the rail scrolls), then keep the ring on it as the layout moves.
  useLayoutEffect(() => {
    if (!step) return;
    document.querySelector(step.target)?.scrollIntoView({ block: 'nearest' });
    const measure = () => {
      const t = rectOf(document.querySelector(step.target));
      const f = rectOf(document.querySelector('[data-tour="film"]'));
      setTarget((prev) => (same(prev, t) ? prev : t));
      setFilm((prev) => (same(prev, f) ? prev : f));
    };
    measure();
    const id = window.setInterval(measure, 250);
    window.addEventListener('resize', measure);
    window.addEventListener('scroll', measure, true);
    return () => {
      clearInterval(id);
      window.removeEventListener('resize', measure);
      window.removeEventListener('scroll', measure, true);
    };
  }, [step]);

  useLayoutEffect(() => {
    const el = cardRef.current;
    if (!el) return;
    const ro = new ResizeObserver(() => setCardH((prev) => (Math.abs(el.offsetHeight - prev) > 1 ? el.offsetHeight : prev)));
    ro.observe(el);
    return () => ro.disconnect();
  }, [step]);
  useEffect(() => { nextRef.current?.focus({ preventScroll: true }); }, [i]);

  if (!step) return null;
  const go = (a: 'next' | 'back') => {
    const n = tourStep({ i, n: steps.length }, a);
    if (n) setI(n.i);
    else end(true);
  };
  const vp = { w: window.innerWidth, h: window.innerHeight };
  const place = target ? placeCard(target, { w: CARD_W, h: cardH }, vp, film) : { left: Math.max(8, vp.w - CARD_W - 24), top: 80, side: 'inside' as const };
  const last = i === steps.length - 1;
  return (
    <div className={s.root} data-testid="tutorial" data-step={step.id}>
      {target && (
        <div className={s.ring} aria-hidden="true" data-testid="tutorial-ring"
          style={{ left: target.left - 4, top: target.top - 4, width: target.width + 8, height: target.height + 8 }} />
      )}
      <div
        ref={cardRef}
        className={s.card}
        role="dialog"
        aria-labelledby="tutorial-title"
        aria-describedby="tutorial-body"
        // Above its target the card hangs from its bottom edge, so a taller text never grows down over the control.
        style={place.side === 'above'
          ? { left: place.left, bottom: Math.max(8, vp.h - (place.top + cardH)), width: CARD_W }
          : { left: place.left, top: place.top, width: CARD_W }}
        data-side={place.side}
        data-testid="tutorial-card"
        onKeyDown={(e) => {
          if (e.key === 'ArrowRight') { e.preventDefault(); go('next'); }
          else if (e.key === 'ArrowLeft') { e.preventDefault(); go('back'); }
          else if (e.key === 'Escape') { e.preventDefault(); end(false); }
          // Keys pressed on the card stay here: reading-room shortcuts must not fire behind it.
          if (e.key !== 'Tab') e.stopPropagation();
        }}
      >
        <p className={s.count} data-testid="tutorial-count">How to read here · step {i + 1} of {steps.length}</p>
        <h2 id="tutorial-title" className={s.title}>{step.title}</h2>
        <p id="tutorial-body" className={s.body}>{step.body}</p>
        <div className={s.row}>
          <button type="button" className={s.skip} onClick={() => end(false)} data-testid="tutorial-skip">Skip</button>
          <span className={s.spacer} />
          <button type="button" className={s.back} onClick={() => go('back')} disabled={i === 0} data-testid="tutorial-back">Back</button>
          <button ref={nextRef} type="button" className={s.next} onClick={() => go('next')} data-testid="tutorial-next">
            {last ? 'Start reading' : 'Next'}
          </button>
        </div>
      </div>
    </div>
  );
}
