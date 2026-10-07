// The rail's only door to the on-film signs layer (viewer-owned store, viewer/signs.ts): `focusSign(id)` pulses a
// sign on the film and turns the layer on if it was off; `useSigns` reads `visible` / `focused`. Nothing else in
// rail/ or reference/ imports the viewer. See docs/PROGRESS.md FRONTEND SEAMS (signs).
export { focusSign, useSigns, useSignsVisible } from '../viewer/signs';
