"""Cloud providers: keys kept encrypted, what each provider is used for, and the cloud image calls."""

import base64
import io
import json
import os
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from PIL import Image

from image_studio.api.app import app
from image_studio.api.schemas import EditRequest, GenerateRequest
from image_studio.core import credentials, paths, providers
from image_studio.services import cloud
from image_studio.services.jobs import store


def png_bytes(size=(64, 48), color=(200, 40, 40)):
    buffer = io.BytesIO()
    Image.new('RGB', size, color).save(buffer, 'PNG')
    return buffer.getvalue()


class Sandboxed(unittest.TestCase):
    """Settings, keys and the library in a temporary folder; provider variables cleared."""

    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.folder = Path(folder.name)
        for module, name, replacement in ((paths, 'SETTINGS_FILE', self.folder / 'settings.json'),
                                          (paths, 'config_dir', lambda: self.folder),
                                          (cloud, 'IMAGES', self.folder / 'images')):
            patcher = patch.object(module, name, replacement)
            patcher.start()
            self.addCleanup(patcher.stop)
        names = [spec['env'] for spec in providers.PROVIDERS.values() if spec.get('env')]
        saved = {name: os.environ.pop(name) for name in names if name in os.environ}
        self.addCleanup(os.environ.update, saved)


class CredentialTests(Sandboxed):
    def test_keys_are_stored_sealed_and_can_be_removed(self):
        self.assertEqual(credentials.get('provider:openai'), '')
        credentials.put('provider:openai', 'sk-secret-123')
        self.assertTrue(credentials.stored('provider:openai'))
        self.assertEqual(credentials.get('provider:openai'), 'sk-secret-123')
        text = (self.folder / credentials.FILE_NAME).read_text(encoding='utf-8')
        self.assertNotIn('sk-secret-123', text)
        if sys.platform == 'win32':
            self.assertIn('dpapi:', text)  # sealed for this Windows account
        credentials.delete('provider:openai')
        self.assertFalse(credentials.stored('provider:openai'))
        self.assertEqual(credentials.get('provider:openai'), '')

    def test_the_environment_wins(self):
        credentials.put('provider:openai', 'stored')
        with patch.dict(os.environ, {'OPENAI_API_KEY': 'from-env'}):
            self.assertEqual(credentials.get('provider:openai', 'OPENAI_API_KEY'), 'from-env')
        self.assertEqual(credentials.get('provider:openai', 'OPENAI_API_KEY'), 'stored')

    def test_settings_never_hold_a_key(self):
        providers.save('openai', api_key='sk-abc', image_model='gpt-image-2', enabled=True)
        self.assertNotIn('sk-abc', paths.SETTINGS_FILE.read_text(encoding='utf-8'))


