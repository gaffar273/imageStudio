"""Download only the components used by this app; resumable."""

import argparse
import json
import os
from pathlib import Path
from image_studio.core.catalog import (
    MODELS,
    KONTEXT,
    BRAIN,
    ASSISTANT,
    REPAIR,
    FACE_REFERENCE,
    SEARCH,
    SEGMENT,
    WORK,
)

os.environ.setdefault('HF_HOME', str(WORK / 'huggingface'))
os.environ.setdefault('HF_HUB_DISABLE_TELEMETRY', '1')
os.environ.setdefault('HF_HUB_DOWNLOAD_TIMEOUT', '120')
# Plain HTTP downloads keep partial files and resume them after a dropped
# connection; the Xet transfer path restarts large files from zero instead.
os.environ.setdefault('HF_HUB_DISABLE_XET', '1')
from huggingface_hub import HfApi, get_token, hf_hub_download, snapshot_download
from huggingface_hub.errors import GatedRepoError

T5_FP8 = 'model-fp8.safetensors'
T5_POSITION_BIAS = 'position-bias-bf16.safetensors'


def login_token():
    """The project keeps its own HF_HOME; also accept a login made in a normal shell."""
    default = Path.home() / '.cache' / 'huggingface' / 'token'
    return get_token() or (default.read_text().strip() if default.exists() else None)


def download_sdxl(model):
    revision = HfApi().model_info(model['repo']).sha
    print(f'Downloading {model["repo"]} (about 6.94 GB). Interrupted downloads can be resumed.', flush=True)
    snapshot_download(
        model['repo'],
        revision=revision,
        local_dir=str(model['folder']),
        max_workers=4,
        allow_patterns=[
            'model_index.json',
            'scheduler/scheduler_config.json',
            'text_encoder/config.json',
            'text_encoder/model.fp16.safetensors',
            'text_encoder_2/config.json',
            'text_encoder_2/model.fp16.safetensors',
            'tokenizer/*',
            'tokenizer_2/*',
            'unet/config.json',
            'unet/diffusion_pytorch_model.fp16.safetensors',
            'vae/config.json',
            'vae/diffusion_pytorch_model.fp16.safetensors',
            'LICENSE*',
            'README.md',
        ],
    )
    return revision


def convert_t5_to_fp8(folder):
    """Store T5's linear weights as float8 (4.8 GB instead of 9.5 GB); they are
    expanded back to bfloat16 one layer at a time while the prompt is encoded."""
    import torch
    from safetensors import safe_open
    from safetensors.torch import save_file

    encoder = folder / 'text_encoder_2'
    shards = sorted(encoder.glob('model-0000*-of-*.safetensors'))
    if (encoder / T5_FP8).exists() and not shards:
        return
    print('Converting the text encoder to 8-bit storage...', flush=True)
    state = {}
    for shard in shards:
        # One tensor at a time keeps memory use near the 4.8 GB result.
        with safe_open(str(shard), framework='pt') as source:
            for key in source.keys():
                tensor = source.get_tensor(key)
                linear = (
                    tensor.ndim == 2
                    and ('.SelfAttention.' in key or '.DenseReluDense.' in key)
                    and 'relative_attention_bias' not in key
                )
                state[key] = tensor.to(torch.float8_e4m3fn if linear else torch.bfloat16)
    save_file(state, str(encoder / f'{T5_FP8}.partial'))
    os.replace(encoder / f'{T5_FP8}.partial', encoder / T5_FP8)
    for shard in shards:
        shard.unlink()
    (encoder / 'model.safetensors.index.json').unlink(missing_ok=True)


def repair_t5_position_bias(folder, revision, token):
    """Early conversions stored T5's small position-bias table as float8. Fetch only
    that 4 KB tensor from the original shard (an HTTP range request) and keep it
    beside the converted encoder in bfloat16."""
    import struct
    import requests
    import torch
    from huggingface_hub import hf_hub_url
    from safetensors import safe_open
    from safetensors.torch import save_file

    key = 'encoder.block.0.layer.0.SelfAttention.relative_attention_bias.weight'
    target = folder / 'text_encoder_2' / T5_POSITION_BIAS
    with safe_open(str(folder / 'text_encoder_2' / T5_FP8), framework='pt') as source:
        if target.exists() or source.get_slice(key).get_dtype() != 'F8_E4M3':
            return
    print('Repairing the text encoder position table (4 KB download)...', flush=True)
    url = hf_hub_url(KONTEXT['repo'], 'text_encoder_2/model-00001-of-00002.safetensors', revision=revision)
    headers = {'Authorization': f'Bearer {token}'} if token else {}

    def fetch(start, end):
        response = requests.get(url, headers={**headers, 'Range': f'bytes={start}-{end}'}, timeout=120)
        response.raise_for_status()
        return response.content

    header_size = struct.unpack('<Q', fetch(0, 7))[0]
    entry = json.loads(fetch(8, 8 + header_size - 1))[key]
    begin, end = entry['data_offsets']
    if entry['dtype'] != 'BF16':
        raise RuntimeError(f'Unexpected position-bias dtype {entry["dtype"]}')
    data = fetch(8 + header_size + begin, 8 + header_size + end - 1)
    tensor = torch.frombuffer(bytearray(data), dtype=torch.bfloat16).reshape(entry['shape']).clone()
    save_file({key: tensor}, str(target))


