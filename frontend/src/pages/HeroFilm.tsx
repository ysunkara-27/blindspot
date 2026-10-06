// A drawn key to the colour logic, not a radiograph: graticule lung outlines, a cyan expert outline, the amber
// search trace and mark, and the grease-pencil arrow to the miss. Static (only the reveal animates, SPEC §14.3).
// Patient right is on image left, marked "R" (CLAUDE.md rule 3).
export function HeroFilm() {
  const trace: [number, number, number][] = [
    [92, 96, 30], [84, 140, 34], [98, 186, 30], [118, 118, 24], [96, 232, 26], [224, 96, 26], [236, 132, 22], [150, 150, 18],
  ];
  return (
    <svg viewBox="0 0 320 320" role="img" aria-labelledby="hero-film-t" data-testid="hero-film">
      <title id="hero-film-t">Diagram: an expert outline in cyan that the learner's amber search trace never reached, with an amber arrow pointing to it.</title>
      <defs>
        <radialGradient id="hf-trace">
          <stop offset="0" stopColor="#F0A92E" stopOpacity="0.55" />
          <stop offset="1" stopColor="#F0A92E" stopOpacity="0" />
        </radialGradient>
        <marker id="hf-head" viewBox="0 0 10 10" refX="7" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
          <path d="M1 1 L8 5 L1 9" fill="none" stroke="#F0A92E" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
        </marker>
      </defs>
      <rect width="320" height="320" fill="#000" />
      {/* graticule: lungs and zone lines, ~40% */}
      <g fill="none" stroke="#8C99A6" strokeOpacity="0.42" strokeWidth="1.4">
        <path d="M118 52 C 78 60, 46 120, 44 196 C 42 236, 50 262, 62 270 C 92 262, 124 262, 146 268 C 150 210, 148 120, 140 70 C 136 56, 128 50, 118 52 Z" />
        <path d="M202 52 C 242 60, 274 120, 276 196 C 278 236, 270 262, 258 270 C 228 262, 196 262, 174 268 C 170 210, 172 120, 180 70 C 184 56, 192 50, 202 52 Z" />
        <path d="M50 132 H146 M44 202 H147 M174 132 H270 M173 202 H276" strokeDasharray="3 4" />
      </g>
      {/* where you looked */}
      <g style={{ mixBlendMode: 'screen' }}>
        {trace.map(([x, y, r], i) => <circle key={i} cx={x} cy={y} r={r} fill="url(#hf-trace)" />)}
      </g>
      {/* expert outline (missed) */}
      <path d="M214 214 C 220 200, 244 198, 252 210 C 262 222, 254 242, 236 244 C 218 246, 206 230, 214 214 Z"
        fill="#35C9DD" fillOpacity="0.08" stroke="#35C9DD" strokeWidth="2.2" strokeLinejoin="round" />
      <text x="290" y="196" textAnchor="end" fontSize="12" fontWeight="700" fill="#35C9DD" stroke="#000" strokeWidth="3" paintOrder="stroke">F1 · Nodule</text>
      {/* your mark */}
      <circle cx="96" cy="122" r="9" fill="none" stroke="#F0A92E" strokeWidth="2.2" />
      <circle cx="96" cy="122" r="1.8" fill="#F0A92E" />
      <text x="109" y="114" fontSize="12" fontWeight="700" fill="#F0A92E" stroke="#000" strokeWidth="3" paintOrder="stroke">M1</text>
      {/* grease-pencil arrow */}
      <path id="hf-arrow" d="M108 136 Q 176 140, 208 212" fill="none" stroke="#F0A92E" strokeWidth="2.4" strokeLinecap="round" markerEnd="url(#hf-head)" />
      {/* the label rides above the arrow, never on it */}
      <text fontSize="11.5" fontWeight="700" fill="#F0A92E" stroke="#000" strokeWidth="3.2" paintOrder="stroke" dy="-7">
        <textPath href="#hf-arrow" startOffset="43%" textAnchor="middle">Never looked there</textPath>
      </text>
      <text x="14" y="26" fontSize="15" fontWeight="700" fill="#c9d1d8">R</text>
    </svg>
  );
}