class ProviderTests(Sandboxed):
    def test_connecting_and_disconnecting(self):
        self.assertFalse(providers.connected('openai'))
        self.assertEqual(providers.options('openai')['image_model'], providers.PROVIDERS['openai']['images'][0])
        providers.save('openai', api_key='sk-1', image_model='gpt-image-2', enabled=True)
        self.assertTrue(providers.connected('openai'))
        self.assertEqual(providers.key('openai'), 'sk-1')
        models = {model['provider']: model for model in providers.image_models()}
        self.assertEqual(models['openai'], dict(id='openai:gpt-image-2', provider='openai', label='OpenAI',
                                                model='gpt-image-2', ready=True))
        self.assertFalse(models['gemini']['ready'])
        self.assertNotIn('anthropic', models)  # Claude does not make pictures
        editors = {model['provider'] for model in providers.edit_models()}
        self.assertEqual(editors, {'openai', 'gemini', 'fal'})
        providers.disconnect('openai')
        self.assertFalse(providers.connected('openai'))
        self.assertNotIn('openai', providers.saved())

    def test_servers_on_this_pc_need_no_key_but_must_be_switched_on(self):
        self.assertFalse(providers.connected('ollama'))
        providers.save('ollama', enabled=True)
        self.assertTrue(providers.connected('ollama'))
        providers.save('custom', enabled=True)
        self.assertFalse(providers.connected('custom'))  # no address yet
        providers.save('custom', base_url='http://10.0.0.5:8000/v1')
        self.assertTrue(providers.connected('custom'))

    def test_model_ids(self):
        self.assertEqual(providers.split('fal:fal-ai/flux/dev'), ('fal', 'fal-ai/flux/dev'))
        self.assertEqual(providers.split('realistic'), (None, 'realistic'))
        self.assertEqual(providers.split('nobody:model'), (None, 'nobody:model'))

    def test_the_assistant_follows_the_choice(self):
        from image_studio.pipelines import models

        self.assertEqual(providers.assistant(), dict(provider='local', model=''))
        providers.save('anthropic', api_key='sk-ant-1', enabled=True)
        with patch('image_studio.services.brain.available', return_value=False):
            providers.use_assistant('anthropic', 'claude-opus-5-5')
        self.assertEqual(providers.assistant(), dict(provider='anthropic', model='claude-opus-5-5'))
        for role, spec in models.settings().items():
            with self.subTest(role=role):
                self.assertEqual((spec['kind'], spec['model']), ('anthropic', 'claude-opus-5-5'))
        self.assertEqual(models.adapter('planner').api_key(), 'sk-ant-1')  # read from the key store
        self.assertTrue(models.warnings('grounder'))  # Claude was never measured at boxing things
        # With the bundled model installed, it keeps finding objects; Claude plans and checks.
        with patch('image_studio.services.brain.available', return_value=True):
            providers.use_assistant('anthropic', 'claude-opus-5-5')
        roles = models.settings()
        self.assertEqual(roles['grounder']['kind'], 'local')
        self.assertEqual((roles['planner']['kind'], roles['checker']['kind']), ('anthropic', 'anthropic'))
        # A model trained on the grid grounds wherever it is served.
        self.assertTrue(models.can_ground({'preset': 'ollama', 'model': 'qwen3-vl:8b'}))
        self.assertFalse(models.can_ground({'preset': 'ollama', 'model': 'qwen2.5vl:7b'}))
        self.assertTrue(models.can_ground({'preset': 'gemini', 'model': 'gemini-3-pro'}))

        providers.save('custom', api_key='tok', base_url='http://10.0.0.5:8000/v1', enabled=True)
        providers.use_assistant('custom', 'llama-4')
        spec = models.settings()['checker']
        self.assertEqual((spec['kind'], spec['base_url'], spec['model']), ('openai', 'http://10.0.0.5:8000/v1',
                                                                          'llama-4'))
        self.assertEqual(models.adapter('checker').api_key(), 'tok')
        providers.use_assistant('local')
        self.assertEqual(models.settings()['planner']['kind'], 'local')

    def test_a_test_reports_a_refused_key_plainly(self):
        import urllib.error

        refused = urllib.error.HTTPError('https://api.openai.com/v1/models', 401, 'Unauthorized', {}, io.BytesIO())
        with patch.object(providers, '_get', side_effect=refused):
            ok, message, names = providers.test('openai', 'sk-bad')
        self.assertFalse(ok)
        self.assertIn('refused', message)
        with patch.object(providers, '_get', return_value=dict(data=[dict(id='gpt-image-2'), dict(id='gpt-5')])):
            ok, message, names = providers.test('openai', 'sk-good')
        self.assertTrue(ok)
        self.assertEqual(names, ['gpt-5', 'gpt-image-2'])
        self.assertEqual(providers.test('openai', ''), (False, 'Paste a key first.', []))


