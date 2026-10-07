// "What you can read": one card per scan type. Counts come from GET /api/health `cases_by_modality` when the server
// sends them (else the static numbers); the "Segmented by …" line comes from GET /api/about `provenance` when present
// (else the static copy of config/provenance.yaml). Each button opens /start with that scan type preselected.
import { useQuery } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import { api, apiMode } from '../api/client';
import { MODALITY_DISPLAY } from '../api/labels';
import { availableModalities } from '../api/sessionOptions';
import { guardProvenance, PROVENANCE_DATASETS, provenanceText, type Provenance } from '../app/provenance';
import { useNarrow } from '../app/useMediaQuery';
import { ServerLine } from '../pages/ServerLine';
import { useHealth } from '../tutor/health';
import type { Modality } from '../types/contracts';
import l from '../pages/Landing.module.css';

type Card = {
  modality: Modality;
  /** Shown when the server has not said how many cases it holds. */
  staticCount: string;
  /** What the count describes, after a live number ("85 studies · pancreas and liver tumours"). */
  subject: string;
  noun: [string, string];
  text: string;
  /** config/provenance.yaml keys whose "Segmented by" lines belong on this card. */
  provenanceKeys: string[];
  button: string;
};

const CARDS: Card[] = [
  {
    modality: 'cxr', staticCount: '3,400+ films', subject: '13 finding types', noun: ['film', 'films'],
    text: 'Frontal chest radiographs: pneumothorax, nodule, effusion, consolidation and more. About half the films are normal.',
    provenanceKeys: ['chestx-det'], button: 'Read chest X-rays',
  },
  {
    modality: 'ct', staticCount: 'Pancreas and liver tumours', subject: 'pancreas and liver tumours', noun: ['study', 'studies'],
    text: 'Axial slabs of contrast CT, cropped around one lesion. Scroll the slices, mark the lesion where you see it, and size it.',
    provenanceKeys: ['Task07_Pancreas', 'Task08_HepaticVessel'], button: 'Read abdominal CT',
  },
  {
    modality: 'mr', staticCount: 'Gliomas', subject: 'gliomas', noun: ['study', 'studies'],
    text: 'Axial slabs of post-contrast T1 brain MRI. The reference marks oedema, core and enhancing tumour; marking any part counts.',
    provenanceKeys: ['Task01_BrainTumour'], button: 'Read brain MRI',
  },
];

type Obj = Record<string, unknown>;
const isObj = (v: unknown): v is Obj => typeof v === 'object' && v !== null && !Array.isArray(v);

/** The server's provenance map (GET /api/about), keyed as config/provenance.yaml; empty when it sends none. */
function serverProvenance(about: unknown): Record<string, Provenance> {
  if (!isObj(about)) return {};
  const pv = about.provenance;
  const map = isObj(pv) ? (isObj(pv.datasets) ? pv.datasets : pv) : null;
  if (!map) return {};
  const out: Record<string, Provenance> = {};
  for (const [k, b] of Object.entries(map)) { const g = guardProvenance(b); if (g) out[k] = g; }
  return out;
}

function countLine(card: Card, by: Record<string, number> | null | undefined): string {
  const n = by?.[card.modality];
  if (!n) return card.staticCount;
  return `${n.toLocaleString()} ${n === 1 ? card.noun[0] : card.noun[1]} · ${card.subject}`;
}

export function ScanCards() {
  const health = useHealth();
  const about = useQuery({ queryKey: ['about'], queryFn: api.about, retry: false, staleTime: 5 * 60_000 });
  const narrow = useNarrow();
  const mock = apiMode().mode === 'mock';
  const by = mock ? null : health.data?.cases_by_modality;
  const available: Modality[] | null = mock ? ['cxr'] : health.data ? availableModalities(health.data) : null;
  const fromServer = serverProvenance(about.data);
  const volumes = !!available && (available.includes('ct') || available.includes('mr'));
  return (
    <section className={l.band} aria-labelledby="read-h" data-testid="what-you-can-read">
      <div className={l.inner}>
        <h2 id="read-h" className={l.h2}>What you can read</h2>
        <p className={l.lede} data-testid={volumes ? 'scan-types-line' : undefined}>
          {volumes ? 'Chest X-ray, abdominal CT and brain MRI.' : 'Chest X-rays now; abdominal CT and brain MRI once their studies are loaded.'}
        </p>
        <ul className={`${l.three} ${l.cards}`}>
          {CARDS.map((c) => {
            // Known to be missing from the library: the card still explains, but cannot start.
            const missing = !!available && !available.includes(c.modality);
            const prov = c.provenanceKeys.map((k) => fromServer[k] ?? PROVENANCE_DATASETS[k]).filter(Boolean);
            return (
              <li key={c.modality} className={l.card} data-testid={`scan-card-${c.modality}`} data-available={missing ? '0' : '1'}>
                <h3 className={l.cardTitle}>{MODALITY_DISPLAY[c.modality].long}</h3>
                <p className={l.cardCount} data-testid={`scan-count-${c.modality}`}>{countLine(c, by)}</p>
                <p className={l.cardText}>{c.text}</p>
                <ul className={l.provList} aria-label="Who made the reference labels">
                  {prov.map((p) => <li key={p.dataset} data-testid="scan-provenance">{provenanceText(p)}</li>)}
                </ul>
                <div className={l.cardFoot}>
                  {narrow ? (
                    <span className={l.cardNote}>Open on a computer to read.</span>
                  ) : missing ? (
                    <span className={l.cardNote} data-testid={`scan-start-${c.modality}`}>Not loaded on this server yet.</span>
                  ) : (
                    <Link to={`/start?modality=${c.modality}`} className={l.cardButton} data-testid={`scan-start-${c.modality}`}>{c.button}</Link>
                  )}
                </div>
              </li>
            );
          })}
        </ul>
        <ServerLine className={l.health} />
      </div>
    </section>
  );
}
