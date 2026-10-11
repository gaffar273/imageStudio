"""Caption the realism LoRA's photos with the local Qwen3-VL prompt assistant.

Captions say only what is in each photo (people, what they do, setting, light), never
that it is a photo or how it looks. What every caption leaves out, the look of an
ordinary camera photo, is then what the LoRA learns. Writes <image>.txt beside each photo.

Usage (from the app folder, with the image generator stopped):
  python training/lora\\caption.py
"""

import sys
from pathlib import Path
from PIL import Image

APP = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(APP / 'backend'))
IMAGES = APP.parent.parent / 'work' / 'lora-data' / 'images'

SYSTEM = (
    'You write captions for training an image generator. Describe what the picture shows in one plain '
    'sentence of 20 to 45 words: the people (approximate age, clothing) or main objects, what they are '
    'doing, the setting, and the light and time of day. Do not say it is a photo or picture, and do not '
    'describe its quality, style, camera, colors in general, or mood. No names, no text you read.'
)
EXAMPLES = []


def main():
    from image_studio.services import assistant

    images = sorted(IMAGES.glob('*.jpg'))
    todo = [path for path in images if not path.with_suffix('.txt').exists()]
    print(f'{len(images)} photos, {len(todo)} to caption', flush=True)
    with assistant.Session() as session:
        for index, path in enumerate(todo):
            text = assistant.clean(
                session.ask(
                    SYSTEM, EXAMPLES, 'Describe this picture.', Image.open(path), max_new_tokens=90, prefix=''
                )
            )
            text = text.removeprefix('A photo of ').removeprefix('A picture of ').strip()
            path.with_suffix('.txt').write_text(text, encoding='utf-8')
            if index % 50 == 0:
                print(f'{index + 1}/{len(todo)} {path.name}: {text}', flush=True)
    print('Done', flush=True)


if __name__ == '__main__':
    main()
