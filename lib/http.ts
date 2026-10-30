import { timingSafeEqual } from 'node:crypto';
import type { Run } from './types';
export function authorize(req: Request) {
  const token = process.env.PAPER_RUN_TOKEN;
  if (!token) throw new Error('EXECUTION_DISABLED');
  const supplied = req.headers.get('x-run-token') || '';
  const a = Buffer.from(token),
    b = Buffer.from(supplied);
  if (a.length !== b.length || !timingSafeEqual(a, b)) throw new Error('UNAUTHORIZED');
  const origin = req.headers.get('origin');
  if (origin && new URL(origin).host !== req.headers.get('host')) throw new Error('UNAUTHORIZED');
}
export function publicRun(run: Run) {
  const { modelConfig: _, readingJobs: __, organizeIds: ___, ...rest } = run;
  return { ...rest, readingJobs: [], organizeIds: [] };
}
export async function body(req: Request) {
  const reader = req.body?.getReader();
  if (!reader) throw new Error('EMPTY_BODY');
  let bytes = 0;
  const chunks: Uint8Array[] = [];
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    bytes += value.length;
    if (bytes > 850000) {
      await reader.cancel();
      throw new Error('TOO_LARGE');
    }
    chunks.push(value);
  }
  return JSON.parse(Buffer.concat(chunks).toString('utf8'));
}
export function failure(e: unknown) {
  const message = e instanceof Error ? e.message : '';
  if (['UNAUTHORIZED', 'EXECUTION_DISABLED'].includes(message))
    return Response.json(
      { error: message === 'UNAUTHORIZED' ? '运行口令不正确。' : '服务端尚未启用新任务。' },
      { status: message === 'UNAUTHORIZED' ? 401 : 503 },
    );
  if (message === 'TOO_LARGE') return Response.json({ error: '输入文件过大。' }, { status: 413 });
  if ((e as NodeJS.ErrnoException)?.code === 'ENOENT')
    return Response.json({ error: '任务不存在。' }, { status: 404 });
  return Response.json(
    { error: message.includes('任务正在') ? message : '请求失败，请检查输入或服务端配置。' },
    { status: message.includes('任务正在') ? 409 : 400 },
  );
}
