// /reference — the finding library: every finding type Blindspot trains, with its definition, key signs, mimics, a
// search tip, example films with the radiologist's outline, normal films, and a Radiopaedia link (link only).
// Content comes from GET /api/reference (teaching cards + annotated example films from a separate reference set);
// nothing here is written by a model at view time. The fetch, guard and types are the reading room's
// (api/reference.ts, reference/guard.ts), so this page and the reference drawer share one cached payload; only the
// page layout (all thirteen entries in one report column) is local.
import { useEffect, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Link, useLocation } from 'react-router-dom';
import { apiMode, assetUrl } from '../api/client';
import { FOCAL_LABELS, labelDisplay, PATTERN_LABELS } from '../api/labels';
import { fetchReference, type ReferenceExample, type ReferenceFilm, type ReferenceLabel } from '../api/reference';
import { PageShell } from '../app/Shell';
import { useTitle } from '../app/useTitle';
import { PROVENANCE } from '../rail/debriefCopy';
import { EXAMPLES_NOTE } from '../reference';
import { uiTerms } from '../reference/guard';
import p from './Pages.module.css';
import r from './Reference.module.css';

const KIND_NOTE = { focal: 'Marked on the film', pattern: 'Called for the whole film' } as const;

function ExampleFilm({ ex, outline, alt }: { ex: ReferenceExample | ReferenceFilm; outline: boolean; alt: string }) {
  const [failed, setFailed] = useState(false);
  const f = 'finding' in ex ? ex.finding : null;
  return (
    <figure className={r.filmFig} data-testid="ref-example">
      <div className={r.film} style={{ aspectRatio: `${ex.width} / ${ex.height}` }}>
        {failed ? <p className={r.filmMissing}>This example film did not load.</p> : (
          <>
            <img src={assetUrl(ex.image_url)} alt={alt} loading="lazy" onError={() => setFailed(true)} />
            {outline && f && (f.polygon || f.bbox) && (
              <svg viewBox={`0 0 ${ex.width} ${ex.height}`} aria-hidden="true" data-testid="ref-outline">
                {f.polygon
                  ? <polygon points={f.polygon.map((q) => `${q[0]},${q[1]}`).join(' ')} fill="#35C9DD" fillOpacity={0.06} stroke="#35C9DD" strokeWidth={2} vectorEffect="non-scaling-stroke" strokeLinejoin="round" />
                  : f.bbox && <rect x={f.bbox[0]} y={f.bbox[1]} width={f.bbox[2] - f.bbox[0]} height={f.bbox[3] - f.bbox[1]} fill="#35C9DD" fillOpacity={0.06} stroke="#35C9DD" strokeWidth={2} vectorEffect="non-scaling-stroke" />}
              </svg>
            )}
          </>
        )}
      </div>
      {f?.relative_location && <figcaption className={r.filmCap}>{f.relative_location.charAt(0).toUpperCase() + f.relative_location.slice(1)}</figcaption>}
    </figure>
  );
}

function Entry({ l, outline, known }: { l: ReferenceLabel; outline: boolean; known: Set<string> }) {
  const confused = l.commonly_confused_with.filter((x) => x !== l.label);
  return (
    <section className={r.entry} id={l.label} aria-labelledby={`ref-${l.label}`} data-testid="ref-entry">
      <div className={r.entryHead}>
        <h2 className={r.h2} id={`ref-${l.label}`}>{l.display}</h2>
        <span className={r.kind}>{KIND_NOTE[l.kind]}</span>
      </div>
      {l.one_liner && <p className={r.oneLiner}>{uiTerms(l.one_liner)}</p>}
      <div className={r.cols}>
        {l.key_signs.length > 0 && (
          <div>
            <h3 className={r.h3}>Key signs</h3>
            <ul className={r.list}>{l.key_signs.map((k) => <li key={k}>{uiTerms(k)}</li>)}</ul>
          </div>
        )}
        {l.mimics.length > 0 && (
          <div>
            <h3 className={r.h3}>Often mistaken for it</h3>
            <ul className={r.list}>{l.mimics.map((k) => <li key={k}>{uiTerms(k)}</li>)}</ul>
          </div>
        )}
      </div>
      {l.search_tip && <p className={r.tip}><strong>Where to look</strong>{uiTerms(l.search_tip)}</p>}
      {confused.length > 0 && (
        <p className={r.confused}>
          Commonly confused with:{' '}
          {confused.map((x, i) => (
            <span key={x}>{i > 0 ? ', ' : ''}{known.has(x) ? <a href={`#${x}`}>{labelDisplay(x)}</a> : labelDisplay(x)}</span>
          ))}
        </p>
      )}
      <h3 className={r.h3}>Example films{l.examples.length ? ` (${l.examples.length})` : ''}</h3>
      {l.examples.length ? (
        <ul className={r.films}>
          {l.examples.map((ex, i) => <li key={ex.case_id || i}><ExampleFilm ex={ex} outline={outline} alt={`Chest radiograph with ${l.display.toLowerCase()}`} /></li>)}
        </ul>
      ) : <p className={r.none}>No example films are loaded for this finding yet.</p>}
      <p className={r.foot}>
        {l.review_status && <span className={r.status}>{PROVENANCE[l.review_status] ?? l.review_status.replace(/_/g, ' ')}</span>}
        {l.radiopaedia_url && <a href={l.radiopaedia_url} target="_blank" rel="noreferrer">Read more on Radiopaedia</a>}
      </p>
    </section>
  );
}

