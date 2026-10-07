// /reference — the finding library, grouped by scan type: every finding type Blindspot trains, with its definition,
// key signs, mimics, a search tip, example films (or CT / MR slices) with the reference outline, normal films, and a
// Radiopaedia link (link only). Round 5: "Signs to know" schematics under each entry, and a Signs tab (?tab=signs)
// listing every schematic, including signs no graded finding carries yet (bat-wing, Kerley B).
// Content comes from GET /api/reference (teaching cards + annotated example films from a separate reference set);
// nothing here is written by a model at view time. The fetch, guard and types are the reading room's
// (api/reference.ts, reference/guard.ts), so this page and the reference drawer share one cached payload; only the
// page layout (all thirteen entries in one report column) is local.
import { useEffect, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Link, useLocation, useSearchParams } from 'react-router-dom';
import { apiMode, assetUrl } from '../api/client';
import { FOCAL_LABELS, labelDisplay, MODALITIES, MODALITY_DISPLAY, PATTERN_LABELS, VOLUMETRIC_LABELS } from '../api/labels';
import { fetchReference, type ReferenceExample, type ReferenceFilm, type ReferenceLabel } from '../api/reference';
import { ProvenanceBadge } from '../app/ProvenanceBadge';
import { PageShell } from '../app/Shell';
import { useTitle } from '../app/useTitle';
import { PROVENANCE } from '../rail/debriefCopy';
import { EXAMPLES_NOTE } from '../reference';
import { uiTerms } from '../reference/guard';
import { SchematicBadge, SignCard, SignsToKnow } from '../reference/SignsToKnow';
import { NOT_GRADED, useSignSchematics } from '../reference/signsData';
import { VolumeExample } from '../reference/VolumeExample';
import type { Modality } from '../types/contracts';
import p from './Pages.module.css';
import r from './Reference.module.css';

const KIND_NOTE = { focal: 'Marked on the film', pattern: 'Called for the whole film' } as const;
const KIND_NOTE_VOL = { focal: 'Marked on a slice', pattern: 'Called for the whole study' } as const;
const SCAN_NOTE: Record<Modality, string> = {
  cxr: 'Example films with the radiologists\' outline.',
  ct: 'Example studies with the reference segmentation; scroll the slices under each one.',
  mr: 'Example studies with the reference segmentation; scroll the slices under each one.',
};

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
      <figcaption className={r.filmCap}>
        {f?.relative_location ? `${f.relative_location.charAt(0).toUpperCase()}${f.relative_location.slice(1)} ` : ''}
        <ProvenanceBadge provenance={ex.provenance} modality={ex.modality} short />
      </figcaption>
    </figure>
  );
}

function Entry({ l, outline, known }: { l: ReferenceLabel; outline: boolean; known: Set<string> }) {
  const confused = l.commonly_confused_with.filter((x) => x !== l.label);
  const volumetric = l.modality !== 'cxr';
  const scan = MODALITY_DISPLAY[l.modality].long.toLowerCase();
  return (
    <section className={r.entry} id={l.label} aria-labelledby={`ref-${l.label}`} data-testid="ref-entry" data-modality={l.modality}>
      <div className={r.entryHead}>
        <h2 className={r.h2} id={`ref-${l.label}`}>{l.display}</h2>
        <span className={r.kind}>{(volumetric ? KIND_NOTE_VOL : KIND_NOTE)[l.kind]}</span>
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
      <SignsToKnow label={l.label} className={r.signs} />
      {l.search_tip && <p className={r.tip}><strong>Where to look</strong>{uiTerms(l.search_tip)}</p>}
      {confused.length > 0 && (
        <p className={r.confused}>
          Commonly confused with:{' '}
          {confused.map((x, i) => (
            <span key={x}>{i > 0 ? ', ' : ''}{known.has(x) ? <a href={`#${x}`}>{labelDisplay(x)}</a> : labelDisplay(x)}</span>
          ))}
        </p>
      )}
      <h3 className={r.h3}>{volumetric ? 'Example studies' : 'Example films'}{l.examples.length ? ` (${l.examples.length})` : ''}</h3>
      {l.examples.length ? (
        <ul className={r.films}>
          {l.examples.map((ex, i) => (
            <li key={ex.case_id || i}>
              {ex.volume
                ? <VolumeExample ex={ex} outline={outline} alt={`${MODALITY_DISPLAY[ex.modality].long} with ${l.display.toLowerCase()}`} />
                : <ExampleFilm ex={ex} outline={outline} alt={`Chest radiograph with ${l.display.toLowerCase()}`} />}
            </li>
          ))}
        </ul>
      ) : <p className={r.none}>No example {volumetric ? `${scan} studies` : 'films'} are loaded for this finding yet.</p>}
      <p className={r.foot}>
        {l.review_status && <span className={r.status}>{PROVENANCE[l.review_status] ?? l.review_status.replace(/_/g, ' ')}</span>}
        {l.radiopaedia_url && <a href={l.radiopaedia_url} target="_blank" rel="noreferrer">Read more on Radiopaedia</a>}
      </p>
    </section>
  );
}

