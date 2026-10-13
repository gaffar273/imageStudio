"""Installed copies: where they keep things, the engine's own environment, its setup, and the build."""

import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from image_studio.cli import setup_engine
from image_studio.core import engine_env, paths

ROOT = Path(__file__).resolve().parents[1]
HAS_QT = importlib.util.find_spec('PySide6') is not None


def load_build():
    spec = importlib.util.spec_from_file_location('build', ROOT / 'packaging' / 'build.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def fake_env(folder, **record):
    """An environment folder as setup_engine leaves it: Python, pyvenv.cfg and the marker."""
    env = Path(folder) / 'engine'
    python = engine_env.env_python(env)
    python.parent.mkdir(parents=True)
    python.write_bytes(b'')
    base = Path(getattr(sys, '_base_executable', sys.executable)).parent
    (env / 'pyvenv.cfg').write_text(f'home = {base}\ninclude-system-site-packages = true\n', encoding='utf-8')
    if record is not None:
        (env / engine_env.MARKER).write_text(
            json.dumps(dict(engine_env.wanted(), **record)), encoding='utf-8'
        )
    return env


class InstalledFolderTests(unittest.TestCase):
    def test_an_installed_copy_ignores_the_source_checkout_folders(self):
        with patch.object(paths, 'INSTALLED', True):
            self.assertEqual(paths.default_models_dir(), paths.data_dir() / 'models')
            self.assertFalse(paths.default_library_dir().is_relative_to(paths.ROOT))

    def test_pictures_go_where_the_system_keeps_them(self):
        found = paths.pictures_dir()
        self.assertTrue(found.is_absolute())
        with (
            tempfile.TemporaryDirectory() as folder,
            patch.object(sys, 'platform', 'linux'),
            patch.dict(os.environ, {'XDG_CONFIG_HOME': folder}),
        ):
            (Path(folder) / 'user-dirs.dirs').write_text('# xdg\nXDG_PICTURES_DIR="$HOME/Bilder"\n')
            self.assertEqual(paths.pictures_dir(), Path.home() / 'Bilder')

    def test_the_engine_environment_lives_with_the_user_data(self):
        self.assertFalse(paths.ENGINE_ENV.is_relative_to(paths.ROOT))


class EngineEnvironmentTests(unittest.TestCase):
    def test_status_follows_what_setup_left(self):
        with tempfile.TemporaryDirectory() as folder:
            self.assertEqual(engine_env.status(Path(folder) / 'engine'), 'missing')
            env = fake_env(folder)
            self.assertEqual(engine_env.status(env), 'ready')
            (env / engine_env.MARKER).write_text(json.dumps(dict(engine_env.wanted(), requirements='older')))
            self.assertEqual(engine_env.status(env), 'update')  # an app update pinned other libraries
            (env / engine_env.MARKER).write_text(json.dumps(engine_env.wanted()))
            (env / 'pyvenv.cfg').write_text('home = C:/moved/away\n', encoding='utf-8')
            self.assertEqual(engine_env.status(env), 'update')  # the app moved
            (env / engine_env.MARKER).unlink()
            self.assertEqual(engine_env.status(env), 'missing')  # setup never finished

    def test_the_engine_runs_on_its_environment_only_when_installed(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop('IMAGE_STUDIO_ENGINE_PYTHON', None)
            with patch.object(paths, 'INSTALLED', False):
                self.assertEqual(engine_env.engine_python(), engine_env.app_python())
                self.assertFalse(engine_env.needs_setup())
            with (
                patch.object(paths, 'INSTALLED', True),
                tempfile.TemporaryDirectory() as folder,
                patch.object(paths, 'ENGINE_ENV', Path(folder) / 'engine'),
            ):
                self.assertEqual(engine_env.engine_python(), str(engine_env.env_python()))
                self.assertTrue(engine_env.needs_setup())
                fake_env(folder)
                self.assertFalse(engine_env.needs_setup())
            os.environ['IMAGE_STUDIO_ENGINE_PYTHON'] = 'custom-python'
            self.assertEqual(engine_env.engine_python(), 'custom-python')

    def test_requirement_files_ship_with_the_app(self):
        for file in engine_env.REQUIREMENTS + engine_env.CLOUD_REQUIREMENTS:
            self.assertTrue(file.is_file(), file)
        self.assertIn('--index-url', engine_env.REQUIREMENTS[0].read_text(encoding='utf-8'))

    def test_cloud_mode_has_no_pytorch_and_keeps_the_full_engines_versions(self):
        def pins(files):
            lines = [line.split('#')[0].strip() for file in files for line in file.read_text().splitlines()]
            return dict(line.split('==') for line in lines if '==' in line)

        cloud = pins(engine_env.CLOUD_REQUIREMENTS)
        self.assertFalse({'torch', 'torchvision', 'diffusers', 'transformers'} & set(cloud))
        full = pins(engine_env.REQUIREMENTS)
        for name, version in cloud.items():  # adding the full engine later must not change these
            self.assertEqual(full.get(name, version), version, name)

    def test_a_cloud_engine_is_ready_for_its_own_libraries(self):
        with tempfile.TemporaryDirectory() as folder:
            env = fake_env(folder, kind='cloud')
            self.assertEqual(engine_env.status(env), 'update')  # marked cloud, but pinned like the full engine
            (env / engine_env.MARKER).write_text(json.dumps(dict(engine_env.wanted('cloud'), kind='cloud')))
            self.assertEqual((engine_env.status(env), engine_env.kind(env)), ('ready', 'cloud'))
            (env / engine_env.MARKER).write_text(json.dumps(engine_env.wanted()))
            self.assertEqual((engine_env.status(env), engine_env.kind(env)), ('ready', 'full'))  # older markers

    def test_cloud_setup_installs_only_the_engine_libraries(self):
        with (
            tempfile.TemporaryDirectory() as folder,
            patch.object(setup_engine, 'prepare'),
            patch.object(setup_engine, 'pip_install', return_value=(0, '')) as install,
            patch.object(setup_engine, 'check', return_value=dict(torch=None, cuda=False)) as check,
        ):
            self.assertEqual(setup_engine.main(['--env', folder, '--cloud']), 0)
            self.assertEqual([call.args[1] for call in install.call_args_list], engine_env.CLOUD_REQUIREMENTS)
            self.assertEqual(check.call_args.args[1], 'cloud')
            record = engine_env.recorded(folder)
            self.assertEqual((record['kind'], record['requirements']), ('cloud', engine_env.wanted('cloud')['requirements']))


class SetupOutputTests(unittest.TestCase):
    def test_pip_output_becomes_installer_progress(self):
        translate = setup_engine.Translator()
        self.assertEqual(
            translate(
                'Downloading https://download.pytorch.org/whl/cu128/torch-2.11.0%2Bcu128-cp312-cp312-'
                'win_amd64.whl (2752.0 MB)'
            ),
            'Downloading torch (2752.0 MB)',
        )
        self.assertEqual(translate('Progress 1376000000 of 2752000000'), 'torch: 50%| 1.38 GB/2.75 GB')
        self.assertIsNone(translate('Progress 0 of 0'))
        self.assertEqual(
            translate('  Downloading diffusers-0.37.1-py3-none-any.whl (4.6 MB)'),
            'Downloading diffusers (4.6 MB)',
        )
        self.assertEqual(translate('Progress 2300000 of 4600000'), 'diffusers: 50%| 2 MB/5 MB')
        self.assertEqual(
            translate('Installing collected packages: torch'), 'Installing collected packages: torch'
        )
        self.assertIsNone(translate('   '))

    @unittest.skipUnless(HAS_QT, 'PySide6 is not installed')
    def test_the_installer_reads_those_lines(self):
        from image_studio.desktop import installs

        self.assertEqual(installs.progress_of('torch: 50%| 1.38 GB/2.75 GB'), ('torch · 1.38 GB/2.75 GB', 50))


class BuildTests(unittest.TestCase):
    def test_everything_the_app_reads_is_copied(self):
        build = load_build()
        for item in build.CONTENT:
            self.assertTrue((ROOT / item).exists(), item)
        copied = {Path(item) for item in build.CONTENT}
        for file in engine_env.REQUIREMENTS + engine_env.CLOUD_REQUIREMENTS:
            self.assertIn(file.relative_to(ROOT), copied)
        self.assertIn(Path('integrations/krita-plugin'), copied)  # install_krita_plugin.SOURCE
        self.assertIn(Path('training/lora'), copied)  # personal_lora

    def test_the_app_finds_its_code_from_any_folder(self):
        build = load_build()
        with tempfile.TemporaryDirectory() as folder:
            app = Path(folder) / 'Image Studio'
            packages = build.site_packages(app, 'windows')
            packages.mkdir(parents=True)
            build.link_backend(app, 'windows')
            line = (packages / 'image-studio.pth').read_text(encoding='utf-8').strip()
            self.assertEqual(line, '../../../backend')
            self.assertEqual((packages / line).resolve(), (app / 'backend').resolve())

    def test_the_version_comes_from_the_project(self):
        self.assertRegex(load_build().version(), r'^\d+\.\d+\.\d+')


if __name__ == '__main__':
    unittest.main()
