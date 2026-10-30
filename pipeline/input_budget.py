"""Conservative local input estimate and lossless subdivision of independent objects."""
import copy
import json
import math
from functools import lru_cache

LIMIT = 30000
POLICY = 'cl100k_base-times-1.15-plus-512-columnar-v2'


class InputBudgetExceeded(ValueError):
    pass


@lru_cache(maxsize=1)
def encoder():
    import tiktoken
    return tiktoken.get_encoding('cl100k_base')


def serialize(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'))


def estimate(sent, historical=False):
    # Exactly the two strings sent by Calls, including duplicated contract and repair.
    enc = encoder()
    value = {k: v for k, v in sent.items() if k != 'prompt'}
    user = json.dumps(value, ensure_ascii=False) if historical else serialize(value)
    raw = len(enc.encode(sent['prompt'], disallowed_special=())) + len(enc.encode(user, disallowed_special=())) + 16
    return math.ceil(raw * 1.15) + 512


def request_body(prompt, payload, repair=None):
    data = copy.deepcopy(payload)
    for key in ('candidate_index', 'index'):
        rows = data.get(key)
        if isinstance(rows, list) and rows and all(isinstance(x, dict) for x in rows):
            columns = list(rows[0])
            if all(set(x) == set(columns) for x in rows):
                data[key] = {'columns': columns, 'rows': [[x[k] for k in columns] for x in rows]}
    # Columnar indexes retain every field and candidate, with fewer repeated keys.
    result = {'prompt': prompt, 'input': data, 'task_contract_after_materials': prompt}
    if repair:
        result['protocol_repair'] = repair
    return result


def atoms(payload):
    # A comparison component is a joint identity decision, not independent candidates.
    if 'comparison_edges' in payload or 'allowed_member_ids' in payload:
        return None, []
    if 'objects' in payload:
        return 'objects', payload['objects']
    if 'candidates' in payload:
        return 'candidates', payload['candidates']
    return None, []


def ids_for(key, items):
    return {x['canonical_id' if key == 'objects' else 'id'] for x in items}


def project_answer(answer, ids):
    if not isinstance(answer, dict):
        return answer
    result = copy.deepcopy(answer)
    for key in ('rows', 'definitions', 'decisions'):
        if isinstance(result.get(key), list):
            result[key] = [x for x in result[key] if isinstance(x, dict) and x.get('id') in ids]
    return result


def subset(payload, key, items):
    result = copy.deepcopy(payload)
    result[key] = copy.deepcopy(items)
    ids = ids_for(key, items)
    member_ids = {i for o in items for i in o.get('member_ids', [])} if key == 'objects' else ids
    if key == 'objects' and 'candidates' in result:
        result['candidates'] = [x for x in result['candidates'] if x['id'] in member_ids]
    for field in ('first_round',):
        if field in result:
            result[field] = [x for x in result[field] if x['id'] in member_ids]
    if 'drafts' in result:
        result['drafts'] = [x for x in result['drafts'] if x['id'] in ids]
    if 'previous_definition' in result:
        result['previous_definition'] = project_answer(result['previous_definition'], ids)
    if 'required_review_ids_per_candidate' in result:
        result['required_review_ids_per_candidate'] = {i:v for i,v in result['required_review_ids_per_candidate'].items() if i in member_ids}
    candidates = result.get('candidates', [])
    if candidates and all('source_ids' in x for x in candidates):
        sids = {s for c in candidates for s in c['source_ids']}
        # Retain prior definition references even if not present in old associations.
        for o in items if key == 'objects' else []:
            sids.update(o.get('evidence_shard_ids', []))
        for row in result.get('drafts', []) + result.get('previous_definition', {}).get('definitions', []):
            for claim in row.get('claims', []):
                sids.update(claim.get('shard_ids', []))
        missing = sids - result.get('sources', {}).keys()
        if missing:
            raise InputBudgetExceeded('Referenced source absent: ' + ','.join(sorted(missing)))
        result['sources'] = {s:v for s,v in result['sources'].items() if s in sids}
        if 'meta_reference_only' in result:
            chapters = {s['chapter_id'] for s in result['sources'].values() if 'chapter_id' in s}
            result['meta_reference_only'] = {k:v for k,v in result['meta_reference_only'].items() if k == 'document' or k in chapters}
    # Global candidate indexes and metadata are preserved, never top-k truncated.
    return result


def subset_repair(repair, ids):
    if not repair:
        return None
    result = copy.deepcopy(repair)
    result['previous_answer'] = project_answer(result.get('previous_answer'), ids)
    return result


def plan(prompt, payload, repair=None, limit=LIMIT):
    before = estimate(request_body(prompt, payload, repair))
    if before <= limit:
        return [(payload, repair, before)]
    key, items = atoms(payload)
    if not key or len(items) < 2:
        raise InputBudgetExceeded(f'Indivisible input estimated {before} > {limit}; no evidence truncated')
    parts, pending = [], []
    def part(group):
        data = subset(payload, key, group)
        context = subset_repair(repair, ids_for(key, group))
        return data, context, estimate(request_body(prompt, data, context))
    for item in items:
        trial = part(pending + [item])
        if trial[2] <= limit:
            pending.append(item)
            continue
        if pending:
            parts.append(part(pending))
        pending = [item]
        if part(pending)[2] > limit:
            raise InputBudgetExceeded(f'Single object {list(ids_for(key, pending))} exceeds {limit}; no evidence truncated')
    if pending:
        parts.append(part(pending))
    return parts


def validate_piece(answer, payload):
    key, items = atoms(payload)
    expected = ids_for(key, items)
    fields = [k for k in ('rows', 'definitions', 'decisions') if isinstance(answer.get(k), list)]
    if len(fields) != 1:
        raise ValueError('Budget child requires one result collection')
    ids = [r['id'] for r in answer[fields[0]]]
    if len(ids) != len(set(ids)) or set(ids) != expected:
        raise ValueError('Budget child ID coverage mismatch')


def combine(answers):
    result = {}
    for answer in answers:
        for key, value in answer.items():
            if key in ('rows', 'definitions', 'decisions'):
                result.setdefault(key, []).extend(value)
            else:
                # Never drop auxiliary model output, including review notes.
                result.setdefault('budget_child_metadata', []).append({key: value})
    return result
