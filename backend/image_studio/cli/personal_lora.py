"""Train the personal style LoRA from the pictures marked as favorites (see services/personal.py).

Usage (from the app folder):
  python -m image_studio.cli.personal_lora            # through the running studio, or here if it is closed
  python -m image_studio.cli.personal_lora --if-needed  # only when enough favorites changed (for a scheduler)
  python -m image_studio.cli.personal_lora --run      # the training itself; the studio must not be rendering
"""

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime

from PIL import Image, ImageOps

from image_studio.core.paths import IMAGES, ROOT
from image_studio.services import memory, personal

URL = 'http://127.0.0.1:7860'


def export(names):
    """Copy the favorites into the training folder as JPEGs; drop pictures no longer favorites."""
    folder = personal.DATA / 'images'
    cache = personal.DATA / 'cache'
    folder.mkdir(parents=True, exist_ok=True)
    wanted = set()
    for name in names:
        source = IMAGES / name
        if not source.is_file():
            continue
        stem = source.stem
        wanted.add(stem)
        target = folder / f'{stem}.jpg'
        if not target.exists():
            with Image.open(source) as image:
                image = ImageOps.exif_transpose(image)
                if image.mode in ('RGBA', 'LA', 'P'):
                    image = image.convert('RGBA')
                    flat = Image.new('RGB', image.size, (255, 255, 255))
                    flat.paste(image, mask=image.getchannel('A'))
                    image = flat
                image.convert('RGB').save(target, quality=95)
    for path in list(folder.glob('*')) + list(cache.glob('*.pt')):
        if path.stem not in wanted and path.name != 'empty.pt':
            path.unlink()
    return sorted(wanted)


def caption(stems):
    """One plain sentence about what each picture shows, never its style (as caption.py)."""
    sys.path.insert(0, str(ROOT / 'training' / 'lora'))
    import caption as captions
    from image_studio.services import assistant

    folder = personal.DATA / 'images'
    todo = [stem for stem in stems if not (folder / f'{stem}.txt').exists()]
    if not todo:
        return
    with assistant.Session() as session:
        for index, stem in enumerate(todo):
            with Image.open(folder / f'{stem}.jpg') as image:
                text = assistant.clean(
                    session.ask(
                        captions.SYSTEM,
                        captions.EXAMPLES,
                        'Describe this picture.',
                        image.convert('RGB'),
                        max_new_tokens=90,
                        prefix='',
                    )
                )
            text = text.removeprefix('A photo of ').removeprefix('A picture of ').strip()
            (folder / f'{stem}.txt').write_text(text, encoding='utf-8')
            print(f'caption {index + 1}/{len(todo)}', flush=True)
    assistant.release()


def run():
    """Export, caption and train. Writes status.json; the server reads it."""
    personal.FOLDER.mkdir(parents=True, exist_ok=True)
    personal.LOCK.write_text(str(os.getpid()))
    try:
        names = memory.favorites()
        stems = export(names)
        if len(stems) < personal.MIN_IMAGES:
            raise SystemExit(f'Only {len(stems)} favorites found; at least {personal.MIN_IMAGES} are needed.')
        print(f'{len(stems)} favorites', flush=True)
        caption(stems)
        sys.path.insert(0, str(ROOT / 'training' / 'lora'))
        import train_lora

        train_lora.use_folders(personal.DATA, personal.FOLDER, f'{len(stems)} favorites from the Library')
        items = train_lora.build_cache()
        steps = personal.steps_for(len(items))
        train_lora.train(items, steps, personal.RANK, 1e-4, steps + 1, 7)
        personal._save(
            images=[f'{stem}.png' for stem in stems],
            trained_at=time.time(),
            message=f'Learned your style from {len(stems)} favorites.',
        )
    finally:
        try:
            personal.LOCK.unlink()
        except OSError:
            pass


def through_server(if_needed):
    """Ask the running studio to train (it frees the GPU first). False if it is not running."""
    body = json.dumps(dict(action='train', if_needed=if_needed)).encode()
    request = urllib.request.Request(
        f'{URL}/api/personal-lora', data=body, method='POST', headers={'Content-Type': 'application/json'}
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            print(json.loads(response.read()).get('message') or 'Training started in the studio.')
        return True
    except urllib.error.HTTPError as exc:
        print(json.loads(exc.read()).get('detail', exc))
        return True
    except OSError:
        return False


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument('--run', action='store_true', help='train now, in this process')
    parser.add_argument('--if-needed', action='store_true', help='only when enough favorites changed')
    args = parser.parse_args()
    if args.run:
        return run()
    if through_server(args.if_needed):
        return None
    if personal.training_elsewhere():
        return print('Already training.')
    if args.if_needed and not personal.needed():
        return print(f'{datetime.now():%H:%M} Nothing new to learn.')
    return run()


if __name__ == '__main__':
    main()