/** The Signs tab: every schematic, the ones of graded findings first, then the rest with a "not graded yet" note. */
function SignsTab({ known }: { known: Set<string> }) {
  const q = useSignSchematics();
  if (q.isPending) return <p className={p.muted}>Loading the signs…</p>;
  const all = q.data ?? [];
  if (q.isError || all.length === 0) return <p className={r.notice} data-testid="signs-offline">The sign drawings did not load. Check your connection, then reload the page.</p>;
  const graded = all.filter((sg) => sg.labels.some((l) => known.has(l)));
  const other = all.filter((sg) => !sg.labels.some((l) => known.has(l)));
  return (
    <div data-testid="signs-tab">
      <div className={r.signsHead}>
        <p className={p.lede} style={{ margin: 0 }}>{all.length} signs, drawn and explained. A sign is a shape to look for, not a diagnosis; the finding it points to is named under each drawing.</p>
        <SchematicBadge />
      </div>
      <section className={r.entry} aria-labelledby="signs-graded">
        <div className={r.entryHead}><h2 className={r.h2} id="signs-graded">Signs of the findings Blindspot grades</h2></div>
        <ul className={r.signGrid} data-testid="signs-graded">
          {graded.map((sg) => <SignCard key={sg.id} sign={sg} showLabels />)}
        </ul>
      </section>
      {other.length > 0 && (
        <section className={r.entry} aria-labelledby="signs-other">
          <div className={r.entryHead}><h2 className={r.h2} id="signs-other">Other signs worth knowing</h2><span className={r.kind}>{NOT_GRADED}</span></div>
          <ul className={r.signGrid} data-testid="signs-other">
            {other.map((sg) => <SignCard key={sg.id} sign={sg} notGraded />)}
          </ul>
        </section>
      )}
      <p className={p.mutedSmall} style={{ marginTop: 18 }}>
        Schematic drawings are AI-drafted line sketches, not radiographs, and have not been reviewed yet. Radiopaedia is linked, never copied. For education, not for clinical use.
      </p>
    </div>
  );
}

