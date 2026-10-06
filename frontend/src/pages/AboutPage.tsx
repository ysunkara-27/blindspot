// /about — data sources, attributions, limits, disclaimer. Uses GET /api/about when available.
import { useQuery } from '@tanstack/react-query';
import { api } from '../api/client';
import { DISCLAIMER, PageShell } from '../app/Shell';
import s from './Pages.module.css';

type Json = string | number | boolean | null | Json[] | { [k: string]: Json };
const human = (k: string) => k.replace(/_/g, ' ').replace(/^./, (c) => c.toUpperCase());

function Value({ v }: { v: Json }) {
  if (v == null || typeof v !== 'object') {
    const str = String(v ?? '');
    return /^https?:\/\//.test(str) ? <a href={str} target="_blank" rel="noreferrer">{str}</a> : <>{str}</>;
  }
  if (Array.isArray(v)) return <ul className={s.list}>{v.map((x, i) => <li key={i}><Value v={x} /></li>)}</ul>;
  const o = v as Record<string, Json>;
  const title = o.name ?? o.title ?? o.label;
  return (
    <span>
      {title != null && <strong>{String(title)}. </strong>}
      {Object.entries(o).filter(([k]) => !['name', 'title', 'label'].includes(k)).map(([k, x]) => (
        <span key={k} className={s.kv}><span className={s.muted}>{human(k)}:</span> <Value v={x} /> </span>
      ))}
    </span>
  );
}

export function AboutPage() {
  const q = useQuery({ queryKey: ['about'], queryFn: api.about, retry: false });
  const data = q.data && typeof q.data === 'object' ? (q.data as Record<string, Json>) : null;
  return (
    <PageShell>
      <h1 className={s.h1}>About Blindspot</h1>
      <p className={s.lede}>A chest X-ray perception trainer. You mark what you see; we score your marks against radiologist outlines, replay your search, and explain each miss from facts the software computed.</p>
      {data ? (
        <div data-testid="about-api">
          {Object.entries(data).map(([k, v]) => (
            <section key={k} className={s.ruled}>
              <h2 className={s.h2}>{human(k)}</h2>
              <Value v={v} />
            </section>
          ))}
        </div>
      ) : (
        <div data-testid="about-static">
          <section className={s.ruled}>
            <h2 className={s.h2}>Data</h2>
            <p><strong>ChestX-Det.</strong> Expert instance-level outlines for 13 thoracic findings on about 3,500 frontal chest radiographs, drawn on images from NIH ChestX-ray14. Lian J, et al. A Structure-Aware Relation Network for Thoracic Diseases Detection and Segmentation. IEEE Transactions on Medical Imaging, 2021.</p>
            <p><strong>NIH ChestX-ray14.</strong> Wang X, Peng Y, Lu L, Lu Z, Bagheri M, Summers RM. ChestX-ray8: Hospital-scale chest X-ray database and benchmarks on weakly-supervised classification and localization of common thorax diseases. CVPR 2017. Images courtesy of the NIH Clinical Center.</p>
            <p><strong>Anatomy.</strong> Lung, heart and mediastinum outlines come from a public segmentation model (TorchXRayVision), used to name zones and review areas.</p>
          </section>
          <section className={s.ruled}>
            <h2 className={s.h2}>How the feedback works</h2>
            <p>Ground truth always comes from the radiologist annotations. The tutor (Claude) only explains facts the software computed: which findings you found, where they are, and how your search moved. Every debrief is checked by a rule-based validator; if it fails, you see a built-in explanation instead. Each debrief shows whether its teaching content has been reviewed by a student or a radiologist.</p>
          </section>
          <section className={s.ruled}>
            <h2 className={s.h2}>Limits</h2>
            <ul className={s.list}>
              <li>Miss types are based on your cursor, loupe and zoom — a proxy for where you looked, not eye tracking.</li>
              <li>The images come from a single US hospital, and expert labels contain some noise.</li>
              <li>Pixel spacing is unknown for these images, so sizes are never given in centimetres.</li>
              <li>Patient right is shown on the image left, as on a standard frontal film.</li>
            </ul>
          </section>
        </div>
      )}
      <section className={s.ruled}>
        <h2 className={s.h2}>Disclaimer</h2>
        <p>{DISCLAIMER} Blindspot gives no advice about patient care. Feedback is for practice only and may be wrong; use the "This seems wrong" link to flag it.</p>
      </section>
    </PageShell>
  );
}
