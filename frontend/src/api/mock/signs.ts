// SYNTHETIC sign schematics and on-film signs for mock mode (round 5). The drawings are simple line schematics in
// the app's three colours (cyan = the sign, amber = pointer, graticule = anatomy), viewBox 0 0 200 200, so the
// drawer, the /reference Signs tab and the debrief chips can be built and tested before the backend's content lands.
// Wording is a short stand-in for content/signs; every schematic is marked as an AI draft.
import type { Sign, SignSchematic } from '../../types/contracts';

const CYAN = '#35C9DD';
const AMBER = '#F0A92E';
const GRAT = '#8C99A6';

/** A schematic chest (two lungs, mediastinum, diaphragm) in graticule; patient right is on the image left. */
const CHEST = `<path d="M20 180 L20 60 Q100 20 180 60 L180 180 Z" fill="none" stroke="${GRAT}" stroke-width="2"/>`
  + `<path d="M28 170 Q30 70 86 50 L86 170 Z" fill="none" stroke="${GRAT}" stroke-width="1.5" opacity="0.7"/>`
  + `<path d="M172 170 Q170 70 114 50 L114 170 Z" fill="none" stroke="${GRAT}" stroke-width="1.5" opacity="0.7"/>`
  + `<path d="M28 170 Q60 150 86 165" fill="none" stroke="${GRAT}" stroke-width="1.5"/>`
  + `<path d="M114 165 Q140 148 172 170" fill="none" stroke="${GRAT}" stroke-width="1.5"/>`;
const svg = (body: string) => `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 200" role="img">${CHEST}${body}</svg>`;
const arrow = (x1: number, y1: number, x2: number, y2: number) =>
  `<path d="M${x1} ${y1} L${x2} ${y2}" stroke="${AMBER}" stroke-width="2.5" fill="none" stroke-linecap="round"/>`
  + `<circle cx="${x2}" cy="${y2}" r="3" fill="${AMBER}"/>`;
const cyan = (d: string, w = 3) => `<path d="${d}" fill="none" stroke="${CYAN}" stroke-width="${w}" stroke-linecap="round" stroke-linejoin="round"/>`;

const RP = (slug: string) => `https://radiopaedia.org/articles/${slug}`;

