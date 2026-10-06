// SYNTHETIC reference payload for mock mode (GET /reference). The "films" are drawn shapes, built here as inline SVG
// (not the practice fixtures), so the mock keeps the same promise as the real set: examples never come from your cases.
// The wording is a short stand-in for the teaching cards in content/teaching_cards/ and is marked as an AI draft.

type Blob = { cx: number; cy: number; r: number; where: string; side: 'right' | 'left' | null };
const W = 256;

function chestSvg(b: Blob | null, seed: number): string {
  const lesion = b
    ? `<ellipse cx="${b.cx}" cy="${b.cy}" rx="${b.r}" ry="${(b.r * 0.9).toFixed(1)}" fill="#cfd4d8" opacity="0.72"/>`
    : '';
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${W} ${W}" width="${W}" height="${W}">
<rect width="${W}" height="${W}" fill="#0b0c0d"/>
<path d="M28 250 L28 70 Q128 ${18 + (seed % 5)} 228 70 L228 250 Z" fill="#6f777d"/>
<ellipse cx="82" cy="140" rx="46" ry="88" fill="#17191b"/>
<ellipse cx="174" cy="140" rx="46" ry="88" fill="#17191b"/>
<ellipse cx="${140 + (seed % 3)}" cy="176" rx="40" ry="46" fill="#8b9399"/>
<rect x="122" y="20" width="12" height="230" fill="#8b9399" opacity="0.6"/>
${lesion}
<text x="128" y="14" text-anchor="middle" font-family="sans-serif" font-size="9" fill="#9aa5af">synthetic — drawn shapes</text>
</svg>`;
  return `data:image/svg+xml;utf8,${encodeURIComponent(svg)}`;
}

function ring(b: Blob): [number, number][] {
  return Array.from({ length: 20 }, (_, i) => {
    const t = (i / 20) * Math.PI * 2;
    return [Math.round((b.cx + (b.r + 2) * Math.cos(t)) * 10) / 10, Math.round((b.cy + (b.r * 0.9 + 2) * Math.sin(t)) * 10) / 10];
  });
}

type Card = {
  label: string; display: string; kind: 'focal' | 'pattern'; one_liner: string; key_signs: string[]; mimics: string[];
  commonly_confused_with: string[]; search_tip: string; radiopaedia_url: string | null; blobs: Blob[];
};

// Patient RIGHT is on the image LEFT (CLAUDE.md rule 3): x < 128 is the patient's right.
const CARDS: Card[] = [
  { label: 'pneumothorax', display: 'Pneumothorax', kind: 'focal', one_liner: 'Air between the lung and the chest wall.', key_signs: ['A thin white pleural line', 'No lung markings beyond the line'], mimics: ['A skin fold', 'The inner edge of the scapula'], commonly_confused_with: [], search_tip: 'Follow the lung edge from apex to base on both sides.', radiopaedia_url: 'https://radiopaedia.org/articles/pneumothorax', blobs: [{ cx: 190, cy: 62, r: 14, where: 'left upper zone, at the apex', side: 'left' }, { cx: 58, cy: 70, r: 12, where: 'right upper zone, along the chest wall', side: 'right' }] },
  { label: 'effusion', display: 'Pleural effusion', kind: 'focal', one_liner: 'Fluid in the pleural space; it collects at the bottom first.', key_signs: ['A blunted costophrenic angle', 'A meniscus curving up the chest wall'], mimics: ['A raised diaphragm', 'Pleural thickening'], commonly_confused_with: ['pleural_thickening'], search_tip: 'Check both costophrenic angles on every film.', radiopaedia_url: 'https://radiopaedia.org/articles/pleural-effusion', blobs: [{ cx: 56, cy: 214, r: 18, where: 'right lower zone, at the costophrenic angle', side: 'right' }, { cx: 198, cy: 216, r: 16, where: 'left lower zone, at the costophrenic angle', side: 'left' }] },
  { label: 'consolidation', display: 'Consolidation', kind: 'focal', one_liner: 'Airspaces filled with fluid or cells, so the lung turns white.', key_signs: ['Hazy white lung that hides the vessels', 'Air bronchograms'], mimics: ['Overlapping breast tissue', 'A poor inspiration'], commonly_confused_with: ['atelectasis'], search_tip: 'Compare each zone with the same zone on the other side.', radiopaedia_url: 'https://radiopaedia.org/articles/air-space-opacification-1', blobs: [{ cx: 76, cy: 170, r: 24, where: 'right lower zone', side: 'right' }, { cx: 180, cy: 110, r: 20, where: 'left mid zone', side: 'left' }] },
  { label: 'atelectasis', display: 'Atelectasis', kind: 'focal', one_liner: 'Part of the lung has lost volume and collapsed.', key_signs: ['Volume loss with shifted fissures', 'A band of increased density'], mimics: ['A scar', 'A fissure seen edge-on'], commonly_confused_with: ['consolidation'], search_tip: 'Look for structures pulled toward the white area.', radiopaedia_url: 'https://radiopaedia.org/articles/lung-atelectasis', blobs: [{ cx: 186, cy: 186, r: 16, where: 'left lower zone, behind the heart', side: 'left' }, { cx: 70, cy: 150, r: 14, where: 'right mid zone', side: 'right' }] },
  { label: 'nodule', display: 'Nodule', kind: 'focal', one_liner: 'A small, round, well-defined spot in the lung.', key_signs: ['A round white spot surrounded by lung', 'Rounder and brighter than nearby vessels'], mimics: ['A nipple shadow', 'A vessel seen end-on', 'A spot where two ribs cross'], commonly_confused_with: ['mass', 'calcification'], search_tip: 'Use the loupe on the apices, the hila and behind the heart.', radiopaedia_url: 'https://radiopaedia.org/articles/pulmonary-nodule', blobs: [{ cx: 70, cy: 150, r: 7, where: 'right mid zone', side: 'right' }, { cx: 186, cy: 84, r: 6, where: 'left upper zone', side: 'left' }, { cx: 92, cy: 200, r: 6, where: 'right lower zone', side: 'right' }] },
  { label: 'mass', display: 'Mass', kind: 'focal', one_liner: 'A round lesion larger than a nodule.', key_signs: ['A large round opacity', 'May distort nearby structures'], mimics: ['A large hilum', 'A rounded area of consolidation'], commonly_confused_with: ['nodule', 'consolidation'], search_tip: 'Check the hila and the apices; compare the two sides.', radiopaedia_url: 'https://radiopaedia.org/articles/pulmonary-mass', blobs: [{ cx: 78, cy: 96, r: 18, where: 'right upper zone', side: 'right' }, { cx: 178, cy: 160, r: 20, where: 'left mid zone', side: 'left' }] },
  { label: 'calcification', display: 'Calcification', kind: 'focal', one_liner: 'A very dense, bright spot: calcium in an old scar, node or nodule.', key_signs: ['Brighter than a rib of the same thickness', 'Sharp edges'], mimics: ['An ECG lead or button', 'A rib end'], commonly_confused_with: ['nodule'], search_tip: 'Compare its brightness with the nearest rib.', radiopaedia_url: null, blobs: [{ cx: 96, cy: 128, r: 5, where: 'right mid zone, near the hilum', side: 'right' }, { cx: 182, cy: 70, r: 5, where: 'left upper zone', side: 'left' }] },
  { label: 'fracture', display: 'Fracture', kind: 'focal', one_liner: 'A break in a rib or the clavicle.', key_signs: ['A step or gap in the edge of a bone', 'Trace every rib from back to front'], mimics: ['A costochondral junction', 'Overlapping rib edges'], commonly_confused_with: [], search_tip: 'Run along each rib and both clavicles.', radiopaedia_url: 'https://radiopaedia.org/articles/rib-fractures', blobs: [{ cx: 40, cy: 130, r: 8, where: 'right mid zone, lateral ribs', side: 'right' }, { cx: 214, cy: 100, r: 8, where: 'left upper zone, lateral ribs', side: 'left' }] },
  { label: 'pleural_thickening', display: 'Pleural thickening', kind: 'focal', one_liner: 'A thickened band of pleura along the chest wall or at the apex.', key_signs: ['A smooth white band along the chest wall', 'Does not move or layer like fluid'], mimics: ['A small effusion', 'Companion shadows of the ribs'], commonly_confused_with: ['effusion'], search_tip: 'Follow the chest wall from the apex to the costophrenic angle.', radiopaedia_url: null, blobs: [{ cx: 42, cy: 96, r: 10, where: 'right upper zone, along the chest wall', side: 'right' }, { cx: 212, cy: 190, r: 10, where: 'left lower zone, along the chest wall', side: 'left' }] },
  { label: 'cardiomegaly', display: 'Cardiomegaly', kind: 'pattern', one_liner: 'An enlarged heart shadow.', key_signs: ['Heart wider than half the chest on a PA film', 'Check the cardiothoracic ratio'], mimics: ['An AP or supine film', 'A poor inspiration'], commonly_confused_with: [], search_tip: 'Compare the widest heart width with the widest inner chest width.', radiopaedia_url: 'https://radiopaedia.org/articles/cardiomegaly', blobs: [{ cx: 140, cy: 176, r: 48, where: 'cardiac silhouette, enlarged', side: null }] },
  { label: 'emphysema', display: 'Emphysema', kind: 'pattern', one_liner: 'Over-inflated lungs with destroyed airspaces.', key_signs: ['Flat diaphragms', 'Dark lungs with few vessels'], mimics: ['A deep inspiration in a slim patient'], commonly_confused_with: [], search_tip: 'Count the ribs above the diaphragm and look at its shape.', radiopaedia_url: null, blobs: [] },
  { label: 'fibrosis', display: 'Fibrosis', kind: 'pattern', one_liner: 'Scarring of the lung with fine lines and volume loss.', key_signs: ['A net-like pattern of lines', 'Usually worse at the bases and edges'], mimics: ['Crowded vessels on a poor inspiration'], commonly_confused_with: ['diffuse_nodule'], search_tip: 'Look at the lung edges at the bases with the loupe.', radiopaedia_url: null, blobs: [] },
  { label: 'diffuse_nodule', display: 'Diffuse nodules', kind: 'pattern', one_liner: 'Many small nodules spread through both lungs.', key_signs: ['Countless small dots in every zone', 'Both lungs involved'], mimics: ['Vessels seen end-on'], commonly_confused_with: ['fibrosis'], search_tip: 'Check whether the dots are in every zone or only one.', radiopaedia_url: null, blobs: [] },
];

export function mockReference() {
  return {
    labels: CARDS.map((c, ci) => ({
      label: c.label, display: c.display, kind: c.kind, one_liner: c.one_liner, key_signs: c.key_signs, mimics: c.mimics,
      commonly_confused_with: c.commonly_confused_with, search_tip: c.search_tip, radiopaedia_url: c.radiopaedia_url, review_status: 'ai_draft',
      examples: c.blobs.map((b, i) => ({
        case_id: `synref_${c.label}_${i + 1}`,
        image_url: chestSvg(b, ci + i),
        width: W,
        height: W,
        finding: {
          finding_id: `synref_${c.label}_${i + 1}#F1`,
          polygon: ring(b),
          bbox: [b.cx - b.r, b.cy - b.r, b.cx + b.r, b.cy + b.r],
          relative_location: b.where,
          side: b.side,
        },
      })),
    })),
    normal_examples: [0, 1, 2].map((i) => ({ case_id: `synref_normal_${i + 1}`, image_url: chestSvg(null, i), width: W, height: W })),
  };
}
