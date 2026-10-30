import { loadRun } from '@/lib/store';
import { authorize, failure, publicRun } from '@/lib/http';
import { progress } from '@/lib/types';
export const runtime = 'nodejs';
export async function GET(req: Request, { params }: { params: Promise<{ id: string }> }) {
  try {
    const { id } = await params;
    if (id !== 'attention-demo') authorize(req);
    const run = await loadRun(id);
    return Response.json(
      { run: publicRun(run), progress: progress(run) },
      { headers: { 'Cache-Control': 'no-store' } },
    );
  } catch (e) {
    return failure(e);
  }
}
