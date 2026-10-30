import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'pipeline'))
import copy
import json
from pathlib import Path
import unittest

from workflow import apply_reading, execute, validate_meta, current_reading_source, KNOWN_PROMPT, DISCOVERY_PROMPT
from reading_text import ReadingText


def blank():
    return dict(processed=True, updates=[], new_candidates=[], negative_evidence=[], name_suggestions=[], association_doubts=[], pending=[])


class FakeTransport:
    def __init__(self):
        self.calls = []
        self.call_ids = []
        self.saved = {}
        self.prompts = {}

    def ask(self, cid, stage, prompt, data, limit):
        self.calls.append((stage, data))
        self.call_ids.append(cid)
        self.prompts[cid] = prompt
        if stage == 'meta':
            refs = [data['sources'][0]['id']]
            field = {'text': 'Source-supported overview', 'shard_ids': refs}
            return {'shared': {'overview': field, 'content_role': field, 'uncertainties': []},
                    'ontology_specific': {'focus': field, 'uncertainties': []}}, {'status': 'complete'}
        fields = ('new_candidates',) if cid.endswith('-discover') else ('updates', 'name_suggestions', 'association_doubts')
        return dict(processed=True, pending=[], relations=[], **{key: [] for key in fields}), {'status': 'complete'}

    def save(self, name, data):
        self.saved[name] = copy.deepcopy(data)