export const MOCK_SCHEMATICS: SignSchematic[] = [
  { id: 'visceral_pleural_line', name: 'Visceral pleural line', labels: ['pneumothorax'], modality: 'cxr', radiopaedia_url: RP('pneumothorax'), review_status: 'ai_draft',
    description: 'A thin white line parallel to the chest wall with no lung markings beyond it; the lung edge has pulled away from the ribs.',
    svg: svg(cyan('M150 56 Q166 100 164 150') + arrow(120, 40, 152, 62)) },
  { id: 'deep_sulcus', name: 'Deep sulcus sign', labels: ['pneumothorax'], modality: 'cxr', radiopaedia_url: RP('deep-sulcus-sign-lungs'), review_status: 'ai_draft',
    description: 'On a film taken lying down, air collects at the front and base, so one costophrenic angle looks unusually deep and dark.',
    svg: svg(cyan('M28 170 L34 186 L52 172') + arrow(70, 190, 40, 180)) },
  { id: 'meniscus', name: 'Meniscus sign', labels: ['effusion'], modality: 'cxr', radiopaedia_url: RP('meniscus-sign-pleural-effusion'), review_status: 'ai_draft',
    description: 'Fluid in the pleural space rises up the chest wall, so the top of the white area curves upward at the edge.',
    svg: svg(`<path d="M114 170 Q140 150 172 170 L172 125 Q150 150 114 150 Z" fill="${CYAN}" fill-opacity="0.18" stroke="none"/>` + cyan('M114 150 Q150 150 172 125') + arrow(140, 110, 160, 136)) },
  { id: 'blunted_angle', name: 'Blunted costophrenic angle', labels: ['effusion', 'pleural_thickening'], modality: 'cxr', radiopaedia_url: RP('costophrenic-angle-blunting'), review_status: 'ai_draft',
    description: 'The sharp corner where the diaphragm meets the chest wall is filled in; a small amount of fluid or thickened pleura does this first.',
    svg: svg(cyan('M28 160 Q36 168 48 168') + arrow(70, 150, 40, 164)) },
  { id: 'air_bronchogram', name: 'Air bronchogram', labels: ['consolidation'], modality: 'cxr', radiopaedia_url: RP('air-bronchogram'), review_status: 'ai_draft',
    description: 'Dark branching airways seen through a white lung: the airspaces around them are filled, the bronchi are not.',
    svg: svg(`<ellipse cx="60" cy="120" rx="26" ry="30" fill="${CYAN}" fill-opacity="0.18"/>` + cyan('M48 100 L58 118 L52 138 M58 118 L70 134', 2.5) + arrow(100, 100, 72, 116)) },
  { id: 'silhouette_sign', name: 'Silhouette sign', labels: ['consolidation', 'atelectasis'], modality: 'cxr', radiopaedia_url: RP('silhouette-sign'), review_status: 'ai_draft',
    description: 'A border that should be visible (heart, diaphragm) disappears because the lung next to it has the same density; that tells you where the opacity is.',
    svg: svg(`<path d="M114 165 Q140 148 172 170 L172 140 Q140 142 114 150 Z" fill="${CYAN}" fill-opacity="0.18"/>` + `<path d="M114 165 Q140 148 172 170" stroke="${GRAT}" stroke-width="1.5" stroke-dasharray="3 4" fill="none"/>` + arrow(100, 120, 140, 152)) },
  { id: 'golden_s', name: 'Golden S sign', labels: ['atelectasis', 'mass'], modality: 'cxr', radiopaedia_url: RP('golden-s-sign'), review_status: 'ai_draft',
    description: 'A collapsed upper lobe draws the fissure up in a curve while a central mass bulges it down: the edge looks like a reversed S.',
    svg: svg(cyan('M86 62 Q104 70 92 92 Q82 110 60 104') + arrow(60, 40, 86, 70)) },
  { id: 'volume_loss', name: 'Volume loss', labels: ['atelectasis'], modality: 'cxr', radiopaedia_url: RP('lung-atelectasis'), review_status: 'ai_draft',
    description: 'Structures pulled toward the white area: a raised diaphragm, a shifted trachea or mediastinum, crowded ribs.',
    svg: svg(cyan('M96 30 L92 60 L104 90') + cyan('M28 160 Q60 130 86 150') + arrow(60, 100, 70, 140)) },
  { id: 'spiculated_edge', name: 'Spiculated edge', labels: ['nodule', 'mass'], modality: 'cxr', radiopaedia_url: RP('spiculated-pulmonary-nodule'), review_status: 'ai_draft',
    description: 'Fine lines radiating from the edge of a nodule or mass into the surrounding lung instead of a smooth border.',
    svg: svg(`<circle cx="140" cy="100" r="14" fill="${CYAN}" fill-opacity="0.25" stroke="${CYAN}" stroke-width="2"/>` + cyan('M154 100 L166 100 M150 90 L160 80 M150 110 L160 120 M140 86 L140 76 M140 114 L140 124 M126 100 L116 100', 1.5) + arrow(100, 60, 128, 88)) },
  { id: 'popcorn_calcification', name: 'Popcorn calcification', labels: ['calcification', 'nodule'], modality: 'cxr', radiopaedia_url: RP('popcorn-calcification-1'), review_status: 'ai_draft',
    description: 'Dense, lumpy calcium inside a nodule, brighter than the ribs; a pattern that points to an old, benign lesion.',
    svg: svg(`<path d="M56 112 l6 -8 l8 2 l6 -6 l6 8 l-2 8 l4 6 l-8 6 l-8 -2 l-6 4 l-4 -8 l-6 -4 Z" fill="${CYAN}" fill-opacity="0.6" stroke="${CYAN}" stroke-width="2"/>` + arrow(100, 80, 76, 104)) },
  { id: 'cortical_step', name: 'Cortical step-off', labels: ['fracture'], modality: 'cxr', radiopaedia_url: RP('rib-fractures'), review_status: 'ai_draft',
    description: 'The smooth edge of a rib or clavicle shows a step or gap; trace each bone from back to front.',
    svg: svg(`<path d="M20 90 Q60 70 100 86" fill="none" stroke="${GRAT}" stroke-width="5"/>` + cyan('M56 76 L58 84') + arrow(40, 120, 56, 88)) },
  { id: 'pleural_band', name: 'Pleural band', labels: ['pleural_thickening'], modality: 'cxr', radiopaedia_url: RP('pleural-thickening'), review_status: 'ai_draft',
    description: 'A smooth white band along the inside of the chest wall or over the apex that does not layer or shift like fluid.',
    svg: svg(cyan('M28 80 Q26 120 30 160', 6) + arrow(70, 110, 36, 116)) },
  { id: 'cardiothoracic_ratio', name: 'Cardiothoracic ratio', labels: ['cardiomegaly'], modality: 'cxr', radiopaedia_url: RP('cardiothoracic-ratio'), review_status: 'ai_draft',
    description: 'Widest heart width over widest inner chest width; above about 0.5 on a PA film suggests an enlarged heart.',
    svg: svg(`<ellipse cx="112" cy="140" rx="40" ry="30" fill="none" stroke="${CYAN}" stroke-width="2.5"/>` + `<path d="M72 170 L152 170 M24 184 L176 184" stroke="${AMBER}" stroke-width="2.5"/>`) },
  { id: 'flat_diaphragm', name: 'Flattened diaphragm', labels: ['emphysema'], modality: 'cxr', radiopaedia_url: RP('pulmonary-emphysema'), review_status: 'ai_draft',
    description: 'Over-inflated lungs push the diaphragms down and flat; more than ten ribs show above them and the lungs look dark.',
    svg: svg(cyan('M28 172 L86 172 M114 172 L172 172') + arrow(100, 140, 60, 170)) },
  { id: 'honeycombing', name: 'Honeycombing', labels: ['fibrosis'], modality: 'cxr', radiopaedia_url: RP('honeycombing-lungs'), review_status: 'ai_draft',
    description: 'Clustered small ring shadows with thick walls at the lung bases and edges: end-stage scarring.',
    svg: svg([[40, 140], [52, 150], [40, 160], [64, 140], [64, 160], [52, 170]].map(([x, y]) => `<circle cx="${x}" cy="${y}" r="5" fill="none" stroke="${CYAN}" stroke-width="2"/>`).join('') + arrow(90, 120, 62, 142)) },
  { id: 'miliary_pattern', name: 'Miliary pattern', labels: ['diffuse_nodule'], modality: 'cxr', radiopaedia_url: RP('miliary-opacities-lungs'), review_status: 'ai_draft',
    description: 'Countless tiny dots of the same size spread evenly through both lungs, from apex to base.',
    svg: svg(Array.from({ length: 36 }, (_, i) => { const x = 36 + (i % 6) * 10 + (Math.floor(i / 6) % 2) * 5; const y = 70 + Math.floor(i / 6) * 16; return `<circle cx="${x}" cy="${y}" r="1.6" fill="${CYAN}"/><circle cx="${x + 92}" cy="${y}" r="1.6" fill="${CYAN}"/>`; }).join('')) },
  { id: 'kerley_b', name: 'Kerley B lines', labels: [], modality: 'cxr', radiopaedia_url: RP('kerley-lines'), review_status: 'ai_draft',
    description: 'Short horizontal lines at the lung edges just above the costophrenic angles: thickened interlobular septa, classically from fluid.',
    svg: svg(cyan('M28 140 L40 140 M28 150 L42 150 M28 160 L40 160', 2) + arrow(70, 120, 42, 142)) },
  { id: 'bat_wing', name: 'Bat-wing opacity', labels: [], modality: 'cxr', radiopaedia_url: RP('bat-wing-opacities-lungs'), review_status: 'ai_draft',
    description: 'Hazy opacity fanning out from both hila with the lung edges spared, like a bat\'s wings: a pattern of pulmonary oedema.',
    svg: svg(`<path d="M86 80 Q60 100 70 140 Q86 150 100 120 Q114 150 130 140 Q140 100 114 80 Q100 70 86 80 Z" fill="${CYAN}" fill-opacity="0.25" stroke="${CYAN}" stroke-width="2"/>`) },
  { id: 'hypoenhancing_mass', name: 'Hypoenhancing mass', labels: ['pancreatic_tumour', 'liver_tumour'], modality: 'ct', radiopaedia_url: RP('pancreatic-ductal-adenocarcinoma'), review_status: 'ai_draft',
    description: 'On contrast CT the tumour takes up less contrast than the gland or liver around it, so it looks darker than its organ.',
    svg: `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 200" role="img"><ellipse cx="100" cy="100" rx="80" ry="60" fill="none" stroke="${GRAT}" stroke-width="2"/><path d="M40 110 Q80 80 160 100" fill="none" stroke="${GRAT}" stroke-width="12" stroke-linecap="round" opacity="0.6"/><circle cx="76" cy="98" r="11" fill="${CYAN}" fill-opacity="0.35" stroke="${CYAN}" stroke-width="2.5"/>${arrow(110, 60, 84, 90)}</svg>` },
  { id: 'ring_enhancement', name: 'Ring enhancement', labels: ['brain_tumour'], modality: 'mr', radiopaedia_url: RP('ring-enhancing-lesion-brain'), review_status: 'ai_draft',
    description: 'A bright rim around a darker centre after contrast: the enhancing tumour margin around necrosis, with oedema spreading beyond it.',
    svg: `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 200" role="img"><ellipse cx="100" cy="100" rx="72" ry="84" fill="none" stroke="${GRAT}" stroke-width="2"/><path d="M100 20 L100 180" stroke="${GRAT}" stroke-width="1.5" stroke-dasharray="3 4"/><circle cx="130" cy="96" r="22" fill="${CYAN}" fill-opacity="0.12" stroke="${CYAN}" stroke-width="1" stroke-dasharray="3 3"/><circle cx="130" cy="96" r="12" fill="none" stroke="${CYAN}" stroke-width="4"/>${arrow(70, 60, 116, 86)}</svg>` },
];