export function ReferencePage() {
  useTitle('Finding library');
  const mock = apiMode().mode === 'mock';
  // Same key and fetcher as the reading room's reference drawer: one cached payload for both.
  const q = useQuery({ queryKey: ['reference'], queryFn: fetchReference, retry: false, staleTime: Infinity });
  const [outline, setOutline] = useState(true);
  const { hash } = useLocation();
  // /reference#nodule lands on that entry once the library has loaded.
  useEffect(() => {
    if (q.data && hash.length > 1) document.getElementById(decodeURIComponent(hash.slice(1)))?.scrollIntoView();
  }, [q.data, hash]);

  const labels = q.data?.labels ?? [];
  const known = new Set(labels.map((l) => l.label));
  const offline = q.isError || (q.data && labels.length === 0);
  const group = (kind: 'focal' | 'pattern') => labels.filter((l) => l.kind === kind);

  return (
    <PageShell width={860}>
      <h1 className={p.h1}>Finding library</h1>
      <p className={p.lede}>
        The thirteen findings Blindspot trains: what each one is, the signs to look for, what gets mistaken for it, and
        example films with the radiologist's outline.
      </p>

      {q.isPending ? <p className={p.muted}>Loading the library…</p> : offline ? (
        <div data-testid="ref-offline">
          <p className={r.notice}>
            The library did not load. Check your connection, then reload the page. These are the findings it covers:
          </p>
          <ul className={r.names} data-testid="ref-names">
            {[...FOCAL_LABELS, ...PATTERN_LABELS].map((l) => <li key={l.id} data-testid="ref-name">{l.display}</li>)}
          </ul>
        </div>
      ) : (
        <div data-testid="reference">
          {mock && (
            <p className={r.notice} data-testid="ref-synthetic">
              The film library is not reachable, so the example films below are drawn shapes, not radiographs, and the text is a short stand-in. Reload the page to try the library again.
            </p>
          )}
          <dl className={r.index} data-testid="ref-index">
            {(['focal', 'pattern'] as const).map((k) => group(k).length > 0 && (
              <div key={k} style={{ display: 'contents' }}>
                <dt>{KIND_NOTE[k]}</dt>
                <dd>{group(k).map((l) => <a key={l.label} href={`#${l.label}`}>{l.display}</a>)}</dd>
              </div>
            ))}
            {(q.data?.normal_examples.length ?? 0) > 0 && <div style={{ display: 'contents' }}><dt>For comparison</dt><dd><a href="#normal">Normal films</a></dd></div>}
          </dl>
          <label className={r.toggle}>
            <input type="checkbox" checked={outline} onChange={(e) => setOutline(e.target.checked)} data-testid="ref-outline-toggle" />
            Show the expert outlines on the example films
          </label>

          {labels.map((l) => <Entry key={l.label} l={l} outline={outline} known={known} />)}

          {(q.data?.normal_examples.length ?? 0) > 0 && (
            <section className={r.entry} id="normal" aria-labelledby="ref-normal" data-testid="ref-normal">
              <div className={r.entryHead}><h2 className={r.h2} id="ref-normal">Normal films</h2></div>
              <p className={r.oneLiner}>About half the films you read are normal. Knowing what nothing looks like is half the skill.</p>
              <ul className={r.films}>
                {q.data!.normal_examples.map((ex, i) => <li key={ex.case_id || i}><ExampleFilm ex={ex} outline={false} alt="Normal chest radiograph" /></li>)}
              </ul>
            </section>
          )}
          <p className={p.mutedSmall} style={{ marginTop: 18 }}>
            {EXAMPLES_NOTE} They are de-identified research radiographs with radiologist outlines (ChestX-Det). Radiopaedia is linked, never copied.
            Sources and licences are on the <Link to="/about">About page</Link>. For education, not for clinical use.
          </p>
        </div>
      )}
    </PageShell>
  );
}
