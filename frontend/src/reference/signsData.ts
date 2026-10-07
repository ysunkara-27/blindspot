// Sign schematics (round 5): one cached fetch of GET /api/signs for the drawer, the library and the debrief rows,
// and the two lines of copy every list of schematics carries.
import { useQuery } from '@tanstack/react-query';
import { fetchSigns } from '../api/signs';

export const SCHEMATIC_PROVENANCE = 'Schematic drawings, AI-drafted, not yet reviewed';
export const NOT_GRADED = 'Not graded in Blindspot yet; worth knowing';

export const useSignSchematics = (enabled = true) =>
  useQuery({ queryKey: ['signs'], queryFn: fetchSigns, enabled, staleTime: Infinity, retry: false });
