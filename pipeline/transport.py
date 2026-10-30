"""OpenAI-compatible transport; saves artifacts, never saves credentials."""
import hashlib
import json
import os
import threading
from pathlib import Path
from types import SimpleNamespace
import input_budget

_client = None

def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

class BudgetClient:
    def __init__(self, cfg, root, max_calls):
        from openai import OpenAI
        self.client = OpenAI(api_key=os.environ['PAPER_API_KEY'], base_url=cfg['base_url'], timeout=180, max_retries=0)
        self.path = root / 'request-budget.json'
        self.count = json.loads(self.path.read_text())['attempted_calls'] if self.path.exists() else 0
        self.maximum = max_calls
        self.lock = threading.Lock()
        self.chat = SimpleNamespace(completions=self)

    def create(self, **kwargs):
        with self.lock:
            if self.count >= self.maximum:
                raise RuntimeError('Request limit reached; raise --max-calls to resume')
            self.count += 1
            write(self.path, {'attempted_calls': self.count, 'max_calls': self.maximum})
        return self.client.chat.completions.create(**kwargs)

def configure(cfg, root, max_calls):
    global _client
    _client = BudgetClient(cfg, root, max_calls)

def get_client():
    if _client is None:
        raise RuntimeError('Transport not configured')
    return _client

class ReadingTransport:
    def __init__(self, output, cfg):
        self.output, self.cfg = output, cfg

    def save(self, name, value):
        write(self.output / name, value)

    def ask(self, cid, stage, prompt, data, limit=4500):
        payload = {'prompt': prompt, 'input': data}
        fingerprint = hashlib.sha256(json.dumps([payload, self.cfg], sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        folder = self.output / 'calls' / cid
        receipt_path, answer_path = folder / 'receipt.json', folder / 'answer.json'
        if receipt_path.exists() and answer_path.exists():
            receipt = json.loads(receipt_path.read_text())
            if receipt.get('request_hash') == fingerprint and receipt.get('status') == 'complete':
                return json.loads(answer_path.read_text()), receipt
        attempt = len(list(folder.glob('attempt-*-request.json'))) + 1
        prefix = f'attempt-{attempt:03}'
        write(folder / (prefix + '-request.json'), payload)
        receipt = {'request_hash': fingerprint, 'kind': stage, 'model': self.cfg['model'], 'status': 'failed'}
        answer = {}
        try:
            estimate = input_budget.estimate(payload)
            if estimate > input_budget.LIMIT:
                raise ValueError('Input exceeds 30000-token estimate; adjust chapters/input before running')
            response = get_client().chat.completions.create(
                model=self.cfg['model'], messages=[{'role': 'system', 'content': prompt},
                {'role': 'user', 'content': json.dumps(data, ensure_ascii=False)}],
                temperature=0, max_tokens=limit, response_format={'type': 'json_object'}, **self.cfg.get('request_options', {}))
            raw = response.choices[0].message.content
            write(folder / (prefix + '-raw.json'), {'content': raw})
            receipt.update(usage=response.usage.model_dump() if response.usage else {}, finish_reason=response.choices[0].finish_reason)
            if response.choices[0].finish_reason != 'stop':
                raise ValueError('Incomplete model response')
            answer = json.loads(raw)
            if not isinstance(answer, dict):
                raise ValueError('Expected JSON object')
            write(answer_path, answer)
            receipt['status'] = 'complete'
        except Exception as exc:
            receipt['error_type'] = type(exc).__name__
        write(folder / (prefix + '-receipt.json'), receipt)
        write(receipt_path, receipt)
        return answer, receipt
