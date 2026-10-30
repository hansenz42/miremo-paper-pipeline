import demo from '@/data/attention.json';
import type { Run } from '@/lib/types';
import PaperStudio from '@/components/PaperStudio';
export default function Home() {
  return <PaperStudio initialRun={demo as Run} />;
}
