import sys
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'pipeline'))
import workflow
import refine
import transport
from prepare import structure
from test_workflow import FakeTransport

class DiskFake(FakeTransport):
    def __init__(self, output, cfg=None):
        super().__init__()
        self.output = output
    def save(self, name, value):
        transport.write(self.output/name, value)

class FakeCalls:
    def __init__(self, output, cfg, execute):
        pass
    def connect(self):
        pass
    def run(self, cid, prompt, payload, validator, initial_repair=None):
        if cid.startswith('judge'):
            answer = {'decisions': [dict(id=c['id'],name=c['name'],decision='retain',reason='Supported by input',
                      evidence_shard_ids=list(payload['sources']),suspected_merge_ids=[],uncertainties=[],material_reviews=[])
                      for c in payload['candidates']]}
        elif cid.startswith('define'):
            answer = {'definitions': [dict(id=c['canonical_id'],status='defined',definition='Attention maps a query and keys to an output.',
                      claims=[{'text':'Attention maps a query and keys to an output.','shard_ids':list(payload['sources'])}],
                      uncertainties=[],excluded_materials=[]) for c in payload['objects']]}
        else:
            raise AssertionError(cid)
        validator(answer,payload)
        return answer

class PipelineTests(unittest.TestCase):
    def test_structure_preserves_offsets_and_boundaries(self):
        text='# Example\n\n'+'Attention uses queries and keys. '*120+'\n\n# Conclusion\n\nEnd.\n'
        result=structure(text)
        shards=result['shards']
        self.assertEqual(''.join(s['text'] for s in shards),text)
        self.assertTrue(all(len(s['text'])<=1200 for s in shards))
        for s in shards:self.assertEqual(text[s['start']:s['end']],s['text'])

    def test_pdf_page_numbers_are_not_chapters(self):
        result=structure('  Abstract\n\nText.\n\n1    Introduction\n\nBody.\n\n2\nMore text.\n')
        self.assertEqual([c['title'] for c in result['chapters']],['Abstract','1    Introduction'])

    def test_reading_to_final_delivery(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);reading=root/'reading'
            text='Attention maps a query and keys to an output.'
            tables={'shards':[dict(id='S1',chapter_id='C1',text=text,start=0,end=len(text),kind='paragraph',document_version='v')],
                    'chapters':[dict(id='C1',shard_ids=['S1'],sample_shard_ids=['S1'],document_version='v')],
                    'candidates':[dict(id='J1',name='Attention',document_version='v',mention_shard_ids=['S1'])]}
            ontology=dict(entity_type_id='term',name='术语',description='Terms',guide='Only source facts')
            state=workflow.execute(tables,ontology,DiskFake(reading),str.casefold)
            self.assertEqual(state['stages']['reading'],'complete')
            transport.write(root/'tables/shards.json',tables['shards'])
            with patch.object(refine,'Calls',FakeCalls):
                refine.run(reading,root/'tables',root/'refinement',ontology,{'model':'offline-test','request_options':{}},workers=1)
            final=json.loads((root/'refinement/04-delivery/organized-objects.json').read_text())
            self.assertEqual(final[0]['definition_result']['claims'][0]['shard_ids'],['S1'])
            self.assertEqual(final[0]['final_adoption'],'not_performed')
            self.assertEqual(final[0]['review_status'],'pending_user_review')

    def test_transport_cache_includes_model_and_refuses_truncation(self):
        class Client:
            def __init__(self):
                self.chat=SimpleNamespace(completions=self);self.calls=0;self.finish='stop'
            def create(self,**kwargs):
                self.calls+=1
                return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content='{}'),finish_reason=self.finish)],usage=None)
        with tempfile.TemporaryDirectory() as temp:
            client=Client();root=Path(temp)
            with patch.object(transport,'get_client',return_value=client):
                llm=transport.ReadingTransport(root,{'model':'a'})
                llm.ask('x','test','prompt',{},100)
                llm.ask('x','test','prompt',{},100)
                self.assertEqual(client.calls,1)
                llm.cfg={'model':'b'};llm.ask('x','test','prompt',{},100)
                self.assertEqual(client.calls,2)
                client.finish='length'
                _,receipt=llm.ask('y','test','prompt',{},100)
                self.assertEqual(receipt['status'],'failed')

    def test_complete_cli_with_real_preselection_and_mock_model(self):
        import importlib.util
        import os
        root=Path(__file__).resolve().parents[1]
        spec=importlib.util.spec_from_file_location('paper_cli',root/'run.py')
        cli=importlib.util.module_from_spec(spec);spec.loader.exec_module(cli)
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp);source=path/'paper.md';output=path/'result'
            source.write_text('# Attention\n\nAttention maps a query and keys to an output.\n')
            config=path/'config.json'
            config.write_text(json.dumps({'model':'offline-test','base_url':'https://example.invalid/v1','request_options':{}}))
            argv=['run.py','--input',str(source),'--output',str(output),'--config',str(config),'--execute']
            with patch.object(sys,'argv',argv), patch.dict(os.environ,{'PAPER_API_KEY':'offline-test-value'}), \
                 patch.object(transport,'configure'), patch.object(transport,'ReadingTransport',DiskFake), \
                 patch.object(refine,'Calls',FakeCalls):
                cli.main()
                cli.main()
            for name in ['REPORT.md','final-candidates.json','candidate-mapping.json','document-meta.json','chapter-meta.json']:
                self.assertTrue((output/name).exists(),name)
            self.assertGreater(len(json.loads((output/'tables/candidates.json').read_text())),0)
            self.assertTrue(all(c['type']=='TERM' for c in json.loads((output/'tables/candidates.json').read_text())))
            self.assertTrue(all(c['type']=='TERM' for c in json.loads((output/'final-candidates.json').read_text())))
            manifest=json.loads((output/'manifest.json').read_text())
            self.assertEqual(manifest['candidate_type'],'TERM')
            state=json.loads((output/'reading/workflow-state.json').read_text())
            self.assertEqual(state['relation_status'],'not_requested')
            self.assertEqual(state['relation_proposals'],[])
            self.assertFalse((output/'reading/relation-proposals.json').exists())


    def test_unknown_evidence_is_rejected(self):
        answer={'definitions':[dict(id='J1',status='defined',definition='Claim',claims=[{'text':'Claim','shard_ids':['invented']}],uncertainties=[],excluded_materials=[])]}
        with self.assertRaises(ValueError):
            refine.validate_define(answer,{'objects':[{'canonical_id':'J1'}],'candidates':[],'sources':{'S1':{}}})

if __name__=='__main__':unittest.main()
