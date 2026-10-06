// /about — a readable report: what Blindspot does, how your search is estimated, data sources with citations and
// licences, how to read the badges, limitations, privacy, what is planned, where the code is, disclaimer.
// Uses GET /api/about when available; falls back to the same text built in.
import { useQuery } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import { api } from '../api/client';
import { DISCLAIMER, PageShell } from '../app/Shell';
import rail from '../rail/Rail.module.css';
import { PROVENANCE, SOURCE } from '../rail/debriefCopy';
import { useTitle } from '../app/useTitle';
import a from './About.module.css';
import s from './Pages.module.css';

type Source = { name: string; role?: string; citation?: string; acknowledgment?: string; url?: string; license?: string };
type About = { tutor?: string; datasets: Source[]; limitations: string[]; privacy?: string; links: { name: string; note?: string; url?: string }[] };

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
};

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
  return {
    tutor: str(v.tutor),
    datasets: datasets.length ? datasets : FALLBACK.datasets,
    limitations: limitations.length ? limitations : FALLBACK.limitations,
    privacy: str(v.privacy),
    links: links.length ? links : FALLBACK.links,
  };
}

export function AboutPage() {
  useTitle('About');
  const q = useQuery({ queryKey: ['about'], queryFn: api.about, retry: false });
  const about = guard(q.data);
  return (
    <PageShell>
      <h1 className={s.h1}>About Blindspot</h1>
      <p className={s.lede}>
        A chest X-ray perception trainer for medical students and anyone curious about how films are read. You mark what
        you see; Blindspot scores your marks against radiologist outlines, replays where you looked, and explains each
        miss from facts the software computed.
      </p>

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
        <ul className={s.list}>{about.limitations.map((l) => <li key={l}>{l}</li>)}</ul>
      </section>

      <section className={s.ruled} data-testid="about-privacy">
        <h2 className={s.h2}>Privacy</h2>
        {about.privacy && <p>{about.privacy}</p>}
        <p>
          Your reads are stored so your reading log can be built: your marks, your confidence, and the cursor, magnifier
          and zoom trace for each film, with the name or code you gave, if any. This browser remembers a reader id so
          you can pick up where you left off; “Start as someone new” on the first page clears it.
        </p>
      </section>

      <section className={s.ruled} data-testid="about-next">
        <h2 className={s.h2}>What's next</h2>
        <p>These are plans, not promises, and nothing here has a date.</p>
        <ul className={s.list}>
          <li>More finding types, and more example films for each one in the finding library.</li>
          <li>Limb films and other radiographs beyond the chest.</li>
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
