// Local mirrors of the dashboard payloads. Source of truth: backend/app/analytics/{learner,cohort,calibration,froc,
// blindspot_map}.py and backend/app/routes/dashboard.py. The API types these as `unknown`, so every payload goes through
// a guard below: a missing or malformed block becomes `null` and its section renders an empty state instead of crashing.

export const MISS_BUCKETS = ['search', 'recognition', 'decision', 'interpretation', 'overcall'] as const;
export type MissBucket = (typeof MISS_BUCKETS)[number];
export type MissMix = Record<MissBucket, number>;

export type CaseStats = {
  n: number;
  n_abnormal: number;
  n_normal: number;
  sensitivity: number | null;
  specificity: number | null;
  localization_fraction: number | null;
  n_focal_findings: number;
  false_positives_per_image: number;
  miss_type_mix: MissMix;
  score_mean: number;
};

export type CurvePoint = { attempt: number; success_rate: number; window_n?: number; score?: number };
export type LearningCurve = {
  window: number;
  n: number;
  overall: CurvePoint[];
  per_label: Record<string, CurvePoint[]>;
};

export type MissWindow = { from: number; to: number; n: number } & MissMix;
export type MissTypeMix = { window: number; n: number; windows: MissWindow[] };

export type CalibrationBin = { confidence: number; n: number; correct: number; accuracy: number | null };
export type Calibration = { bins: CalibrationBin[]; n: number; confident_misses: number };

export type FrocPoint = { threshold: number; llf: number | null; nlf: number | null; n_ll: number; n_nl: number };
export type Froc = { n_images: number; n_lesions: number; n_marks: number; points: FrocPoint[] };

export type BlindspotPoint = { x: number; y: number; label: string; result: string; found: boolean; zone: string | null; modality: string | null };
export type BlindspotMap = { frame: string; n: number; n_missed: number; points: BlindspotPoint[] };

/** Round 4 (CT / MR): misses counted by zone, when the server sends them; else derived from the map's points. */
export type ZoneMisses = { zone: string; human: string; n: number; n_missed: number };

export type ReviewArea = { area: string; human: string; visited_pct: number | null };
export type ReviewAreaHabit = { n: number; areas: ReviewArea[] };

export type Ability = { label: string; theta: number; n: number };
export type LabelDifficulty = { label: string; display: string; n: number; empirical_success: number; mean_b: number };
export type CohortLearner = {
  learner_id: string;
  n: number;
  sensitivity: number | null;
  specificity: number | null;
  score_mean: number;
};

export type LearnerDashboard = {
  n_attempts: number;
  /** cxr | ct | mr counts; absent on a server that does not split by scan type. */
  n_by_modality: Record<string, number> | null;
  /** Echo of the `?modality=` filter the server applied; null when it applied none. */
  modality: string | null;
  misses_by_zone: ZoneMisses[] | null;
  summary: CaseStats | null;
  learning_curve: LearningCurve | null;
  miss_type_mix: MissTypeMix | null;
  calibration: Calibration | null;
  froc: Froc | null;
  blindspot_map: BlindspotMap | null;
  review_area_habit: ReviewAreaHabit | null;
  abilities: Ability[];
  empty_message: string | null;
  learner: { id: string; display_name: string; level: string } | null;
};

export type CohortDashboard = {
  n_attempts: number;
  n_learners: number;
  summary: CaseStats | null;
  miss_type_mix: MissTypeMix | null;
  calibration: Calibration | null;
  froc: Froc | null;
  blindspot_map: BlindspotMap | null;
  review_area_habit: ReviewAreaHabit | null;
  label_difficulty: LabelDifficulty[];
  learners: CohortLearner[];
  filters: Record<string, string | null>;
};

// ---------- runtime guards ----------
type Obj = Record<string, unknown>;
const isObj = (v: unknown): v is Obj => typeof v === 'object' && v !== null && !Array.isArray(v);
const num = (v: unknown): v is number => typeof v === 'number' && Number.isFinite(v);
const numOrNull = (v: unknown): number | null => (num(v) ? v : null);
const arr = (v: unknown): unknown[] => (Array.isArray(v) ? v : []);
const str = (v: unknown, d = ''): string => (typeof v === 'string' ? v : d);

function missMix(v: unknown): MissMix {
  const o = isObj(v) ? v : {};
  return Object.fromEntries(MISS_BUCKETS.map((b) => [b, num(o[b]) ? o[b] : 0])) as MissMix;
}

