// Three small drawn glyphs for "How it works": a film tile with the colour logic of the reading room (cyan is the
// expert outline, amber is the learner). Decorative; the step text carries the meaning.
const TILE = { width: 56, height: 56, viewBox: '0 0 56 56', 'aria-hidden': true, focusable: false } as const;
const CYAN = '#35C9DD';
const AMBER = '#F0A92E';

function Film({ children }: { children: React.ReactNode }) {
  return (
    <svg {...TILE}>
      <rect width="56" height="56" rx="8" fill="#1C1F22" />
      {/* faint lung outlines, as on the hero film */}
      <g fill="none" stroke="#8C99A6" strokeOpacity="0.38" strokeWidth="1.2">
        <path d="M22 11 C 15 13, 10 23, 10 33 C 10 39, 12 44, 15 46 C 20 44, 24 44, 26 45 C 26 36, 26 22, 25 15 Z" />
        <path d="M34 11 C 41 13, 46 23, 46 33 C 46 39, 44 44, 41 46 C 36 44, 32 44, 30 45 C 30 36, 30 22, 31 15 Z" />
      </g>
      {children}
    </svg>
  );
}

/** Step 1: your mark, an amber ring with a dot. */
export function GlyphMark() {
  return (
    <Film>
      <circle cx="18" cy="26" r="6" fill="none" stroke={AMBER} strokeWidth="2" />
      <circle cx="18" cy="26" r="1.5" fill={AMBER} />
      <path d="M27 20 l3 -3 M27 20 l0 -4 M27 20 l-4 0" stroke={AMBER} strokeWidth="1.6" strokeLinecap="round" fill="none" opacity="0.8" />
    </Film>
  );
}

/** Step 2: where you looked (amber) never reached the expert outline (cyan). */
export function GlyphLooked() {
  return (
    <Film>
      <g fill={AMBER} style={{ mixBlendMode: 'screen' }}>
        <circle cx="17" cy="20" r="8" opacity="0.5" />
        <circle cx="21" cy="30" r="7" opacity="0.35" />
        <circle cx="36" cy="18" r="6" opacity="0.4" />
      </g>
      <path d="M35 34 C 36 31, 42 30, 44 33 C 46 36, 43 41, 39 41 C 35 41, 33 37, 35 34 Z" fill={CYAN} fillOpacity="0.1" stroke={CYAN} strokeWidth="1.8" />
      <path d="M24 32 Q 30 38, 34 39" fill="none" stroke={AMBER} strokeWidth="1.6" strokeLinecap="round" />
      <path d="M31 40 l3.5 -1 l-1.5 -3" fill="none" stroke={AMBER} strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
    </Film>
  );
}

/** Step 3: the expert outline, named, with the debrief's lines beside it. */
export function GlyphExpert() {
  return (
    <Film>
      <path d="M14 27 C 15 22, 24 21, 27 26 C 30 31, 25 38, 19 37 C 13 36, 12 31, 14 27 Z" fill={CYAN} fillOpacity="0.12" stroke={CYAN} strokeWidth="1.8" />
      <g stroke="#c9d1d8" strokeWidth="1.8" strokeLinecap="round">
        <path d="M34 24 h10" stroke={CYAN} />
        <path d="M34 30 h12" />
        <path d="M34 36 h8" />
      </g>
    </Film>
  );
}
