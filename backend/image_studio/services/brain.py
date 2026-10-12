"""The editing brain: Qwen3.5-9B, a vision-language model served by llama.cpp on this laptop.

It shares the GPU like the other language models (assistant.Resident): started on first use
and kept while editing, stopped before an image model loads or after a few idle minutes.
Answers can be constrained to a JSON schema, so plans always parse."""

import base64
import io
import json
import subprocess
import time
import urllib.error
import urllib.request

from image_studio.core.catalog import BRAIN, WORK
from image_studio.services import assistant

URL = f'http://127.0.0.1:{BRAIN["port"]}'
CONTEXT = 16384
LOG = WORK / 'editor-brain.log'


def available():
    folder = BRAIN['folder']
    return all((folder / name).exists() for name in (BRAIN['model'], BRAIN['mmproj'])) and BRAIN['server'].exists()


def _request(path, body=None, timeout=600):
    data = json.dumps(body).encode('utf-8') if body is not None else None
    request = urllib.request.Request(URL + path, data=data, headers={'Content-Type': 'application/json'},
                                     method='POST' if data is not None else 'GET')
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read())


def _stop_strays():
    """Stop brain servers left by processes that exited without closing them. Each holds
    ~7 GB of the 8 GB GPU, so a stray one pushes a new one into slow shared memory
    (measured: 0.3 instead of 37 tokens per second)."""
    import os

    import psutil

    server = os.path.normcase(os.path.realpath(BRAIN['server']))
    for process in psutil.process_iter(['exe', 'ppid', 'create_time']):
        try:
            if os.path.normcase(os.path.realpath(process.info['exe'] or '')) != server:
                continue
            try:
                # A reused PID belongs to a process newer than the server it would be parent of.
                orphan = psutil.Process(process.info['ppid']).create_time() > process.info['create_time']
            except psutil.NoSuchProcess:
                orphan = True
            if orphan:
                process.kill()
                process.wait(timeout=10)
        except (psutil.Error, OSError):
            continue


def _start():
    """Start llama-server with the model on the GPU and wait until it answers."""
    _stop_strays()
    folder = BRAIN['folder']
    log = open(LOG, 'ab')
    process = subprocess.Popen(
        [str(BRAIN['server']), '-m', str(folder / BRAIN['model']), '--mmproj', str(folder / BRAIN['mmproj']),
         '--host', '127.0.0.1', '--port', str(BRAIN['port']), '-ngl', '99', '-c', str(CONTEXT),
         '--parallel', '1', '-fa', 'on', '--jinja', '--no-webui'],
        cwd=str(BRAIN['server'].parent), stdout=log, stderr=log,
        creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
    )

    def close():
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=20)
            except subprocess.TimeoutExpired:
                process.kill()
        log.close()

    deadline = time.monotonic() + 180
    while time.monotonic() < deadline:
        if process.poll() is not None:
            close()
            raise RuntimeError(f'The editing brain stopped while starting; see {LOG}.')
        try:
            if _request('/health', timeout=5).get('status') == 'ok':
                return dict(close=close)
        except (urllib.error.URLError, OSError, ValueError):
            pass
        time.sleep(1)
    close()
    raise RuntimeError(f'The editing brain did not start in time; see {LOG}.')


def image_part(image, longest=1024):
    picture = image.convert('RGB')
    picture.thumbnail((longest, longest))
    buffer = io.BytesIO()
    picture.save(buffer, format='JPEG', quality=90)
    return {'type': 'image_url',
            'image_url': {'url': 'data:image/jpeg;base64,' + base64.b64encode(buffer.getvalue()).decode('ascii')}}


def chat(system, content, schema=None, max_tokens=2500, temperature=0.2, thinking=False):
    """The brain's answer to one message. `content` is text or a list of text and
    image_part() items; with a JSON `schema` the answer is that JSON, parsed."""
    body = dict(
        messages=[{'role': 'system', 'content': system}, {'role': 'user', 'content': content}],
        max_tokens=max_tokens, temperature=temperature, top_p=0.9,
        chat_template_kwargs=dict(enable_thinking=thinking),
    )
    if schema is not None:
        body['response_format'] = {'type': 'json_object', 'schema': schema}
    with assistant.Resident('brain', _start, keep=True):
        reply = _request('/v1/chat/completions', body)
    text = reply['choices'][0]['message'].get('content') or ''
    if schema is None:
        return text
    try:
        return json.loads(text[text.find('{'):text.rfind('}') + 1])
    except ValueError:
        if temperature >= 0.3:
            raise
        # A rare answer breaks off mid-string (“glitch effect”); a second, slightly freer try is whole.
        return chat(system, content, schema, max_tokens, temperature + 0.3, thinking)
