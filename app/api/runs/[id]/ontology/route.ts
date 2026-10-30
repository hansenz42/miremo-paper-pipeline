import { authorize, failure } from '@/lib/http';
import { loadRun } from '@/lib/store';
import { ontology } from '@/lib/types';
export const runtime = 'nodejs';
export async function GET(req: Request, { params }: { params: Promise<{ id: string }> }) {
  try {
    const { id } = await params;
    if (id !== 'attention-demo') authorize(req);
    return Response.json(ontology(await loadRun(id)), {
      headers: {
        'Content-Disposition': `attachment; filename="${id}-terms.json"`,
        'Cache-Control': 'no-store',
      },
    });
  } catch (e) {
    return failure(e);
  }
}
