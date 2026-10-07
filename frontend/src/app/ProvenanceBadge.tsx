// A small neutral pill saying where a case's reference truth comes from: "Segmented by {segmented_by} · {dataset}".
// Shown wherever a case is shown (reading-room header, film review, summary rows in short form, reference examples).
// It is a statement about the labels, never about the learner: no tone colour.
import { provenanceFor, provenanceText, type Provenance } from './provenance';
import s from './ProvenanceBadge.module.css';

export function ProvenanceBadge({ provenance, modality, short = false, className }: {
  /** The API's provenance block (`case.provenance`, `reveal.provenance`, a reference example's), or a guarded one. */
  provenance?: unknown;
  /** Lets an X-ray without a block default to ChestX-Det. */
  modality?: string | null;
  /** Dataset only (summary rows). The full sentence stays in the title. */
  short?: boolean;
  className?: string;
}) {
  const p: Provenance | null = provenanceFor(provenance, modality);
  if (!p) return null;
  const full = provenanceText(p);
  return (
    <span className={`${s.pill} ${short ? s.short : ''} ${className ?? ''}`} title={full} data-testid="provenance-badge" data-grade={p.grade}>
      {provenanceText(p, short)}
    </span>
  );
}