export function ReferencePage() {
  useTitle('Finding library');
  const mock = apiMode().mode === 'mock';
  // Same key and fetcher as the reading room's reference drawer: one cached payload for both.
  const q = useQuery({ queryKey: ['reference'], queryFn: fetchReference, retry: false, staleTime: Infinity });
  const [outline, setOutline] = useState(true);
  const { hash } = useLocation();
  const [params, setParams] = useSearchParams();
  const tab: 'findings' | 'signs' = params.get('tab') === 'signs' ? 'signs' : 'findings';
  const setTab = (t: 'findings' | 'signs') => setParams(t === 'signs' ? { tab: 'signs' } : {}, { replace: true });
  // /reference#nodule lands on that entry once the library has loaded.
  useEffect(() => {
    if (q.data && hash.length > 1) document.getElementById(decodeURIComponent(hash.slice(1)))?.scrollIntoView();
  }, [q.data, hash]);

  const labels = q.data?.labels ?? [];
  const known = new Set(labels.map((l) => l.label));
  const offline = q.isError || (q.data && labels.length === 0);
  // Grouped by scan type (chest films first), then marked-on-the-film before whole-film findings.
  const scans = MODALITIES.filter((m) => labels.some((l) => l.modality === m));
  const group = (m: Modality, kind: 'focal' | 'pattern') => labels.filter((l) => l.modality === m && l.kind === kind);
  const normals = q.data?.normal_examples ?? [];
  const normalsOf = (m: Modality) => normals.filter((n) => n.modality === m);
  const many = scans.length > 1;

  return (
    <PageShell width={860}>
      <h1 className={p.h1}>Finding library</h1>
      <div className={r.tabs} role="tablist" aria-label="Library sections">
        <button type="button" role="tab" aria-selected={tab === 'findings'} className={`${r.tab} ${tab === 'findings' ? r.tabOn : ''}`} onClick={() => setTab('findings')} data-testid="ref-tab-findings">Findings</button>
        <button type="button" role="tab" aria-selected={tab === 'signs'} className={`${r.tab} ${tab === 'signs' ? r.tabOn : ''}`} onClick={() => setTab('signs')} data-testid="ref-tab-signs">Signs</button>
      </div>
      {tab === 'signs' ? <SignsTab known={known} /> : <>
      <p className={p.lede} data-testid="ref-lede">
        {many
          ? `The ${labels.length} findings Blindspot trains, by scan type: what each one is, the signs to look for, what gets mistaken for it, and example films or studies with the reference outline.`
          : 'The thirteen findings Blindspot trains: what each one is, the signs to look for, what gets mistaken for it, and example films with the radiologist\'s outline.'}
      </p>

      {q.isPending ? <p className={p.muted}>Loading the library…</p> : offline ? (
        <div data-testid="ref-offline">
          <p className={r.notice}>
            The library did not load. Check your connection, then reload the page. These are the findings it covers:
          </p>
          <ul className={r.names} data-testid="ref-names">
            {[...FOCAL_LABELS, ...PATTERN_LABELS, ...VOLUMETRIC_LABELS].map((l) => <li key={l.id} data-testid="ref-name">{l.display}</li>)}
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
            {scans.map((m) => (['focal', 'pattern'] as const).map((k) => group(m, k).length > 0 && (
              <div key={`${m}-${k}`} style={{ display: 'contents' }}>
                <dt>{many ? `${MODALITY_DISPLAY[m].long} · ` : ''}{(m === 'cxr' ? KIND_NOTE : KIND_NOTE_VOL)[k]}</dt>
                <dd>{group(m, k).map((l) => <a key={l.label} href={`#${l.label}`}>{l.display}</a>)}</dd>
              </div>
            )))}
            {normals.length > 0 && <div style={{ display: 'contents' }}><dt>For comparison</dt><dd><a href="#normal">Normal films</a></dd></div>}
          </dl>
          <label className={r.toggle}>
            <input type="checkbox" checked={outline} onChange={(e) => setOutline(e.target.checked)} data-testid="ref-outline-toggle" />
            Show the expert outlines on the examples
          </label>

          {scans.map((m) => (
            <section key={m} className={r.scan} id={`scan-${m}`} aria-labelledby={`ref-scan-${m}`} data-testid="ref-scan-group" data-modality={m}>
              {many && (
                <div className={r.scanHead}>
                  <h2 className={r.scanTitle} id={`ref-scan-${m}`}>{MODALITY_DISPLAY[m].long}</h2>
                  <p className={r.scanNote}>{SCAN_NOTE[m]}</p>
                </div>
              )}
              {[...group(m, 'focal'), ...group(m, 'pattern')].map((l) => <Entry key={l.label} l={l} outline={outline} known={known} />)}
              {m === 'cxr' && normalsOf('cxr').length > 0 && (
                <section className={r.entry} id="normal" aria-labelledby="ref-normal" data-testid="ref-normal">
                  <div className={r.entryHead}><h2 className={r.h2} id="ref-normal">Normal films</h2></div>
                  <p className={r.oneLiner}>About half the films you read are normal. Knowing what nothing looks like is half the skill.</p>
                  <ul className={r.films}>
                    {normalsOf('cxr').map((ex, i) => <li key={ex.case_id || i}><ExampleFilm ex={ex} outline={false} alt="Normal chest radiograph" /></li>)}
                  </ul>
                </section>
              )}
              {m !== 'cxr' && normalsOf(m).length > 0 && (
                <section className={r.entry} id={`normal-${m}`} aria-labelledby={`ref-normal-${m}`} data-testid="ref-normal-volume">
                  <div className={r.entryHead}><h2 className={r.h2} id={`ref-normal-${m}`}>No lesion, for comparison</h2></div>
                  <p className={r.oneLiner}>A slab where the dataset labelled no lesion; not certified normal by a radiologist.</p>
                  <ul className={r.films}>
                    {normalsOf(m).map((ex, i) => <li key={ex.case_id || i}>{ex.volume
                      ? <VolumeExample ex={{ ...ex, finding: null }} outline={false} alt={`${MODALITY_DISPLAY[m].long} with no labelled lesion`} />
                      : <ExampleFilm ex={ex} outline={false} alt={`${MODALITY_DISPLAY[m].long} with no labelled lesion`} />}</li>)}
                  </ul>
                </section>
              )}
            </section>
          ))}
          <p className={p.mutedSmall} style={{ marginTop: 18 }}>
            {EXAMPLES_NOTE} Chest films are de-identified research radiographs with radiologist outlines (ChestX-Det)
            {many ? '; CT and MR studies are slabs from the Medical Segmentation Decathlon with their reference segmentations (CC BY-SA 4.0)' : ''}. Radiopaedia is linked, never copied.
            Sources and licences are on the <Link to="/about">About page</Link>. For education, not for clinical use.
          </p>
        </div>
      )}
      </>}
    </PageShell>
  );
}
