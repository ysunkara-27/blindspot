// The reveal, one slice at a time: expert outlines are the 0.5 iso-contours of the label mask on the slice being
// shown (marching squares over the finding's label values), converted to display px; brain components get their own
// rings; the anatomy tint comes from every mask value that is not a finding. Pure, unit-tested.
import type { RevealFinding } from '../../types/contracts';
import { marchingSquares, ringBounds, type Ring } from './marching';
import type { PlaneGeom } from './planes';
import { extractSlice, type MaskVolume } from './volume';

export type ComponentRings = { name: string; label_value: number; rings: Ring[]; opacity: number };
export type SliceFinding = RevealFinding & { rings: Ring[]; components_rings?: ComponentRings[] };

/** Component fill opacities, outermost first (oedema, core, enhancing): three cyan tints. */
export const COMPONENT_OPACITY = [0.14, 0.3, 0.5];

const toDisplay = (g: PlaneGeom, rings: Ring[]): Ring[] => rings.map((r) => r.map(([u, v]) => [u * g.ax, v * g.ay] as [number, number]));

/** Findings present on this slice, with their rings in display px and the bbox of those rings. Findings whose label
 *  values do not appear on the slice are left out (their label is not drawn there). */
export function findingsOnSlice(findings: RevealFinding[], mask: MaskVolume, g: PlaneGeom, slice: number): SliceFinding[] {
  const ms = extractSlice(mask.data, mask.shape, g.plane, slice);
  const out: SliceFinding[] = [];
  for (const f of findings) {
    const values = new Set(f.label_values ?? []);
    if (values.size === 0) continue;
    const rings = toDisplay(g, marchingSquares(ms, g.w, g.h, (v) => values.has(v)));
    if (rings.length === 0) continue;
    const bbox = ringBounds(rings)!;
    const comps = f.components?.length
      ? f.components.map((c, i) => ({
          name: c.name, label_value: c.label_value, opacity: COMPONENT_OPACITY[Math.min(i, COMPONENT_OPACITY.length - 1)],
          rings: toDisplay(g, marchingSquares(ms, g.w, g.h, (v) => v === c.label_value)),
        })).filter((c) => c.rings.length > 0)
      : undefined;
    out.push({ ...f, polygon: null, bbox, centroid: [(bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2], rings, components_rings: comps });
  }
  return out;
}

export type SliceZone = { value: number; name: string; rings: Ring[] };

/** Anatomy on this slice: every mask value that is not one of the findings' values, as rings in display px. */
export function anatomyOnSlice(mask: MaskVolume, g: PlaneGeom, slice: number, findingValues: Set<number>, names: Record<string, string> = {}): SliceZone[] {
  const ms = extractSlice(mask.data, mask.shape, g.plane, slice);
  const present = new Set<number>();
  for (let i = 0; i < ms.length; i++) if (ms[i] !== 0 && !findingValues.has(ms[i])) present.add(ms[i]);
  const out: SliceZone[] = [];
  for (const value of [...present].sort((a, b) => a - b)) {
    const rings = toDisplay(g, marchingSquares(ms, g.w, g.h, (v) => v === value));
    if (rings.length) out.push({ value, name: names[String(value)] ?? `Structure ${value}`, rings });
  }
  return out;
}

export const ringsPath = (rings: Ring[]) => rings.map((r) => `M${r.map(([x, y]) => `${x.toFixed(2)} ${y.toFixed(2)}`).join('L')}Z`).join(' ');

/** All label values that belong to findings (the rest of the mask is anatomy). */
export const findingValues = (findings: RevealFinding[]): Set<number> => new Set(findings.flatMap((f) => f.label_values ?? []));
