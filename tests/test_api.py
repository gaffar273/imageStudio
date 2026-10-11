import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from fastapi.testclient import TestClient
from PIL import Image
from image_studio.api.app import app
from image_studio.api import routes
from image_studio.core.paths import ROOT, WORK
from image_studio.core.catalog import SIZES
from image_studio.services import library, workflows
from image_studio.services.jobs import JobStore


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_krita_import_validates_and_opens_a_separate_png(self):
        import base64
        import io

        buffer = io.BytesIO()
        Image.new('RGBA', (32, 24), (120, 60, 20, 128)).save(buffer, format='PNG')
        value = 'data:image/png;base64,' + base64.b64encode(buffer.getvalue()).decode()
        with tempfile.TemporaryDirectory() as folder, patch.object(routes, 'CACHE', Path(folder)):
            with patch.object(workflows, 'open_in_krita', return_value='Opening in Krita.') as open_image:
                for bad in [None, '', 'not-an-image']:
                    result = self.client.post('/api/krita', json=dict(action='import', image=bad))
                    self.assertEqual(result.status_code, 422)
                open_image.assert_not_called()
                result = self.client.post('/api/krita', json=dict(action='import', image=value))
                self.assertEqual(result.status_code, 200)
                imported = open_image.call_args.args[0]
                self.assertEqual(imported.parent, Path(folder) / 'krita-imports')
                with Image.open(imported) as image:
                    self.assertEqual(image.size, (32, 24))
                    self.assertEqual(image.getpixel((0, 0)), (120, 60, 20, 128))
            with patch.object(workflows, 'open_in_krita', side_effect=ValueError('Not connected')):
                result = self.client.post('/api/krita', json=dict(action='import', image=value))
                self.assertEqual(result.status_code, 409)
                self.assertEqual(list(imported.parent.iterdir()), [imported])

    def test_krita_closed_document_clears_preview(self):
        from image_studio.integrations.bridge import Link

        link = Link()
        link.update(state=dict(name='Test'), preview=b'preview')
        link.update()
        self.assertEqual(link.state['name'], 'Test')
        link.update(state=None)
        self.assertIsNone(link.state)
        self.assertIsNone(link.preview)

    def test_paths_survive_package_move(self):
        self.assertTrue((ROOT / 'frontend' / 'package.json').is_file())
        self.assertTrue((WORK / 'image-env').is_dir())

    def test_config_and_library_contract(self):
        self.assertEqual(self.client.get('/api/health').json()['version'], '2.0.0')
        config = self.client.get('/api/config').json()
        self.assertEqual(len(config['models']), 3)
        self.assertGreater(len(config['sizes']), 3)
        result = self.client.get('/api/library').json()
        self.assertIn('images', result)
        if result['images']:
            image = result['images'][0]
            self.assertEqual(self.client.get(image['thumbnail']).status_code, 200)
            self.assertEqual(
                self.client.get(f'/api/library/{image["name"]}/download').headers['content-type'], 'image/png'
            )

    def test_reject_invalid_generation_before_dispatch(self):
        with patch.object(routes, 'submit') as submit:
            for payload in [
                dict(prompt='', size=next(iter(SIZES))),
                dict(prompt='hello', size='invalid'),
                dict(prompt='hello', size=next(iter(SIZES)), count=8),
                dict(prompt='hello', size=next(iter(SIZES)), seed=-1),
            ]:
                self.assertEqual(self.client.post('/api/generate', json=payload).status_code, 422)
            submit.assert_not_called()

    def test_path_traversal_and_bad_image_rejected(self):
        for value in ['../README.png', '..\\README.png', 'C:\\file.png', 'test.json']:
            with self.assertRaises((ValueError, FileNotFoundError)):
                library.image_path(value)
        self.assertEqual(
            self.client.post('/api/edit', json=dict(image='not-an-image', prompt='change it')).status_code,
            422,
        )

    def test_foreign_browser_cannot_submit(self):
        result = self.client.post('/api/generate', json={}, headers={'Origin': 'https://example.com'})
        self.assertEqual(result.status_code, 403)

    def test_generation_adapter_keeps_settings_and_results(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'result.png'
            Image.new('RGB', (32, 32)).save(path)

            def generate(*args, **kwargs):
                self.assertEqual(args[0], 'A quiet lake')
                self.assertEqual(args[1], '42')
                self.assertEqual(args[2], 'turbo')
                kwargs['progress'](0.5, desc='Rendering')
                yield dict(value=[(str(path), None)]), 'Saved', [], 'A quiet lake', ''

            updates = []

            def submit(run):
                run(lambda *args, **kwargs: None, lambda **values: updates.append(values))
                return dict(id='test')

            with (
                patch.object(workflows, 'generate', side_effect=generate),
                patch.object(routes, 'submit', side_effect=submit),
            ):
                response = self.client.post(
                    '/api/generate',
                    json=dict(prompt='A quiet lake', size=next(iter(SIZES)), model='turbo', seed=42),
                )
            self.assertEqual(response.status_code, 202)
            self.assertEqual(updates[-1]['images'][0]['name'], 'result.png')

    def test_unknown_job_is_404(self):
        self.assertEqual(self.client.get('/api/jobs/missing').status_code, 404)
        self.assertEqual(self.client.post('/api/jobs/missing/cancel', json={}).status_code, 404)

    def test_legacy_nonfinite_metadata_serializes(self):
        import json

        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'legacy.png'
            Image.new('RGB', (2, 2)).save(path)
            path.with_suffix('.json').write_text('{"scheduler": {"value": -Infinity}}')
            result = library.item(path)
            json.dumps(result, allow_nan=False)
            self.assertEqual(result['metadata']['scheduler']['value'], '-inf')


class JobTests(unittest.TestCase):
    def wait_for(self, store, job_id):
        for _ in range(200):
            job = store.get(job_id)
            if job['state'] != 'running' and store.active is None:
                return job
            time.sleep(0.01)
        self.fail('Job did not finish')

    def test_cancel_and_busy_admission(self):
        from image_studio.services.jobs import BusyError

        store = JobStore()
        finish = threading.Event()
        job = store.submit(lambda progress, update: finish.wait(2))
        try:
            with self.assertRaises(BusyError):
                store.submit(lambda progress, update: None)
            store.cancel(job['id'])
            self.assertTrue(workflows.engine.cancelled.is_set())
        finally:
            finish.set()
        self.assertEqual(self.wait_for(store, job['id'])['state'], 'cancelled')

    def test_failure_releases_gpu_session(self):
        store = JobStore()

        def fail(progress, update):
            raise RuntimeError('Model unavailable')

        job = store.submit(fail)
        result = self.wait_for(store, job['id'])
        self.assertEqual(result['state'], 'error')
        self.assertEqual(result['message'], 'Model unavailable')
        next_job = store.submit(lambda progress, update: update(message='Saved'))
        self.assertEqual(self.wait_for(store, next_job['id'])['state'], 'done')


if __name__ == '__main__':
    unittest.main()
