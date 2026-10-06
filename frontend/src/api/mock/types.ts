// Ground truth for SYNTHETIC mock cases. Only the mock "server" reads this; UI code never imports it.
export type MockFinding = {
  finding_id: string;
  label: string;
  kind: 'focal' | 'pattern';
  bbox: [number, number, number, number];
  polygon: [number, number][] | null;
  centroid: [number, number];
  side: string | null;
  zones: string[];
  primary_zone: string | null;
  relative_location: string | null;
};
export type MockCase = {
  case_id: string;
  width: number;
  height: number;
  is_normal: boolean;
  ctr: number | null;
  findings: MockFinding[];
};
