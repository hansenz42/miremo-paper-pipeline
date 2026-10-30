'use client';
import { useEffect, useMemo, useState } from 'react';
import {
  ArrowDownToLine,
  ArrowLeft,
  ArrowRight,
  ArrowUpRight,
  BookOpen,
  ChevronDown,
  FileText,
  Layers,
  Search,
  SlidersHorizontal,
  Sparkles,
  X,
} from 'lucide-react';
import type { Run, Candidate, Span, Meta } from '@/lib/types';
import { ontology } from '@/lib/types';
import { highlightedSegments } from '@/lib/highlights';
const labels: Record<Candidate['status'], string> = {
  retain: '保留',
  merged: '已归并',
  exclude: '排除',
  pending: '待确认',
  unprocessed: '未处理',
};
function MetaCard({
  meta,
  name,
  jump,
}: {
  meta?: Meta;
  name: string;
  jump: (span: { shardId: string }) => void;
}) {
  if (!meta) return null;
  return (
    <section className="meta-card">
      <span className="eyebrow">READING NOTES</span>
      <h3>{name}</h3>
      <p>{meta.overview}</p>
      <dl>
        <dt>内容作用</dt>
        <dd>{meta.role}</dd>
        <dt>关注方向</dt>
        <dd>{meta.focus}</dd>
      </dl>
      <div className="evidence-links">
        {meta.sourceIds.map((id) => (
          <button key={id} onClick={() => jump({ shardId: id })}>
            {id}
            <ArrowUpRight size={12} />
          </button>
        ))}
      </div>
      {meta.uncertainties.length > 0 && <p className="muted">{meta.uncertainties.join('；')}</p>}
    </section>
  );
}
export default function PaperStudio({ initialRun }: { initialRun: Run }) {
  const run = initialRun;
  const [selectedId, setSelectedId] = useState('J0055');
  const [query, setQuery] = useState('');
  const [filter, setFilter] = useState('all');
  const [limit, setLimit] = useState(80);
  const [view, setView] = useState<'paper' | 'meta'>('paper');
  const [allMarks, setAllMarks] = useState(false);
  const [occurrence, setOccurrence] = useState(0);
  const [mobile, setMobile] = useState<'list' | 'paper' | 'detail'>('paper');
  useEffect(() => {
    const first = initialRun.candidates.find((c) => c.id === 'J0055')?.spans[0];
    if (first) jump(first);
  }, [initialRun]);
  const selected = run.candidates.find((c) => c.id === selectedId) || run.candidates[0];
  const filtered = useMemo(
    () =>
      run.candidates.filter(
        (c) =>
          (filter === 'all' || (filter === 'processed' ? c.modelProcessed : c.status === filter)) &&
          (!query ||
            [c.name, c.canonicalName, ...c.aliases].some((v) =>
              v?.toLowerCase().includes(query.toLowerCase()),
            )),
      ),
    [run, query, filter],
  );
  const processed = run.candidates.filter((c) => c.modelProcessed).length;
  const spans = selected?.spans || [];
  const marks = useMemo(() => {
    const map = new Map<string, Span[]>();
    for (const c of allMarks ? run.candidates : selected ? [selected] : [])
      for (const s of c.spans) map.set(s.shardId, [...(map.get(s.shardId) || []), s]);
    return map;
  }, [allMarks, run, selected]);
  const canonical = run.terms.find((t) => t.id === selected?.canonicalId);
  function jump(span: Pick<Span, 'shardId'> & Partial<Span>) {
    setView('paper');
    setMobile('paper');
    setTimeout(() => {
      const element = document.getElementById(`shard-${span.shardId}`);
      const hit =
        span.start !== undefined ? element?.querySelector(`[data-start="${span.start}"]`) : null;
      (hit || element)?.scrollIntoView({ behavior: 'smooth', block: 'center' });
      element?.classList.add('pulse');
      setTimeout(() => element?.classList.remove('pulse'), 1300);
    }, 30);
  }
  function choose(c: Candidate) {
    setSelectedId(c.id);
    setOccurrence(0);
    if (c.spans[0]) jump(c.spans[0]);
    else if (c.evidenceShardIds[0]) jump({ shardId: c.evidenceShardIds[0] });
  }
  function nextHit(direction: number) {
    if (!spans.length) return;
    const n = (occurrence + direction + spans.length) % spans.length;
    setOccurrence(n);
    jump(spans[n]);
  }
  function download() {
    const blob = new Blob([JSON.stringify(ontology(run), null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = `${run.id}-terms.json`;
    link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  return (
    <main className="studio">
      <header className="topbar">
        <a className="brand" href="/" aria-label="Miremo 首页">
          <span className="brand-icon">
            <Layers size={21} />
          </span>
          <strong>
            miremo<span> / paper studio</span>
          </strong>
        </a>
        <div className="top-actions">
          <a
            href="https://github.com/hansenz42/miremo-paper-pipeline"
            target="_blank"
            rel="noreferrer"
          >
            GitHub <ArrowUpRight size={14} />
          </a>
        </div>
      </header>
      <section className="hero">
        <div className="hero-heading">
          <h1>{run.title}</h1>
          <p className="hero-subtitle">从词语到概念，让每一个术语都有出处。</p>
        </div>
        <div className="hero-actions">
          <button className="secondary" onClick={download}>
            <ArrowDownToLine size={16} />
            导出 TERM 集合
          </button>
        </div>
      </section>
      <section className="run-strip">
        <div className="run-info">
          <span className="model-badge">
            <Sparkles size={13} />
            {run.provenance.kind === 'historical_model_run' ? '历史模型结果' : '当前运行'}
          </span>
          <span>{run.provenance.model}</span>
          <span className="separator">/</span>
          <span>待人工确认</span>
        </div>
        <div className="run-numbers">
          <span>
            <b>{run.candidates.length.toLocaleString()}</b> 候选词
          </span>
          <span>
            <b>{processed.toLocaleString()}</b> 已处理
          </span>
          <span>
            <b>{run.terms.length}</b> 最终术语
          </span>
        </div>
      </section>
      <nav className="mobile-tabs">
        {(
          [
            ['list', '候选词'],
            ['paper', '论文正文'],
            ['detail', '术语详情'],
          ] as const
        ).map(([id, name]) => (
          <button className={mobile === id ? 'active' : ''} onClick={() => setMobile(id)} key={id}>
            {name}
          </button>
        ))}
      </nav>
      <div className={`workspace mobile-${mobile}`}>
        <aside className="candidate-panel">
          <div className="panel-title">
            <h2>候选词表</h2>
            <span>{run.candidates.length}</span>
          </div>
          <label className="searchbox">
            <Search size={15} />
            <input
              aria-label="搜索候选词"
              placeholder="搜索名称、别名…"
              value={query}
              onChange={(e) => {
                setQuery(e.target.value);
                setLimit(80);
              }}
            />
            {query && (
              <button onClick={() => setQuery('')} aria-label="清空搜索">
                <X size={13} />
              </button>
            )}
          </label>
          <div className="filterbar">
            <SlidersHorizontal size={13} />
            <select
              aria-label="筛选候选状态"
              value={filter}
              onChange={(e) => {
                setFilter(e.target.value);
                setLimit(80);
              }}
            >
              <option value="all">全部候选 · {run.candidates.length}</option>
              <option value="processed">模型已处理 · {processed}</option>
              {Object.entries(labels).map(([value, label]) => (
                <option key={value} value={value}>
                  {label} · {run.candidates.filter((c) => c.status === value).length}
                </option>
              ))}
            </select>
          </div>
          <div className="candidate-list">
            {filtered.slice(0, limit).map((c) => (
              <button
                className={`candidate-row ${selected?.id === c.id ? 'selected' : ''}`}
                key={c.id}
                onClick={() => choose(c)}
              >
                <div className="candidate-name">{c.name}</div>
                <div className="candidate-sub">
                  <span className={`status-dot ${c.status}`} />
                  <span>{labels[c.status]}</span>
                  <span className="row-count">{c.spans.length} 处</span>
                </div>
              </button>
            ))}
            {filtered.length === 0 && <p className="empty-small">没有匹配的候选词。</p>}
            {filtered.length > limit && (
              <button className="load-more" onClick={() => setLimit((v) => v + 100)}>
                继续显示 · 还有 {filtered.length - limit} 条
              </button>
            )}
          </div>
          <div className="panel-foot">
            <span className="live-dot" />
            {filtered.length} 条结果 · 点击定位原文
          </div>
        </aside>
        <section className="paper-panel">
          <div className="paper-toolbar">
            <div className="view-tabs">
              <button className={view === 'paper' ? 'active' : ''} onClick={() => setView('paper')}>
                <FileText size={14} />
                论文正文
              </button>
              <button className={view === 'meta' ? 'active' : ''} onClick={() => setView('meta')}>
                <BookOpen size={14} />
                阅读提纲
              </button>
            </div>
            <div className="paper-tools">
              {view === 'paper' && (
                <label className="highlight-toggle">
                  <input
                    type="checkbox"
                    checked={allMarks}
                    onChange={(e) => setAllMarks(e.target.checked)}
                  />
                  全部标记
                </label>
              )}
              <a
                href={run.sourceUrl || '#'}
                target={run.sourceUrl ? '_blank' : undefined}
                rel="noreferrer"
                aria-label="查看原论文"
              >
                原论文
                <ArrowUpRight size={13} />
              </a>
            </div>
          </div>
          <div className="chapter-nav">
            <span>CHAPTER</span>
            <select
              aria-label="跳转章节"
              defaultValue=""
              onChange={(e) => {
                setView('paper');
                document
                  .getElementById(`chapter-${e.target.value}`)
                  ?.scrollIntoView({ behavior: 'smooth', block: 'start' });
              }}
            >
              <option value="" disabled>
                选择章节
              </option>
              {run.chapters.map((c, i) => (
                <option value={c.id} key={c.id}>
                  {String(i + 1).padStart(2, '0')} · {c.title.slice(0, 80)}
                </option>
              ))}
            </select>
            <ChevronDown size={12} />
          </div>
          <div className="paper-scroll">
            {view === 'paper' ? (
              <article className="manuscript">
                <div className="manuscript-heading">
                  <span>ANNOTATED MANUSCRIPT</span>
                  <h2>{run.title}</h2>
                  <p>原文提取文本 · {run.chapters.length} 个章节单元</p>
                </div>
                {run.chapters.map((chapter, index) => (
                  <section key={chapter.id} className="chapter" id={`chapter-${chapter.id}`}>
                    <div className="chapter-title">
                      <span>{String(index + 1).padStart(2, '0')}</span>
                      <h3>{chapter.title}</h3>
                    </div>
                    {run.shards
                      .filter((s) => s.chapterId === chapter.id)
                      .map((shard) => (
                        <div
                          key={shard.id}
                          id={`shard-${shard.id}`}
                          className={`shard ${marks.has(shard.id) ? 'has-highlight' : ''}`}
                        >
                          <span className="shard-id">{shard.id}</span>
                          <p>
                            {highlightedSegments(shard.text, marks.get(shard.id) || []).map(
                              (segment, i) =>
                                segment.highlight ? (
                                  <mark key={i} data-start={segment.start}>
                                    {segment.text}
                                  </mark>
                                ) : (
                                  <span key={i}>{segment.text}</span>
                                ),
                            )}
                          </p>
                        </div>
                      ))}
                  </section>
                ))}
              </article>
            ) : (
              <div className="meta-content">
                <MetaCard jump={jump} meta={run.documentMeta} name="文章 Meta" />
                {run.chapters.map((c) => (
                  <MetaCard jump={jump} key={c.id} meta={run.chapterMeta[c.id]} name={c.title} />
                ))}
              </div>
            )}
          </div>
        </section>
        <aside className="detail-panel">
          <div className="panel-title">
            <h2>术语详情</h2>
            <span className="tiny-label">TERM</span>
          </div>
          {selected && (
            <div className="detail-scroll">
              <div className="detail-heading">
                <span className="detail-id">
                  {selected.id}{' '}
                  <span>· {selected.modelProcessed ? '模型已处理' : '等待模型整理'}</span>
                </span>
                <h2>{selected.canonicalName || selected.name}</h2>
                <span className={`status-pill ${selected.status}`}>{labels[selected.status]}</span>
              </div>
              {selected.canonicalName !== selected.name && selected.canonicalName && (
                <div className="original-name">
                  原始候选 <b>{selected.name}</b>
                </div>
              )}
              {selected.aliases.length > 0 && (
                <div className="aliases">
                  {selected.aliases.map((a, i) => (
                    <span key={i}>{a}</span>
                  ))}
                </div>
              )}
              <section className="detail-section">
                <h3>
                  定义 <span>DEFINITION</span>
                </h3>
                <p>
                  {selected.definition || '暂无定义。排除、待确认或未完成整理的候选可能没有定义。'}
                </p>
              </section>
              <section className="detail-section">
                <h3>
                  原文位置 <span>{spans.length} OCCURRENCES</span>
                </h3>
                {spans.length > 0 ? (
                  <>
                    <div className="hit-nav">
                      <button onClick={() => nextHit(-1)} aria-label="上一个位置">
                        <ArrowLeft size={15} />
                      </button>
                      <span>
                        {occurrence + 1} / {spans.length}
                      </span>
                      <button onClick={() => nextHit(1)} aria-label="下一个位置">
                        <ArrowRight size={15} />
                      </button>
                    </div>
                    <div className="evidence-links">
                      {[...new Set(spans.map((s) => s.shardId))].map((id) => (
                        <button
                          key={id}
                          onClick={() => {
                            const n = spans.findIndex((s) => s.shardId === id);
                            setOccurrence(n);
                            jump(spans[n]);
                          }}
                        >
                          {id}
                          <ArrowUpRight size={12} />
                        </button>
                      ))}
                    </div>
                  </>
                ) : (
                  <>
                    <p className="muted">未记录精确词面位置，可查看模型引用的证据段落。</p>
                    <div className="evidence-links">
                      {selected.evidenceShardIds.map((id) => (
                        <button key={id} onClick={() => jump({ shardId: id })}>
                          {id}
                          <ArrowUpRight size={12} />
                        </button>
                      ))}
                    </div>
                  </>
                )}
              </section>
              <section className="detail-section">
                <h3>
                  模型判断 <span>ASSESSMENT</span>
                </h3>
                <p>{selected.reason || '等待模型阅读与整理。'}</p>
              </section>
              {selected.notes.length > 0 && (
                <section className="detail-section">
                  <h3>
                    阅读批注 <span>{selected.notes.length} NOTES</span>
                  </h3>
                  {selected.notes.slice(0, 8).map((n, i) => (
                    <button className="note" key={i} onClick={() => jump({ shardId: n.shardId })}>
                      <span>
                        {n.shardId}
                        <ArrowUpRight size={12} />
                      </span>
                      <p>{n.text}</p>
                    </button>
                  ))}
                  {selected.notes.length > 8 && (
                    <p className="muted">完整 {selected.notes.length} 条批注包含在导出的集合中。</p>
                  )}
                </section>
              )}
              {canonical && canonical.memberIds.length > 1 && (
                <section className="detail-section">
                  <h3>归并来源</h3>
                  <div className="evidence-links">
                    {canonical.memberIds.map((id) => (
                      <button
                        key={id}
                        onClick={() => {
                          const c = run.candidates.find((x) => x.id === id);
                          if (c) choose(c);
                        }}
                      >
                        {id}
                      </button>
                    ))}
                  </div>
                </section>
              )}
              <p className="review-note">
                模型处理结果，尚待人工确认。高亮只表示原文位置，不代表术语已被正式采纳。
              </p>
            </div>
          )}
        </aside>
      </div>
      <footer className="footer">
        <span>MIREMO PAPER STUDIO</span>
        <span>Read closely. Keep the evidence.</span>
        <button
          onClick={() => {
            setQuery('');
            setFilter('all');
            const candidate = run.candidates.find((c) => c.id === 'J0055');
            if (candidate) choose(candidate);
          }}
        >
          查看 Attention 示例 <ArrowUpRight size={12} />
        </button>
      </footer>
    </main>
  );
}
