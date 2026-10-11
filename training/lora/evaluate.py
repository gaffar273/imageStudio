"""Same prompts and seeds with the realism LoRA at several strengths, side by side.

Usage (from the app folder, image generator stopped):
  python training/lora\\evaluate.py <output folder> [checkpoint folder]
Writes one sheet per prompt (rows: seeds, columns: strengths) and timings.json.
"""

import json
import sys
import time
from pathlib import Path
from PIL import Image, ImageDraw

APP = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(APP / 'backend'))
from image_studio.core import engine as engine_module
from image_studio.core.engine import ImageEngine

PROMPTS = [
    'A candid photo of a young woman sitting on a park bench, afternoon light',
    'Five friends standing in a row on a beach at sunset, waving at the camera',
    'A man cooking dinner in a small home kitchen in the evening',
    'A busy street market in the afternoon with people shopping',
    'An old man reading a newspaper at a cafe table by the window',
]
SEEDS = [101, 202]
STRENGTHS = [0.0, 0.6, 1.0]


def main():
    out = Path(sys.argv[1])
    out.mkdir(parents=True, exist_ok=True)
    if len(sys.argv) > 2:
        engine_module.REALISM_LORA = Path(sys.argv[2])
    engine = ImageEngine()
    timings = []
    for number, prompt in enumerate(PROMPTS):
        cells = []
        for seed in SEEDS:
            row = []
            for strength in STRENGTHS:
                started = time.time()
                path, details = engine.generate(
                    prompt,
                    seed,
                    30,
                    status=lambda text: None,
                    model='realistic',
                    size='Square · 1024 × 1024',
                    detail='Off',
                    style='Natural photo',
                    finish='Off',
                    realism=strength,
                    folder=out / 'images',
                )
                timings.append(
                    dict(prompt=prompt, seed=seed, strength=strength, seconds=round(time.time() - started, 1))
                )
                row.append(Image.open(path).convert('RGB'))
                print(
                    f'{prompt[:40]} seed {seed} strength {strength}: {time.time() - started:.0f}s', flush=True
                )
            cells.append(row)
        side = 512
        sheet = Image.new('RGB', (side * len(STRENGTHS), side * len(SEEDS) + 30), 'white')
        draw = ImageDraw.Draw(sheet)
        for c, strength in enumerate(STRENGTHS):
            draw.text((c * side + 8, 8), f'LoRA {strength}', fill='black')
        for r, row in enumerate(cells):
            for c, image in enumerate(row):
                sheet.paste(image.resize((side, side)), (c * side, 30 + r * side))
        sheet.save(out / f'sheet-{number}.jpg', quality=90)
    (out / 'timings.json').write_text(json.dumps(timings, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
