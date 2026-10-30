import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { mkdtemp, readFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { structure, preselect } from '../lib/preselect';
import { createRun, step, advance } from '../lib/pipeline';
import { loadRun, saveRun, withLock } from '../lib/store';
import { ontology } from '../lib/types';
import { highlightedSegments } from '../lib/highlights';
import { authorize, publicRun } from '../lib/http';
import { ask, type Ask } from '../lib/model';
import { z } from 'zod';
let dir: string;
beforeEach(async () => {
  dir = await mkdtemp(path.join(tmpdir(), 'paper-ts-test-'));
  vi.stubEnv('PAPER_DATA_DIR', dir);
  vi.stubEnv('PAPER_MODEL', 'test-model');
  vi.stubEnv('PAPER_API_KEY', 'test-key');
  vi.stubEnv('PAPER_RUN_TOKEN', 'test-passphrase');
  vi.stubEnv('PAPER_BASE_URL', 'https://example.invalid/v1');
  vi.stubEnv('PAPER_REQUEST_OPTIONS', '{}');
  vi.stubEnv('PAPER_MAX_CALLS', '500');
});
afterEach(async () => {
  vi.unstubAllEnvs();
  vi.restoreAllMocks();
  await rm(dir, { recursive: true, force: true });
});
const fake: Ask = async (_run, callId, _prompt, input, schema, validate) => {
  const data = input as {
    sources?: { id: string; text: string }[];
    candidates?: { id: string; name: string }[];
    currentSource?: { id: string; text: string };
  };
  let value: unknown;
  if (callId.startsWith('meta'))
    value = {
      overview: 'Test overview',
      role: 'Test role',
      focus: 'TERM',
      sourceIds: [data.sources![0].id],
      uncertainties: [],
    };
  else if (callId.startsWith('read')) {
    const discovery = _prompt.startsWith('发现');
    value = {
      updates: discovery
        ? []
        : data.candidates!.map((c) => ({ id: c.id, note: 'Context read in the current source.' })),
      newCandidates: [],
    };
  } else
    value = {
      decisions: data.candidates!.map((c) => ({
        id: c.id,
        decision: 'retain',
        name: c.name,
        aliases: [],
        definition: 'A definition from the supplied source.',
        reason: 'Supported in the source.',
        claims: [
          {
            text: 'A definition from the supplied source.',
            shardId: data.sources![0].id,
            quote: data.sources![0].text,
          },
        ],
      })),
    };
  const parsed = schema.parse(value);
  validate?.(parsed);
  return parsed;
};
describe('preselection and evidence', () => {
  it('preserves complete text and does not mistake page numbers for chapters', () => {
    const text =
      '  Abstract\n\nAttention maps queries.\n\n1 Introduction\n\n' +
      'Attention uses keys and values. '.repeat(80) +
      '\n\n2\nMore prose.';
    const result = structure(text);
    expect(result.chapters).toHaveLength(2);
    expect(result.shards.map((s) => s.text).join('')).toBe(text);
    expect(result.shards.every((s) => s.text.length <= 1200)).toBe(true);
  });
  it('uses actual NLP results with exact offsets including unicode', () => {
    const text =
      '😀 Attention maps queries and keys. Neural networks use attention. Neural networks use attention.';
    const { shards } = structure(text);
    const candidates = preselect(shards);
    expect(candidates.length).toBeGreaterThan(0);
    expect(candidates.some((c) => c.name.toLowerCase().includes('neural networks'))).toBe(true);
    for (const c of candidates)
      for (const s of c.spans)
        expect(shards.find((x) => x.id === s.shardId)!.text.slice(s.start, s.end)).toBe(s.quote);
    expect(candidates.every((c) => !c.modelProcessed)).toBe(true);
  });
  it('merges overlapping marks but refuses invalid highlights', () => {
    const s = (start: number, end: number, quote: string) => ({ shardId: 'S', start, end, quote });
    const parts = highlightedSegments('abc def', [s(0, 3, 'abc'), s(1, 3, 'bc'), s(4, 7, 'bad')]);
    expect(parts).toEqual([
      { text: 'abc', highlight: true, start: 0 },
      { text: ' def', highlight: false, start: 3 },
    ]);
  });
});
describe('historical Attention data', () => {
  it('contains all model judged candidates and checked source locations', async () => {
    const run = await loadRun('attention-demo');
    expect(run.candidates).toHaveLength(998);
    expect(run.terms).toHaveLength(160);
    expect(run.candidates.every((c) => c.modelProcessed && c.reason && c.type === 'TERM')).toBe(
      true,
    );
    for (const c of run.candidates)
      for (const s of c.spans)
        expect(run.shards.find((x) => x.id === s.shardId)!.text.slice(s.start, s.end)).toBe(
          s.quote,
        );
    for (const t of run.terms)
      for (const claim of t.claims)
        expect(claim.shardIds.every((id) => run.shards.some((s) => s.id === id))).toBe(true);
    expect(
      /\/Users\/|api_key|file_id|[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}/.test(
        JSON.stringify(run),
      ),
    ).toBe(false);
  });
});
describe('complete execution', () => {
  it('runs all stages and persists a model-processed TERM collection', async () => {
    let run = await createRun({
      title: 'Example',
      text: '# Attention\n\nAttention maps queries and keys to values.',
    });
    expect(ontology(run).complete).toBe(false);
    let calls = 0;
    while (run.stage !== 'complete') {
      run = await step(run, fake);
      await saveRun(run);
      run = await loadRun(run.id);
      if (++calls > 100) throw new Error('Loop');
    }
    expect(run.terms.length).toBeGreaterThan(0);
    expect(run.candidates.every((c) => c.modelProcessed)).toBe(true);
    expect(run.terms.every((t) => t.type === 'TERM' && t.claims.length > 0)).toBe(true);
    expect(ontology(run).finalAdoption).toBe(false);
    const again = await step(run, fake);
    expect(again).toEqual(run);
  });
  it('rejects fabricated meta sources before changing progress', async () => {
    const run = await createRun({ title: 'Example', text: 'Attention maps keys.' });
    const bad: Ask = async (r, id, p, input, schema, validate) => {
      const v = schema.parse({
        overview: 'x',
        role: 'x',
        focus: 'x',
        sourceIds: ['invented'],
        uncertainties: [],
      });
      validate?.(v);
      return v;
    };
    await expect(step(run, bad)).rejects.toThrow('Meta');
    expect(run.cursor).toBe(0);
    expect(run.candidates.every((c) => !c.modelProcessed)).toBe(true);
  });
  it('rejects incomplete candidate coverage', async () => {
    const run = await createRun({ title: 'Example', text: 'Attention maps queries.' });
    run.stage = 'organize';
    run.organizeIds = run.candidates.map((c) => c.id);
    const bad: Ask = async (r, id, p, input, schema, validate) => {
      const v = schema.parse({ decisions: [] });
      validate?.(v);
      return v;
    };
    await expect(step(run, bad)).rejects.toThrow('ID');
    expect(run.candidates.every((c) => !c.modelProcessed)).toBe(true);
  });
  it('refuses concurrent execution and leaves the historical demo read-only', async () => {
    const run = await createRun({ title: 'Example', text: 'Attention maps queries.' });
    await withLock(run.id, async () => {
      await expect(withLock(run.id, async () => 0)).rejects.toThrow('正在处理');
    });
    await expect(advance('attention-demo')).rejects.toThrow('只读');
  });
});
describe('model transport', () => {
  it('caches validated output without leaking credentials and enforces request budget', async () => {
    const run = await createRun({ title: 'Example', text: 'Attention maps keys.' });
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(
        JSON.stringify({
          choices: [{ finish_reason: 'stop', message: { content: '{"answer":"ok"}' } }],
          usage: { prompt_tokens: 3, completion_tokens: 2 },
        }),
      ),
    );
    const schema = z.object({ answer: z.string() });
    await ask(run, 'a', 'prompt', {}, schema);
    await ask(run, 'a', 'prompt', {}, schema);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(run.attemptedCalls).toBe(1);
    vi.stubEnv('PAPER_MAX_CALLS', '1');
    await expect(ask(run, 'b', 'prompt', {}, schema)).rejects.toThrow('上限');
    expect(JSON.stringify(publicRun(run))).not.toContain('modelConfig');
    expect(JSON.stringify(publicRun(run))).not.toContain('test-key');
  });
  it('does not accept truncated outputs', async () => {
    const run = await createRun({ title: 'Example', text: 'Attention maps keys.' });
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(
        JSON.stringify({ choices: [{ finish_reason: 'length', message: { content: '{}' } }] }),
      ),
    );
    await expect(ask(run, 'a', 'prompt', {}, z.object({}))).rejects.toThrow('完整');
    expect(run.attemptedCalls).toBe(1);
  });
});
describe('execution authentication', () => {
  it('requires a token and rejects cross-origin requests', () => {
    const req = (token: string, origin = 'http://localhost:3030') =>
      new Request('http://localhost:3030/api/runs', {
        headers: { host: 'localhost:3030', 'x-run-token': token, origin },
      });
    expect(() => authorize(req('wrong'))).toThrow('UNAUTHORIZED');
    expect(() => authorize(req('test-passphrase', 'https://evil.example'))).toThrow('UNAUTHORIZED');
    expect(() => authorize(req('test-passphrase'))).not.toThrow();
  });
});
