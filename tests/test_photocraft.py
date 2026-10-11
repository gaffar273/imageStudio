import base64
import io
import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from image_studio.api import routes
from image_studio.api.app import app
from image_studio.integrations import photocraft
from image_studio.services import library
from image_studio.services.jobs import JobStore
from PIL import Image


def image_data():
    buffer = io.BytesIO()
    Image.new('RGBA', (64, 48), (80, 100, 120, 128)).save(buffer, format='PNG')
    return 'data:image/png;base64,' + base64.b64encode(buffer.getvalue()).decode()


class PhotoCraftTests(unittest.TestCase):
    def test_unsupported_clauses_and_masks_are_not_silently_ignored(self):
        client = TestClient(app)
        with (
            patch.object(photocraft, 'available', return_value=True),
            patch.object(routes, 'submit') as submit,
        ):
            for prompt in ['make it brighter and remove the dog', 'make the sky warmer', '']:
                response = client.post(
                    '/api/edit', json={'engine': 'photocraft', 'image': image_data(), 'prompt': prompt}
                )
                self.assertEqual(response.status_code, 422)
            response = client.post(
                '/api/edit',
                json={
                    'engine': 'photocraft',
                    'image': image_data(),
                    'mask': image_data(),
                    'prompt': 'professional polish',
                },
            )
            self.assertEqual(response.status_code, 422)
            submit.assert_not_called()

    def test_missing_install_and_missing_documents(self):
        client = TestClient(app)
        with patch.object(photocraft, 'available', return_value=False):
            response = client.post(
                '/api/edit',
                json={'engine': 'photocraft', 'image': image_data(), 'prompt': 'professional polish'},
            )
            self.assertEqual(response.status_code, 409)
        self.assertEqual(client.get('/api/photocraft/missing.png/download').status_code, 404)
        self.assertEqual(client.post('/api/photocraft/missing.png/open', json={}).status_code, 404)

    @unittest.skipUnless(photocraft.available(), 'PhotoCraft CLI not installed')
    def test_real_edit_api_exports_layers_and_preserves_them_on_next_edit(self):
        client = TestClient(app)
        jobs = JobStore()
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            with (
                patch.object(photocraft, 'IMAGES', folder),
                patch.object(library, 'IMAGES', folder),
                patch.object(photocraft, 'CACHE', folder / 'cache'),
                patch.object(routes, 'store', jobs),
            ):
                source = image_data()
                for index, prompt in enumerate(['make it brighter and warmer', 'make it grayscale']):
                    response = client.post(
                        '/api/edit', json={'engine': 'photocraft', 'image': source, 'prompt': prompt}
                    )
                    self.assertEqual(response.status_code, 202, response.text)
                    job_id = response.json()['id']
                    deadline = time.monotonic() + 20
                    while jobs.get(job_id)['state'] == 'running' and time.monotonic() < deadline:
                        time.sleep(0.05)
                    job = jobs.get(job_id)
                    self.assertEqual(job['state'], 'done', job)
                    result = job['images'][0]
                    output = folder / result['name']
                    with Image.open(output) as rendered:
                        pixel = rendered.convert('RGBA').getpixel((0, 0))
                        self.assertEqual(pixel[3], 128)
                        self.assertNotEqual(pixel[:3], (80, 100, 120))
                    info = json.loads(photocraft.run_cli(['info', output.with_suffix('.psd'), '--compact']))
                    self.assertEqual(
                        sum(layer['kind'] == 'Adjustment' for layer in info['layers']), 2 + index
                    )
                    self.assertEqual(
                        client.get(f'/api/photocraft/{output.name}/download').content[:4], b'8BPS'
                    )
                    with patch.object(photocraft, 'open_document') as launch:
                        self.assertEqual(
                            client.post(f'/api/photocraft/{output.name}/open', json={}).status_code, 200
                        )
                        launch.assert_called_once_with(output.with_suffix('.psd'))
                    source = result['url']

    @unittest.skipUnless(photocraft.available(), 'PhotoCraft CLI not installed')
    def test_presets_render_and_cancel_leaves_no_output(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(photocraft, 'IMAGES', Path(folder)):
            image = Image.new('RGB', (32, 24), (80, 100, 120))
            for prompt in [
                'professional polish',
                'warm portrait',
                'cinematic teal and orange',
                'soft faded film',
            ]:
                result = photocraft.edit(
                    image, prompt, photocraft.plan(prompt), lambda *a, **k: None, threading.Event()
                )
                with Image.open(result) as rendered:
                    self.assertNotEqual(
                        rendered.convert('RGB').getpixel((0, 0)), image.getpixel((0, 0)), prompt
                    )
            before = set(Path(folder).iterdir())
            cancelled = threading.Event()
            cancelled.set()
            self.assertIsNone(
                photocraft.edit(
                    image, 'warm portrait', photocraft.plan('warm portrait'), lambda *a, **k: None, cancelled
                )
            )
            self.assertEqual(set(Path(folder).iterdir()), before)
