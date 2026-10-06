// "Show anatomy" overlay: zone outlines in graticule grey at 40%, the hovered zone a little stronger.
// Rendered inside the transformed layer, so outlines are in image coordinates like everything else.
import { ringPath, type Anatomy } from './anatomy';
import s from './Viewer.module.css';

export function AnatomyLayer({ anatomy, width, height, k, hovered, onHover }: {
  anatomy: Anatomy; width: number; height: number; k: number; hovered: string | null; onHover: (id: string | null) => void;
}) {
  return (
    <svg className={s.overlay} viewBox={`0 0 ${width} ${height}`} width={width} height={height} data-testid="anatomy-layer" aria-hidden="true">
      {anatomy.zones.map((z) => (
        <path
          key={z.id}
          d={z.rings.map(ringPath).join(' ')}
          className={`${s.zone} ${hovered === z.id ? s.zoneOn : ''}`}
          strokeWidth={1.5 * k}
          strokeDasharray={z.reviewArea ? `${5 * k} ${4 * k}` : undefined}
          fillRule="evenodd"
          data-zone={z.id}
          onPointerEnter={() => onHover(z.id)}
          onPointerLeave={() => onHover(null)}
        >
          <title>{z.name}</title>
        </path>
      ))}
    </svg>
  );
}
