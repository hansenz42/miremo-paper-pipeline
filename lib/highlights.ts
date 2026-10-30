import type { Span } from './types';
export function highlightedSegments(text: string, spans: Span[]) {
  const valid = spans
    .filter(
      (s) =>
        Number.isInteger(s.start) &&
        Number.isInteger(s.end) &&
        s.start >= 0 &&
        s.end > s.start &&
        s.end <= text.length &&
        text.slice(s.start, s.end) === s.quote,
    )
    .sort((a, b) => a.start - b.start || a.end - b.end);
  const ranges: { start: number; end: number }[] = [];
  for (const span of valid) {
    const last = ranges.at(-1);
    if (last && span.start <= last.end) last.end = Math.max(last.end, span.end);
    else ranges.push({ start: span.start, end: span.end });
  }
  const result: { text: string; highlight: boolean; start: number }[] = [];
  let at = 0;
  for (const range of ranges) {
    if (range.start > at)
      result.push({ text: text.slice(at, range.start), highlight: false, start: at });
    result.push({ text: text.slice(range.start, range.end), highlight: true, start: range.start });
    at = range.end;
  }
  if (at < text.length) result.push({ text: text.slice(at), highlight: false, start: at });
  return result;
}
