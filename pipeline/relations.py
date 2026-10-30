"""Relation proposals are independent of entity mutations and graph admission."""
import copy
import hashlib
import json
import re


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


RELATION_PROMPT = '''
同时提取当前正文明确支持的关系，不穷举实体对，不凭共现、Meta或外部知识补边。
relation_candidates是本片及相邻阅读上下文的完整已知端点索引，不限于已有候选理解的子批。
本次new_candidates可额外提供唯一local_id（例如NEW1）；关系可引用该local_id，程序在新词成功保存后解析。
返回顶层relations数组，即使无关系也返回[]。每项为：
{"source_candidate_id":"索引ID或本次local_id","target_candidate_id":"索引ID或本次local_id","relation_type":"包含/使用/属于/变体等简短类型","description":"正文支持的有向关系","qualifier":"适用条件，无则空字符串","evidence_quote":"从current_source.text连续摘录的直接支持片段"}。
候选实体处理仍遵守原协议；只有relations.evidence_quote允许返回引文，不返回模型自定分片ID或偏移。
关系证据只能来自current_source，邻片只供消歧。没有合适端点不得强行接到相似实体；在pending记录缺失端点。
区分机制与层、上位概念与实现，保留否定、条件、配置与时态，不把局部陈述泛化。
输出的是待复核提议，不是已确认事实。不得输出同一端点的自关系。
'''


def collect(answer, rows, endpoint_ids, current_source, call_id, topic, version, matching_key):
    """Resolve local discovery IDs; quarantine bad relations without losing entities."""
    accepted, issues = [], []
    if not isinstance(answer, dict) or answer.get('processed') is not True or not isinstance(answer.get('relations'), list):
        return [], [{'reason': 'missing completed relations array', 'operation': 'relations'}]
    known = {r['id']: r for r in rows}
    endpoint_map = {i: i for i in endpoint_ids if i in known}
    local_items = answer.get('new_candidates', [])
    local_counts = {}
    for item in local_items if isinstance(local_items, list) else []:
        if isinstance(item, dict) and isinstance(item.get('local_id'), str):
            local_counts[item['local_id']] = local_counts.get(item['local_id'], 0) + 1
    for item in local_items if isinstance(local_items, list) else []:
        if not isinstance(item, dict):
            continue
        local = item.get('local_id')
        if not isinstance(local, str) or not local or local in known or local_counts[local] != 1:
            continue
        matches = [r for r in rows if isinstance(item.get('name'), str)
                   and matching_key(r['name']) == matching_key(item['name'])
                   and r.get('sense', '') == item.get('sense', '')
                   and any(a.get('understanding') == item.get('understanding')
                           and any(s['shard_id'] == current_source['id'] for s in a.get('sources', []))
                           for a in r.get('associations', []))]
        if len(matches) == 1:
            endpoint_map[local] = matches[0]['id']
    for item in answer['relations']:
        try:
            if not isinstance(item, dict):
                raise ValueError('relation must be an object')
            for field in ('source_candidate_id', 'target_candidate_id', 'relation_type', 'description', 'evidence_quote'):
                if not isinstance(item.get(field), str) or not item[field].strip():
                    raise ValueError('missing relation field: ' + field)
            if not isinstance(item.get('qualifier'), str):
                raise ValueError('relation qualifier must be a string')
            source, target = (endpoint_map.get(item[k]) for k in ('source_candidate_id', 'target_candidate_id'))
            if source is None or target is None:
                raise ValueError('unresolved relation endpoint')
            if source == target:
                raise ValueError('self relation requires review')
            # Whitespace-only formatting differences do not change evidence.
            # Store the actual contiguous input substring, retain the original quote.
            pattern = r'\s+'.join(re.escape(part) for part in item['evidence_quote'].split())
            match = re.search(pattern, current_source['text'])
            if not match:
                raise ValueError('relation quote absent from current reading text')
            row = {k: item[k] for k in ('relation_type', 'description', 'qualifier')}
            row.update(source_candidate_id=source, target_candidate_id=target,
                       original_source_candidate_id=source, original_target_candidate_id=target,
                       evidence=[{'shard_id': current_source['id'], 'quote': match.group(),
                                  'text_basis': 'reading_projection'}],
                       status='proposed', topic_id=topic, document_version=version,
                       call_id=call_id, original_proposal=copy.deepcopy(item))
            row['relation_id'] = 'R-' + digest([version, topic, call_id, item])[:24]
            if not any(x['relation_id'] == row['relation_id'] for x in accepted):
                accepted.append(row)
        except ValueError as exc:
            issues.append({'reason': str(exc), 'operation': 'relations', 'proposal': copy.deepcopy(item)})
    return accepted, issues


def remap(proposals, mapping):
    """No semantic merging: only identical statements after endpoint resolution."""
    lookup = {}
    for row in mapping:
        for original in row['original_member_ids']:
            if original in lookup:
                raise ValueError('duplicate original ID in entity mapping')
            lookup[original] = row
    groups, held = {}, []
    if len({r['relation_id'] for r in proposals}) != len(proposals):
        raise ValueError('duplicate relation proposal ID')
    for row in proposals:
        result = copy.deepcopy(row)
        a, b = row['source_candidate_id'], row['target_candidate_id']
        left, right = lookup.get(a), lookup.get(b)
        source, target = (left or {}).get('result_id'), (right or {}).get('result_id')
        result.update(original_source_candidate_id=a, original_target_candidate_id=b,
                      source_candidate_id=source, target_candidate_id=target)
        if not source or not target or source == target:
            result.update(status='pending', reason='endpoint_unavailable' if not source or not target else 'self_loop_after_merge')
            held.append(result)
            continue
        result['identity_changed'] = (source != a or target != b or
                                      left.get('route') == 'repaired' or right.get('route') == 'repaired')
        key = (source, target, row['relation_type'], row['qualifier'], row['description'])
        if key not in groups:
            groups[key] = {**result, 'relation_id': 'G-' + digest([row.get('document_version'), row.get('topic_id'), key])[:24],
                           'proposal_ids': [], 'original_endpoints': [], 'evidence': [], 'status': 'proposed'}
        group = groups[key]
        group['identity_changed'] |= result['identity_changed']
        group['proposal_ids'].append(row['relation_id'])
        group['original_endpoints'].append({'proposal_id': row['relation_id'], 'source': a, 'target': b})
        for ev in row['evidence']:
            if ev not in group['evidence']:
                group['evidence'].append(copy.deepcopy(ev))
    return list(groups.values()), held
