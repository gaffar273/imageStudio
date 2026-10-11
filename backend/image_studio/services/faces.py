"""Reference faces: a different face for each person in a picture.

Image models drift to one face per kind of person, so a group can look like relatives.
IP-Adapter Plus Face for SDXL (h94/IP-Adapter, Apache 2.0) lets RealVisXL redraw a face
after a reference face. During face repair, each face in the picture gets its own
reference from a pool of portraits. The reference is picked at random (from the seed)
among the pool faces the image encoder finds most alike (similar age, sex, skin tone and
light), so a face changes identity without changing who the picture shows, and no two
faces in one picture share a reference.

The pool is ../../work/face-pool. `python faces.py build` fills it with generated
portraits of invented people. You may add photos of yourself or of people who agreed
to it; only the largest face in each photo is used."""

import argparse
import json
import random
import re
from PIL import Image
from image_studio.core.catalog import FACE_REFERENCE

POOL = FACE_REFERENCE['pool']
CACHE = POOL / 'embeddings.safetensors'
SCALE = 0.45  # how strongly the reference shapes the redrawn face
STRENGTH = 0.42  # repair strength for faces with a reference (the face must be redrawn enough to change)
CHOICES = 5  # pick among this many most alike qualifying pool faces
VOTERS = 7  # most alike labelled pool faces that decide a face's sex and age
AGE_RANGE = 12  # references at most this many years from the face's age
MIN_LIKENESS = 0.57  # below this best likeness the encoder does not recognise the face: no reference
LIKENESS_MARGIN = 0.08  # references at most this far below the face's best likeness
MIN_POOL = 8
CROP_PAD = 0.3  # surroundings given to the adapter around a detected face, as a share of its size
# Likeness is judged on the face alone, so neighbours in a tight group photo do not count.
MATCH_PAD = 0.0
VERSION = 2  # of the embeddings cache
EXTENSIONS = ('.png', '.jpg', '.jpeg', '.webp')


def downloaded():
    return (FACE_REFERENCE['folder'] / 'download-complete.json').exists()


def pool_files():
    if not POOL.exists():
        return []
    return sorted(path for path in POOL.iterdir() if path.suffix.lower() in EXTENSIONS)


def available():
    return downloaded() and len(pool_files()) >= MIN_POOL


def face_crop(image, box, pad=CROP_PAD):
    """A square around a detected face, kept inside the picture."""
    x0, y0, x1, y1 = box
    side = min(round(max(x1 - x0, y1 - y0) * (1 + 2 * pad)), *image.size)
    left = min(max(round((x0 + x1 - side) / 2), 0), image.width - side)
    top = min(max(round((y0 + y1 - side) / 2), 0), image.height - side)
    return image.crop((left, top, left + side, top + side))


def largest_face(image):
    """(crop with surroundings, face-only crop) of the biggest face in a photo, or None."""
    from image_studio.services import repair

    found = [item for item in repair.detect(image) if item['kind'] == 'face']
    if not found:
        return None
    box = max(found, key=lambda item: (item['box'][2] - item['box'][0]) * (item['box'][3] - item['box'][1]))[
        'box'
    ]
    image = image.convert('RGB')
    return face_crop(image, box), face_crop(image, box, MATCH_PAD)


class Encoder:
    """The CLIP ViT-H image encoder on the GPU (1.3 GB in half precision), freed on exit."""

    def __enter__(self):
        import torch
        from transformers import CLIPImageProcessor, CLIPVisionModelWithProjection

        self.model = (
            CLIPVisionModelWithProjection.from_pretrained(
                FACE_REFERENCE['folder'] / FACE_REFERENCE['encoder'], dtype=torch.float16
            )
            .to('cuda')
            .eval()
        )
        # The same preprocessing diffusers uses for IP-Adapter images.
        self.processor = CLIPImageProcessor(size=224, crop_size=224)
        return self

    def __exit__(self, *exc):
        import gc
        import torch

        del self.model
        gc.collect()
        torch.cuda.empty_cache()

    def encode(self, images):
        """(hidden states the adapter reads [n, 257, 1280], unit-length embeddings for likeness [n, 1024])."""
        import torch

        pixels = self.processor([image.convert('RGB') for image in images], return_tensors='pt').pixel_values
        with torch.inference_mode():
            output = self.model(pixels.to('cuda', torch.float16), output_hidden_states=True)
        pooled = torch.nn.functional.normalize(output.image_embeds.float(), dim=-1)
        return output.hidden_states[-2].cpu(), pooled.cpu()

    def negative(self):
        """What the adapter is given for "no reference" (a blank image), as diffusers does."""
        import torch

        pixels = torch.zeros(1, 3, 224, 224, device='cuda', dtype=torch.float16)
        with torch.inference_mode():
            return self.model(pixels, output_hidden_states=True).hidden_states[-2].cpu()


