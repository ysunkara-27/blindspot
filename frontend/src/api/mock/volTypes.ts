// Ground truth for SYNTHETIC volumetric mock cases (CT / MR). Only the mock "server" reads this.
export type MockVolFinding = {
  finding_id: string;
  label: string;
  kind: 'focal' | 'pattern';
  bbox: [number, number, number, number];
  centroid: [number, number];
  side: string | null;
  zones: string[];
  primary_zone: string | null;
  relative_location: string | null;
  label_values: number[];
  centroid3: [number, number, number];
  slice_range: [number, number];
  measure: { long_mm: number; slice: number };
  components: { name: string; label_value: number }[] | null;
};
export type MockVolCase = {
  case_id: string;
  modality: 'ct' | 'mr';
  body_region: string;
  width: number;
  height: number;
  is_normal: boolean;
  volume: { shape: [number, number, number]; spacing: [number, number, number]; window: { wc: number; ww: number }; labels: Record<string, string>; sequence: string | null };
  provenance: Record<string, unknown>;
  findings: MockVolFinding[];
};
