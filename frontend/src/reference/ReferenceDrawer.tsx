// "What does this look like?" — a right-side drawer over the rail with generic teaching material for one finding
// type: definition, key signs, look-alikes, and example films from a separate reference set with the expert outline in
// cyan. It never says anything about the case being read, so it is available before submit.
// Mount <ReferenceDrawer /> once on a page; open it from anywhere with openReference(label) or <InfoButton />.
import { useEffect, useRef, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { assetUrl } from '../api/client';
import { fetchReference } from '../api/reference';
import { labelDisplay } from '../api/labels';
import type { ReferenceExample, ReferenceFilm, ReferenceLabel } from './guard';
import { uiTerms } from './guard';
import { openReference, useReference } from './store';
import s from './Reference.module.css';

const REVIEW: Record<string, string> = {
  ai_draft: 'AI draft — not yet reviewed',
  student_reviewed: 'Student reviewed',
  radiologist_reviewed: 'Radiologist reviewed',
};

export const EXAMPLES_NOTE = 'Examples from a separate reference set, not from your cases.';

/** The small "i" next to a finding name. */
export function InfoButton({ label, display, dark = false }: { label: string; display?: string; dark?: boolean }) {
  const name = display ?? labelDisplay(label);
  return (
    <button
      type="button"
      className={`${s.info} ${dark ? s.infoDark : ''}`}
      aria-label={`What does ${name.toLowerCase()} look like?`}
      title={`What does ${name.toLowerCase()} look like?`}
      data-testid={`info-${label}`}
      onClick={(e) => { e.stopPropagation(); openReference(label); }}
    >
      i
    </button>
  );
}

function Film({ film, finding, caption, showOutline, alt, small = false }: {
  film: ReferenceFilm; finding?: ReferenceExample['finding']; caption: string; showOutline: boolean; alt: string; small?: boolean;
}) {
  const [failed, setFailed] = useState(false);
  const pts = finding?.polygon?.map(([x, y]) => `${x},${y}`).join(' ');
  const b = finding?.bbox;
  return (
    <figure className={`${s.figure} ${small ? s.figureSmall : ''}`} data-testid="reference-example">
      <div className={s.film} style={{ aspectRatio: `${film.width} / ${film.height}` }}>
        {failed ? (
          <p className={s.filmNote}>This example film could not be loaded.</p>
        ) : (
          <img src={assetUrl(film.image_url)} alt={alt} loading="lazy" draggable={false} onError={() => setFailed(true)} />
        )}
        {!failed && showOutline && (pts || b) && (
          <svg viewBox={`0 0 ${film.width} ${film.height}`} preserveAspectRatio="none" aria-hidden="true" data-testid="reference-outline">
            {pts ? <polygon points={pts} className={s.outline} /> : b ? <rect x={b[0]} y={b[1]} width={b[2] - b[0]} height={b[3] - b[1]} className={s.outline} /> : null}
          </svg>
        )}
      </div>
      {caption && <figcaption className={s.caption}>{caption}</figcaption>}
    </figure>
  );
}

function Card({ card, normals }: { card: ReferenceLabel; normals: ReferenceFilm[] }) {
  const [outlines, setOutlines] = useState(true);
  const examples = card.examples.slice(0, 3);
  const cap = (e: ReferenceExample) => {
    const where = e.finding?.relative_location ?? '';
    return where ? where.charAt(0).toUpperCase() + where.slice(1) : card.display;
  };
  return (
    <>
      {card.one_liner ? <p className={s.lede} data-testid="reference-definition">{uiTerms(card.one_liner)}</p> : <p className={s.muted}>No definition for this finding yet.</p>}

      {card.key_signs.length > 0 && (
        <section className={s.section}>
          <h3 className={s.h3}>Key signs</h3>
          <ul className={s.list}>{card.key_signs.map((k, i) => <li key={i}>{uiTerms(k)}</li>)}</ul>
        </section>
      )}

      {card.commonly_confused_with.length > 0 && (
        <section className={s.section}>
          <h3 className={s.h3}>Often confused with</h3>
          <div className={s.chips}>
            {card.commonly_confused_with.map((l) => (
              <button key={l} type="button" className={s.chip} onClick={() => openReference(l)} title={`Open ${labelDisplay(l).toLowerCase()}`}>
                {labelDisplay(l)}
              </button>
            ))}
          </div>
        </section>
      )}

      {card.mimics.length > 0 && (
        <section className={s.section}>
          <h3 className={s.h3}>Commonly mistaken normal structures</h3>
          <ul className={s.list}>{card.mimics.map((k, i) => <li key={i}>{uiTerms(k)}</li>)}</ul>
        </section>
      )}

      {card.search_tip && (
        <section className={s.section}>
          <h3 className={s.h3}>How to look for it</h3>
          <p className={s.p}>{uiTerms(card.search_tip)}</p>
        </section>
      )}

      <section className={s.section} data-testid="reference-examples">
        <div className={s.row}>
          <h3 className={s.h3}>Example films</h3>
          {examples.some((e) => e.finding?.polygon || e.finding?.bbox) && (
            <button type="button" className={s.link} aria-pressed={outlines} onClick={() => setOutlines((v) => !v)}>
              {outlines ? 'Hide outlines' : 'Show outlines'}
            </button>
          )}
        </div>
        <p className={s.note} data-testid="reference-note">{EXAMPLES_NOTE}</p>
        {examples.length === 0 ? (
          <p className={s.muted} data-testid="reference-no-examples">No example films for this finding yet.</p>
        ) : (
          <>
            {examples.map((e) => (
              <Film key={e.case_id || e.image_url} film={e} finding={e.finding} caption={cap(e)} showOutline={outlines}
                alt={`Example chest radiograph with ${card.display.toLowerCase()}${outlines ? ' outlined' : ''}`} />
            ))}
            <p className={s.key}><span className={s.keyCyan} /> Expert outline · patient right is on the image left</p>
          </>
        )}
      </section>

      {normals.length > 0 && (
        <section className={s.section} data-testid="reference-normals">
          <h3 className={s.h3}>Normal chest, for comparison</h3>
          <div className={s.normals}>
            {normals.slice(0, 3).map((n, i) => (
              <Film key={n.case_id || n.image_url} film={n} caption="" showOutline={false} alt={`Normal chest radiograph, example ${i + 1}`} small />
            ))}
          </div>
        </section>
      )}

      <div className={s.foot}>
        {card.radiopaedia_url && (
          <a href={card.radiopaedia_url} target="_blank" rel="noopener noreferrer" className={s.ext} data-testid="reference-radiopaedia">
            Read more on Radiopaedia <span aria-hidden="true">↗</span><span className={s.sr}> (opens in a new tab)</span>
          </a>
        )}
        {card.review_status && <span className={s.badge}>{REVIEW[card.review_status] ?? card.review_status.replace(/_/g, ' ')}</span>}
      </div>
    </>
  );
}

export function ReferenceDrawer() {
  const label = useReference((st) => st.label);
  const close = useReference((st) => st.close);
  const ref = useRef<HTMLElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);
  const q = useQuery({ queryKey: ['reference'], queryFn: fetchReference, enabled: !!label, staleTime: Infinity, retry: false });

  // Close when the page that mounted the drawer goes away.
  useEffect(() => () => useReference.getState().close(), []);
  // Focus moves into the drawer when it opens and returns to where it was when it closes.
  const open = !!label;
  useEffect(() => {
    if (!open) return;
    const prev = document.activeElement as HTMLElement | null;
    closeRef.current?.focus({ preventScroll: true });
    return () => { if (prev && document.contains(prev)) prev.focus?.({ preventScroll: true }); };
  }, [open]);
  useEffect(() => { ref.current?.scrollTo?.({ top: 0 }); }, [label]);

  if (!label) return null;
  const card = q.data?.labels.find((l) => l.label === label) ?? null;
  const title = card?.display ?? labelDisplay(label);
  return (
    <aside
      ref={ref}
      className={s.drawer}
      role="dialog"
      aria-labelledby="reference-h"
      data-testid="reference-drawer"
      data-label={label}
      // Keys typed in the drawer stay in the drawer: reading-room shortcuts (N, H, Enter…) must not fire behind it.
      onKeyDown={(e) => {
        if (e.key === 'Escape') { e.preventDefault(); close(); }
        if (e.key !== 'Tab') e.stopPropagation();
      }}
    >
      <header className={s.head}>
        <div>
          <p className={s.kicker}>What does this look like?</p>
          <h2 id="reference-h" className={s.title}>{title}</h2>
        </div>
        <button ref={closeRef} type="button" className={s.close} onClick={close} data-testid="reference-close">Close</button>
      </header>
      <p className={s.generic}>General teaching material. It says nothing about the film you are reading.</p>
      {q.isPending ? (
        <p className={s.muted}>Loading the reference…</p>
      ) : q.isError ? (
        <p className={s.notice} data-testid="reference-unavailable">
          The reference is not available right now. <button type="button" className={s.link} onClick={() => q.refetch()}>Try again</button>
        </p>
      ) : card ? (
        <Card key={card.label} card={card} normals={q.data?.normal_examples ?? []} />
      ) : (
        <p className={s.notice} data-testid="reference-empty">There is no reference card for {title.toLowerCase()} yet.</p>
      )}
    </aside>
  );
}
