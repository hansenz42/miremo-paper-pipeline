export type Status = 'unprocessed' | 'retain' | 'exclude' | 'pending' | 'merged';
export interface Span {
  shardId: string;
  start: number;
  end: number;
  quote: string;
}
export interface Shard {
  id: string;
  chapterId: string;
  text: string;
  kind: string;
}
export interface Chapter {
  id: string;
  title: string;
  shardIds: string[];
}
export interface Note {
  shardId: string;
  text: string;
}
export interface Candidate {
  id: string;
  name: string;
  type: 'TERM';
  score: number;
  origin: 'algorithm' | 'model';
  spans: Span[];
  evidenceShardIds: string[];
  notes: Note[];
  modelProcessed: boolean;
  status: Status;
  reason: string;
  canonicalId?: string;
  canonicalName?: string;
  aliases: string[];
  definition: string;
  claims: { text: string; shardIds: string[]; quote?: string }[];
}
export interface Meta {
  overview: string;
  role: string;
  focus: string;
  sourceIds: string[];
  uncertainties: string[];
}
export interface Term {
  id: string;
  type: 'TERM';
  name: string;
  aliases: string[];
  definition: string;
  memberIds: string[];
  claims: Candidate['claims'];
  spans: Span[];
  reviewStatus: 'pending_user_review';
}
export type Stage = 'meta' | 'reading' | 'organize' | 'complete';
export interface ReadingJob {
  shardId: string;
  candidateIds: string[];
  discovery: boolean;
}
export interface Run {
  schemaVersion: 1;
  id: string;
  title: string;
  createdAt: string;
  sourceUrl?: string;
  provenance: {
    kind: 'historical_model_run' | 'live';
    model: string;
    note: string;
    algorithm: string;
  };
  stage: Stage;
  status: 'ready' | 'running' | 'failed' | 'complete';
  error?: string;
  chapters: Chapter[];
  shards: Shard[];
  candidates: Candidate[];
  terms: Term[];
  documentMeta?: Meta;
  chapterMeta: Record<string, Meta>;
  cursor: number;
  readingJobs: ReadingJob[];
  organizeIds: string[];
  attemptedCalls: number;
  usage: { input: number; output: number };
  modelConfig?: { model: string; baseUrl: string; requestOptions: Record<string, unknown> };
}
export interface Progress {
  id: string;
  stage: Stage;
  status: Run['status'];
  cursor: number;
  total: number;
  processed: number;
  candidates: number;
  terms: number;
  attemptedCalls: number;
  error?: string;
}
export function progress(run: Run): Progress {
  const total =
    run.stage === 'meta'
      ? run.chapters.length + 1
      : run.stage === 'reading'
        ? run.readingJobs.length
        : run.stage === 'organize'
          ? Math.ceil(run.organizeIds.length / 6)
          : 1;
  return {
    id: run.id,
    stage: run.stage,
    status: run.status,
    cursor: run.cursor,
    total,
    processed: run.candidates.filter((c) => c.modelProcessed).length,
    candidates: run.candidates.length,
    terms: run.terms.length,
    attemptedCalls: run.attemptedCalls,
    error: run.error,
  };
}
export function ontology(run: Run) {
  return {
    schemaVersion: 1,
    type: 'TERM',
    document: { title: run.title, sourceUrl: run.sourceUrl },
    complete: run.stage === 'complete',
    provenance: run.provenance,
    terms: run.terms,
    candidates: run.candidates,
    documentMeta: run.documentMeta,
    chapterMeta: run.chapterMeta,
    reviewStatus: 'pending_user_review',
    finalAdoption: false,
  };
}
