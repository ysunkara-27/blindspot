// "Signs to know" (round 5): the generic sign schematics for one finding type — a small line drawing, the sign's
// name, one paragraph on what to look for, and a Radiopaedia link (link only). Generic material from GET /api/signs:
// it never says anything about the case being read, so it is shown before submit (the "i" drawer) as well as after.
// The drawing is our own API's SVG, guarded in api/signs.ts (no scripts, handlers or external references) and
// rendered inline in a fixed 120×120 box.
import { labelDisplay } from '../api/labels';
import { signsForLabel, type SignSchematic } from '../api/signs';
import { NOT_GRADED, SCHEMATIC_PROVENANCE, useSignSchematics } from './signsData';
import s from './Reference.module.css';

export function Schematic({ sign }: { sign: SignSchematic }) {
  return (
    // The markup comes from our own API and passed safeSvg(); nothing user-written is ever rendered this way.
    <div className={s.schematic} aria-hidden="true" data-testid="sign-schematic-svg" dangerouslySetInnerHTML={{ __html: sign.svg }} />
  );
}

/** `showLabels` (the Signs tab): name the graded finding(s) the sign points to. */
export function SignCard({ sign, onFilm = false, notGraded = false, showLabels = false }: { sign: SignSchematic; onFilm?: boolean; notGraded?: boolean; showLabels?: boolean }) {
  return (
    <li className={s.signCard} data-testid="sign-card" data-sign={sign.id}>
      <Schematic sign={sign} />
      <div className={s.signBody}>
        <p className={s.signName}>
          {sign.name}
          {onFilm && <span className={s.signTag} title="This sign is drawn on the film you just read">Drawn on your film</span>}
        </p>
        {sign.description && <p className={s.signText}>{sign.description}</p>}
        {showLabels && sign.labels.length > 0 && <p className={s.signNote}>Points to: {sign.labels.map(labelDisplay).join(', ')}</p>}
        {notGraded && <p className={s.signNote}>{NOT_GRADED}</p>}
        {sign.radiopaedia_url && (
          <a href={sign.radiopaedia_url} target="_blank" rel="noopener noreferrer" className={s.signLink} data-testid="sign-radiopaedia">
            Read more on Radiopaedia <span aria-hidden="true">↗</span><span className={s.sr}> (opens in a new tab)</span>
          </a>
        )}
      </div>
    </li>
  );
}

export function SchematicBadge() {
  return <span className={`${s.badge} ${s.badgeSmall}`} data-testid="sign-provenance">{SCHEMATIC_PROVENANCE}</span>;
}

/** The section for one finding type. `first`: schematic ids drawn on the film just read, listed first and tagged. */
export function SignsToKnow({ label, first = [], heading = 'Signs to know', className = '' }: { label: string; first?: string[]; heading?: string; className?: string }) {
  const q = useSignSchematics();
  const list = q.data ? signsForLabel(q.data, label, first) : [];
  if (!q.data || list.length === 0) return null;
  return (
    <section className={className || s.section} data-testid="signs-to-know" data-label={label}>
      <div className={s.signsHead}>
        <h3 className={s.h3}>{heading}</h3>
        <SchematicBadge />
      </div>
      <ul className={s.signList}>
        {list.map((sg) => <SignCard key={sg.id} sign={sg} onFilm={first.includes(sg.id)} />)}
      </ul>
    </section>
  );
}