class CloudTests(Sandboxed):
    def connect(self, provider, **values):
        providers.save(provider, api_key='key-1', enabled=True, **values)

    def test_openai_creates_pictures_and_saves_them_with_their_settings(self):
        self.connect('openai', image_model='gpt-image-2')
        calls = []

        def answer(provider, method, url, headers=None, body=None, **kwargs):
            calls.append((url, headers, body))
            return json.dumps(dict(data=[dict(b64_json=base64.b64encode(png_bytes()).decode())])).encode()

        progress = []
        with patch.object(cloud, '_request', side_effect=answer):
            made = cloud.generate('openai:gpt-image-2', 'A red barn', 1344, 768, 2,
                                  lambda value, text: progress.append(text), threading.Event())
        self.assertEqual(len(made), 2)
        url, headers, body = calls[0]
        self.assertEqual(url, 'https://api.openai.com/v1/images/generations')
        self.assertEqual(headers['Authorization'], 'Bearer key-1')
        self.assertEqual(body, dict(model='gpt-image-2', prompt='A red barn', size='1536x1024', n=1))
        details = json.loads(made[0].with_suffix('.json').read_text(encoding='utf-8'))
        self.assertEqual((details['provider'], details['cloud_model'], details['request']),
                         ('openai', 'openai:gpt-image-2', 'A red barn'))
        self.assertIn('Waiting for OpenAI… (1 of 2)', progress)

    def test_gemini_reads_the_inline_picture_and_explains_a_refusal(self):
        self.connect('gemini')
        picture = base64.b64encode(png_bytes()).decode()
        reply = dict(candidates=[dict(content=dict(parts=[dict(text='Here it is'),
                                                          dict(inlineData=dict(mimeType='image/png',
                                                                               data=picture))]))])
        with patch.object(cloud, '_request', return_value=json.dumps(reply).encode()) as call:
            image = cloud.gemini_generate('gemini-3.1-flash-image', 'A fox', 832, 1216, 'key-1',
                                          providers.options('gemini')['base_url'])
        self.assertEqual(image.size, (64, 48))
        body = call.call_args.args[4]
        self.assertEqual(body['generationConfig']['imageConfig'], dict(aspectRatio='2:3'))
        self.assertTrue(call.call_args.args[2].endswith('/models/gemini-3.1-flash-image:generateContent'))
        blocked = dict(promptFeedback=dict(blockReason='SAFETY'))
        with patch.object(cloud, '_request', return_value=json.dumps(blocked).encode()):
            with self.assertRaisesRegex(cloud.CloudError, 'blocked'):
                cloud.gemini_generate('gemini-3.1-flash-image', 'x', 1024, 1024, 'key-1', 'https://g')

    def test_fal_and_replicate_download_the_result(self):
        def fal(provider, method, url, headers=None, body=None, **kwargs):
            if method == 'GET':
                return png_bytes((32, 32))
            self.assertEqual(headers['Authorization'], 'Key key-1')
            self.assertEqual(body['image_size'], dict(width=1024, height=1024))
            return json.dumps(dict(images=[dict(url='https://cdn.fal/x.png')])).encode()

        with patch.object(cloud, '_request', side_effect=fal):
            self.assertEqual(cloud.fal_generate('fal-ai/flux/dev', 'p', 1024, 1024, 'key-1', 'https://fal.run').size,
                             (32, 32))
        replies = iter([dict(status='processing', urls=dict(get='https://r/p/1')),
                        dict(status='succeeded', output=['https://r/out.png'])])

        def replicate(provider, method, url, headers=None, body=None, **kwargs):
            if url == 'https://r/out.png':
                return png_bytes((16, 16))
            return json.dumps(next(replies)).encode()

        with patch.object(cloud, '_request', side_effect=replicate), patch.object(cloud, 'POLL_SECONDS', 0):
            image = cloud.replicate_generate('black-forest-labs/flux-schnell', 'p', 1344, 768, 'key-1',
                                             'https://api.replicate.com/v1', threading.Event())
        self.assertEqual(image.size, (16, 16))

    def test_editing_sends_the_photo(self):
        self.connect('openai')
        photo = Image.new('RGB', (40, 30), 'blue')

        def answer(provider, method, url, headers=None, body=None, raw=None, content_type=None):
            self.assertTrue(url.endswith('/images/edits'))
            self.assertIn(b'name="image"; filename="photo.png"', raw)
            self.assertIn(b'gpt-image-2.5-sunburst', raw)
            self.assertTrue(content_type.startswith('multipart/form-data; boundary='))
            return json.dumps(dict(data=[dict(b64_json=base64.b64encode(png_bytes()).decode())])).encode()

        with patch.object(cloud, '_request', side_effect=answer):
            path = cloud.edit('openai:gpt-image-2.5-sunburst', photo, 'Make it night', lambda *_: None)
        self.assertTrue(json.loads(path.with_suffix('.json').read_text(encoding='utf-8'))['edit'])

    def test_a_provider_that_is_not_connected_is_refused(self):
        with self.assertRaisesRegex(cloud.CloudError, 'Connect OpenAI'):
            cloud.generate('openai:gpt-image-2', 'x', 1024, 1024, 1, lambda *_: None, threading.Event())

    def test_sizes_and_shapes(self):
        self.assertEqual(cloud.openai_size(832, 1216), (1024, 1536))
        self.assertEqual(cloud.openai_size(768, 768), (1024, 1024))
        self.assertEqual(cloud.aspect(1344, 768), '16:9')
        self.assertEqual(cloud.aspect(1216, 832), '3:2')


