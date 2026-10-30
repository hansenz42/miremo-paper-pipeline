import { authorize, failure } from '@/lib/http';
import { advance } from '@/lib/pipeline';
import { progress } from '@/lib/types';
export const runtime = 'nodejs';
export const maxDuration = 180;
export async function POST(req: Request, { params }: { params: Promise<{ id: string }> }) {
  try {
    authorize(req);
    const { id } = await params;
    return Response.json(progress(await advance(id)));
  } catch (e) {
    return failure(e);
  }
}