def load_pool(encoder, status=print):
    """The pool's embeddings, recomputed when files were added or removed."""
    from safetensors.torch import load_file, save_file

    names = [path.name for path in pool_files()]
    index_file = POOL / 'embeddings.json'
    if CACHE.exists() and index_file.exists():
        saved = json.loads(index_file.read_text(encoding='utf-8'))
        if saved['files'] == names and saved.get('version') == VERSION:
            # Rows follow the photos that had a face.
            return dict(names=saved['kept'], **load_file(str(CACHE)))
    status(f'Reading {len(names)} reference faces...')
    crops, kept = [], []
    for path in pool_files():
        found = largest_face(Image.open(path))
        if found is not None:
            crops.append(found)
            kept.append(path.name)
    hidden, pooled = [], []
    for start in range(0, len(crops), 8):
        hidden.append(encoder.encode([crop for crop, _ in crops[start : start + 8]])[0])
        pooled.append(encoder.encode([face for _, face in crops[start : start + 8]])[1])
    import torch

    data = dict(
        hidden=torch.cat(hidden).contiguous(),
        pooled=torch.cat(pooled).contiguous(),
        negative=encoder.negative().contiguous(),
    )
    save_file(data, str(CACHE))
    index_file.write_text(json.dumps(dict(files=names, kept=kept, version=VERSION)), encoding='utf-8')
    if len(kept) < len(names):
        status(f'{len(names) - len(kept)} pool photos had no face and are skipped.')
    return dict(names=kept, **data)


def label(name):
    """(sex, age, heritage) of a generated pool portrait, read from its prompt; None where
    unknown (photos you added)."""
    path = (POOL / name).with_suffix('.txt')
    text = path.read_text(encoding='utf-8') if path.exists() else ''
    found = re.search(r'(\d+)-year-old (\w+)', text)
    return (
        'female'
        if re.search(r'\b(girl|woman)\b', text)
        else 'male'
        if re.search(r'\b(boy|man)\b', text)
        else None,
        int(found.group(1)) if found else None,
        found.group(2) if found else None,
    )


