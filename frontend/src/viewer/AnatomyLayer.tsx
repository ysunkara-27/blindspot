// "Show anatomy" overlay. Each outline is a near-black line over a 1 px light casing, so it reads on dark lung and on
// the bright mediastinum without touching contrast. Review areas are dashed. Zones take hover so their names can show.
// Rendered inside the transformed layer, so outlines are in image coordinates like everything else.
import { ringPath, type Anatomy } from './anatomy';
import s from './Viewer.module.css';

export function AnatomyLayer({ anatomy, width, height, k, hovered, onHover }: {
  anatomy: Anatomy; width: number; height: number; k: number; hovered: string | null; onHover: (id: string | null) => void;
}) {
  const line = 1.75 * k;
  return (
    <svg className={s.overlay} viewBox={`0 0 ${width} ${height}`} width={width} height={height} data-testid="anatomy-layer" aria-hidden="true">
      {anatomy.zones.map((z) => {
        const d = z.rings.map(ringPath).join(' ');
        const dash = z.reviewArea ? `${6 * k} ${4 * k}` : undefined;
        const on = hovered === z.id;
        return (
          <g key={z.id}>
            <path d={d} className={`${s.zoneCasing} ${on ? s.zoneCasingOn : ''}`} strokeWidth={line + 2 * k} strokeDasharray={dash} />
            <path
              d={d}
              className={`${s.zone} ${on ? s.zoneOn : ''}`}
              strokeWidth={line}
              strokeDasharray={dash}
              fillRule="evenodd"
              data-zone={z.id}
              onPointerEnter={() => onHover(z.id)}
              onPointerLeave={() => onHover(null)}
            >
              <title>{z.name}</title>
            </path>
          </g>
        );
      })}
    </svg>
  );
}
