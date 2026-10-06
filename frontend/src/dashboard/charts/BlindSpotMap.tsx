// Blind-spot map (SPEC §10.1): finding centroids in a canonical chest frame (x, y normalised to the union lung bounding
// box), drawn as a density of misses over a schematic chest on a small film. Found = cyan, missed = amber (task brief).
// Image convention: patient RIGHT on the image LEFT (CLAUDE.md rule 3) — the R marker sits top-left.
import { labelDisplay, OUTCOME_COPY } from '../../api/labels';
import type { OutcomeResult } from '../../types/contracts';
import { densityGrid } from '../helpers';
import { C } from '../palette';
import type { BlindspotMap as BM } from '../types';
import { Empty, Section, TableView } from '../parts';
import s from '../Dashboard.module.css';

const W = 340;
const H = 380;
const PAD = 0.12; // show points slightly outside the lung box (below the diaphragm, apices)
const FX = 46; // lung-box frame inside the panel
const FY = 44;
const FW = W - 2 * FX;
const FH = H - FY - 40;
const GRID = 30;

const px = (x: number) => FX + Math.min(1 + PAD, Math.max(-PAD, x)) * FW;
const py = (y: number) => FY + Math.min(1 + PAD, Math.max(-PAD, y)) * FH;

// Schematic outline in unit lung-box coordinates.
const RIGHT_LUNG = 'M .36 .02 C .2 0 .08 .25 .04 .55 C .02 .75 0 .92 .02 .98 C .15 .87 .32 .85 .45 .9 C .44 .7 .44 .4 .43 .12 C .42 .05 .4 .02 .36 .02 Z';
const LEFT_LUNG = 'M .64 .02 C .8 0 .92 .25 .96 .55 C .98 .75 1 .92 .98 1 C .88 .9 .78 .88 .7 .93 C .62 .86 .58 .72 .57 .55 C .57 .35 .57 .2 .57 .12 C .58 .05 .6 .02 .64 .02 Z';
const HEART = 'M .47 .46 C .62 .45 .75 .62 .72 .9 C .6 .96 .45 .96 .38 .91 C .37 .75 .41 .55 .47 .46 Z';
const scalePath = (d: string) => d.replace(/(-?\d*\.?\d+) (-?\d*\.?\d+)/g, (_, a: string, b: string) => `${(FX + +a * FW).toFixed(1)} ${(FY + +b * FH).toFixed(1)}`);

const resultText = (r: string) => OUTCOME_COPY[r as OutcomeResult]?.text ?? r.replace(/_/g, ' ');