QWEN_FP8 = 'model-fp8.safetensors'
FP8_MAX = 448.0  # Largest float8_e4m3fn value.


def convert_qwen_to_fp8(folder):
    """Store the Qwen3 text encoder's linear weights as float8 with one scale per output
    row (4.4 GB instead of 8 GB), so it fits the GPU while a prompt is read. Its weights
    are small (around 0.02), where unscaled float8 keeps only a bit or two of precision."""
    import torch
    from safetensors import safe_open
    from safetensors.torch import save_file

    encoder = folder / 'text_encoder'
    shards = sorted(encoder.glob('model-0000*-of-*.safetensors'))
    if (encoder / QWEN_FP8).exists() and not shards:
        return
    print('Converting the text encoder to 8-bit storage...', flush=True)
    state = {}
    for shard in shards:
        with safe_open(str(shard), framework='pt') as source:
            for key in source.keys():
                tensor = source.get_tensor(key)
                if tensor.ndim == 2 and 'embed_tokens' not in key:
                    scale = (tensor.float().abs().amax(dim=1, keepdim=True) / FP8_MAX).clamp(min=1e-12)
                    state[key] = (tensor.float() / scale).to(torch.float8_e4m3fn)
                    state[key.removesuffix('.weight') + '.scale'] = scale.to(torch.bfloat16)
                else:
                    state[key] = tensor.to(torch.bfloat16)
    save_file(state, str(encoder / f'{QWEN_FP8}.partial'))
    os.replace(encoder / f'{QWEN_FP8}.partial', encoder / QWEN_FP8)
    for shard in shards:
        shard.unlink()
    (encoder / 'model.safetensors.index.json').unlink(missing_ok=True)


def download_zimage():
    model = MODELS['accurate']
    folder = model['folder']
    print(
        f'Downloading {model["repo"]} text encoder and VAE (about 8.2 GB, stored as 4.6 GB after '
        'conversion). Interrupted downloads can be resumed.',
        flush=True,
    )
    snapshot_download(
        model['repo'],
        revision=model['revision'],
        local_dir=str(folder),
        max_workers=4,
        allow_patterns=[
            'model_index.json',
            'scheduler/*',
            'text_encoder/*',
            'tokenizer/*',
            'transformer/config.json',
            'vae/*',
            'LICENSE*',
            'README.md',
        ],
        # Already converted to 8-bit on a previous run.
        ignore_patterns=['text_encoder/model-0000*']
        if (folder / 'text_encoder' / QWEN_FP8).exists()
        else None,
    )
    print(f'Downloading {model["gguf_file"]} (about 5.6 GB).', flush=True)
    hf_hub_download(
        model['gguf_repo'], model['gguf_file'], revision=model['gguf_revision'], local_dir=str(folder)
    )
    convert_qwen_to_fp8(folder)
    return model['revision']


def download_kontext():
    token = login_token()
    folder = KONTEXT['folder']
    try:
        revision = HfApi().model_info(KONTEXT['repo'], token=token).sha
        print(
            f'Downloading {KONTEXT["repo"]} text encoders and VAE (about 9.9 GB, '
            'stored as 5 GB after conversion).',
            flush=True,
        )
        snapshot_download(
            KONTEXT['repo'],
            revision=revision,
            local_dir=str(folder),
            max_workers=4,
            token=token,
            allow_patterns=[
                'model_index.json',
                'scheduler/*',
                'text_encoder/*',
                'text_encoder_2/*',
                'tokenizer/*',
                'tokenizer_2/*',
                'transformer/config.json',
                'vae/*',
                'LICENSE*',
                'README.md',
            ],
            # Already converted to 8-bit on a previous run.
            ignore_patterns=['text_encoder_2/model-0000*']
            if (folder / 'text_encoder_2' / T5_FP8).exists()
            else None,
        )
    except GatedRepoError:
        raise SystemExit(
            'FLUX.1 Kontext needs a one-time license acceptance:\n'
            '  1. Sign in at https://huggingface.co and accept the license at\n'
            f'     https://huggingface.co/{KONTEXT["repo"]}\n'
            '  2. Create a Read token at https://huggingface.co/settings/tokens\n'
            '  3. Run: ..\\..\\work\\image-env\\Scripts\\hf.exe auth login\n'
            'Then run this download again.'
        )
    print(f'Downloading {KONTEXT["gguf_file"]} (about 6.93 GB).', flush=True)
    hf_hub_download(
        KONTEXT['gguf_repo'], KONTEXT['gguf_file'], revision=KONTEXT['gguf_revision'], local_dir=str(folder)
    )
    convert_t5_to_fp8(folder)
    repair_t5_position_bias(folder, revision, token)
    return revision


