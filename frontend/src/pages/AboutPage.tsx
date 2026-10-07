// /about — a readable report: what Blindspot does, how your search is estimated, data sources with citations and
// licences, how to read the badges, limitations, privacy, what is planned, where the code is, disclaimer.
// Uses GET /api/about when available; falls back to the same text built in.
import { useQuery } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import { api, apiMode } from '../api/client';
import { MODALITY_DISPLAY } from '../api/labels';
import { availableModalities } from '../api/sessionOptions';
import { guardProvenance, MSD_CITATION, PROVENANCE_DATASETS, provenanceText, type Provenance } from '../app/provenance';
import { ProvenanceBadge } from '../app/ProvenanceBadge';
import { DISCLAIMER, PageShell } from '../app/Shell';
import { useHealth } from '../tutor/health';
import type { Modality } from '../types/contracts';
import rail from '../rail/Rail.module.css';
import { PROVENANCE, SOURCE } from '../rail/debriefCopy';
import { useTitle } from '../app/useTitle';
import a from './About.module.css';
import s from './Pages.module.css';

type Source = { name: string; role?: string; citation?: string; acknowledgment?: string; url?: string; license?: string };
/** One row of "Where the reference truth comes from": a provenance block plus the scan type it labels. */
type ProvRow = Provenance & { key: string; modality: Modality | null };
type About = {
  tutor?: string; datasets: Source[]; limitations: string[]; privacy?: string; links: { name: string; note?: string; url?: string }[];
  /** From GET /api/about `provenance` (config/provenance.yaml) when the server sends it; else the static copy. */
  provenance: ProvRow[]; provenanceFromServer: boolean;
};

const STATIC_PROVENANCE: ProvRow[] = Object.entries(PROVENANCE_DATASETS).map(([key, d]) => ({ ...d, key }));

// Licence/terms lines for the sources we use, shown when the API entry has no `license` field yet.
export const REPO_URL = 'https://github.com/ysunkara-27/blindspot';

const KNOWN_TERMS: Record<string, string> = {
  'ChestX-Det': 'Annotations by Deepwise AI Lab, released under the Apache-2.0 licence.',
  'NIH ChestX-ray14': 'Public release by the NIH Clinical Center; users are asked to cite the paper and acknowledge the NIH Clinical Center.',
  TorchXRayVision: 'Open-source library, Apache-2.0 licence.',
};

const FALLBACK: About = {
  datasets: [
    { name: 'ChestX-Det', role: 'Instance-level expert annotations (polygons) for 13 thoracic findings, used as the reference standard for scoring.', citation: 'Lian J, Liu J, Zhang S, et al. A Structure-Aware Relation Network for Thoracic Diseases Detection and Segmentation. IEEE Transactions on Medical Imaging, 2021.', url: 'https://github.com/Deepwise-AILab/ChestX-Det-Dataset' },
    { name: 'NIH ChestX-ray14', role: 'Source radiographs for ChestX-Det.', citation: 'Wang X, Peng Y, Lu L, Lu Z, Bagheri M, Summers RM. ChestX-ray8: Hospital-scale Chest X-ray Database and Benchmarks on Weakly-Supervised Classification and Localization of Common Thorax Diseases. IEEE CVPR 2017.', acknowledgment: 'Images courtesy of the NIH Clinical Center.', url: 'https://nihcc.app.box.com/v/ChestXray-NIHCC' },
    { name: 'TorchXRayVision', role: 'Anatomy segmentation (lungs, heart, hila, mediastinum) used to name zones and review areas.', citation: 'Cohen JP, Viviano JD, Bertin P, et al. TorchXRayVision: A library of chest X-ray datasets and models. MIDL 2022.', url: 'https://github.com/mlmed/torchxrayvision' },
  ],
  limitations: [
    'Where you looked is estimated from your cursor, magnifier and zoom — a proxy for gaze, not eye tracking.',
    'Images come from a single US centre (NIH Clinical Center); findings may not generalise to other populations or equipment.',
    'Expert labels contain some noise, and not every abnormality on an image is necessarily annotated.',
    'Pixel spacing is unknown for these images, so sizes are never given in centimetres.',
  ],
  links: [{ name: 'Radiopaedia', note: 'Linked from teaching cards only; no content is copied.' }],
  provenance: STATIC_PROVENANCE,
  provenanceFromServer: false,
};

const MODALITY_OF_KEY: Record<string, Modality> = Object.fromEntries(Object.entries(PROVENANCE_DATASETS).map(([k, d]) => [k, d.modality]));

type Obj = Record<string, unknown>;
const isObj = (v: unknown): v is Obj => typeof v === 'object' && v !== null && !Array.isArray(v);
const str = (v: unknown) => (typeof v === 'string' ? v : undefined);

