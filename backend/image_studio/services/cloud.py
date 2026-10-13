"""Creating and editing pictures with a cloud provider (Settings → Providers).

Each provider gets one small function per job that turns the studio's request (a prompt, a
size, maybe a photo) into that provider's HTTP call and returns PIL images. Results are saved
to the library like local renders, with their settings beside them, so Library, Edit and
"Use these settings" treat them the same way. Keys come from core/credentials.py.
"""

import base64
import io
import json
import time
import urllib.error
import urllib.request
import uuid

from PIL import Image
from PIL.PngImagePlugin import PngInfo

from image_studio.core import providers
from image_studio.core.paths import IMAGES

TIMEOUT = 300
POLL_SECONDS = 2
ASPECTS = ['1:1', '2:3', '3:2', '3:4', '4:3', '4:5', '5:4', '9:16', '16:9', '21:9']
OPENAI_SIZES = [(1024, 1024), (1536, 1024), (1024, 1536)]


class CloudError(RuntimeError):
    pass


def _label(provider):
    return providers.PROVIDERS[provider]['label']


def _request(provider, method, url, headers=None, body=None, raw=None, content_type='application/json'):
    data = raw if raw is not None else (json.dumps(body).encode('utf-8') if body is not None else None)
    request = urllib.request.Request(url, data=data, method=method, headers={
        'User-Agent': 'ImageStudio/2.0', **({'Content-Type': content_type} if data is not None else {}),
        **(headers or {})})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            return response.read()
    except urllib.error.HTTPError as exc:
        payload = exc.read().decode('utf-8', 'replace')
        try:
            detail = json.loads(payload)
            error = detail.get('error') if isinstance(detail, dict) else None
            detail = (error.get('message') if isinstance(error, dict) else error) or detail.get('detail') or payload
        except (ValueError, AttributeError):
            detail = payload
        if exc.code in (401, 403):
            raise CloudError(f'{_label(provider)} refused the API key. Check it in Settings → Providers.') from exc
        raise CloudError(f'{_label(provider)} answered {exc.code}: {str(detail)[:300]}') from exc
    except (urllib.error.URLError, OSError) as exc:
        raise CloudError(f'Could not reach {_label(provider)}: {getattr(exc, "reason", exc)}') from exc


def _json(provider, *args, **kwargs):
    try:
        return json.loads(_request(provider, *args, **kwargs) or b'{}')
    except ValueError as exc:
        raise CloudError(f'{_label(provider)} sent an answer the studio could not read.') from exc


def _picture(data):
    try:
        image = Image.open(io.BytesIO(data))
        image.load()
    except OSError as exc:
        raise CloudError('The provider sent something that is not a picture.') from exc
    return image.convert('RGBA' if image.mode in ('RGBA', 'LA', 'P') else 'RGB')


def _download(provider, url):
    if url.startswith('data:'):
        return _picture(base64.b64decode(url.split(',', 1)[1]))
    return _picture(_request(provider, 'GET', url))


def _png(image):
    buffer = io.BytesIO()
    image.save(buffer, 'PNG')
    return buffer.getvalue()


def _data_url(image):
    return 'data:image/png;base64,' + base64.b64encode(_png(image)).decode('ascii')


def aspect(width, height):
    """The closest standard aspect ratio name, e.g. 1344 × 768 -> '16:9'."""
    ratio = width / height
    return min(ASPECTS, key=lambda name: abs(int(name.split(':')[0]) / int(name.split(':')[1]) - ratio))


def openai_size(width, height):
    ratio = width / height
    return min(OPENAI_SIZES, key=lambda size: abs(size[0] / size[1] - ratio))


# Providers ---------------------------------------------------------------------------------

def _openai_images(answer):
    images = []
    for item in answer.get('data') or []:
        if item.get('b64_json'):
            images.append(_picture(base64.b64decode(item['b64_json'])))
        elif item.get('url'):
            images.append(_download('openai', item['url']))
    if not images:
        raise CloudError('OpenAI returned no picture.')
    return images


def openai_generate(model, prompt, width, height, key, base):
    size = '{}x{}'.format(*openai_size(width, height))
    answer = _json('openai', 'POST', f'{base}/images/generations', {'Authorization': f'Bearer {key}'},
                   dict(model=model, prompt=prompt, size=size, n=1))
    return _openai_images(answer)[0]


def _multipart(fields, files):
    boundary = uuid.uuid4().hex
    parts = []
    for name, value in fields.items():
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode())
    for name, (filename, data) in files.items():
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"; filename="{filename}"\r\n'
                     f'Content-Type: image/png\r\n\r\n'.encode() + data + b'\r\n')
    parts.append(f'--{boundary}--\r\n'.encode())
    return b''.join(parts), f'multipart/form-data; boundary={boundary}'


def openai_edit(model, prompt, image, key, base):
    body, kind = _multipart(dict(model=model, prompt=prompt, n='1'), dict(image=('photo.png', _png(image))))
    answer = _json('openai', 'POST', f'{base}/images/edits', {'Authorization': f'Bearer {key}'}, raw=body,
                   content_type=kind)
    return _openai_images(answer)[0]


