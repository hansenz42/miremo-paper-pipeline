import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'pipeline'))
import copy
import unittest
from unittest.mock import patch

from relations import collect, remap
from workflow import apply_reading, execute, reading_calls
from test_workflow import FakeTransport


class RelationTests(unittest.TestCase):
    def setUp(self):
        self.source = {'id': 'S', 'text': 'A contains B.', 'chapter_id': 'C'}
        self.rows = [{'id': 'A', 'name': 'alpha'}, {'id': 'B', 'name': 'beta'}]
        self.proposal = dict(source_candidate_id='A', target_candidate_id='B', relation_type='contains',
                             description='A contains B', qualifier='', evidence_quote='A contains B.')

    def collect(self, proposal=None, **overrides):
        answer = {'processed': True, 'relations': [proposal or self.proposal], **overrides}
        return collect(answer, self.rows, {'A', 'B'}, self.source, 'call', 'TERM', 'v', str.casefold)

    def test_exact_evidence_and_replay_stable_id(self):
        a, issues = self.collect()
        self.assertFalse(issues)
        self.assertEqual(a, self.collect()[0])
        self.assertEqual(a[0]['status'], 'proposed')
        self.assertEqual(a[0]['evidence'][0]['shard_id'], 'S')

    def test_quote_whitespace_normalization_preserves_actual_source(self):
        self.source['text'] = 'A contains\nB.'
        rows, issues = self.collect()
        self.assertFalse(issues)
        self.assertEqual(rows[0]['evidence'][0]['quote'], 'A contains\nB.')
        self.assertEqual(rows[0]['original_proposal']['evidence_quote'], 'A contains B.')

    def test_neighbor_only_quote_unknown_endpoint_and_self_edge_rejected(self):
        for changed in [{'evidence_quote': 'neighbor only'}, {'target_candidate_id': 'X'}, {'target_candidate_id': 'A'}]:
            rows, issues = self.collect({**self.proposal, **changed})
            self.assertFalse(rows)
            self.assertEqual(len(issues), 1)
            self.assertIn('proposal', issues[0])

    def test_missing_relation_array_not_empty_success(self):
        rows, issues = collect({'processed': True}, self.rows, {'A'}, self.source, 'c', 'TERM', 'v', str.casefold)
        self.assertTrue(issues)

    def test_known_candidate_batch_cannot_silently_emit_relations(self):
        answer = dict(processed=True, updates=[], name_suggestions=[], association_doubts=[], pending=[], relations=[self.proposal])
        rows, issues = apply_reading(self.rows, answer, {'S': self.source}, 'S', 'TERM', str.casefold, {'A', 'B'})
        self.assertEqual(rows, self.rows)
        self.assertEqual(issues[0]['reason'], 'response crossed batch responsibility')

    def test_new_entity_local_endpoint_resolved_only_after_successful_storage(self):
        new = {'local_id': 'NEW1', 'name': 'beta', 'sense': '', 'understanding': 'component'}
        answer = {'processed': True, 'new_candidates': [new], 'pending': [],
                  'relations': [{**self.proposal, 'target_candidate_id': 'NEW1'}]}
        rows, issues = apply_reading(self.rows[:1], answer, {'S': self.source}, 'S', 'TERM', str.casefold, set(), discovery=True)
        self.assertFalse(issues)
        relations, issues = collect(answer, rows, {'A'}, self.source, 'c', 'TERM', 'v', str.casefold)
        self.assertFalse(issues)
        self.assertEqual(relations[0]['target_candidate_id'], rows[1]['id'])
        self.assertFalse(collect(answer, self.rows[:1], {'A'}, self.source, 'c', 'TERM', 'v', str.casefold)[0])
        answer['new_candidates'].append(copy.deepcopy(new))
        self.assertFalse(collect(answer, rows, {'A'}, self.source, 'c', 'TERM', 'v', str.casefold)[0])

    def test_mapping_preserves_conditions_directions_and_held_edges(self):
        p = self.collect()[0][0]
        second = {**p, 'relation_id': 'R2', 'qualifier': 'training only'}
        reverse = {**p, 'relation_id': 'R3', 'source_candidate_id': 'B', 'target_candidate_id': 'A'}
        mapping = [{'original_member_ids': ['A'], 'result_id': 'X', 'route': 'repaired'},
                   {'original_member_ids': ['B'], 'result_id': 'Y', 'route': 'direct'}]
        groups, held = remap([p, second, reverse], mapping)
        self.assertEqual(len(groups), 3)
        self.assertFalse(held)
        self.assertEqual(groups[0]['original_endpoints'][0]['source'], 'A')
        self.assertTrue(groups[0]['identity_changed'])
        mapping[1]['result_id'] = None
        self.assertEqual(remap([p], mapping)[1][0]['reason'], 'endpoint_unavailable')
        mapping[1]['result_id'] = 'X'
        self.assertEqual(remap([p], mapping)[1][0]['reason'], 'self_loop_after_merge')

    def test_exact_duplicates_keep_all_proposals(self):
        p = self.collect()[0][0]
        mapping = [{'original_member_ids': [i], 'result_id': i} for i in ('A', 'B')]
        groups, held = remap([p, {**p, 'relation_id': 'R2'}], mapping)
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0]['proposal_ids'], [p['relation_id'], 'R2'])
        with self.assertRaises(ValueError):
            remap([p], mapping + [mapping[0]])

    def test_relation_index_crosses_entity_batches_and_runs_once_per_shard(self):
        class Reader(FakeTransport):
            def ask(self, cid, stage, prompt, data, limit):
                answer, receipt = super().ask(cid, stage, prompt, data, limit)
                if cid.endswith('-discover'):
                    assert len(data['relation_candidates']) == 25
                    answer['relations'] = [dict(source_candidate_id='E0', target_candidate_id='E24',
                        relation_type='contains', description='first contains last', qualifier='', evidence_quote='first contains last')]
                return answer, receipt
        tables = {'shards': [dict(id='S', chapter_id='C', document_version='v', text='first contains last')],
                  'chapters': [dict(id='C', document_version='v', shard_ids=['S'], sample_shard_ids=['S'])],
                  'candidates': [dict(id=f'E{i}', name=f'term{i}', document_version='v', mention_shard_ids=['S']) for i in range(25)]}
        llm = Reader()
        state = execute(tables, {'entity_type_id': 'TERM'}, llm, str.casefold)
        self.assertEqual(state['relation_status'], 'complete')
        self.assertEqual(len(state['relation_proposals']), 1)
        self.assertEqual(len([s for s, _ in llm.calls if s == 'term_reading']), 3)
        self.assertIn('relation-proposals.json', llm.saved)

    def test_oversized_reading_blocked_before_model_call(self):
        llm = FakeTransport()
        # Production encoder, pathological single object: must not truncate.
        result = reading_calls(llm, ('S-discover', {'related_candidates': [], 'text': 'x ' * 40000}, 'p', set(), True))
        self.assertFalse(llm.calls)
        self.assertEqual(result[0][2]['status'], 'budget_blocked')

    def test_partial_relation_protocol_preserves_entity_results(self):
        class LegacyReader(FakeTransport):
            def ask(self, cid, stage, prompt, data, limit):
                answer, receipt = super().ask(cid, stage, prompt, data, limit)
                if cid.endswith('-discover'):
                    answer.pop('relations')
                    answer['new_candidates'] = [dict(name='beta', understanding='new entity', sense='')]
                return answer, receipt
        tables = {'shards': [dict(id='S', chapter_id='C', text='alpha beta', document_version='v')],
                  'chapters': [dict(id='C', document_version='v', shard_ids=['S'], sample_shard_ids=['S'])],
                  'candidates': [dict(id='A', name='alpha', document_version='v', mention_shard_ids=['S'])]}
        state = execute(tables, {'entity_type_id': 'TERM'}, LegacyReader(), str.casefold)
        self.assertEqual(len(state['rows']), 2)
        self.assertEqual(state['relation_status'], 'partial')
        self.assertEqual(state['stages']['reading'], 'partial')


if __name__ == '__main__':
    unittest.main()