function guard(v: unknown): About {
  if (!isObj(v)) return FALLBACK;
  const datasets = (Array.isArray(v.datasets) ? v.datasets : []).flatMap((d) => (isObj(d) && typeof d.name === 'string'
    ? [{ name: d.name, role: str(d.role), citation: str(d.citation), acknowledgment: str(d.acknowledgment) ?? str(d.acknowledgement), url: str(d.url), license: str(d.license) ?? str(d.licence) }]
    : []));
  // The server's list still carries a line about an early usability test and calls the magnifier a loupe.
  const limitations = (Array.isArray(v.limitations) ? v.limitations : [])
    .filter((x): x is string => typeof x === 'string' && !/^pilot\b/i.test(x.trim()))
    .map((x) => x.replace(/\bloupe\b/g, 'magnifier'));
  const links = (Array.isArray(v.links) ? v.links : []).flatMap((l) => (isObj(l) && typeof l.name === 'string' ? [{ name: l.name, note: str(l.note), url: str(l.url) }] : []));
  // `provenance`: either the YAML map {key: block} or a list of blocks (with `key` / `id`).
  const pv = v.provenance;
  const provEntries: [string, unknown][] = Array.isArray(pv)
    ? pv.map((b, i) => [isObj(b) ? str(b.key) ?? str(b.id) ?? String(i) : String(i), b])
    : isObj(pv) ? Object.entries(isObj(pv.datasets) ? pv.datasets : pv) : [];
  const provenance = provEntries.flatMap(([key, b]) => {
    const g = guardProvenance(b);
    if (!g) return [];
    const m = isObj(b) && typeof b.modality === 'string' ? b.modality : MODALITY_OF_KEY[key];
    const modality: Modality | null = m === 'cxr' || m === 'ct' || m === 'mr' ? m : null;
    return [{ ...g, key, modality }];
  });
  return {
    tutor: str(v.tutor),
    datasets: datasets.length ? datasets : FALLBACK.datasets,
    limitations: limitations.length ? limitations : FALLBACK.limitations,
    privacy: str(v.privacy),
    links: links.length ? links : FALLBACK.links,
    provenance: provenance.length ? provenance : STATIC_PROVENANCE,
    provenanceFromServer: provenance.length > 0,
  };
}

