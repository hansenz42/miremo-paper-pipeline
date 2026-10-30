"""Conservative, auditable reading links; source order and offsets never change."""
import re

POLICY = 'shard-continuation-v2'

def annotate_reading_order(shards):
    for i,s in enumerate(shards):
        prev=shards[i-1] if i else None;following=shards[i+1] if i+1<len(shards) else None
        s['source_prev_shard_id']=prev['id'] if prev else None
        s['source_next_shard_id']=following['id'] if following else None
        s['reading_prev_shard_id']=prev['id'] if prev and prev['chapter_id']==s['chapter_id'] else None
        s['reading_next_shard_id']=following['id'] if following and following['chapter_id']==s['chapter_id'] else None
        s['reading_order']={'policy':POLICY,'status':'source_order','notes':[]}
    for i,left in enumerate(shards):
        if left.get('kind') in ('image','opaque','heading'):continue
        j=i+1;skipped=[]
        while j<len(shards) and shards[j]['chapter_id']==left['chapter_id'] and shards[j].get('kind') in ('image','opaque','heading'):
            skipped.append(shards[j]);j+=1
        if not skipped or j>=len(shards):continue
        right=shards[j]
        if right['chapter_id']!=left['chapter_id']:continue
        tail=left['text'].strip()
        head=right['text'].strip()
        supported=(len(skipped)<=6 and any(s.get('kind')=='image' or re.search(r'<image\b|!\[',s['text']) for s in skipped)
                   and not re.search(r'[.!?。！？:：;；][\"\u201d\u2019)]?$',tail)
                   and not re.search(r'^\s*#{1,6}\s',right['text'],re.M)
                   and bool(re.match(r'^(?:of|and|or|which|where|that|with|to|for|by|from|in|on|as)\b',head)))
        if not supported:
            left['reading_order']['notes'].append({'status':'unresolved','next_body_shard_id':right['id'],'reason':'Interrupted body lacks sufficient continuation signals'})
            continue
        note={'status':'heuristic','from':left['id'],'to':right['id'],'skipped_shard_ids':[s['id'] for s in skipped],
              'reason':'Unfinished body followed across image blocks by a continuation phrase; requires review'}
        left['reading_next_shard_id']=right['id'];right['reading_prev_shard_id']=left['id']
        for s in [left,right]:s['reading_order']['status']='heuristic';s['reading_order']['notes'].append(dict(note))
        for s in skipped:
            s['reading_prev_shard_id']=None;s['reading_next_shard_id']=None
            s['reading_order']['status']='separate_visual';s['reading_order']['notes'].append(dict(note))
    return shards
