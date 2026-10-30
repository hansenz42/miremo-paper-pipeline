import { loadRun } from '@/lib/store';
import { publicRun } from '@/lib/http';
import PaperStudio from '@/components/PaperStudio';
export const dynamic = 'force-dynamic';
export default async function Home() {
  return <PaperStudio initialRun={publicRun(await loadRun('attention-demo'))} />;
}
