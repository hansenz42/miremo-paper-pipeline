#!/usr/bin/env python3
"""Prepare or run the complete Attention paper example from the command line."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import urllib.request

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / 'pipeline'))

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, help='UTF-8 Markdown/text or local PDF')
    parser.add_argument('--attention', action='store_true', help='Download Attention Is All You Need (arXiv v7)')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--config', type=Path, default=ROOT / 'config/model.json')
    parser.add_argument('--execute', action='store_true', help='Call model API for all semantic stages')
    parser.add_argument('--max-calls', type=int, default=500, help='Total request attempt limit, including resumed runs')
    args = parser.parse_args()
    if bool(args.input) == args.attention:
        parser.error('Choose exactly one of --input or --attention')
    if args.max_calls < 1:
        parser.error('--max-calls must be positive')
    from transport import write
    output = args.output.resolve()
    if output == ROOT or ROOT.is_relative_to(output):
        parser.error('Use a dedicated output subdirectory')
    cfg = json.loads(args.config.read_text(encoding='utf-8'))
    from term_scope import TERM_SCOPE
    ontology = dict(TERM_SCOPE)
    if args.execute and (not os.environ.get('PAPER_API_KEY') or cfg['model'] == 'YOUR_MODEL'):
        parser.error('Set PAPER_API_KEY and configure model before --execute')
    output.mkdir(parents=True, exist_ok=True)
    if args.attention:
        source = output / 'attention-v7.pdf'
        if not source.exists():
            with urllib.request.urlopen('https://arxiv.org/pdf/1706.03762v7', timeout=60) as response:
                body = response.read(30_000_001)
            if len(body) > 30_000_000 or not body.startswith(b'%PDF'):
                raise ValueError('Expected a PDF smaller than 30 MB')
            source.write_bytes(body)
    else:
        source = args.input.resolve()
    if source.suffix.lower() == '.pdf':
        from pypdf import PdfReader
        text = '\n\n'.join(page.extract_text(extraction_mode='layout') or '' for page in PdfReader(source).pages)
    else:
        text = source.read_text(encoding='utf-8')
    if not text.strip():
        raise ValueError('No text extracted; supply readable Markdown/text')
    import importlib.metadata
    manifest = {'input_sha256': hashlib.sha256(text.encode()).hexdigest(), 'candidate_type': 'TERM', 'term_rules': ontology,
                'code_sha256': hashlib.sha256(b''.join(p.read_bytes() for p in sorted((ROOT/'pipeline').glob('*.py'))) + Path(__file__).read_bytes()).hexdigest(),
                'dependencies': {name: importlib.metadata.version(name) for name in ('jate','spacy','en_core_web_sm','pypdf','openai','tiktoken')},
                'final_adoption': False}
    marker = output / 'manifest.json'
    if marker.exists() and json.loads(marker.read_text()) != manifest:
        raise ValueError('Input, TERM rules or code changed. Use a new output directory.')
    if not marker.exists() and any(p.name != 'attention-v7.pdf' for p in output.iterdir()):
        raise ValueError('Output is nonempty and has no matching manifest; use a new directory')
    write(marker, manifest)
    input_file = output / 'input.txt'
    input_file.write_text(text, encoding='utf-8')
    from prepare import prepare
    if (output / 'prepared.json').exists():
        tables = {key: json.loads((output/'tables'/(key+'.json')).read_text()) for key in ('shards','chapters','candidates')}
    else:
        tables = prepare(input_file, output)
        write(output/'prepared.json', {'status':'complete'})
    tables = {k: tables[k] for k in ('shards', 'chapters', 'candidates')}
    counts = {k: len(tables[k]) for k in ('shards', 'chapters', 'candidates')}
    print(json.dumps({'stage': 'preselection', **counts}, ensure_ascii=False), flush=True)
    if not args.execute:
        print('Prepared. Add --execute with the same arguments to run Meta, reading and refinement.')
        return
    import transport
    import workflow
    import refine
    from term_matching import matching_key
    model_marker = output / 'model-config.json'
    if model_marker.exists() and json.loads(model_marker.read_text()) != cfg:
        raise ValueError('Model configuration changed; use a new output directory')
    write(model_marker, cfg)
    transport.configure(cfg, output, args.max_calls)
    reading_dir = output / 'reading'
    state = workflow.execute(tables, ontology, transport.ReadingTransport(reading_dir, cfg), matching_key, extract_relations=False)
    if state['stages']['meta'] != 'complete' or state['stages']['reading'] != 'complete':
        raise RuntimeError('Reading incomplete. Inspect reading/workflow-state.json; rerun to retry failed calls.')
    write(output/'document-meta.json', state['metas']['document'])
    write(output/'chapter-meta.json', {k:v for k,v in state['metas'].items() if k != 'document'})
    refine.run(reading_dir, output/'tables', output/'refinement', ontology, cfg, workers=2)
    delivery = output / 'refinement/04-delivery'
    for original, name in [('organized-objects.json','final-candidates.json'), ('original-mapping.json','candidate-mapping.json'), ('summary.json','summary.json')]:
        shutil.copyfile(delivery/original, output/name)
    summary = json.loads((output/'summary.json').read_text())
    rows = json.loads((output/'final-candidates.json').read_text())
    lines = ['# 论文处理结果', '', '模型整理结果，待人工检查；未写入知识图谱。', '',
             f"初始候选：{counts['candidates']}；保留：{summary['retained']}；排除：{summary['excluded']}；待确认：{summary['pending']}。", '',
             '- [预选候选表](tables/candidates.json)', '- [文章 Meta](document-meta.json)', '- [章节 Meta](chapter-meta.json)',
             '- [最终候选表](final-candidates.json)', '- [候选归并映射](candidate-mapping.json)', '- [逐阶段审阅](refinement/REVIEW.md)', '', '## 保留的术语', '']
    for row in rows:
        if row['decision'] == 'retain':
            definition = row.get('definition_result') or {}
            lines.extend(['### ' + row['name'], '', str(definition.get('definition','')), ''])
    (output/'REPORT.md').write_text('\n'.join(lines), encoding='utf-8')
    print('Complete, pending user review: ' + str(output/'REPORT.md'))

if __name__ == '__main__':
    main()