def download_segment():
    """SAM 2.1 tiny from Ultralytics' release assets, resuming a partial file."""
    import urllib.request

    SEGMENT['folder'].mkdir(parents=True, exist_ok=True)
    target = SEGMENT['folder'] / SEGMENT['file']
    print('Downloading SAM 2.1 tiny (about 80 MB). Interrupted downloads can be resumed.', flush=True)
    while not target.exists() or target.stat().st_size < SEGMENT['size']:
        done = target.stat().st_size if target.exists() else 0
        request = urllib.request.Request(SEGMENT['url'], headers={'Range': f'bytes={done}-'})
        with urllib.request.urlopen(request, timeout=120) as response, target.open('ab') as out:
            while chunk := response.read(1 << 20):
                out.write(chunk)
    if target.stat().st_size != SEGMENT['size']:
        raise RuntimeError('The segmentation model file has the wrong size. Delete it and run this again.')


def download_brain():
    """Qwen3.5-9B (4-bit GGUF and its vision part) and the pinned llama.cpp CUDA build."""
    import urllib.request
    import zipfile

    print(f'Downloading {BRAIN["repo"]} (about 6.6 GB).', flush=True)
    for name in (BRAIN['mmproj'], BRAIN['model']):
        hf_hub_download(BRAIN['repo'], name, revision=BRAIN['revision'], local_dir=str(BRAIN['folder']))
    folder = BRAIN['server'].parents[1]
    if not BRAIN['server'].exists():
        print(f'Downloading llama.cpp {BRAIN["llama_release"]} for CUDA (about 650 MB).', flush=True)
        folder.mkdir(parents=True, exist_ok=True)
        base = f'https://github.com/ggml-org/llama.cpp/releases/download/{BRAIN["llama_release"]}/'
        for asset in BRAIN['llama_assets']:
            archive = folder / asset
            urllib.request.urlretrieve(base + asset, archive)
            with zipfile.ZipFile(archive) as packed:
                packed.extractall(BRAIN['server'].parent)
            archive.unlink()
    return BRAIN['revision']


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument(
        '--model',
        choices=[*MODELS, 'kontext', 'assistant', 'repair', 'faces', 'search', 'segment', 'brain'],
        default='realistic',
    )
    args = parser.parse_args()
    if args.model == 'kontext':
        model, revision = KONTEXT, download_kontext()
    elif args.model == 'repair':
        model, revision = REPAIR, REPAIR['revision']
        print('Downloading the face and hand detectors (about 100 MB).', flush=True)
        for name in (REPAIR['face'], REPAIR['hand']):
            hf_hub_download(REPAIR['repo'], name, revision=revision, local_dir=str(REPAIR['folder']))
    elif args.model == 'faces':
        model, revision = FACE_REFERENCE, FACE_REFERENCE['revision']
        print('Downloading IP-Adapter Plus Face and its image encoder (about 3.4 GB).', flush=True)
        for name in (
            FACE_REFERENCE['weights'],
            f'{FACE_REFERENCE["encoder"]}/config.json',
            f'{FACE_REFERENCE["encoder"]}/model.safetensors',
        ):
            hf_hub_download(
                FACE_REFERENCE['repo'], name, revision=revision, local_dir=str(FACE_REFERENCE['folder'])
            )
    elif args.model == 'accurate':
        model, revision = MODELS['accurate'], download_zimage()
    elif args.model == 'assistant':
        model, revision = ASSISTANT, ASSISTANT['revision']
        print(f'Downloading {ASSISTANT["repo"]} (about 4.3 GB).', flush=True)
        snapshot_download(
            ASSISTANT['repo'],
            revision=revision,
            local_dir=str(ASSISTANT['folder']),
            max_workers=4,
            allow_patterns=['*.json', '*.safetensors', '*.txt', 'LICENSE*', 'README.md', '*.jinja'],
        )
    elif args.model == 'search':
        model, revision = SEARCH, SEARCH['revision']
        print(f'Downloading {SEARCH["repo"]} (about 1.5 GB).', flush=True)
        snapshot_download(
            SEARCH['repo'],
            revision=revision,
            local_dir=str(SEARCH['folder']),
            max_workers=4,
            allow_patterns=['*.json', '*.safetensors', '*.jinja', 'tokenizer.model', 'LICENSE*', 'README.md'],
        )
    elif args.model == 'segment':
        model, revision = SEGMENT, 'v8.3.0'
        download_segment()
    elif args.model == 'brain':
        model, revision = BRAIN, download_brain()
    else:
        model = MODELS[args.model]
        revision = download_sdxl(model)
    (model['folder'] / 'download-complete.json').write_text(
        json.dumps({'model': model['repo'], 'revision': revision}), encoding='utf-8'
    )
    print('Model is ready. Open Start image generator.bat.', flush=True)