class WorkflowTests(unittest.TestCase):
    def test_reading_text_restores_attested_wraps_and_compounds(self):
        normalize = ReadingText(['Convolutional models. Convolu-\ntional im-\nage'], ['image'])
        self.assertEqual(normalize('Convolu-\ntional im-\nage short-term multi-head attention'),
                         'Convolutional image short term multi head attention')
        self.assertEqual(normalize('unknown-\nfragment'), 'unknown-\nfragment')
        self.assertEqual(normalize(normalize('multi-head attention')), 'multi head attention')

    def test_reading_text_preserves_math_ranges_and_structural_content(self):
        normalize = ReadingText([])
        text = ('x-y -2 1e-3 10-20 10–20 −1\nalpha-beta = gamma\n'
                '$alpha-beta$ `multi-head` https://example.com/multi-head\n'
                '<image file_id="multi-head"/>\n```\nalpha-beta\n```')
        self.assertEqual(normalize(text), text)
        self.assertEqual(normalize('short-term\nmulti‑head'), 'short term\nmulti head')

    def setUp(self):
        self.rows = [{'id': 'J0001', 'name': 'scaled dot', 'topic_id': 'TERM', 'definition': ''}]
        self.visible = {'S1': {'text': 'scaled dot-product attention computes attention.'},
                        'S2': {'text': 'The adjacent description.'}}
        self.ref = [{'shard_id': 'S1'}]

    def apply(self, answer, rows=None, *, discovery=False):
        return apply_reading(rows or self.rows, answer, self.visible, 'S1', 'TERM', str.casefold, {'J0001'}, discovery=discovery)

    def test_suggestion_is_append_only_and_idempotent(self):
        answer = blank()
        answer['name_suggestions'] = [{'id': 'J0001', 'name': 'scaled dot',
                                      'suggested_name': 'scaled dot-product attention',
                                      'reason': 'Incomplete term boundary', 'sources': self.ref}]
        rows, issues = self.apply(answer)
        self.assertFalse(issues)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['name'], 'scaled dot')
        self.assertEqual(rows[0]['definition'], '')
        self.assertNotIn('confirmed_aliases', rows[0])
        self.assertEqual(self.apply(answer, rows)[0], rows)
        answer['name_suggestions'][0]['suggested_name'] = 'another proposed name'
        self.assertEqual(len(self.apply(answer, rows)[0][0]['associations']), 2)

    def test_negative_evidence_is_disabled_without_changing_history(self):
        answer = blank()
        answer['negative_evidence'] = [{'id': 'J0001', 'name': 'scaled dot', 'reason': 'fragment',
                                       'scope': 'occurrence', 'sources': self.ref}]
        original = copy.deepcopy(self.rows)
        original[0]['associations'] = [dict(kind='negative_evidence', reason='historical')]
        rejected, issues = self.apply(answer, original)
        self.assertTrue(issues)
        self.assertEqual(rejected, original)

    def test_all_operations_accept_no_model_sources(self):
        for field in ('updates', 'new_candidates', 'name_suggestions', 'association_doubts'):
            answer = blank()
            answer[field] = [dict(id='J0001', name='scaled dot', understanding='context',
                                  reason='需结合全文整理名称边界', suggested_name='scaled dot product')]
            rows, issues = self.apply(answer, discovery=field == 'new_candidates')
            self.assertFalse(issues)
            if field == 'association_doubts':
                self.assertEqual(rows[0][field][0]['reading_context'], {'shard_id': 'S1'})
            else:
                record = rows[0]['associations'][0]
                self.assertEqual(record['sources'], self.ref)
                self.assertEqual(record['source_binding'], 'current_reading_context')

    def test_legacy_sources_cannot_change_call_provenance(self):
        for sources in ([], None, 'S2', [{}], [{'shard_id': 'S9'}], self.ref + [{'shard_id': 'S2'}]):
            answer = blank()
            answer['updates'] = [dict(id='J0001', name='scaled dot', understanding='context',
                                      sources=sources, shard_id='S2', quote='fabricated', start=-1, end=999)]
            original = copy.deepcopy(answer)
            rows, issues = self.apply(answer)
            self.assertFalse(issues)
            self.assertEqual(answer, original)
            self.assertEqual(rows[0]['associations'][0]['sources'], self.ref)
            self.assertNotIn('quote', rows[0]['associations'][0])

    def test_missing_current_context_never_falls_back_to_neighbor(self):
        answer = blank()
        answer['updates'] = [dict(id='J0001', name='scaled dot', understanding='context')]
        rows, issues = apply_reading(self.rows, answer, {'S2': {}}, 'S1', 'TERM', str.casefold, {'J0001'})
        self.assertTrue(issues)
        self.assertEqual(rows, self.rows)

    def test_positions_are_server_owned_and_text_is_never_matched(self):
        visible = {'S1': {'text': 'English-\nto-German repeated repeated', 'start': 100, 'end': 142}}
        source = current_reading_source(visible, 'S1')
        self.assertEqual(source, {'shard_id': 'S1', 'document_start': 100, 'document_end': 142})
        for prompt in (KNOWN_PROMPT, DISCOVERY_PROMPT):
            self.assertNotIn('"sources":', prompt)
            self.assertNotIn('"quote":', prompt)

    def test_invalid_call_context_is_rejected(self):
        for shard in ({'id': 'S2'}, {'source_role': 'context_only'}, {'start': 0},
                      {'start': -1, 'end': 20}, {'start': 2, 'end': 1}):
            with self.assertRaises(ValueError):
                current_reading_source({'S1': shard}, 'S1')

    def test_hidden_existing_candidate_is_not_duplicated(self):
        answer = blank()
        answer['new_candidates'] = [{'name': 'scaled dot', 'understanding': 'context', 'sources': self.ref}]
        rows, issues = apply_reading(self.rows, answer, self.visible, 'S1', 'TERM', str.casefold, set(), discovery=True)
        self.assertFalse(issues)
        self.assertEqual(len(rows), 1)


    def test_association_doubt_is_separate_append_only_and_idempotent(self):
        answer = blank()
        answer['association_doubts'] = [dict(id='J0001', name='scaled dot',
            reason='候选含义与当前段落讨论对象无法对应，请核查预选边界。')]
        original = copy.deepcopy(self.rows)
        rows, issues = self.apply(answer)
        self.assertFalse(issues)
        self.assertEqual(self.rows, original)
        self.assertNotIn('associations', rows[0])
        self.assertEqual(rows[0]['association_doubts'][0]['status'], 'pending')
        self.assertEqual(rows[0]['association_doubts'][0]['preselection_link'],
                         dict(candidate_id='J0001', shard_id='S1'))
        self.assertEqual(self.apply(answer, rows)[0], rows)

    def test_doubt_conflict_rejects_both_but_keeps_other_candidate(self):
        answer = blank()
        answer['association_doubts'] = [dict(id='J0001', name='scaled dot', reason='无法解释关联对象')]
        answer['updates'] = [dict(id='J0001', name='scaled dot', understanding='语境', sources=['S1']),
                             dict(id='J0002', name='attention', understanding='注意力机制', sources=['S1'])]
        original = self.rows + [dict(id='J0002', name='attention')]
        rows, issues = apply_reading(original, answer, self.visible, 'S1', 'TERM', str.casefold, {'J0001', 'J0002'})
        self.assertEqual(len(issues), 2)
        self.assertEqual(rows[0], original[0])
        self.assertEqual(len(rows[1]['associations']), 1)

    def test_doubt_requires_current_batch_identity_and_explanation(self):
        for item in [dict(id='J9999', name='scaled dot', reason='疑点'),
                     dict(id='J0001', name='wrong', reason='疑点'),
                     dict(id='J0001', name='scaled dot', reason=''),
                     dict(id='J0001', name='scaled dot', reason='不是独立术语')]:
            answer = blank()
            answer['association_doubts'] = [item]
            rows, issues = self.apply(answer)
            self.assertEqual(rows, self.rows)
            self.assertTrue(issues)

    def test_missing_doubt_array_is_not_accepted_as_complete(self):
        answer = blank()
        del answer['association_doubts']
        self.assertTrue(self.apply(answer)[1])


    def test_ignored_candidates_require_no_output_or_rejection_record(self):
        answer = dict(processed=True, updates=[], name_suggestions=[], association_doubts=[], pending=[])
        rows, issues = self.apply(answer)
        self.assertFalse(issues)
        self.assertEqual(rows, self.rows)

    def test_doubt_cannot_repackage_absence_or_type_exclusion(self):
        for reason in ('该候选未出现于当前正文。', '不属于当前ontology', '仅为长词组组成部分'):
            answer = blank()
            answer['association_doubts'] = [dict(id='J0001', name='scaled dot', reason=reason)]
            rows, issues = self.apply(answer)
            self.assertEqual(rows, self.rows)
            self.assertTrue(issues)

    def test_absence_in_active_operations_is_blocked_without_source_text(self):
        for field, explanation in [('updates', 'understanding'), ('name_suggestions', 'reason')]:
            answer = blank()
            answer[field] = [dict(id='J0001', name='scaled dot', sources=['S1'],
                                  suggested_name='scaled dot product', **{explanation: '当前正文未出现该候选。'})]
            rows, issues = apply_reading(self.rows, answer, {'S1': {}}, 'S1', 'TERM', str.casefold, {'J0001'})
            self.assertEqual(rows, self.rows)
            self.assertIn('preselection association contradicted', issues[0]['reason'])

    def test_fragment_understanding_is_not_an_absence_claim(self):
        answer = blank()
        answer['updates'] = [dict(id='J0001', name='scaled dot', sources=['S1'],
                                 understanding='作为完整注意力术语的片段，本处没有独立定义。')]
        rows, issues = self.apply(answer)
        self.assertFalse(issues)
        self.assertEqual(len(rows[0]['associations']), 1)

    def test_discovery_schema_does_not_require_known_arrays(self):
        answer = dict(processed=True, new_candidates=[dict(name='attention', understanding='注意力机制', sources=['S1'])], pending=[])
        rows, issues = self.apply(answer, discovery=True)
        self.assertFalse(issues)
        self.assertEqual(len(rows), 2)

    def test_discovery_rejects_known_operations_before_mutation(self):
        for field in ('updates', 'name_suggestions', 'association_doubts', 'negative_evidence'):
            answer = blank()
            answer[field] = [dict(id='J0001', name='scaled dot', reason='疑点')]
            rows, issues = self.apply(answer, discovery=True)
            self.assertEqual(rows, self.rows)
            self.assertEqual(issues[0]['reason'], 'response crossed batch responsibility')

    def test_known_batch_rejects_discovery_before_mutation(self):
        answer = blank()
        answer['new_candidates'] = [dict(name='attention', understanding='机制', sources=['S1'])]
        rows, issues = self.apply(answer)
        self.assertEqual(rows, self.rows)
        self.assertEqual(issues[0]['reason'], 'response crossed batch responsibility')

    def test_bad_id_or_incomplete_response_is_not_applied(self):
        answer = blank()
        answer['updates'] = [{'id': 'J001', 'name': 'scaled dot', 'understanding': 'context', 'sources': self.ref}]
        self.assertEqual(self.apply(answer)[0], self.rows)
        self.assertTrue(self.apply(answer)[1])
        answer['processed'] = False
        self.assertEqual(self.apply(answer)[0], self.rows)

    def test_integration_preserves_sampling_and_stops_before_refinement(self):
        shards, chapters = [], []
        for i in range(11):
            ids = []
            for j in range(4):
                sid = f'C{i}S{j}'
                ids.append(sid)
                shards.append(dict(id=sid, chapter_id=f'C{i}', text='source', document_version='v',
                                   kind='paragraph', reading_prev_shard_id=f'C{i}S{j-1}' if j else None,
                                   reading_next_shard_id=f'C{i}S{j+1}' if j < 3 else None))
            chapters.append(dict(id=f'C{i}', shard_ids=ids, sample_shard_ids=[ids[0], ids[-1]], document_version='v'))
        llm = FakeTransport()
        state = execute({'shards': shards, 'chapters': chapters, 'candidates': []},
                        {'entity_type_id': 'TERM', 'name': '术语'}, llm, str.casefold, lambda t, n: [])
        self.assertEqual(len(llm.calls[0][1]['sources']), 16)
        self.assertEqual(len(llm.calls[3][1]['previous_chapter_overviews']), 2)
        reading = [data for stage, data in llm.calls if stage == 'term_reading']
        self.assertEqual(len(reading), 44)
        self.assertNotIn('reading_sources', reading[0])
        self.assertEqual(reading[0]['current_source']['id'], 'C0S0')
        self.assertEqual([x['id'] for x in reading[0]['reference_context']['neighbor_shards']], ['C0S1'])
        self.assertEqual(reading[0]['reference_context']['neighbor_shards'][0]['source_role'], 'context_only')
        self.assertEqual(set(reading[0]['document_meta']), {'shared', 'ontology_specific'})
        self.assertEqual(state['stages'], dict(meta='complete', reading='complete', refinement='pending', delivery='pending', admission='deferred'))
        self.assertFalse(any(stage == 'definition_draft' for stage, _ in llm.calls))

    def test_meta_reference_and_unknown_are_distinct(self):
        field = {'text': '', 'shard_ids': []}
        answer = {'shared': {'overview': field, 'content_role': field, 'uncertainties': ['Unknown']},
                  'ontology_specific': {'focus': field, 'uncertainties': ['Unclear scope']}}
        self.assertIn('TERM', validate_meta(answer, {'S1'}, 'TERM')['by_ontology'])
        answer['ontology_specific']['focus'] = {'text': 'unsupported', 'shard_ids': ['S9']}
        with self.assertRaises(ValueError):
            validate_meta(answer, {'S1'}, 'TERM')


    def test_normalized_recall_and_discovery_keep_original_names_and_positions(self):
        class Discover(FakeTransport):
            def ask(self, cid, stage, prompt, data, limit):
                answer, receipt = super().ask(cid, stage, prompt, data, limit)
                if cid.endswith('-discover'):
                    answer['new_candidates'] = [dict(name='multi head attention', sense='',
                        understanding='Current passage explains attention.')]
                return answer, receipt
        text = 'multi-head attention uses image recognition; im-\nage recognition.'
        tables = {'shards': [dict(id='S1', chapter_id='C1', text=text, start=100, end=100+len(text),
                                 document_version='v')],
                  'chapters': [dict(id='C1', shard_ids=['S1'], sample_shard_ids=['S1'], document_version='v')],
                  'candidates': [dict(id='A', name='multi-head attention', document_version='v', mention_shard_ids=['S1']),
                                 dict(id='B', name='image recognition', document_version='v', mention_shard_ids=['S1'])]}
        original = copy.deepcopy(tables)
        llm = Discover()
        state = execute(tables, {'entity_type_id': 'TERM'}, llm, str.casefold,
                        lambda text, name: name in text)
        self.assertEqual(tables, original)
        self.assertEqual(len(state['rows']), 2)
        self.assertEqual(state['rows'][0]['name'], 'multi-head attention')
        self.assertEqual(state['rows'][0]['associations'][0]['sources'],
                         [dict(shard_id='S1', document_start=100, document_end=100+len(text))])
        for stage, data in llm.calls:
            source = data['current_source'] if stage == 'term_reading' else data['sources'][0]
            self.assertNotIn('im-\nage', source['text'])
            if stage == 'term_reading':
                self.assertEqual({r['id'] for r in data['related_candidates']}, {'A', 'B'})

    def test_candidate_selection_uses_only_preselection_without_second_matching(self):
        shards = [dict(id='S1', chapter_id='C1', text='alpha', document_version='v',
                       reading_next_shard_id='S2'),
                  dict(id='S2', chapter_id='C1', text='beta', document_version='v',
                       reading_prev_shard_id='S1')]
        rows = [dict(id='A', name='alpha'), dict(id='B', name='beta'),
                dict(id='C', name='marked here', mention_shard_ids=['S1']),
                dict(id='D', name='marked there', mention_shard_ids=['S2']),
                dict(id='E', name='linked here', associations=[{'sources': [{'shard_id': 'S1'}]}]),
                dict(id='F', name='linked there', associations=[{'sources': [{'shard_id': 'S2'}]}])]
        for row in rows:
            row['document_version'] = 'v'
        llm = FakeTransport()
        def forbidden_match(*args):
            raise AssertionError('Fine reading must not match shard text again')
        execute({'shards': shards, 'chapters': [dict(id='C1', shard_ids=['S1', 'S2'],
                 sample_shard_ids=['S1', 'S2'], document_version='v')], 'candidates': rows},
                {'entity_type_id': 'TERM'}, llm, str.casefold, forbidden_match)
        for stage, data in llm.calls:
            if stage != 'term_reading':
                continue
            current = data['current_shard_id']
            self.assertEqual({r['id'] for r in data['related_candidates']},
                             {'C'} if current == 'S1' else {'D'})
            self.assertEqual(data['current_source']['id'], current)
            self.assertEqual(len(data['reference_context']['neighbor_shards']), 1)
            self.assertNotEqual(data['reference_context']['neighbor_shards'][0]['id'], current)

    def test_workflow_records_fallback_coverage_without_negative_evidence(self):
        class DoubtTransport(FakeTransport):
            def ask(self, cid, stage, prompt, data, limit):
                answer, receipt = super().ask(cid, stage, prompt, data, limit)
                if '-known-' in cid:
                    candidate = data['related_candidates'][0]
                    self_link = candidate['preselection_link']
                    assert self_link == {'candidate_id': 'A', 'shard_id': 'S1'}
                    answer['association_doubts'] = [dict(id='A', name='fragment', reason='无法解释候选与当前讨论对象的关系')]
                return answer, receipt
        tables = {'shards': [dict(id='S1', chapter_id='C1', text='unrelated text', document_version='v')],
                  'chapters': [dict(id='C1', shard_ids=['S1'], sample_shard_ids=['S1'], document_version='v')],
                  'candidates': [dict(id='A', name='fragment', document_version='v', mention_shard_ids=['S1'])]}
        state = execute(tables, {'entity_type_id': 'TERM'}, DoubtTransport(), str.casefold)
        self.assertEqual(state['coverage']['pending_association_doubts'], 1)
        self.assertEqual(state['rows'][0]['mention_shard_ids'], ['S1'])
        self.assertNotIn('associations', state['rows'][0])
        self.assertFalse(state['issues'])

    def test_executor_dispatches_separate_prompts_and_accepts_empty_results(self):
        tables = {'shards': [dict(id='S1', chapter_id='C1', text='Petrov', document_version='v')],
                  'chapters': [dict(id='C1', shard_ids=['S1'], sample_shard_ids=['S1'], document_version='v')],
                  'candidates': [dict(id='A', name='Petrov', document_version='v', mention_shard_ids=['S1'])]}
        llm = FakeTransport()
        state = execute(tables, {'entity_type_id': 'TERM'}, llm, str.casefold)
        self.assertEqual(llm.prompts['S1-known-000'], KNOWN_PROMPT)
        self.assertEqual(llm.prompts['S1-discover'], DISCOVERY_PROMPT)
        self.assertNotIn('new_candidates', KNOWN_PROMPT)
        self.assertNotIn('association_doubts', DISCOVERY_PROMPT)
        self.assertEqual(state['stages']['reading'], 'complete')
        self.assertEqual(state['rows'][0]['mention_shard_ids'], ['S1'])
        self.assertNotIn('associations', state['rows'][0])

    def test_failed_meta_stops_reading_and_marks_partial(self):
        class Failed(FakeTransport):
            def ask(self, *args):
                return {}, {'status': 'failed'}
        tables = {'shards': [dict(id='S1', chapter_id='C1', text='x', document_version='v')],
                  'chapters': [dict(id='C1', shard_ids=['S1'], sample_shard_ids=['S1'], document_version='v')],
                  'candidates': []}
        state = execute(tables, {'entity_type_id': 'TERM'}, Failed(), str.casefold, lambda t, n: [])
        self.assertEqual(state['stages']['meta'], 'partial')
        self.assertEqual(state['stages']['reading'], 'pending')
        self.assertEqual(state['units'], [])


if __name__ == '__main__':
    unittest.main()
