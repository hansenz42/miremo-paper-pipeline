"""Structure-first source spans. Never rewrite text or count XML as invisible."""

import re
from pydantic import BaseModel, Field
from markdown_it import MarkdownIt

POLICY_ID = "structure-first-1200-v2"
TARGET = 1000
MERGE_LIMIT = 1200
LONG_PARAGRAPH = 1200
SHORT = 300


class StructureSpan(BaseModel):
    start: int
    end: int
    kind: str = "paragraph"
    continuation_group: str | None = None
    level: int = 0
    heading_path: list[str] = Field(default_factory=list)


def source_blocks(text: str, *, markdown: bool = True) -> list[StructureSpan]:
    if not text.strip():
        return []
    if not markdown:
        return [
            StructureSpan(start=m.start(), end=m.end())
            for m in re.finditer(r"\S(?:.*?\S)?(?=\n[ \t]*\n|\Z)", text, re.S)
        ]
    lines = text.splitlines(keepends=True)
    offsets = [0]
    for line in lines:
        offsets.append(offsets[-1] + len(line))
    spans: list[StructureSpan] = []
    covered = 0
    for token in MarkdownIt("commonmark").enable("table").parse(text):
        if token.map is None or token.level != 0 or token.type.endswith("_close"):
            continue
        start, end = (offsets[i] for i in token.map)
        if start < covered:
            continue
        if text[covered:start].strip():
            spans.append(StructureSpan(start=covered, end=start, kind="opaque"))
        kind = {
            "heading_open": "heading",
            "bullet_list_open": "list",
            "ordered_list_open": "list",
            "fence": "code",
            "code_block": "code",
            "table_open": "table",
            "html_block": "opaque",
            "blockquote_open": "quote",
        }.get(token.type, "paragraph")
        spans.append(
            StructureSpan(
                start=start,
                end=end,
                kind=kind,
                level=int(token.tag[1:]) if kind == "heading" else 0,
            )
        )
        covered = end
    if text[covered:].strip():
        spans.append(StructureSpan(start=covered, end=len(text), kind="opaque"))
    # Keep extension admonitions opaque until their matching closing delimiter.
    grouped: list[StructureSpan] = []
    pending: StructureSpan | None = None
    for span in spans:
        value = text[span.start : span.end].strip()
        if pending is not None:
            pending.end = span.end
            if value == "///":
                grouped.append(pending)
                pending = None
        elif value.startswith("///") and value != "///":
            pending = span.model_copy(update={"kind": "opaque", "level": 0})
        else:
            grouped.append(span)
    if pending is not None:
        grouped.append(pending)
    return grouped


def protected_regions(text):
    """Source ranges, not rewritten math. Explicit math and conservative formula blocks."""
    regions = [(m.start(), m.end()) for m in re.finditer(
        r"(?s)\$\$.*?\$\$|\\\[.*?\\\]", text)]
    blocks = list(re.finditer(r"\S.*?(?=\n\s*\n|\Z)", text, re.S))
    for i, block in enumerate(blocks):
        value = block.group()
        first = value.splitlines()[0]
        if len(first) < 180 and '=' in first and not re.search(r'[.!?]\s', first) and (
            re.search(r'\w+\s*\([^)]*\)\s*=', first) or
            re.match(r'(?i)^(?:where|其中)\b', first)):
            end = block.end()
            for following in blocks[i+1:]:
                if re.match(r'(?i)^(?:where\b|其中|式中)', following.group()):
                    end = following.end()
                else:
                    break
            regions.append((block.start(), end))
    merged = []
    for a,b in sorted(regions):
        if merged and a <= merged[-1][1]: merged[-1] = (merged[-1][0], max(b,merged[-1][1]))
        else: merged.append((a,b))
    return merged


def isolate_images(text, blocks):
    # XML image exports may include OCR lines in the same paragraph. Keep that
    # paragraph and an immediately following caption together, never following prose.
    ranges=[]
    for m in re.finditer(r'<image\b[^>]*>|!\[[^\]]*\]\([^\n]*?\)',text):
        a=m.start(); b=m.end()
        if m.group().startswith('<image'):
            stop=re.search(r'\n\s*\n',text[b:])
            b=b+stop.start() if stop else len(text)
        cap=re.match(r'\s*?(?:Figure|Fig\.|Table|图|表)\s*\d[^\n]*(?:\n(?!\s*\n)[^\n]+)*',text[b:],re.I)
        if cap: b+=cap.end()
        ranges.append((a,b))
    result=[]
    for block in blocks:
        cuts=sorted({block.start,block.end}|{p for a,b in ranges for p in (a,b) if block.start<p<block.end})
        for a,b in zip(cuts,cuts[1:]):
            kind='image' if any(x<=a and b<=y for x,y in ranges) else block.kind
            if not text[a:b].strip(): continue
            if kind=='image' and result and result[-1].kind=='image' and any(x<=result[-1].start and b<=y for x,y in ranges):
                result[-1].end=b
            else:
                result.append(block.model_copy(update={'start':a,'end':b,'kind':kind}))
    return result