export function AboutPage() {
  useTitle('About');
  const q = useQuery({ queryKey: ['about'], queryFn: api.about, retry: false });
  const about = guard(q.data);
  const health = useHealth();
  const have = apiMode().mode === 'mock' ? (['cxr'] as Modality[]) : availableModalities(health.data);
  const volumes = have.includes('ct') || have.includes('mr');
  return (
    <PageShell>
      <h1 className={s.h1}>About Blindspot</h1>
      <p className={s.lede}>
        A {volumes ? 'radiology' : 'chest X-ray'} perception trainer for medical students and anyone curious about how {volumes ? 'scans' : 'films'} are read. You mark what
        you see; Blindspot scores your marks against expert outlines, replays where you looked, and explains each
        miss from facts the software computed.
      </p>

      <section className={s.ruled} data-testid="about-scans">
        <h2 className={s.h2}>Scan types</h2>
        <p>
          {volumes
            ? 'You choose the scan type on the start screen. The reading room works the same way for each: pick what you see, click where it is, say how sure you are, submit, then see the expert reference and how you looked.'
            : 'Chest X-rays today. Abdominal CT and brain MRI are built and will appear on the start screen once their studies are loaded; the reading room works the same way for each.'}
        </p>
        <dl className={a.scans}>
          <dt>{MODALITY_DISPLAY.cxr.long}</dt>
          <dd>Frontal chest radiographs. Findings are outlined by three board-certified radiologists (ChestX-Det). About half the films are normal.</dd>
          <dt>{MODALITY_DISPLAY.ct.long}</dt>
          <dd>Axial slabs from contrast CT, cropped around one lesion from the Medical Segmentation Decathlon (pancreas, liver). You scroll the slices, mark on the slice where you see the lesion, and may be asked for its size. Organs in the reference masks become zones, not findings.</dd>
          <dt>{MODALITY_DISPLAY.mr.long}</dt>
          <dd>Axial slabs of post-contrast T1 brain MRI from the same collection (BraTS). The reference segmentation has oedema, core and enhancing parts; marking any part of the tumour counts.</dd>
        </dl>
        <p className={s.mutedSmall} data-testid="about-slab-caveat">
          A "normal" CT or MR study here is a slab where the dataset labelled no lesion; not certified normal by a radiologist.
          Public segmentation sets are not exhaustive either, so a mark the reference does not label is reported as "not in the reference" and never penalised.
        </p>
      </section>

      <section className={s.ruled} data-testid="about-provenance">
        <h2 className={s.h2}>Where the reference truth comes from</h2>
        <p>Every case carries a badge saying who made its reference labels. These are the datasets behind the badges{about.provenanceFromServer ? '' : ' (a copy of the configuration; the server did not send its own list)'}.</p>
        <div className={a.tableWrap}>
          <table className={a.provTable} data-testid="provenance-table">
            <thead><tr><th scope="col">Scan type</th><th scope="col">Dataset</th><th scope="col">Labels made by</th><th scope="col">Readers</th><th scope="col">Licence</th></tr></thead>
            <tbody>
              {about.provenance.map((d) => (
                <tr key={d.key} data-testid="provenance-row" data-key={d.key}>
                  <td>{d.modality ? MODALITY_DISPLAY[d.modality].short : '—'}</td>
                  <td>{d.url ? <a href={d.url} target="_blank" rel="noreferrer">{d.dataset}</a> : d.dataset}{d.institution && <span className={a.inst}>{d.institution}</span>}</td>
                  <td>{d.segmented_by}<span className={a.inst}>{d.grade === 'radiologist' ? 'Radiologist-grade' : d.grade === 'clinician' ? 'Clinician-grade' : d.grade === 'model' ? 'Model output' : 'Grade unknown'}</span></td>
                  <td>{d.readers ?? '—'}</td>
                  <td>{d.license ?? '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className={s.mutedSmall}>On a case the badge reads, for example, <ProvenanceBadge modality="cxr" /> or <span className={a.inlinePill}>{provenanceText({ ...PROVENANCE_DATASETS.Task07_Pancreas })}</span>.</p>
        <p className={a.citation} data-testid="msd-citation">{MSD_CITATION}</p>
        {about.provenance.filter((d) => d.citation && d.modality !== 'cxr').map((d) => <p key={d.key} className={a.citation}>{d.citation}</p>)}
      </section>

      <section className={s.ruled} data-testid="about-how">
        <h2 className={s.h2}>How the feedback works</h2>
        <p>Ground truth always comes from the radiologist annotations. Nothing on the film is decided by a language model.</p>
        <p>{about.tutor ?? 'Debriefs are written by Claude (Anthropic) from facts computed by Blindspot, then checked by a deterministic validator; if a debrief fails, a built-in explanation is shown instead.'}</p>
      </section>

      <section className={s.ruled} data-testid="about-search">
        <h2 className={s.h2}>How your search is estimated</h2>
        <p>
          Blindspot does not track your eyes. While you read, it records where your cursor rests, where you hold the
          magnifier and what you zoom into, and treats those three as a stand-in for where you looked.
        </p>
        <p>
          A missed finding is then sorted by what that trace shows: none of the three reached it (never looked there),
          they crossed it without stopping (looked past it), or they stayed on it and you left it unmarked (looked,
          judged it normal). The categories follow Kundel and colleagues' division of search, recognition and decision errors.
        </p>
        <p>
          The idea draws on research into inattentional blindness, how readers miss what they are not looking for. In
          Drew, Võ and Wolfe's 2013 study, most radiologists searching chest CT scans for nodules did not notice a
          gorilla placed in the lung, and eye tracking showed that many of them had looked right at it.
        </p>
        <p className={a.citation}>
          Drew T, Võ MLH, Wolfe JM. The invisible gorilla strikes again: sustained inattentional blindness in expert observers.
          Psychological Science, 2013.
        </p>
        <p>The cursor is a proxy for gaze, not a measurement of it. Treat a miss type as a strong hint about your search, not a verdict.</p>
      </section>

      <section className={s.ruled} data-testid="about-sources">
        <h2 className={s.h2}>Data and models</h2>
        <ol className={a.sources}>
          {about.datasets.map((d) => (
            <li key={d.name} className={a.source}>
              <h3 className={a.sourceName}>{d.name}</h3>
              {d.role && <p className={a.role}>{d.role}</p>}
              {d.citation && <p className={a.citation}>{d.citation}</p>}
              {d.acknowledgment && <p className={a.ack}>{d.acknowledgment}</p>}
              {(d.license ?? KNOWN_TERMS[d.name]) && <p className={a.terms} data-testid={`terms-${d.name}`}>{d.license ? `Licence: ${d.license}.` : KNOWN_TERMS[d.name]}</p>}
              {d.url && <p className={a.link}><a href={d.url} target="_blank" rel="noreferrer">{d.url.replace(/^https?:\/\//, '')}</a></p>}
            </li>
          ))}
        </ol>
        {about.links.map((l) => (
          <p key={l.name} className={s.mutedSmall}><strong>{l.name}.</strong> {l.note}</p>
        ))}
      </section>

      <section className={s.ruled} id="badges" data-testid="about-badges">
        <h2 className={s.h2}>Reading the badges on a debrief</h2>
        <dl className={a.badges}>
          <dt><span className={`${rail.sourceTag} ${rail.sourceClaude}`}>{SOURCE.live}</span></dt><dd>Claude wrote it from this attempt's facts, and it passed the validator.</dd>
          <dt><span className={`${rail.sourceTag} ${rail.sourceClaude}`}>{SOURCE.cache}</span></dt><dd>Claude explained the same facts before; the saved text is shown.</dd>
          <dt><span className={rail.sourceTag}>{SOURCE.template}</span></dt><dd>A fixed explanation filled from the facts: the tutor is offline or busy, or its draft failed the validator.</dd>
          <dt><span className={rail.badge}>{PROVENANCE.ai_draft}</span></dt><dd>The teaching cards behind it were drafted by AI and are not yet reviewed.</dd>
          <dt><span className={`${rail.badge} ${rail.prov_student_reviewed}`}>{PROVENANCE.student_reviewed}</span></dt><dd>A medical student has checked the teaching cards used.</dd>
          <dt><span className={`${rail.badge} ${rail.prov_radiologist_reviewed}`}>{PROVENANCE.radiologist_reviewed}</span></dt><dd>A radiologist has checked the teaching cards used.</dd>
        </dl>
        <p className={s.mutedSmall}>The badge shows the lowest review level among the cards a debrief draws on. Learners can flag any debrief with “This seems wrong”; flags go to the expert review queue.</p>
      </section>

      <section className={s.ruled} data-testid="about-limits">
        <h2 className={s.h2}>Limitations</h2>
        <ul className={s.list}>
          {about.limitations.map((l) => <li key={l}>{l}</li>)}
          <li>CT and MR studies are cropped slabs around one lesion, not whole scans, and their "normal" slabs are only lesion-free by the dataset's labels.</li>
          <li>CT and MR reference segmentations mostly come from a single reader; a mark the reference does not label is reported, not scored.</li>
        </ul>
      </section>

      <section className={s.ruled} data-testid="about-privacy">
        <h2 className={s.h2}>Privacy</h2>
        {about.privacy && <p>{about.privacy}</p>}
        <p>
          Your reads are stored so your reading log can be built: your marks, your confidence, and the cursor, magnifier
          and zoom trace for each film, with the name or code you gave, if any. This browser remembers a reader id so
          you can pick up where you left off; “Start as someone new” on the first page clears it.
        </p>
        <p data-testid="about-analytics">We count page views and clicks with an anonymous browser id. No names, marks or answers are sent.</p>
      </section>

      <section className={s.ruled} data-testid="about-next">
        <h2 className={s.h2}>What's next</h2>
        <p>These are plans, not promises, and nothing here has a date.</p>
        <ul className={s.list}>
          <li>More finding types, and more example films and studies for each one in the finding library.</li>
          <li>More CT and MR regions (liver, lung, colon) from the same collection, and limb films beyond the chest.</li>
        </ul>
      </section>

      <section className={s.ruled} data-testid="about-run">
        <h2 className={s.h2}>Run it yourself</h2>
        <p>
          The source code is public: <a href={REPO_URL} target="_blank" rel="noreferrer">github.com/ysunkara-27/blindspot</a>.
          Blindspot is a FastAPI service with a React reading room. With the data downloaded, <code>make setup</code>,{' '}
          <code>make data</code>, <code>make anatomy</code> and <code>make features</code> build the case bank, and{' '}
          <code>make dev</code> starts the API and the web app. Without an Anthropic key the tutor runs offline and shows
          the built-in explanations.
        </p>
        <p className={s.mutedSmall}>The images are research radiographs under the NIH terms above; they are not redistributed with the code.</p>
      </section>

      <section className={s.ruled} data-testid="about-staff">
        <h2 className={s.h2}>For instructors and reviewers</h2>
        <p>
          Instructors can open the <Link to="/cohort">cohort view</Link>; clinicians who check the teaching content use
          the <Link to="/review">expert review</Link> page. Both may ask for a reviewer code.
        </p>
      </section>

      <section className={s.ruled}>
        <h2 className={s.h2}>Disclaimer</h2>
        <p>{DISCLAIMER} Blindspot gives no advice about patient care. Feedback is for practice only and may be wrong; use the “This seems wrong” link to flag it.</p>
      </section>
    </PageShell>
  );
}
