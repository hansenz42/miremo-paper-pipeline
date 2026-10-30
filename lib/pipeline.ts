import { randomUUID } from 'node:crypto';
import { z } from 'zod';
import { preselect, structure, key } from './preselect';
import { ask, modelConfig, type Ask } from './model';
import { loadRun, saveRun, withLock } from './store';
import type { Run, Meta, Candidate, ReadingJob } from './types';
const words = z.string().trim().min(1).max(12000),
  ids = z.array(z.string());
const metaSchema = z.object({
  overview: words,
  role: words,
  focus: words,
  sourceIds: ids.min(1),
  uncertainties: z.array(z.string()),
});
const readingSchema = z.object({
  updates: z.array(z.object({ id: z.string(), note: words })),
  newCandidates: z.array(z.object({ name: words, note: words, quote: words })),
});
const organizeSchema = z.object({
  decisions: z.array(
    z.object({
      id: z.string(),
      decision: z.enum(['retain', 'exclude', 'pending']),
      name: words,
      aliases: z.array(z.string()),
      definition: z.string(),
      reason: words,
      claims: z.array(z.object({ text: words, shardId: z.string(), quote: words })),
    }),
  ),
});
function require(condition: unknown, message: string): asserts condition {
  if (!condition) throw new Error(message);
}
function sameIds(actual: string[], expected: string[]) {
  require(actual.length === expected.length &&
    new Set(actual).size === actual.length &&
    actual.every((x) => expected.includes(x)), '模型遗漏、重复或新增了候选 ID，本步骤未采纳。');
}
export async function createRun(input: {
  title: string;
  text?: string;
  attention?: boolean;
}): Promise<Run> {
  const cfg = modelConfig();
  let prepared;
  if (input.attention) {
    const demo = await loadRun('attention-demo');
    prepared = { chapters: demo.chapters, shards: demo.shards };
  } else prepared = structure(input.text || '');
  const candidates = preselect(prepared.shards);
  require(candidates.length > 0, '未找到英文术语候选。');
  const run: Run = {
    schemaVersion: 1,
    id: randomUUID(),
    title: input.title.trim().slice(0, 200) || 'Untitled paper',
    createdAt: new Date().toISOString(),
    ...(input.attention ? { sourceUrl: 'https://arxiv.org/abs/1706.03762' } : {}),
    provenance: {
      kind: 'live',
      model: cfg.model,
      note: '本次独立模型运行，结果待人工检查。',
      algorithm: 'winkNLP POS + TypeScript C-Value',
    },
    ...prepared,
    candidates,
    terms: [],
    stage: 'meta',
    status: 'ready',
    cursor: 0,
    chapterMeta: {},
    readingJobs: [],
    organizeIds: [],
    attemptedCalls: 0,
    usage: { input: 0, output: 0 },
    modelConfig: cfg,
  };
  await saveRun(run);
  return run;
}
export async function step(run: Run, call: Ask = ask): Promise<Run> {
  if (run.stage === 'complete') return run;
  run.status = 'running';
  delete run.error;
  if (run.stage === 'meta') {
    const chapter = run.cursor === 0 ? undefined : run.chapters[run.cursor - 1];
    const scope = chapter ? run.shards.filter((s) => s.chapterId === chapter.id) : run.shards;
    const sample = [
      ...new Map([...scope.slice(0, 3), ...scope.slice(-1)].map((s) => [s.id, s])).values(),
    ];
    const value = await call(
      run,
      `meta-${chapter?.id || 'document'}`,
      '抽样粗读。输出 {overview,role,focus,sourceIds,uncertainties}。overview概述，role说明文档/章节作用，focus描述专业术语关注方向；sourceIds只引用本次sources。承认抽样局限，不把Meta当定义证据。',
      { scope: chapter?.title || run.title, sources: sample },
      metaSchema,
      (v) =>
        require(v.sourceIds.every((id) =>
          sample.some((s) => s.id === id),
        ), 'Meta 引用了本次原文之外的分片。'),
    );
    if (chapter) run.chapterMeta[chapter.id] = value as Meta;
    else run.documentMeta = value as Meta;
    run.cursor++;
    if (run.cursor > run.chapters.length) {
      run.stage = 'reading';
      run.cursor = 0;
      run.readingJobs = [];
      for (const shard of run.shards) {
        if (shard.kind === 'image') continue;
        const related = run.candidates
          .filter((c) => c.spans.some((s) => s.shardId === shard.id))
          .map((c) => c.id);
        for (let n = 0; n < related.length; n += 24)
          run.readingJobs.push({
            shardId: shard.id,
            candidateIds: related.slice(n, n + 24),
            discovery: false,
          });
        run.readingJobs.push({ shardId: shard.id, candidateIds: related, discovery: true });
      }
    }
  } else if (run.stage === 'reading') {
    const job: ReadingJob = run.readingJobs[run.cursor];
    require(job, '阅读任务不存在。');
    const shard = run.shards.find((s) => s.id === job.shardId)!;
    const related = run.candidates.filter((c) => job.candidateIds.includes(c.id));
    const value = await call(
      run,
      `read-${run.cursor}`,
      job.discovery
        ? '发现当前原文中的重要新术语。已有候选不重复新增。输出 {updates:[],newCandidates:[{name,note,quote}]}。quote必须逐字复制currentSource中的连续文字。只做TERM，不抽取关系。'
        : '逐项阅读候选在当前原文中的专业含义或不属于术语的原因。每个输入ID恰好返回一项。输出 {updates:[{id,note}],newCandidates:[]}。note是批注，不能修改名称或写最终定义。',
      {
        currentSource: shard,
        documentMeta: run.documentMeta,
        chapterMeta: run.chapterMeta[shard.chapterId],
        candidates: related.map((c) => ({ id: c.id, name: c.name })),
      },
      readingSchema,
      (v) => {
        sameIds(
          v.updates.map((x) => x.id),
          job.discovery ? [] : job.candidateIds,
        );
        require(job.discovery || v.newCandidates.length === 0, '已有候选批次不接受新词。');
        require(v.newCandidates.every((x) =>
          shard.text.includes(x.quote),
        ), '新候选引用不属于当前原文。');
      },
    );
    for (const update of value.updates) {
      const c = run.candidates.find((c) => c.id === update.id)!;
      c.notes.push({ shardId: shard.id, text: update.note });
    }
    for (const item of value.newCandidates) {
      const existing = run.candidates.find((c) => key(c.name) === key(item.name));
      if (existing) {
        existing.notes.push({ shardId: shard.id, text: item.note });
        if (!existing.evidenceShardIds.includes(shard.id)) existing.evidenceShardIds.push(shard.id);
        continue;
      }
      const spans = [];
      const index = shard.text.toLowerCase().indexOf(item.name.toLowerCase());
      if (index >= 0)
        spans.push({
          shardId: shard.id,
          start: index,
          end: index + item.name.length,
          quote: shard.text.slice(index, index + item.name.length),
        });
      run.candidates.push({
        id: `N${String(run.candidates.filter((c) => c.origin === 'model').length + 1).padStart(4, '0')}`,
        type: 'TERM',
        name: item.name,
        score: 0,
        origin: 'model',
        spans,
        evidenceShardIds: [shard.id],
        notes: [{ shardId: shard.id, text: item.note }],
        status: 'unprocessed',
        modelProcessed: false,
        reason: '',
        aliases: [],
        definition: '',
        claims: [],
      });
    }
    run.cursor++;
    if (run.cursor >= run.readingJobs.length) {
      run.stage = 'organize';
      run.cursor = 0;
      run.organizeIds = run.candidates.map((c) => c.id);
    }
  } else if (run.stage === 'organize') {
    const batch = run.organizeIds
      .slice(run.cursor * 6, (run.cursor + 1) * 6)
      .map((id) => run.candidates.find((c) => c.id === id)!);
    const sourceIds = new Set(batch.flatMap((c) => c.evidenceShardIds));
    const sources = run.shards.filter((s) => sourceIds.has(s.id));
    const value = await call(
      run,
      `organize-${run.cursor}`,
      '根据原文和阅读批注逐项整理TERM候选。每个输入ID恰好返回一项，不跨ID合并。输出 {decisions:[{id,decision:"retain|exclude|pending",name,aliases,definition,reason,claims:[{text,shardId,quote}]}]}。retain须有定义和逐字原文quote依据；定义只由claims支持，不用外部知识补造。exclude/pending可为空定义和claims。name为规范名称；aliases只收集原文支持的同义名称。',
      { candidates: batch.map((c) => ({ id: c.id, name: c.name, notes: c.notes })), sources },
      organizeSchema,
      (v) => {
        sameIds(
          v.decisions.map((d) => d.id),
          batch.map((c) => c.id),
        );
        for (const d of v.decisions) {
          require(d.decision !== 'retain' ||
            (d.definition.trim() && d.claims.length), '保留术语必须有定义和原文证据。');
          for (const claim of d.claims)
            require(sources.some(
              (s) => s.id === claim.shardId && s.text.includes(claim.quote),
            ), '定义引用无法在本次原文中定位。');
        }
      },
    );
    for (const d of value.decisions) {
      const candidate = run.candidates.find((c) => c.id === d.id)!;
      Object.assign(candidate, {
        modelProcessed: true,
        status: d.decision,
        reason: d.reason,
        canonicalId: d.id,
        canonicalName: d.name,
        aliases: d.aliases,
        definition: d.definition,
        claims: d.claims.map((c) => ({ text: c.text, shardIds: [c.shardId], quote: c.quote })),
      });
    }
    run.cursor++;
    if (run.cursor * 6 >= run.organizeIds.length) {
      require(run.candidates.every((c) => c.modelProcessed), '仍有候选未经模型整理。');
      run.terms = run.candidates
        .filter((c) => c.status === 'retain')
        .map((c) => ({
          id: c.id,
          type: 'TERM',
          name: c.canonicalName || c.name,
          aliases: c.aliases,
          definition: c.definition,
          memberIds: [c.id],
          claims: c.claims,
          spans: c.spans,
          reviewStatus: 'pending_user_review',
        }));
      run.stage = 'complete';
      run.status = 'complete';
      run.cursor = 1;
    }
  }
  return run;
}
export async function advance(id: string) {
  require(id !== 'attention-demo', '历史示例只读，请创建新任务。');
  return withLock(id, async () => {
    const run = await loadRun(id);
    try {
      await step(run);
    } catch (e) {
      run.status = 'failed';
      run.error =
        e instanceof z.ZodError
          ? '模型输出结构未通过校验，可重试当前步骤。'
          : e instanceof Error
            ? e.message
            : '任务失败。';
    }
    await saveRun(run);
    return run;
  });
}