def references(image, boxes, seed, heritages=None, status=print):
    """For each face box, a different reference face, or none:
    [(pool file name or None, what was decided, embeds for ip_adapter_image_embeds or None)].

    The image encoder's likeness is trusted only as far as it was measured to be right:
    - A face whose best likeness to any pool face is under MIN_LIKENESS gets no reference.
      (Measured: faces it matched well scored 0.595 and up; two white men in warm light it
      matched to East Asian and Ghanaian faces scored 0.54.)
    - Its sex and age are the majority and median of its most alike labelled pool faces,
      and references must have that sex, be within AGE_RANGE years, and be within
      LIKENESS_MARGIN of its best likeness, so the reference looks like the same kind of
      person (otherwise a young man got a young woman's or an old man's face).
    - When the request said the person's heritage (`heritages`, from Vary faces), a
      reference of that heritage is used, and none if no face of that heritage qualifies.
    No two faces in a picture share a reference."""
    import torch

    with Encoder() as encoder:
        pool = load_pool(encoder, status)
        _, pooled = encoder.encode([face_crop(image, box, MATCH_PAD) for box in boxes])
    likeness = pooled @ pool['pooled'].T
    labels = [label(name) for name in pool['names']]
    heritages = heritages or [None] * len(boxes)
    rng, used, chosen = random.Random(seed), set(), []
    for row, heritage in zip(likeness, heritages):
        ranked = [int(index) for index in torch.argsort(row, descending=True)]
        best = row[ranked[0]].item()
        if best < MIN_LIKENESS:
            chosen.append((None, f'no reference: no pool face is alike (best likeness {best:.2f})', None))
            continue
        voters = [labels[index] for index in ranked if labels[index][0]][:VOTERS]
        sexes = [voter[0] for voter in voters]
        sex = max(('female', 'male'), key=sexes.count) if voters else None
        ages = sorted(voter[1] for voter in voters if voter[1])
        age = ages[len(ages) // 2] if ages else None

        def fits(index):
            if index in used or row[index].item() < best - LIKENESS_MARGIN:
                return False
            other_sex, other_age, _ = labels[index]
            if other_sex is None:
                # A photo you added has no labels: used only for faces it closely resembles.
                return index in ranked[:VOTERS]
            return sex in (None, other_sex) and (
                age is None or other_age is None or abs(other_age - age) <= AGE_RANGE
            )

        order = [index for index in ranked if fits(index)]
        same = [index for index in order if heritage and labels[index][2] == heritage]
        seen = ', '.join(filter(None, [sex, age and f'about {age}']))
        if not order:
            chosen.append((None, f'no reference: none close enough ({seen})', None))
            continue
        if heritage and not same:
            # Another heritage's face recast an Italian woman as East Asian in a test.
            chosen.append((None, f'no reference: no {heritage} face close enough ({seen})', None))
            continue
        index = rng.choice((same or order)[:CHOICES])
        used.add(index)
        # [negative; reference] for classifier-free guidance: shape [2, 1, 257, 1280].
        embeds = torch.stack([pool['negative'], pool['hidden'][index : index + 1]]).to(torch.float16)
        chosen.append((pool['names'][index], seen + (f', {heritage}' if same else ''), embeds))
    return chosen


# Building the pool: invented people spread over sex, age and heritage.
AGES = [
    ('girl', 'boy', (8, 13)),
    ('woman', 'man', (19, 28)),
    ('woman', 'man', (32, 50)),
    ('woman', 'man', (60, 80)),
]


# Hairstyles without colours, so each face has its heritage's usual hair: a dyed-looking
# "Japanese man with blond hair" is a poor stand-in for either.
POOL_HAIR = {
    'female': [
        'long hair',
        'short hair',
        'shoulder-length hair',
        'hair in a ponytail',
        'curly hair',
        'braided hair',
        'a bob',
        'hair in a bun',
    ],
    'male': [
        'short hair',
        'a buzz cut',
        'curly hair',
        'a shaved head',
        'wavy hair',
        'long hair tied back',
        'thick hair',
        'a short beard',
    ],
}
POOL_SIZE = 192  # every heritage, both sexes, every age group


def pool_prompts(count=POOL_SIZE):
    """A grid over sex and age group (fastest) and heritage: the first 192 cover every
    combination once, and any shorter run is still spread over all of them."""
    from image_studio.services import variety

    prompts = []
    heritages = variety.HERITAGES
    groups = 2 * len(AGES)
    for index in range(count):
        rng = random.Random(index)
        group, round_ = index % groups, index // groups
        female = group % 2 == 0
        words = AGES[group // 2]
        age = rng.randint(*words[2])
        # 7 shares no factor with 24, so each sex and age group meets every heritage.
        heritage = heritages[(round_ * 7 + group * 3) % len(heritages)][0]
        hair = rng.choice(POOL_HAIR['female' if female else 'male'])
        person = words[0] if female else words[1]
        prompts.append(
            f'candid head and shoulders photo of a {age}-year-old {heritage} {person} with {hair}, '
            f'{variety.with_article(rng.choice(variety.FACE_SHAPES))} and {rng.choice(variety.DETAILS)}, '
            'looking at the camera, plain grey wall, soft daylight, natural skin texture'
        )
    return prompts


def build(count=POOL_SIZE, status=print):
    """Generate `count` portraits with RealVisXL and keep each face as a pool photo."""
    import tempfile
    from image_studio.core.engine import ImageEngine

    POOL.mkdir(parents=True, exist_ok=True)
    engine = ImageEngine()
    with tempfile.TemporaryDirectory() as temporary:
        for index, prompt in enumerate(pool_prompts(count)):
            target = POOL / f'face-{index:03d}.png'
            if target.exists():
                continue
            status(f'Portrait {index + 1} of {count}: {prompt[:70]}...')
            path, _ = engine.generate(
                prompt,
                5000 + index,
                22,
                status=lambda text: None,
                model='realistic',
                size='Smaller · 768 × 768',
                detail='Off',
                style='Natural photo',
                folder=temporary,
            )
            found = largest_face(Image.open(path))
            if found is None:
                status('  no face found; skipped')
                continue
            found[0].resize((512, 512), Image.LANCZOS).save(target)
            target.with_suffix('.txt').write_text(prompt, encoding='utf-8')
    engine.unload()
    status(f'The pool has {len(pool_files())} faces in {POOL}.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Reference faces for face repair.')
    parser.add_argument('command', choices=['build'])
    parser.add_argument('--count', type=int, default=POOL_SIZE)
    args = parser.parse_args()
    build(args.count, status=lambda text: print(text, flush=True))
