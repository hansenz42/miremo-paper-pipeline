"""Independent input adapter; TERM algorithms are reused from Miremo experiments."""
import hashlib
import json
import re
from pathlib import Path
from splitter import split_structure
from document_tables import prepare_tables
from term_matching import matching_key
from transport import write

# Plain-text PDF extraction cannot recover formula/table semantics reliably.
HEADING = re.compile(r'(?m)^[ \t]*(?:#{1,2}[ \t]+[^\n]+|(?:[1-9]\d?[ \t]+[A-Z][^\n]{0,100})|Abstract|References)[ \t]*$')

def structure(text):
    starts = sorted(set([0] + [m.start() for m in HEADING.finditer(text)] + [len(text)]))
    chapters, shards = [], []
    for a, b in zip(starts, starts[1:]):
        if a == b:
            continue
        cid = f'CH{len(chapters)+1:03}'
        title = text[a:b].splitlines()[0].lstrip('# ').strip() or 'Preamble'
        chapter = {'id': cid, 'title': title, 'start': a, 'end': b, 'shard_ids': []}
        for span in split_structure(text[a:b]):
            sid = f'SH{len(shards)+1:03}'
            shards.append({'id': sid, 'chapter_id': cid, 'start': a+span.start, 'end': a+span.end,
                           'text': text[a+span.start:a+span.end], 'kind': span.kind,
                           'continuation_group': span.continuation_group, 'heading_path': span.heading_path})
            chapter['shard_ids'].append(sid)
        if chapter['shard_ids']:
            chapters.append(chapter)
    if not shards:
        raise ValueError('No readable text')
    return {'source_sha256': hashlib.sha256(text.encode()).hexdigest(), 'chapters': chapters, 'shards': shards}

def prepare(input_path, output):
    import jate
    text = input_path.read_text(encoding='utf-8')
    if not text.strip():
        raise ValueError('Empty input')
    prepared = structure(text)
    result = jate.extract(text, algorithm='cvalue', model='en_core_web_sm', min_frequency=1, min_words=1, max_words=5)
    ranked = [{'name': x.string, 'score': x.score, 'frequency': x.frequency, 'rank': i+1,
               'surface_forms': sorted(x.surface_forms)} for i, x in enumerate(result)]
    pool = {}
    for row in ranked:
        name = re.sub(r'^\s*(?:#\s*)+', '', row['name'])
        name = re.sub(r'\s*-\s*', '-', name).strip()
        if not any(c.isalpha() for c in name):
            continue
        key = matching_key(name, 'en')
        pool.setdefault(key, {'name': name, 'members': []})['members'].append(row)
    prepared['keywords'] = [dict(id=f'J{i:04}', keyword=x['name'], rank=i, positions=[],
        sources={'JATE C-Value': {'score': max(m['score'] for m in x['members']),
        'source_ranks': [m['rank'] for m in x['members']]}}) for i, x in enumerate(pool.values(), 1)]
    tables = prepare_tables(text, prepared, [], language='en')
    for candidate, group in zip(tables['candidates'], pool.values()):
        candidate['type'] = 'TERM'
        candidate['jate_original_forms'] = [x['name'] for x in group['members']]
    for key in ('chapters', 'shards', 'candidates'):
        write(output / 'tables' / (key + '.json'), tables[key])
    write(output / 'rankings.json', ranked)
    return tables