export function BlindSpotMap({ map, title = 'Your blind-spot map', who = 'you' }: { map: BM | null; title?: string; who?: string }) {
  const pts = map?.points ?? [];
  const misses = pts.filter((p) => !p.found);
  const found = pts.filter((p) => p.found);
  // Density over the padded frame, so misses just outside the lungs still warm the map.
  const span = 1 + 2 * PAD;
  const grid = densityGrid(misses.map((p) => ({ x: (Math.min(1 + PAD, Math.max(-PAD, p.x)) + PAD) / span, y: (Math.min(1 + PAD, Math.max(-PAD, p.y)) + PAD) / span })), GRID, GRID, 0.07);
  const cw = (FW * span) / GRID;
  const ch = (FH * span) / GRID;
  const gx0 = FX - PAD * FW;
  const gy0 = FY - PAD * FH;

  return (
    <Section title={title} testid="blindspot-map" n={`n = ${map?.n ?? 0} findings · ${map?.n_missed ?? 0} missed`}
      caption="Every outlined finding on the films you read, placed on one standard chest. Cyan is what you found; amber is what you missed, and the amber haze shows where misses cluster.">
      {!pts.length ? <Empty>No outlined findings read yet.</Empty> : (
        <>
          <div className={s.mapRow}>
            <svg className={s.map} viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`Chest schematic with ${found.length} found and ${misses.length} missed findings`} data-testid="blindspot-svg">
              <defs>
                <filter id="bs-blur" x="-10%" y="-10%" width="120%" height="120%"><feGaussianBlur stdDeviation={cw * 0.9} /></filter>
              </defs>
              <g fill="none" stroke={C.graticule} strokeOpacity={0.45} strokeWidth={1.5}>
                <path d={scalePath(RIGHT_LUNG)} />
                <path d={scalePath(LEFT_LUNG)} />
                <path d={scalePath(HEART)} strokeOpacity={0.3} />
                <line x1={FX + 0.5 * FW} y1={FY - 0.1 * FH} x2={FX + 0.5 * FW} y2={FY + 0.3 * FH} strokeOpacity={0.3} />
              </g>
              <g filter="url(#bs-blur)" data-testid="blindspot-density">
                {grid.flatMap((row, j) => row.map((v, i) => (v > 0.04 ? (
                  <rect key={`${i}-${j}`} x={gx0 + i * cw} y={gy0 + j * ch} width={cw + 0.5} height={ch + 0.5} fill={C.filmAmber} fillOpacity={v * 0.55} />
                ) : null)))}
              </g>
              <text x={12} y={22} fill={C.graticule} fontSize={15} fontWeight={700}>R</text>
              <text x={W - 12} y={22} fill={C.graticule} fontSize={15} fontWeight={700} textAnchor="end">L</text>
              {found.map((p, i) => (
                <g key={`f${i}`} data-testid="bs-found">
                  <title>{`${labelDisplay(p.label)} · ${resultText(p.result)}`}</title>
                  <circle cx={px(p.x)} cy={py(p.y)} r={12} fill="transparent" />
                  <circle cx={px(p.x)} cy={py(p.y)} r={5} fill={C.filmCyan} stroke={'#1C1F22'} strokeWidth={2} />
                </g>
              ))}
              {misses.map((p, i) => (
                <g key={`m${i}`} data-testid="bs-missed">
                  <title>{`${labelDisplay(p.label)} · ${resultText(p.result)}`}</title>
                  <circle cx={px(p.x)} cy={py(p.y)} r={12} fill="transparent" />
                  {/* Missed = a hollow amber ring: shape as well as colour separates it from a found dot. */}
                  <circle cx={px(p.x)} cy={py(p.y)} r={7.5} fill="none" stroke={'#1C1F22'} strokeWidth={5.5} />
                  <circle cx={px(p.x)} cy={py(p.y)} r={5.5} fill="#1C1F22" fillOpacity={0.55} stroke={C.filmAmber} strokeWidth={2.5} />
                </g>
              ))}
            </svg>
            <div className={s.mapSide}>
              {/* The key repeats the marks exactly as drawn, on the same dark film, so no colour has to be matched by eye. */}
              <ul className={s.filmKey} data-testid="blindspot-legend">
                <li>
                  <svg width="26" height="20" viewBox="0 0 26 20" aria-hidden="true"><rect width="26" height="20" rx="4" fill="#1C1F22" /><circle cx="13" cy="10" r="5" fill={C.filmCyan} /></svg>
                  <span>Cyan dot: found by {who} ({found.length})</span>
                </li>
                <li>
                  <svg width="26" height="20" viewBox="0 0 26 20" aria-hidden="true"><rect width="26" height="20" rx="4" fill="#1C1F22" /><circle cx="13" cy="10" r="5" fill="none" stroke={C.filmAmber} strokeWidth="2.5" /></svg>
                  <span>Amber ring: missed ({misses.length})</span>
                </li>
                <li>
                  <svg width="26" height="20" viewBox="0 0 26 20" aria-hidden="true"><rect width="26" height="20" rx="4" fill="#1C1F22" /><ellipse cx="13" cy="10" rx="10" ry="7" fill={C.filmAmber} fillOpacity="0.4" /></svg>
                  <span>Amber haze: where misses cluster</span>
                </li>
              </ul>
              <p>The film is shown as you read it: the patient's right is on the left (R marker).</p>
              <p className={s.legendTerm}>Positions are scaled to the lung outline on each film, so findings from different patients line up.</p>
            </div>
          </div>
          <TableView caption="Findings on the blind-spot map" head={['Finding', 'Result', 'Across (0 = patient right)', 'Down (0 = apex)']}
            rows={pts.map((p) => [labelDisplay(p.label), resultText(p.result), p.x.toFixed(2), p.y.toFixed(2)])} />
        </>
      )}
    </Section>
  );
}
