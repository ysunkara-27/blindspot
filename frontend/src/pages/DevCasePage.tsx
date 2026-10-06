import { useParams } from 'react-router-dom';
import { Placeholder } from './Placeholder';
export function DevCasePage() {
  const { id } = useParams();
  return <Placeholder title={`Dev case ${id ?? ''}`} />;
}
