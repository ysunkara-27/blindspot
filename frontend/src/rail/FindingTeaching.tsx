// Under a debrief row's "What it looks like" (round 5): the signs drawn on the film for this finding ("Look for: …"
// chips that focus the drawing on the film), two example films of the same finding type from the separate reference
// set with the expert outline in cyan, and the teaching card's Radiopaedia link. Everything here is either computed
// by the backend (the signs, from the radiologist mask) or generic reference material; the tutor's words are above.
// Thumbnails load only once the row is on screen.
import { useRef, type KeyboardEvent, type MouseEvent } from 'react';
import { useQuery } from '@tanstack/react-query';
import { assetUrl } from '../api/client';
import { fetchReferenceLabel, type ReferenceExample } from '../api/reference';
import { pickExamples } from '../reference/guard';
import { openReference } from '../reference/store';
import { VolumeExample } from '../reference/VolumeExample';
import type { RevealFinding, Sign } from '../types/contracts';
import { focusSign } from './signsSeam';
import { useInView } from './useInView';
import s from './Rail.module.css';

export const SEPARATE_SET = 'Separate reference set';
export const LINKS_ONLY = 'Links only; Radiopaedia content is not reproduced here.';

const cap = (t: string) => (t ? t.charAt(0).toUpperCase() + t.slice(1) : '');

function Thumb({ ex, display, onOpen }: { ex: ReferenceExample; display: string; onOpen: () => void }) {
  const f = ex.finding;
  const where = cap(f?.relative_location ?? '');
  const pts = f?.polygon?.map(([x, y]) => `${x},${y}`).join(' ');
  const b = f?.bbox;
  return (
    <button type="button" className={s.thumb} onClick={onOpen} title={`Open the reference for ${display.toLowerCase()}`} data-testid="example-thumb" data-case={ex.case_id}>
      {ex.volume ? (
        <span className={s.thumbVol}>
          <VolumeExample ex={ex} outline alt={`Example study with ${display.toLowerCase()} outlined`} thumb />
        </span>
      ) : (
        <span className={s.thumbFilm} style={{ aspectRatio: `${ex.width} / ${ex.height}` }}>
          <img src={assetUrl(ex.image_url)} alt={`Example film with ${display.toLowerCase()} outlined`} loading="lazy" draggable={false} />
          {(pts || b) && (
            <svg viewBox={`0 0 ${ex.width} ${ex.height}`} preserveAspectRatio="none" aria-hidden="true" data-testid="example-outline">
              {pts ? <polygon points={pts} className={s.thumbOutline} /> : b ? <rect x={b[0]} y={b[1]} width={b[2] - b[0]} height={b[3] - b[1]} className={s.thumbOutline} /> : null}
            </svg>
          )}
        </span>
      )}
      <span className={s.thumbCap}>
        {where && <span className={s.thumbWhere}>{where}</span>}
        <span className={s.thumbSet}>{SEPARATE_SET}</span>
      </span>
    </button>
  );
}

export function SignChips({ signs }: { signs: Sign[] }) {
  const go = (e: MouseEvent | KeyboardEvent, id: string) => { e.stopPropagation(); focusSign(id); };
  return (
    <span className={s.signChips} data-testid="sign-chips">
      {signs.map((sg) => (
        <button
          key={sg.id}
          type="button"
          className={s.signChip}
          title={sg.text}
          aria-label={`Look for: ${sg.name}. ${sg.text} Shows it on the film.`}
          onClick={(e) => go(e, sg.id)}
          onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); go(e, sg.id); } }}
          data-testid={`sign-chip-${sg.id}`}
        >
          <span className={s.signChipKey}>Look for:</span> {sg.name}
        </button>
      ))}
    </span>
  );
}

export function FindingTeaching({ finding, compact = false }: { finding: RevealFinding; compact?: boolean }) {
  const ref = useRef<HTMLDivElement>(null);
  const seen = useInView(ref);
  const signs = finding.signs ?? [];
  const signIds = signs.map((sg) => sg.schematic ?? sg.id);
  const q = useQuery({
    queryKey: ['reference', finding.label],
    queryFn: () => fetchReferenceLabel(finding.label),
    enabled: seen,
    staleTime: Infinity,
    retry: false,
  });
  const card = q.data ?? null;
  const examples = card ? pickExamples(card.examples, 2) : [];
  const open = () => openReference(finding.label, { signIds });
  return (
    <div ref={ref} className={`${s.teach} ${compact ? s.teachCompact : ''}`} data-testid={`finding-teaching-${finding.finding_id}`}>
      {signs.length > 0 && (
        <div className={s.teachRow}>
          <span className={s.teachLabel}>Signs on the film</span>
          <SignChips signs={signs} />
        </div>
      )}
      {seen && (q.isPending ? (
        <div className={s.teachRow}><span className={s.teachLabel}>Example films</span><span className={s.mutedSmall}>Loading…</span></div>
      ) : examples.length > 0 ? (
        <div className={s.teachRow}>
          <span className={s.teachLabel}>{examples.some((e) => e.volume) ? 'Example studies' : 'Example films'}</span>
          <span className={s.thumbs} data-testid="example-thumbs">
            {examples.map((ex) => <Thumb key={ex.case_id || ex.image_url} ex={ex} display={finding.display} onOpen={open} />)}
          </span>
        </div>
      ) : null)}
      {card?.radiopaedia_url && (
        <div className={s.teachRow}>
          <a href={card.radiopaedia_url} target="_blank" rel="noopener noreferrer" className={s.ext} data-testid={`radiopaedia-${finding.finding_id}`}>
            Read more on Radiopaedia <span aria-hidden="true">↗</span><span className="sr-only"> (opens in a new tab)</span>
          </a>
          <span className={s.linksOnly}>{LINKS_ONLY}</span>
        </div>
      )}
    </div>
  );
}
