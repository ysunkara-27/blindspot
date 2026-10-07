import { describe, expect, it } from 'vitest';
import { CXR_PROVENANCE, guardProvenance, PROVENANCE_DATASETS, provenanceFor, provenanceText } from './provenance';

describe('provenance badge', () => {
  it('an X-ray without a block is ChestX-Det, outlined by three radiologists', () => {
    const p = provenanceFor(undefined, 'cxr')!;
    expect(p).toBe(CXR_PROVENANCE);
    expect(provenanceText(p)).toBe('Outlined by three board-certified radiologists · ChestX-Det');
    expect(provenanceFor(null, undefined)).toBe(CXR_PROVENANCE);
  });

  it('a CT without a block has no badge rather than a wrong one', () => {
    expect(provenanceFor(null, 'ct')).toBeNull();
  });

  it('a server block is read, with an unknown grade kept as unknown', () => {
    const p = guardProvenance({ dataset: 'Medical Segmentation Decathlon, Task07 Pancreas', segmented_by: 'an abdominal radiologist (single reader)', grade: 'wizard', readers: 1 })!;
    expect(p.grade).toBe('unknown');
    expect(p.readers).toBe(1);
    expect(provenanceText(p)).toBe('Segmented by an abdominal radiologist (single reader) · Medical Segmentation Decathlon, Task07 Pancreas');
    expect(provenanceText(p, true)).toBe('Medical Segmentation Decathlon, Task07 Pancreas');
  });

  it('a block without both names is not a provenance', () => {
    expect(guardProvenance({ dataset: 'x' })).toBeNull();
    expect(guardProvenance('a sentence')).toBeNull();
  });

  it('the static copy lists every dataset of config/provenance.yaml', () => {
    expect(Object.keys(PROVENANCE_DATASETS)).toEqual(['chestx-det', 'Task07_Pancreas', 'Task08_HepaticVessel', 'Task03_Liver', 'Task01_BrainTumour', 'Task06_Lung', 'Task10_Colon']);
    for (const d of Object.values(PROVENANCE_DATASETS)) expect(d.license).toBeTruthy();
  });
});