def split_structure(text: str, *, markdown: bool = True) -> list[StructureSpan]:
    if not text.strip():
        return []
    blocks = isolate_images(text, source_blocks(text, markdown=markdown))
    headings: list[tuple[int, str]] = []
    units: list[StructureSpan] = []
    for block in blocks:
        value = text[block.start : block.end].strip()
        # Explicit Chinese section headings only; don't promote entire numbered clauses.
        if (
            block.kind == "paragraph"
            and len(value) < 90
            and "\n" not in value
            and re.match(
                r"^(?:[一二三四五六七八九十]+、|第[一二三四五六七八九十\d]+[章节])",
                value,
            )
        ):
            block.kind, block.level = "heading", 1
        if block.kind == "heading":
            title = re.sub(r"^#{1,6}(?:\s+|$)|\s+#+\s*$", "", value).splitlines()
            if title and title[0].strip():
                while headings and headings[-1][0] >= block.level:
                    headings.pop()
                headings.append((block.level, title[0]))
            else:
                # Empty Markdown headings contain no new section identity.
                # Preserve their source bytes without erasing parent context.
                block.kind, block.level = "paragraph", 0
        block.heading_path = [title for _, title in headings]
        if block.kind != "heading" and headings:
            block.level = headings[-1][0]
        if block.end - block.start <= LONG_PARAGRAPH:
            units.append(block)
            continue
        boundaries = [
            block.start + m.end()
            for m in re.finditer(
                r'[。！？][”’」』）)]*|[.!?]["\x27)]*(?=\s|$)',
                text[block.start : block.end],
            )
        ]
        tags = [(m.start(), m.end()) for m in re.finditer(r"<[^>]+>", text)]
        boundaries = [p for p in boundaries if not any(a < p < b for a, b in tags)]
        cursor = block.start
        while block.end - cursor > LONG_PARAGRAPH:
            candidates = [
                p for p in boundaries if cursor < p <= cursor + LONG_PARAGRAPH
            ]
            later = [p for p in boundaries if p > cursor]
            preferred = [p for p in candidates if p - cursor >= SHORT]
            end = min(preferred, key=lambda p: abs(p - cursor - TARGET)) if preferred else (candidates[-1] if candidates else min(cursor + TARGET, block.end))
            units.append(block.model_copy(update={"start": cursor, "end": end}))
            cursor = end
        if cursor < block.end:
            units.append(block.model_copy(update={"start": cursor}))
    groups: list[StructureSpan] = []
    for unit in units:
        merge = False
        if groups:
            prior = groups[-1]
            before = text[prior.start : prior.end].strip()
            after = text[unit.start : unit.end].strip()
            size = unit.end - prior.start
            if prior.kind == "heading" and (
                unit.kind != "heading" or unit.level > prior.level
            ):
                merge = size <= MERGE_LIMIT
            elif unit.kind != "heading" and prior.heading_path == unit.heading_path:
                linked = bool(
                    re.match(
                        r"^(上述|前述|该平台|该项目|这些|因此|为此|据此|换言之|This means|Therefore\b)",
                        after,
                    )
                    or re.search(r"[：:]$", before)
                )
                merge = (linked and size <= LONG_PARAGRAPH) or (
                    prior.kind == unit.kind == "paragraph"
                    and len(before) < TARGET
                    and size <= MERGE_LIMIT
                    and (min(len(before), len(after)) < SHORT or abs(size - TARGET) < abs(len(before) - TARGET))
                )
            if prior.kind == "image" or unit.kind == "image":
                merge = False
            if merge:
                prior.end = unit.end
                prior.kind = (
                    unit.kind
                    if prior.kind == "heading"
                    else (prior.kind if prior.kind == unit.kind else "mixed")
                )
                prior.heading_path = unit.heading_path
                prior.level = max(prior.level, unit.level)
        if not merge:
            groups.append(unit.model_copy(deep=True))
    for index, span in enumerate(groups):
        span.start = groups[index - 1].end if index else 0
    if groups:
        groups[-1].end = len(text)
    bounded = []
    for span in groups:
        cursor = span.start
        while span.end - cursor > MERGE_LIMIT:
            end = cursor + TARGET
            bounded.append(span.model_copy(update={"start": cursor, "end": end}))
            cursor = end
        bounded.append(span.model_copy(update={"start": cursor}))
    groups = []
    for unit in bounded:
        if groups and unit.kind not in ("heading", "image") and groups[-1].kind != "image" and groups[-1].heading_path == unit.heading_path and unit.end - groups[-1].start <= MERGE_LIMIT and min(groups[-1].end-groups[-1].start, unit.end-unit.start) < SHORT:
            prior = groups[-1]
            prior.end = unit.end
            if prior.kind != unit.kind:
                prior.kind = "mixed"
        else:
            groups.append(unit)
    # Shift a boundary out of a formula + its where/notation explanation.
    for n,(a,b) in enumerate(protected_regions(text)):
        for i in range(len(groups)-1):
            left,right=groups[i:i+2]
            if a < left.end < b:
                if b-left.start <= MERGE_LIMIT and b < right.end:
                    left.end=right.start=b
                elif a>left.start and right.end-a<=MERGE_LIMIT:
                    left.end=right.start=a
                else:
                    left.continuation_group=right.continuation_group=f'math-{n+1}'
    assert all(s.end - s.start <= MERGE_LIMIT for s in groups)
    assert "".join(text[s.start : s.end] for s in groups) == text
    return groups
