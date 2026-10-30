import { mkdir, readFile, writeFile, rename, unlink, open } from 'node:fs/promises';
import path from 'node:path';
import { randomUUID } from 'node:crypto';
import type { Run } from './types';
export const root = () =>
  path.resolve(/* turbopackIgnore: true */ process.env.PAPER_DATA_DIR || '.paper-runs');
export function validId(id: string) {
  if (!/^[a-z0-9-]{1,80}$/.test(id)) throw new Error('Invalid run ID');
  return id;
}
export async function loadRun(id: string): Promise<Run> {
  validId(id);
  return JSON.parse(
    await readFile(
      id === 'attention-demo'
        ? path.join(process.cwd(), 'data/attention.json')
        : path.join(/* turbopackIgnore: true */ root(), id, 'run.json'),
      'utf8',
    ),
  );
}
export async function saveRun(run: Run) {
  const dir = path.join(/* turbopackIgnore: true */ root(), validId(run.id));
  await mkdir(dir, { recursive: true });
  const temp = path.join(dir, `.${randomUUID()}.tmp`);
  await writeFile(temp, JSON.stringify(run));
  await rename(temp, path.join(dir, 'run.json'));
}
export async function writeArtifact(id: string, file: string, value: unknown) {
  const dir = path.join(/* turbopackIgnore: true */ root(), validId(id), 'calls');
  await mkdir(dir, { recursive: true });
  await writeFile(path.join(dir, file + '.json'), JSON.stringify(value, null, 2));
}
export async function readArtifact<T>(id: string, file: string): Promise<T | undefined> {
  try {
    return JSON.parse(
      await readFile(
        path.join(/* turbopackIgnore: true */ root(), validId(id), 'calls', file + '.json'),
        'utf8',
      ),
    );
  } catch (e) {
    if ((e as NodeJS.ErrnoException).code === 'ENOENT') return;
    throw e;
  }
}
export async function withLock<T>(id: string, fn: () => Promise<T>): Promise<T> {
  const file = path.join(/* turbopackIgnore: true */ root(), validId(id), 'active.lock');
  let handle;
  try {
    handle = await open(file, 'wx');
  } catch (e) {
    if ((e as NodeJS.ErrnoException).code === 'EEXIST')
      throw new Error('任务正在处理，请稍后重试。');
    throw e;
  }
  try {
    await handle.writeFile(
      JSON.stringify({ pid: process.pid, startedAt: new Date().toISOString() }),
    );
    return await fn();
  } finally {
    await handle.close();
    await unlink(file);
  }
}
