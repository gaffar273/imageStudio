"""Image search worker. Runs EmbeddingGemma 2 in its own environment (search-env, which has
the transformers 5 it needs) on the CPU, so the GPU stays free for the image models.

Usage: python search_worker.py MODEL_FOLDER IMAGES_FOLDER INDEX_FOLDER
Reads one JSON request per line on stdin and answers with one JSON line on stdout; exits
when stdin closes. Before every request, pictures added to the images folder since the last
one are embedded and kept in the index, so each picture is read only once."""

import json
import os
import sys
import time
from pathlib import Path

# Libraries print warnings and progress to stdout; keep it for answers only.
ANSWERS = sys.stdout
sys.stdout = sys.stderr

import numpy as np
import torch
from PIL import Image
from sentence_transformers import SentenceTransformer

BATCH = 4


class Index:
    """One unit-length 768-number vector per picture, saved beside a list of names."""

    def __init__(self, model, images, folder):
        self.model, self.images, self.folder = model, images, folder
        folder.mkdir(parents=True, exist_ok=True)
        try:
            self.entries = json.loads((folder / 'index.json').read_text(encoding='utf-8'))
            self.vectors = np.load(folder / 'vectors.npy')
            if len(self.entries) != len(self.vectors):
                raise ValueError('index and vectors differ')
        except (OSError, ValueError):
            self.entries, self.vectors = [], np.zeros((0, 768), np.float32)

    def update(self):
        """Embed new or changed pictures and forget deleted ones; returns how many were added."""
        files = {path.name: path.stat().st_mtime for path in self.images.glob('*.png')}
        keep = [i for i, entry in enumerate(self.entries) if files.get(entry['name']) == entry['mtime']]
        known = {self.entries[i]['name'] for i in keep}
        new = sorted(name for name in files if name not in known)
        if not new and len(keep) == len(self.entries):
            return 0
        entries, vectors = [self.entries[i] for i in keep], [self.vectors[keep]]
        for start in range(0, len(new), BATCH):
            names = new[start : start + BATCH]
            pictures = []
            for name in names:
                with Image.open(self.images / name) as picture:
                    pictures.append({'image': picture.convert('RGB')})
            vectors.append(
                self.model.encode(
                    pictures,
                    batch_size=BATCH,
                    normalize_embeddings=True,
                    convert_to_numpy=True,
                    show_progress_bar=False,
                ).astype(np.float32)
            )
            entries += [{'name': name, 'mtime': files[name]} for name in names]
        self.entries, self.vectors = entries, np.concatenate(vectors)
        self.save()
        return len(new)

    def save(self):
        np.save(self.folder / 'vectors.partial.npy', self.vectors)
        (self.folder / 'index.partial.json').write_text(json.dumps(self.entries), encoding='utf-8')
        os.replace(self.folder / 'vectors.partial.npy', self.folder / 'vectors.npy')
        os.replace(self.folder / 'index.partial.json', self.folder / 'index.json')

    def ranked(self, vector, limit, skip=None):
        scores = self.vectors @ vector
        order = [i for i in np.argsort(-scores) if self.entries[i]['name'] != skip][:limit]
        return [[self.entries[i]['name'], round(float(scores[i]), 4)] for i in order]


def answer(index, model, request):
    started = time.perf_counter()
    # Background reading uses fewer threads; a search the person waits for uses one per core.
    torch.set_num_threads(int(request.get('threads', max(1, (os.cpu_count() or 4) // 2))))
    added = index.update()
    limit = int(request.get('limit', 30))
    if request['op'] == 'search':
        query = model.encode(
            request['text'],
            prompt_name='SearchQuery',
            normalize_embeddings=True,
            convert_to_numpy=True,
            show_progress_bar=False,
        ).astype(np.float32)
        results = index.ranked(query, limit)
    elif request['op'] == 'similar':
        names = [entry['name'] for entry in index.entries]
        if request['name'] not in names:
            raise ValueError(f'{request["name"]} is not in the images folder.')
        results = index.ranked(index.vectors[names.index(request['name'])], limit, skip=request['name'])
    elif request['op'] == 'update':
        results = []
    else:
        raise ValueError(f'Unknown request {request["op"]!r}.')
    return {
        'ok': True,
        'results': results,
        'added': added,
        'total': len(index.entries),
        'seconds': round(time.perf_counter() - started, 2),
    }


def main():
    model_folder, images, index_folder = map(Path, sys.argv[1:4])
    # Only the text and vision parts: the audio encoder (300M parameters) is never used here.
    model = SentenceTransformer(str(model_folder), device='cpu', config_kwargs={'audio_config': None})
    index = Index(model, images, index_folder)
    print(json.dumps({'ok': True, 'ready': True}), file=ANSWERS, flush=True)
    for line in sys.stdin:
        if not line.strip():
            continue
        try:
            reply = answer(index, model, json.loads(line))
        except Exception as error:  # Reported to the app, which shows it; the worker keeps running.
            reply = {'ok': False, 'error': f'{type(error).__name__}: {error}'}
        print(json.dumps(reply), file=ANSWERS, flush=True)


if __name__ == '__main__':
    main()
