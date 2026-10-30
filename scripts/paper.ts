import { parseArgs } from 'node:util';
import { readFile, writeFile } from 'node:fs/promises';
import { createRun, advance } from '../lib/pipeline';
import { loadRun } from '../lib/store';
import { ontology, progress } from '../lib/types';
const { values } = parseArgs({
  options: {
    attention: { type: 'boolean' },
    input: { type: 'string' },
    title: { type: 'string' },
    resume: { type: 'string' },
    export: { type: 'string' },
    output: { type: 'string' },
    help: { type: 'boolean' },
  },
});
if (values.help) {
  console.log(
    'pnpm paper --attention | --input paper.md [--title Title] | --resume RUN_ID | --export RUN_ID [--output terms.json]',
  );
  process.exit(0);
}
if (values.export) {
  const run = await loadRun(values.export);
  await writeFile(values.output || 'terms.json', JSON.stringify(ontology(run), null, 2));
  console.log('Exported TERM ontology');
} else {
  if (!values.resume && !values.attention && !values.input)
    throw new Error('Choose --attention, --input or --resume');
  let run = values.resume
    ? await loadRun(values.resume)
    : await createRun({
        title: values.title || (values.attention ? 'Attention Is All You Need' : 'Paper'),
        attention: values.attention,
        text: values.input ? await readFile(values.input, 'utf8') : undefined,
      });
  console.log(`Run: ${run.id}`);
  while (run.stage !== 'complete') {
    run = await advance(run.id);
    console.log(progress(run));
    if (run.status === 'failed') throw new Error(run.error);
  }
  await writeFile(values.output || 'terms.json', JSON.stringify(ontology(run), null, 2));
  console.log('Complete, pending human review.');
}
