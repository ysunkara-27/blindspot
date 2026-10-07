// The slice dwell bar (the search trace's third dimension), drawn next to the slice slider after submit: one cell per
// slice; cyan where the finding lives, amber height = time that slice was on screen; a finding's slice the learner
// never saw is tagged "not visited". Reads the server's `search.slice_dwell` only.
import { dwellCaption, dwellCells, type SliceDwell } from './dwell';
import { PLANE_DISPLAY } from './nav';
import type { Plane } from './planes';
import s from '../Viewer.module.css';

export function DwellBar({ dwell, plane, n, current, onPick, findingSlicesViewed }: {
  dwell: SliceDwell[] | null | undefined; plane: Plane; n: number; current: number; onPick: (slice: number) => void;
  /** The server's per-finding verdict (`search.finding_slices_viewed`): the caption never contradicts it. */
  findingSlicesViewed?: Record<string, boolean> | null;
}) {
  const cells = dwellCells(dwell, plane, n);
  const missed = cells.filter((c) => c.notVisited).map((c) => c.slice + 1);
  return (
    <div className={s.dwell} data-testid="dwell-bar" data-plane={plane} aria-label={`Time spent per ${PLANE_DISPLAY[plane].toLowerCase()} slice`}>
      <div className={s.dwellCells} role="list">
        {cells.map((c) => (
          <button
            type="button"
            key={c.slice}
            role="listitem"
            className={`${s.dwellCell} ${c.hasFinding ? s.dwellFinding : ''} ${c.slice === current ? s.dwellCurrent : ''} ${c.notVisited ? s.dwellMissed : ''}`}
            title={`Slice ${c.slice + 1}: ${c.ms >= 100 ? `${(c.ms / 1000).toFixed(1)} s` : 'no time'}${c.hasFinding ? ` · ${c.findingIds.join(', ') || 'finding'} here` : ''}${c.notVisited ? ' · not visited' : ''}`}
            aria-label={`Slice ${c.slice + 1}${c.notVisited ? ', not visited' : ''}`}
            data-testid={`dwell-${c.slice}`}
            data-finding={c.hasFinding ? '1' : undefined}
            data-visited={c.hasFinding ? (c.notVisited ? '0' : '1') : undefined}
            onClick={() => onPick(c.slice)}
          >
            <span className={s.dwellFill} style={{ height: `${Math.round(c.frac * 100)}%` }} />
          </button>
        ))}
      </div>
      <span className={s.dwellNote} data-testid="dwell-note">
        {dwellCaption(cells, findingSlicesViewed)}{missed.length ? ` Not visited: slice${missed.length > 1 ? 's' : ''} ${missed.join(', ')}.` : ''}
      </span>
    </div>
  );
}