class CloudEndpointTests(Sandboxed):
    def setUp(self):
        super().setUp()
        self.client = TestClient(app)

    def wait(self, job_id):
        for _ in range(200):
            job = store.get(job_id)
            if job['state'] != 'running':
                return job
            time.sleep(0.02)
        self.fail('the job never finished')

    def test_requests_take_cloud_models_by_id(self):
        GenerateRequest(prompt='x', size='s', model='openai:gpt-image-2')
        EditRequest(image='x', prompt='y', engine='fal:fal-ai/flux-pro/kontext')
        for bad in ('nonsense', 'nobody:model', 'openai:'):
            with self.subTest(model=bad), self.assertRaises(ValueError):
                GenerateRequest(prompt='x', size='s', model=bad)

    def test_config_lists_the_cloud_models(self):
        providers.save('fal', api_key='k', enabled=True)
        answer = self.client.get('/api/config').json()
        ready = {model['id']: model['ready'] for model in answer['cloud_models']}
        self.assertTrue(ready['fal:fal-ai/flux/dev'])
        self.assertFalse(ready['openai:gpt-image-2.5-flare'])
        self.assertIn('fal:fal-ai/flux-pro/kontext', {model['id'] for model in answer['cloud_editors']})

    def test_a_cloud_render_runs_as_a_job_without_the_gpu_models(self):
        from image_studio.core.catalog import SIZES

        made = cloud.save(Image.new('RGB', (8, 8)), dict(prompt='A fox', provider='openai', model='openai/m',
                                                          width=8, height=8))
        with patch.object(cloud, 'generate', return_value=[made]) as generate, \
                patch('image_studio.services.workflows.generate') as local:
            answer = self.client.post('/api/generate', json=dict(prompt='A fox', size=next(iter(SIZES)),
                                                                 model='openai:gpt-image-2', count=1))
            self.assertEqual(answer.status_code, 202)
            job = self.wait(answer.json()['id'])
        local.assert_not_called()
        self.assertEqual(generate.call_args.args[:3], ('openai:gpt-image-2', 'A fox', SIZES[next(iter(SIZES))][0]))
        self.assertEqual(job['state'], 'done')
        self.assertEqual(job['message'], '1 picture from OpenAI.')
        self.assertEqual([image['name'] for image in job['images']], [made.name])


class CloudModeEngineTests(CloudEndpointTests):
    """An engine set up without PyTorch (a PC with no NVIDIA card): cloud jobs only, and it says why."""

    def setUp(self):
        super().setUp()
        from image_studio.api import routes
        from image_studio.core import engine

        for module in (routes, engine):
            patcher = patch.object(module, 'local_models', return_value=False)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_config_offers_no_model_on_this_pc(self):
        answer = self.client.get('/api/config').json()
        self.assertFalse(answer['local_models'])
        self.assertEqual([model['ready'] for model in answer['models']], [False] * len(answer['models']))
        for name in ('editing', 'assistant', 'segment', 'repair', 'references'):
            self.assertFalse(answer[name], name)

    def test_a_local_render_says_the_engine_runs_in_cloud_mode(self):
        from image_studio.core.catalog import SIZES
        from image_studio.core.engine import CLOUD_ONLY

        missing = ModuleNotFoundError("No module named 'torch'", name='torch')
        with patch('image_studio.services.workflows.generate', side_effect=missing):
            answer = self.client.post('/api/generate', json=dict(prompt='A fox', size=next(iter(SIZES)),
                                                                 model='turbo', count=1))
            job = self.wait(answer.json()['id'])
        self.assertEqual((job['state'], job['message']), ('error', CLOUD_ONLY))

    def test_other_missing_libraries_are_not_hidden(self):
        from image_studio.core.engine import explain

        self.assertEqual(explain(ModuleNotFoundError("No module named 'yaml'", name='yaml')),
                         "No module named 'yaml'")
        self.assertEqual(explain(ValueError('Choose a size.')), 'Choose a size.')

    def test_a_request_that_needs_a_model_library_answers_409(self):
        def needs_torch():
            raise ModuleNotFoundError("No module named 'diffusers'", name='diffusers')

        app.add_api_route('/api/test-needs-torch', needs_torch)
        route = app.router.routes.pop()
        app.router.routes.insert(0, route)  # ahead of the pages mounted at /
        self.addCleanup(app.router.routes.remove, route)
        answer = self.client.get('/api/test-needs-torch')
        self.assertEqual(answer.status_code, 409)
        self.assertIn('cloud mode', answer.json()['detail'])

    def test_freeing_the_gpu_works_without_pytorch(self):
        with patch.dict(sys.modules, {'torch': None}):
            answer = self.client.post('/api/system/release')
        self.assertEqual(answer.status_code, 200)