export const mockSignSchematics = (): SignSchematic[] => MOCK_SCHEMATICS;

/** Schematic ids that belong to a finding type (for GET /reference/{label} `signs`). */
export const schematicIdsFor = (label: string): string[] => MOCK_SCHEMATICS.filter((s) => s.labels.includes(label)).map((s) => s.id);

const TEXT: Record<string, [string, string]> = {
  visceral_pleural_line: ['Visceral pleural line', 'A thin white line parallel to the chest wall with no lung markings beyond it.'],
  meniscus: ['Meniscus', 'The top of the fluid curves up the chest wall.'],
  air_bronchogram: ['Air bronchogram', 'Dark branching airways through the white lung.'],
  volume_loss: ['Volume loss', 'Fissures and the diaphragm pulled toward the collapse.'],
  spiculated_edge: ['Edge of the lesion', 'Compare the edge with the vessels around it: rounder, brighter, sharper.'],
  popcorn_calcification: ['Dense calcium', 'Brighter than the nearest rib of the same thickness.'],
  cortical_step: ['Cortical step', 'A step or gap in the smooth edge of the bone.'],
  pleural_band: ['Pleural band', 'A smooth white band along the chest wall that does not layer like fluid.'],
  hypoenhancing_mass: ['Hypoenhancing mass', 'Darker than the organ around it after contrast.'],
  ring_enhancement: ['Enhancing rim', 'A bright rim around a darker centre.'],
};
const FIRST_SIGN: Record<string, string> = {
  pneumothorax: 'visceral_pleural_line', effusion: 'meniscus', consolidation: 'air_bronchogram', atelectasis: 'volume_loss',
  nodule: 'spiculated_edge', mass: 'spiculated_edge', calcification: 'popcorn_calcification', fracture: 'cortical_step',
  pleural_thickening: 'pleural_band', pancreatic_tumour: 'hypoenhancing_mass', liver_tumour: 'hypoenhancing_mass', brain_tumour: 'ring_enhancement',
};

