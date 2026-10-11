"""Collect everyday photographs from Open Images for the realism LoRA.

Open Images (Google) lists its Flickr photos as CC BY 2.0; credits.csv keeps the author,
licence and source page of every photo used. Only human-verified labels are used to pick
photos of people at a distance and everyday scenes, and photos are dropped when they are
small, blurry, black and white, drawings or text, or when a face fills much of the frame:
the LoRA should learn how ordinary photos look, not who is in them.

Usage (from the app folder):
  python training/lora\\prepare_data.py --people 500 --scenes 300
"""

import argparse
import csv
import io
import random
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
from PIL import Image, ImageOps

APP = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(APP / 'backend'))
DATA = APP.parent.parent / 'work' / 'lora-data'
IMAGES = DATA / 'images'
BUCKET = 'https://open-images-dataset.s3.amazonaws.com/validation/{}.jpg'

PEOPLE = {'Person', 'Man', 'Woman', 'Boy', 'Girl', 'Human face'}
SCENES = {
    'Building',
    'Street',
    'House',
    'Room',
    'Kitchen',
    'Food',
    'Car',
    'Tree',
    'Plant',
    'Beach',
    'Restaurant',
    'Table',
    'Bicycle',
    'Dog',
    'Cat',
    'Flower',
    'Furniture',
    'Window',
    'Boat',
    'Road',
    'Sky',
    'Bus',
}
EXCLUDE = {
    'Drawing',
    'Illustration',
    'Cartoon',
    'Text',
    'Poster',
    'Screenshot',
    'Font',
    'Art',
    'Painting',
    'Logo',
    'Black-and-white',
    'Monochrome photography',
    'Monochrome',
    'Sketch',
    'Collage',
    'Graphics',
    'Graphic design',
    'Brand',
    'Advertising',
    'Map',
    'Diagram',
    'Comics',
    'Fictional character',
    'Toy',
    'Sculpture',
    'Statue',
    'Animation',
    'Pattern',
    'Rectangle',
    'Fashion model',
    'Model',
    'Photo shoot',
    'Selfie',
    'Nudity',
}

MIN_SIDE = 640
MIN_SHARPNESS = 60.0  # variance of the Laplacian at 768 px; lower is blurry
MIN_COLOUR = 0.06  # mean saturation; lower is black and white or nearly
MAX_FACE = 0.22  # the largest face may be at most this share of the picture's height


def labels():
    names = {}
    with open(DATA / 'oidv7-class-descriptions.csv', encoding='utf-8') as file:
        for row in csv.DictReader(file):
            names[row['LabelName']] = row['DisplayName']
    found = {}
    with open(DATA / 'oidv7-val-annotations-human-imagelabels.csv', encoding='utf-8') as file:
        for row in csv.DictReader(file):
            if row['Confidence'] == '1' and row['LabelName'] in names:
                found.setdefault(row['ImageID'], set()).add(names[row['LabelName']])
    return found


def sources():
    with open(DATA / 'validation-images-with-rotation.csv', encoding='utf-8') as file:
        return {row['ImageID']: row for row in csv.DictReader(file)}


def fetch(image_id):
    try:
        with urllib.request.urlopen(BUCKET.format(image_id), timeout=60) as response:
            return image_id, response.read()
    except OSError:
        return image_id, None


def quality(image):
    """(sharpness, colour) of a picture."""
    small = image.copy()
    small.thumbnail((768, 768))
    grey = np.asarray(small.convert('L'), dtype=np.float32)
    laplace = (grey[:-2, 1:-1] + grey[2:, 1:-1] + grey[1:-1, :-2] + grey[1:-1, 2:]) - 4 * grey[1:-1, 1:-1]
    hsv = np.asarray(small.convert('HSV'), dtype=np.float32) / 255
    return float(laplace.var()), float(hsv[..., 1].mean())


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--people', type=int, default=500)
    parser.add_argument('--scenes', type=int, default=300)
    args = parser.parse_args()
    from image_studio.services import repair

    IMAGES.mkdir(parents=True, exist_ok=True)
    tagged, rows = labels(), sources()
    people, scenes = [], []
    for image_id, names in tagged.items():
        if image_id not in rows or names & EXCLUDE:
            continue
        if names & PEOPLE:
            people.append(image_id)
        elif names & SCENES:
            scenes.append(image_id)
    rng = random.Random(7)
    rng.shuffle(people)
    rng.shuffle(scenes)
    print(f'Candidates: {len(people)} with people, {len(scenes)} scenes', flush=True)
    wanted = {'people': args.people, 'scenes': args.scenes}
    kept = {'people': [], 'scenes': []}
    rejected = {}
    credits = []
    for kind, queue in (('people', people), ('scenes', scenes)):
        position = 0
        with ThreadPoolExecutor(8) as pool:
            while len(kept[kind]) < wanted[kind] and position < len(queue):
                batch = queue[position : position + 32]
                position += len(batch)
                for image_id, data in pool.map(fetch, batch):
                    if len(kept[kind]) >= wanted[kind]:
                        break
                    reason = None
                    if data is None:
                        reason = 'download failed'
                    else:
                        try:
                            image = ImageOps.exif_transpose(Image.open(io.BytesIO(data))).convert('RGB')
                        except OSError:
                            image, reason = None, 'unreadable'
                    if reason is None and min(image.size) < MIN_SIDE:
                        reason = 'small'
                    if reason is None:
                        sharpness, colour = quality(image)
                        if sharpness < MIN_SHARPNESS:
                            reason = 'blurry'
                        elif colour < MIN_COLOUR:
                            reason = 'black and white'
                    if reason is None:
                        faces = [item for item in repair.detect(image) if item['kind'] == 'face']
                        tallest = max((item['box'][3] - item['box'][1] for item in faces), default=0)
                        if tallest > MAX_FACE * image.height:
                            reason = 'face close-up'
                    if reason:
                        rejected[reason] = rejected.get(reason, 0) + 1
                        continue
                    image.save(IMAGES / f'{image_id}.jpg', quality=95)
                    kept[kind].append(image_id)
                    row = rows[image_id]
                    credits.append(
                        dict(
                            image=f'{image_id}.jpg',
                            kind=kind,
                            author=row['Author'],
                            author_page=row['AuthorProfileURL'],
                            source=row['OriginalLandingURL'],
                            license=row['License'],
                        )
                    )
                print(
                    f'{kind}: kept {len(kept[kind])} of {wanted[kind]} (looked at {position}); '
                    f'rejected {rejected}',
                    flush=True,
                )
    with open(DATA / 'credits.csv', 'w', newline='', encoding='utf-8') as file:
        writer = csv.DictWriter(
            file, fieldnames=['image', 'kind', 'author', 'author_page', 'source', 'license']
        )
        writer.writeheader()
        writer.writerows(credits)
    print(f'Done: {len(kept["people"])} with people, {len(kept["scenes"])} scenes in {IMAGES}', flush=True)


if __name__ == '__main__':
    main()
