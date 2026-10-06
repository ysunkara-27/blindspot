// Below 900 px wide: a polite note instead of the reading room (the viewer is desktop-only by design).
import { Link } from 'react-router-dom';
import { BrandMark } from './BrandMark';
import { DISCLAIMER } from './Shell';
import { useTitle } from './useTitle';
import g from './Gate.module.css';

export const SMALL_SCREEN_TEXT = 'Blindspot needs a laptop or desktop screen to read radiographs properly';

export function SmallScreenNote() {
  useTitle('Use a larger screen', true);
  return (
    <div className={g.narrow} data-testid="small-screen">
      <main className={g.narrowMain}>
        <BrandMark size={44} className={g.mark} />
        <h1 className={g.title}>{SMALL_SCREEN_TEXT}.</h1>
        <p>Chest films need room: the reading room shows the film at full height next to your notes. Open this link on a computer, with the window at least 900 pixels wide.</p>
        <p><Link to="/about">Read about Blindspot</Link> · <Link to="/">Back to the start</Link></p>
      </main>
      <footer className={g.narrowFoot} data-testid="disclaimer">{DISCLAIMER}</footer>
    </div>
  );
}
