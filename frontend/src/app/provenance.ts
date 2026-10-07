// The "___ by ___" badge: who made the reference labels behind a case. Pure helpers (unit-tested in provenance.test.ts)
// plus a STATIC COPY of config/provenance.yaml for the About page when GET /api/about does not list the datasets.
// Keep the copy in step with the YAML (it is the one place the wording is verified against each dataset's paper).
import type { Modality } from '../types/contracts';

export type ProvenanceGrade = 'radiologist' | 'clinician' | 'model' | 'unknown';
export type Provenance = {
  dataset: string;
  segmented_by: string;
  readers: number | null;
  institution: string | null;
  license: string | null;
  citation: string | null;
  url: string | null;
  grade: ProvenanceGrade;
};

/** Static copy of config/provenance.yaml `datasets` (version 1). Keyed as the YAML is. */
export const PROVENANCE_DATASETS: Record<string, Provenance & { modality: Modality }> = {
  'chestx-det': {
    modality: 'cxr',
    dataset: 'ChestX-Det',
    segmented_by: 'three board-certified radiologists',
    readers: 3,
    institution: 'Deepwise AI Lab (images: NIH Clinical Center, ChestX-ray14)',
    license: 'Apache-2.0 (annotations); NIH terms (images)',
    citation: 'Lian J et al. A structure-aware relation network for thoracic diseases detection and segmentation. IEEE TMI 2021. Images: Wang X et al. ChestX-ray8. CVPR 2017.',
    url: 'https://github.com/Deepwise-AILab/ChestX-Det-Dataset',
    grade: 'radiologist',
  },
  Task07_Pancreas: {
    modality: 'ct',
    dataset: 'Medical Segmentation Decathlon, Task07 Pancreas',
    segmented_by: 'an abdominal radiologist (single reader)',
    readers: 1,
    institution: 'Memorial Sloan Kettering Cancer Center',
    license: 'CC BY-SA 4.0',
    citation: 'Antonelli M et al. The Medical Segmentation Decathlon. Nat Commun 2022.',
    url: 'http://medicaldecathlon.com/',
    grade: 'radiologist',
  },
  Task08_HepaticVessel: {
    modality: 'ct',
    dataset: 'Medical Segmentation Decathlon, Task08 Hepatic Vessel',
    segmented_by: 'expert manual segmentation with semi-automatic vessel maps (single reader)',
    readers: 1,
    institution: 'Memorial Sloan Kettering Cancer Center',
    license: 'CC BY-SA 4.0',
    citation: 'Antonelli M et al. The Medical Segmentation Decathlon. Nat Commun 2022.',
    url: 'http://medicaldecathlon.com/',
    grade: 'clinician',
  },
  Task03_Liver: {
    modality: 'ct',
    dataset: 'Medical Segmentation Decathlon, Task03 Liver (LiTS)',
    segmented_by: 'radiologists and oncologists at several hospitals (single reader per case)',
    readers: 1,
    institution: 'IRCAD, LMU Munich and partners (LiTS)',
    license: 'CC BY-SA 4.0',
    citation: 'Bilic P et al. The Liver Tumor Segmentation Benchmark (LiTS). Med Image Anal 2023.',
    url: 'http://medicaldecathlon.com/',
    grade: 'radiologist',
  },
  Task01_BrainTumour: {
    modality: 'mr',
    dataset: 'Medical Segmentation Decathlon, Task01 Brain Tumour (BraTS)',
    segmented_by: 'trained raters to a protocol, approved by board-certified neuroradiologists',
    readers: 1,
    institution: 'BraTS consortium (UPenn and partners)',
    license: 'CC BY-SA 4.0',
    citation: 'Bakas S et al. Advancing The Cancer Genome Atlas glioma MRI collections. Sci Data 2017.',
    url: 'http://medicaldecathlon.com/',
    grade: 'radiologist',
  },
  Task06_Lung: {
    modality: 'ct',
    dataset: 'Medical Segmentation Decathlon, Task06 Lung (NSCLC-Radiomics)',
    segmented_by: 'radiation oncologists (treatment-planning contours)',
    readers: 1,
    institution: 'Maastro Clinic (TCIA)',
    license: 'CC BY-SA 4.0',
    citation: 'Aerts HJWL et al. Decoding tumour phenotype by noninvasive imaging. Nat Commun 2014.',
    url: 'http://medicaldecathlon.com/',
    grade: 'clinician',
  },
  Task10_Colon: {
    modality: 'ct',
    dataset: 'Medical Segmentation Decathlon, Task10 Colon',
    segmented_by: 'expert manual segmentation (single reader)',
    readers: 1,
    institution: 'Memorial Sloan Kettering Cancer Center',
    license: 'CC BY-SA 4.0',
    citation: 'Antonelli M et al. The Medical Segmentation Decathlon. Nat Commun 2022.',
    url: 'http://medicaldecathlon.com/',
    grade: 'clinician',
  },
};

/** Every X-ray case comes from ChestX-Det; older servers send no provenance block, so the badge defaults to it. */
export const CXR_PROVENANCE: Provenance = PROVENANCE_DATASETS['chestx-det'];

export const MSD_CITATION = 'Antonelli M, Reinke A, Bakas S, et al. The Medical Segmentation Decathlon. Nature Communications, 2022. Data under CC BY-SA 4.0.';

type Obj = Record<string, unknown>;
const isObj = (v: unknown): v is Obj => typeof v === 'object' && v !== null && !Array.isArray(v);
const str = (v: unknown): string | null => (typeof v === 'string' && v.trim() ? v.trim() : null);
const GRADES: ProvenanceGrade[] = ['radiologist', 'clinician', 'model', 'unknown'];

/** A provenance block from the API (object), a sentence (string: the summary row / debrief form), or nothing. */
export function guardProvenance(v: unknown): Provenance | null {
  if (!isObj(v)) return null;
  const dataset = str(v.dataset);
  const segmented_by = str(v.segmented_by);
  if (!dataset || !segmented_by) return null;
  const g = v.grade;
  return {
    dataset,
    segmented_by,
    readers: typeof v.readers === 'number' && Number.isFinite(v.readers) ? v.readers : null,
    institution: str(v.institution),
    license: str(v.license),
    citation: str(v.citation),
    url: str(v.url),
    grade: typeof g === 'string' && (GRADES as string[]).includes(g) ? (g as ProvenanceGrade) : 'unknown',
  };
}

/** Which badge a case gets: its own block when the server sends one; an X-ray without one is ChestX-Det. */
export function provenanceFor(v: unknown, modality: string | null | undefined): Provenance | null {
  return guardProvenance(v) ?? (modality == null || modality === 'cxr' ? CXR_PROVENANCE : null);
}

/** "Segmented by an abdominal radiologist (single reader) · Medical Segmentation Decathlon, Task07 Pancreas".
 *  X-ray outlines are polygons, so the verb is "Outlined". `short` keeps the dataset only, for a table row. */
export function provenanceText(p: Provenance, short = false): string {
  const verb = p.dataset === CXR_PROVENANCE.dataset ? 'Outlined' : 'Segmented';
  return short ? p.dataset : `${verb} by ${p.segmented_by} · ${p.dataset}`;
}
