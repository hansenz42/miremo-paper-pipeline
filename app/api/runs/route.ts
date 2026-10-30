import { z } from 'zod';
import { authorize, body, failure } from '@/lib/http';
import { createRun } from '@/lib/pipeline';
import { progress } from '@/lib/types';
export const runtime = 'nodejs';
export async function GET() {
  return Response.json({
    executionEnabled: !!(
      process.env.PAPER_API_KEY &&
      process.env.PAPER_MODEL &&
      process.env.PAPER_RUN_TOKEN
    ),
  });
}
export async function POST(req: Request) {
  try {
    authorize(req);
    const value = z
      .object({
        title: z.string().min(1).max(200),
        attention: z.boolean().optional(),
        text: z.string().max(200000).optional(),
      })
      .parse(await body(req));
    if (!value.attention && !value.text?.trim()) throw new Error('EMPTY_BODY');
    return Response.json(progress(await createRun(value)), { status: 201 });
  } catch (e) {
    return failure(e);
  }
}