def _gemini(model, parts, key, base, ratio=None):
    body = dict(contents=[dict(role='user', parts=parts)],
                generationConfig=dict(responseModalities=['TEXT', 'IMAGE']))
    if ratio:
        body['generationConfig']['imageConfig'] = dict(aspectRatio=ratio)
    url = f'{base}/models/{model}:generateContent'
    try:
        answer = _json('gemini', 'POST', url, {'x-goog-api-key': key}, body)
    except CloudError as exc:
        if not ratio or 'imageConfig' not in str(exc):
            raise
        body['generationConfig'].pop('imageConfig')  # an older model: the prompt alone sets the shape
        answer = _json('gemini', 'POST', url, {'x-goog-api-key': key}, body)
    said = []
    for candidate in answer.get('candidates') or []:
        for part in (candidate.get('content') or {}).get('parts') or []:
            inline = part.get('inlineData') or part.get('inline_data')
            if inline and inline.get('data'):
                return _picture(base64.b64decode(inline['data']))
            if part.get('text'):
                said.append(part['text'])
        if candidate.get('finishReason') not in (None, 'STOP'):
            said.append(f'(stopped: {candidate["finishReason"]})')
    blocked = (answer.get('promptFeedback') or {}).get('blockReason')
    reason = f'the request was blocked ({blocked})' if blocked else ' '.join(said)[:300] or 'no reason given'
    raise CloudError(f'Gemini returned no picture: {reason}')


def gemini_generate(model, prompt, width, height, key, base):
    return _gemini(model, [dict(text=prompt)], key, base, aspect(width, height))


def gemini_edit(model, prompt, image, key, base):
    data = base64.b64encode(_png(image)).decode('ascii')
    return _gemini(model, [dict(text=prompt), dict(inline_data=dict(mime_type='image/png', data=data))], key, base)


def _fal(model, body, key, base):
    answer = _json('fal', 'POST', f'{base}/{model}', {'Authorization': f'Key {key}'}, body)
    images = answer.get('images') or ([answer['image']] if isinstance(answer.get('image'), dict) else [])
    if not images or not images[0].get('url'):
        raise CloudError('fal.ai returned no picture.')
    return _download('fal', images[0]['url'])


def fal_generate(model, prompt, width, height, key, base):
    return _fal(model, dict(prompt=prompt, image_size=dict(width=width, height=height), num_images=1), key, base)


def fal_edit(model, prompt, image, key, base):
    return _fal(model, dict(prompt=prompt, image_url=_data_url(image)), key, base)


def replicate_generate(model, prompt, width, height, key, base, cancelled=None):
    headers = {'Authorization': f'Bearer {key}', 'Prefer': 'wait'}
    body = dict(input=dict(prompt=prompt, aspect_ratio=aspect(width, height), output_format='png'))
    answer = _json('replicate', 'POST', f'{base}/models/{model}/predictions', headers, body)
    while answer.get('status') in ('starting', 'processing'):
        if cancelled is not None and cancelled.is_set():
            raise CloudError('Stopped.')
        time.sleep(POLL_SECONDS)
        answer = _json('replicate', 'GET', answer['urls']['get'], {'Authorization': f'Bearer {key}'})
    if answer.get('status') != 'succeeded':
        raise CloudError(f'Replicate could not make the picture: {answer.get("error") or answer.get("status")}')
    output = answer.get('output')
    url = output[0] if isinstance(output, list) and output else output
    if not isinstance(url, str):
        raise CloudError('Replicate returned no picture.')
    return _download('replicate', url)


GENERATE = dict(openai=openai_generate, gemini=gemini_generate, fal=fal_generate, replicate=replicate_generate)
EDIT = dict(openai=openai_edit, gemini=gemini_edit, fal=fal_edit)


# Jobs --------------------------------------------------------------------------------------

def _connection(model_id, table):
    provider, model = providers.split(model_id)
    if provider not in table:
        raise CloudError(f'{model_id} is not a cloud model the studio knows.')
    if not providers.connected(provider):
        raise CloudError(f'Connect {_label(provider)} in Settings → Providers first.')
    base = providers.options(provider)['base_url'].rstrip('/')
    return provider, model, providers.key(provider), base


def save(image, details):
    IMAGES.mkdir(parents=True, exist_ok=True)
    path = IMAGES / f'{time.strftime("%Y%m%d-%H%M%S")}-{details["provider"]}-{time.time_ns() % 1000000:06d}.png'
    info = PngInfo()
    info.add_text('parameters', f'{details["prompt"]}\nModel: {details["model"]}, '
                                f'Size: {details["width"]}x{details["height"]}')
    image.save(path, pnginfo=info)
    path.with_suffix('.json').write_text(json.dumps(details, indent=2), encoding='utf-8')
    return path


def generate(model_id, prompt, width, height, count, progress, cancelled):
    """Make count pictures; returns their library paths, saving each as it arrives."""
    provider, model, key, base = _connection(model_id, GENERATE)
    paths = []
    for index in range(count):
        if cancelled.is_set():
            break
        progress(0.05 + 0.9 * index / count, f'Waiting for {_label(provider)}… ({index + 1} of {count})'
                 if count > 1 else f'Waiting for {_label(provider)}…')
        started = time.time()
        call = GENERATE[provider]
        image = (call(model, prompt, width, height, key, base, cancelled) if provider == 'replicate'
                 else call(model, prompt, width, height, key, base))
        paths.append(save(image, dict(
            prompt=prompt, request=prompt, provider=provider, model=f'{provider}/{model}', cloud_model=model_id,
            width=image.width, height=image.height, base_width=width, base_height=height, seed=None,
            steps=None, style=_label(provider), negative_prompt='', total_seconds=round(time.time() - started, 1),
        )))
    return paths


def edit(model_id, image, prompt, progress):
    provider, model, key, base = _connection(model_id, EDIT)
    progress(0.1, f'Waiting for {_label(provider)}…')
    started = time.time()
    result = EDIT[provider](model, prompt, image, key, base)
    return save(result, dict(
        prompt=prompt, request=prompt, provider=provider, model=f'{provider}/{model}', cloud_model=model_id,
        width=result.width, height=result.height, seed=None, steps=None, style=f'{_label(provider)} edit',
        negative_prompt='', edit=True, total_seconds=round(time.time() - started, 1),
    ))