/** The on-film sign(s) of a reveal finding, drawn from its outline: a polyline along the outline's outer half for a
 *  line-like sign, else a circle at the outline's centre. Ids are `<finding_id>:<schematic_id>`. */
export function signsForFinding(findingId: string, label: string, polygon: [number, number][] | null, bbox: [number, number, number, number], width = 1024): Sign[] {
  const sid = FIRST_SIGN[label];
  if (!sid) return [];
  const [name, text] = TEXT[sid];
  const cx = (bbox[0] + bbox[2]) / 2;
  const cy = (bbox[1] + bbox[3]) / 2;
  const r = Math.max(8, Math.min(bbox[2] - bbox[0], bbox[3] - bbox[1]) / 2);
  const line = sid === 'visceral_pleural_line' || sid === 'meniscus' || sid === 'pleural_band' || sid === 'cortical_step';
  let geometry: Sign['geometry'];
  if (line && polygon && polygon.length >= 6) {
    // The half of the outline nearer the chest wall (away from the image centre), as a polyline.
    const towardWall = cx < width / 2 ? (p: [number, number]) => p[0] <= cx : (p: [number, number]) => p[0] >= cx;
    const pts = polygon.filter(towardWall);
    geometry = { kind: 'polyline', points: pts.length >= 2 ? pts : polygon.slice(0, Math.ceil(polygon.length / 2)) };
  } else if (line) {
    geometry = { kind: 'polyline', points: [[bbox[0], bbox[1]], [bbox[0], bbox[3]]] };
  } else {
    geometry = { kind: 'circle', points: [[cx, cy]], radius: r };
  }
  return [{ id: `${findingId}:${sid}`, name, text, geometry, schematic: sid }];
}
