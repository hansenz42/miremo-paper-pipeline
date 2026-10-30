import winkNLP, { type ItemToken, type ItsFunction } from 'wink-nlp';
import model from 'wink-eng-lite-web-model';
import type { Candidate, Chapter, Shard, Span } from './types';
const nlp = winkNLP(model, ['sbd', 'pos']);
const { its } = nlp;
export const key = (s: string) =>
  s
    .toLowerCase()
    .replace(/[‐‑–—-]/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();
export function structure(text: string): { chapters: Chapter[]; shards: Shard[] } {
  if (!text.trim() || text.length > 200_000) throw new Error('请输入 1–200000 字符的英文正文。');
  const starts = [
    ...new Set([
      0,
      ...Array.from(
        text.matchAll(
          /^[ \t]*(?:#{1,2}[ \t]+[^\n]+|[1-9]\d?[ \t]+[A-Z][^\n]{0,90}|Abstract|References)[ \t]*$/gm,
        ),
        (m) => m.index!,
      ),
      text.length,
    ]),
  ].sort((a, b) => a - b);
  const chapters: Chapter[] = [],
    shards: Shard[] = [];
  for (let i = 0; i < starts.length - 1; i++) {
    const start = starts[i],
      end = starts[i + 1],
      id = `CH${String(i + 1).padStart(3, '0')}`;
    const chapter: Chapter = {
      id,
      title:
        text
          .slice(start, end)
          .split('\n')[0]
          .replace(/^#+\s*/, '')
          .trim() || 'Front matter',
      shardIds: [],
    };
    let at = start;
    while (at < end) {
      let to = Math.min(at + 1200, end);
      if (to < end) {
        const part = text.slice(at, to);
        const breaks = [...part.matchAll(/\n\s*\n|[.!?]\s+/g)];
        const last = breaks.filter((m) => m.index! > 400).at(-1);
        if (last) to = at + last.index! + last[0].length;
        if (to === at + 1200) {
          const space = part.lastIndexOf(' ');
          if (space > 700) to = at + space + 1;
        }
      }
      const sid = `SH${String(shards.length + 1).padStart(3, '0')}`;
      shards.push({ id: sid, chapterId: id, text: text.slice(at, to), kind: 'paragraph' });
      chapter.shardIds.push(sid);
      at = to;
    }
    chapters.push(chapter);
  }
  return { chapters, shards };
}
export function preselect(shards: Shard[]): Candidate[] {
  const pool = new Map<string, { name: string; words: string[]; spans: Span[] }>();
  for (const shard of shards) {
    const tokens: { value: string; lemma: string; pos: string; start: number; end: number }[] = [];
    let cursor = 0;
    nlp
      .readDoc(shard.text)
      .tokens()
      .each((token: ItemToken) => {
        const value = token.out();
        const start = shard.text.indexOf(value, cursor);
        if (start < 0) {
          tokens.push({ value, lemma: value, pos: 'X', start: cursor, end: cursor });
          return;
        }
        const end = start + value.length;
        cursor = end;
        tokens.push({
          value,
          lemma: String(token.out(its.lemma as unknown as ItsFunction<string>)),
          pos: String(token.out(its.pos)),
          start,
          end,
        });
      });
    for (let i = 0; i < tokens.length; i++)
      for (let length = 1; length <= 5 && i + length <= tokens.length; length++) {
        const list = tokens.slice(i, i + length);
        if (!list.every((t) => ['ADJ', 'NOUN', 'PROPN'].includes(t.pos))) break;
        if (!['NOUN', 'PROPN'].includes(list.at(-1)!.pos)) continue;
        const words = list.map((t) => key(t.pos === 'NOUN' ? t.lemma : t.value));
        const normalized = words.join(' ');
        if (!/[a-z]/i.test(normalized)) continue;
        const start = list[0].start,
          end = list.at(-1)!.end,
          quote = shard.text.slice(start, end);
        const entry = pool.get(normalized) ?? { name: quote, words, spans: [] };
        entry.spans.push({ shardId: shard.id, start, end, quote });
        pool.set(normalized, entry);
      }
  }
  const parents = new Map<string, Set<string>>();
  for (const [k, v] of pool)
    for (let length = 1; length < v.words.length; length++)
      for (let i = 0; i + length <= v.words.length; i++) {
        const sub = v.words.slice(i, i + length).join(' ');
        if (pool.has(sub)) {
          const p = parents.get(sub) ?? new Set();
          p.add(k);
          parents.set(sub, p);
        }
      }
  const scored = [...pool]
    .map(([k, v]) => {
      const p = parents.get(k);
      const nested = p ? [...p].reduce((a, k) => a + pool.get(k)!.spans.length, 0) / p.size : 0;
      return { ...v, score: Math.log2(v.words.length + 0.1) * (v.spans.length - nested) };
    })
    .sort((a, b) => b.score - a.score || a.name.localeCompare(b.name));
  return scored.map((c, i) => ({
    id: `J${String(i + 1).padStart(4, '0')}`,
    name: c.name,
    type: 'TERM',
    score: c.score,
    origin: 'algorithm',
    spans: c.spans,
    evidenceShardIds: [...new Set(c.spans.map((s) => s.shardId))],
    notes: [],
    modelProcessed: false,
    status: 'unprocessed',
    reason: '',
    aliases: [],
    definition: '',
    claims: [],
  }));
}