export function guardStats(v: unknown): CaseStats | null {
  if (!isObj(v) || !num(v.n)) return null;
  return {
    n: v.n,
    n_abnormal: num(v.n_abnormal) ? v.n_abnormal : 0,
    n_normal: num(v.n_normal) ? v.n_normal : 0,
    sensitivity: numOrNull(v.sensitivity),
    specificity: numOrNull(v.specificity),
    localization_fraction: numOrNull(v.localization_fraction),
    n_focal_findings: num(v.n_focal_findings) ? v.n_focal_findings : 0,
    false_positives_per_image: num(v.false_positives_per_image) ? v.false_positives_per_image : 0,
    miss_type_mix: missMix(v.miss_type_mix),
    score_mean: num(v.score_mean) ? v.score_mean : 0,
  };
}

function curvePoints(v: unknown): CurvePoint[] {
  return arr(v).flatMap((p) =>
    isObj(p) && num(p.attempt) && num(p.success_rate)
      ? [{ attempt: p.attempt, success_rate: p.success_rate, window_n: num(p.window_n) ? p.window_n : undefined, score: num(p.score) ? p.score : undefined }]
      : [],
  );
}

export function guardLearningCurve(v: unknown): LearningCurve | null {
  if (!isObj(v)) return null;
  const per = isObj(v.per_label) ? v.per_label : {};
  return {
    window: num(v.window) ? v.window : 10,
    n: num(v.n) ? v.n : 0,
    overall: curvePoints(v.overall),
    per_label: Object.fromEntries(Object.entries(per).map(([k, pts]) => [k, curvePoints(pts)])),
  };
}

export function guardMissTypeMix(v: unknown): MissTypeMix | null {
  if (!isObj(v)) return null;
  const windows = arr(v.windows).flatMap((w) =>
    isObj(w) && num(w.from) && num(w.to) && num(w.n) ? [{ from: w.from, to: w.to, n: w.n, ...missMix(w) }] : [],
  );
  return { window: num(v.window) ? v.window : 10, n: num(v.n) ? v.n : 0, windows };
}

export function guardCalibration(v: unknown): Calibration | null {
  if (!isObj(v)) return null;
  const bins = arr(v.bins).flatMap((b) =>
    isObj(b) && num(b.confidence) && num(b.n)
      ? [{ confidence: b.confidence, n: b.n, correct: num(b.correct) ? b.correct : 0, accuracy: numOrNull(b.accuracy) }]
      : [],
  );
  return { bins, n: num(v.n) ? v.n : 0, confident_misses: num(v.confident_misses) ? v.confident_misses : 0 };
}

export function guardFroc(v: unknown): Froc | null {
  if (!isObj(v)) return null;
  const points = arr(v.points).flatMap((p) =>
    isObj(p) && num(p.threshold)
      ? [{ threshold: p.threshold, llf: numOrNull(p.llf), nlf: numOrNull(p.nlf), n_ll: num(p.n_ll) ? p.n_ll : 0, n_nl: num(p.n_nl) ? p.n_nl : 0 }]
      : [],
  );
  return {
    n_images: num(v.n_images) ? v.n_images : 0,
    n_lesions: num(v.n_lesions) ? v.n_lesions : 0,
    n_marks: num(v.n_marks) ? v.n_marks : 0,
    points,
  };
}

export function guardBlindspot(v: unknown): BlindspotMap | null {
  if (!isObj(v)) return null;
  const points = arr(v.points).flatMap((p) =>
    isObj(p) && num(p.x) && num(p.y)
      ? [{ x: p.x, y: p.y, label: str(p.label), result: str(p.result), found: p.found === true, zone: typeof p.zone === 'string' ? p.zone : null, modality: typeof p.modality === 'string' ? p.modality : null }]
      : [],
  );
  return { frame: str(v.frame), n: num(v.n) ? v.n : points.length, n_missed: num(v.n_missed) ? v.n_missed : points.filter((p) => !p.found).length, points };
}

export function guardZoneMisses(v: unknown): ZoneMisses[] | null {
  if (!Array.isArray(v)) return null;
  return v.flatMap((z) => (isObj(z) && typeof z.zone === 'string' && num(z.n)
    ? [{ zone: z.zone, human: str(z.human, z.zone.replace(/_/g, ' ')), n: z.n, n_missed: num(z.n_missed) ? z.n_missed : 0 }]
    : []));
}

