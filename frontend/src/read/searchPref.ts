// "My search" (the amber trace on the reveal) starts OFF (round 5, clinician feedback B): the first-ever reveal never
// shows it; once the learner has toggled it the choice is remembered here.
export const SEARCH_KEY = 'blindspot.showSearch';

export function searchDefault(): boolean {
  try { return localStorage.getItem(SEARCH_KEY) === '1'; } catch { return false; }
}
