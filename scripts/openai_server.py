"""Serve a Hugging Face vision-language model over OpenAI's /v1/chat/completions, so the pipeline
engine can be measured with a model that is neither the bundled one nor a hosted API.

    python scripts/openai_server.py <model folder or hub id> [--port 8000] [--name qwen3-vl-2b-instruct]
    python scripts/planner_bench.py --set all --planner vllm:qwen3-vl-2b-instruct --structured none

Text and image parts (data URLs) are passed to the model's chat template; the answer is decoded
greedily at temperature 0, sampled otherwise. `response_format` is ignored: nothing here enforces
a schema, which is why the bench connects it with ``--structured none`` (the engine then spells
the schema out and checks every answer itself, as it does for any model without a JSON mode).
"""

import argparse
import base64
import io
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def load(source):
    import torch
    from transformers import AutoModelForImageTextToText, AutoProcessor

    processor = AutoProcessor.from_pretrained(source)
    model = AutoModelForImageTextToText.from_pretrained(source, dtype=torch.bfloat16, device_map='cuda')
    return processor, model


def picture(url):
    from PIL import Image

    if not url.startswith('data:'):
        raise ValueError('Only data: image URLs are supported.')
    return Image.open(io.BytesIO(base64.b64decode(url.partition(';base64,')[2]))).convert('RGB')


def messages_for(messages):
    """OpenAI messages as the chat-template messages transformers expects."""
    out = []
    for message in messages:
        content = message.get('content')
        if isinstance(content, str):
            parts = [{'type': 'text', 'text': content}]
        else:
            parts = []
            for part in content or []:
                if part.get('type') == 'text':
                    parts.append({'type': 'text', 'text': part['text']})
                elif part.get('type') == 'image_url':
                    parts.append({'type': 'image', 'image': picture(part['image_url']['url'])})
        out.append({'role': message['role'], 'content': parts})
    return out


def serve(source, port, name):
    import torch

    processor, model = load(source)
    lock = threading.Lock()  # one answer at a time on the GPU

    def complete(body):
        inputs = processor.apply_chat_template(messages_for(body['messages']), tokenize=True,
                                               add_generation_prompt=True, return_dict=True,
                                               return_tensors='pt').to(model.device)
        temperature = float(body.get('temperature') or 0)
        sampling = dict(do_sample=True, temperature=temperature, top_p=0.95) if temperature > 0 else \
            dict(do_sample=False, temperature=None, top_p=None, top_k=None)
        with lock, torch.inference_mode():
            output = model.generate(**inputs, max_new_tokens=int(body.get('max_tokens') or 1024), **sampling)
        return processor.batch_decode(output[:, inputs['input_ids'].shape[1]:], skip_special_tokens=True)[0]

    class Handler(BaseHTTPRequestHandler):
        def reply(self, code, payload):
            data = json.dumps(payload).encode('utf-8')
            self.send_response(code)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            if self.path.rstrip('/') == '/v1/models':
                return self.reply(200, {'object': 'list', 'data': [{'id': name, 'object': 'model'}]})
            self.reply(404, {'error': {'message': 'not found'}})

        def do_POST(self):
            if self.path.rstrip('/') != '/v1/chat/completions':
                return self.reply(404, {'error': {'message': 'not found'}})
            try:
                body = json.loads(self.rfile.read(int(self.headers.get('Content-Length') or 0)))
                started = time.time()
                text = complete(body)
            except Exception as exc:  # noqa: BLE001 - the client gets the reason
                return self.reply(500, {'error': {'message': f'{type(exc).__name__}: {exc}'}})
            self.reply(200, {'id': f'chatcmpl-{int(started * 1000)}', 'object': 'chat.completion',
                             'created': int(started), 'model': name,
                             'choices': [{'index': 0, 'finish_reason': 'stop',
                                          'message': {'role': 'assistant', 'content': text}}]})

        def log_message(self, format, *args):
            print(time.strftime('%H:%M:%S'), format % args, flush=True)

    print(f'Serving {name} from {source} on http://127.0.0.1:{port}/v1', flush=True)
    ThreadingHTTPServer(('127.0.0.1', port), Handler).serve_forever()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('source', help='a model folder or Hugging Face id (an image-text-to-text model)')
    parser.add_argument('--port', type=int, default=8000)
    parser.add_argument('--name', default='', help='the model id clients send (default: the folder name)')
    args = parser.parse_args()
    from pathlib import Path

    serve(args.source, args.port, args.name or Path(args.source).name)


if __name__ == '__main__':
    main()