/** Misses by zone from the map's points (every point carries its zone on a CT / MR server), for the list view. */
export function zoneMissesFromMap(map: BlindspotMap | null): ZoneMisses[] {
  const by = new Map<string, ZoneMisses>();
  for (const p of map?.points ?? []) {
    if (!p.zone) continue;
    const z = by.get(p.zone) ?? { zone: p.zone, human: p.zone.replace(/_/g, ' '), n: 0, n_missed: 0 };
    z.n += 1;
    if (!p.found) z.n_missed += 1;
    by.set(p.zone, z);
  }
  return [...by.values()].sort((a, b) => b.n_missed - a.n_missed || b.n - a.n || a.zone.localeCompare(b.zone));
}

export function guardModalityCounts(v: unknown): Record<string, number> | null {
  if (!isObj(v)) return null;
  return Object.fromEntries(Object.entries(v).filter(([, n]) => num(n)).map(([k, n]) => [k, n as number]));
}

export function guardReviewAreas(v: unknown): ReviewAreaHabit | null {
  if (!isObj(v)) return null;
  const areas = arr(v.areas).flatMap((a) =>
    isObj(a) && typeof a.area === 'string' ? [{ area: a.area, human: str(a.human, a.area.replace(/_/g, ' ')), visited_pct: numOrNull(a.visited_pct) }] : [],
  );
  return { n: num(v.n) ? v.n : 0, areas };
}

export function guardLearnerDashboard(v: unknown): LearnerDashboard {
  const o = isObj(v) ? v : {};
  const lr = isObj(o.learner) ? o.learner : null;
  return {
    n_attempts: num(o.n_attempts) ? o.n_attempts : 0,
    n_by_modality: guardModalityCounts(o.n_by_modality),
    modality: typeof o.modality === 'string' ? o.modality : isObj(o.filters) && typeof o.filters.modality === 'string' ? o.filters.modality : null,
    misses_by_zone: guardZoneMisses(o.misses_by_zone),
    summary: guardStats(o.summary),
    learning_curve: guardLearningCurve(o.learning_curve),
    miss_type_mix: guardMissTypeMix(o.miss_type_mix),
    calibration: guardCalibration(o.calibration),
    froc: guardFroc(o.froc),
    blindspot_map: guardBlindspot(o.blindspot_map),
    review_area_habit: guardReviewAreas(o.review_area_habit),
    abilities: arr(o.abilities).flatMap((a) => (isObj(a) && typeof a.label === 'string' && num(a.theta) && num(a.n) ? [{ label: a.label, theta: a.theta, n: a.n }] : [])),
    empty_message: typeof o.empty_message === 'string' ? o.empty_message : null,
    learner: lr ? { id: str(lr.id), display_name: str(lr.display_name), level: str(lr.level) } : null,
  };
}

export function guardCohortDashboard(v: unknown): CohortDashboard {
  const o = isObj(v) ? v : {};
  const f = isObj(o.filters) ? o.filters : {};
  return {
    n_attempts: num(o.n_attempts) ? o.n_attempts : 0,
    n_learners: num(o.n_learners) ? o.n_learners : 0,
    summary: guardStats(o.summary),
    miss_type_mix: guardMissTypeMix(o.miss_type_mix),
    calibration: guardCalibration(o.calibration),
    froc: guardFroc(o.froc),
    blindspot_map: guardBlindspot(o.blindspot_map),
    review_area_habit: guardReviewAreas(o.review_area_habit),
    label_difficulty: arr(o.label_difficulty).flatMap((d) =>
      isObj(d) && typeof d.label === 'string' && num(d.n)
        ? [{ label: d.label, display: str(d.display, d.label), n: d.n, empirical_success: num(d.empirical_success) ? d.empirical_success : 0, mean_b: num(d.mean_b) ? d.mean_b : 0 }]
        : [],
    ),
    learners: arr(o.learners).flatMap((l) =>
      isObj(l) && typeof l.learner_id === 'string' && num(l.n)
        ? [{ learner_id: l.learner_id, n: l.n, sensitivity: numOrNull(l.sensitivity), specificity: numOrNull(l.specificity), score_mean: num(l.score_mean) ? l.score_mean : 0 }]
        : [],
    ),
    filters: Object.fromEntries(Object.entries(f).map(([k, x]) => [k, typeof x === 'string' ? x : null])),
  };
}
