"""Available local models and measured-size generation presets."""

import os

from image_studio.core.paths import ROOT as ROOT, WORK

MODELS = {
    'realistic': {
        'repo': 'SG161222/RealVisXL_V5.0',
        'folder': WORK / 'realvisxl-v5',
        'label': 'Realistic — people and scenes',
    },
    # Z-Image Turbo (Apache 2.0): reads prompts with a Qwen3-4B language model, so it
    # follows counts, colors and positions far better than SDXL's CLIP encoders. The
    # official transformer is 24.6 GB in float32; a 5-bit GGUF of the same weights is used.
    'accurate': {
        'repo': 'Tongyi-MAI/Z-Image-Turbo',
        'revision': 'f332072aa78be7aecdf3ee76d5c247082da564a6',
        'gguf_repo': 'unsloth/Z-Image-Turbo-GGUF',
        'gguf_revision': '6c80814333b7b6a70a2e5b469a7c6437ce65de0f',
        'gguf_file': 'z-image-turbo-Q5_K_M.gguf',
        'folder': WORK / 'z-image-turbo',
        'label': 'Accurate — follows detailed prompts (Z-Image Turbo)',
    },
    'turbo': {
        'repo': 'stabilityai/sdxl-turbo',
        'folder': WORK / 'sdxl-turbo',
        'label': 'Turbo — quick drafts',
    },
}
SIZES = {
    'Square · 1024 × 1024': (1024, 1024),
    'Portrait · 832 × 1216': (832, 1216),
    'Landscape · 1216 × 832': (1216, 832),
    'Widescreen · 1344 × 768': (1344, 768),
    'Large portrait · 1024 × 1536': (1024, 1536),
    'Large landscape · 1536 × 1024': (1536, 1024),
    'Smaller · 768 × 768': (768, 768),
}
DEFAULT_NEGATIVE = 'blurry, low quality, illustration, cartoon, CGI, plastic skin, deformed, bad anatomy, extra fingers, text, watermark'

# Instruction-based photo editing (FLUX.1 Kontext dev, 4-bit GGUF). The official
# repository supplies the text encoders, VAE and configs; the 4-bit transformer
# comes from a community GGUF conversion of the same weights.
KONTEXT = {
    'repo': 'black-forest-labs/FLUX.1-Kontext-dev',
    'gguf_repo': 'QuantStack/FLUX.1-Kontext-dev-GGUF',
    'gguf_revision': '2d083027732f81e5548620b57ac47da22d30aa5a',
    'gguf_file': 'flux1-kontext-dev-Q4_K_M.gguf',
    'folder': WORK / 'flux-kontext',
    'label': 'FLUX.1 Kontext — creative photo editing',
}
EDIT_QUALITY = {
    'Standard · about 1 megapixel': 1024 * 1024,
    'Faster · about 0.6 megapixel': 768 * 768,
}

# Prompt assistant: a small vision-language model that turns casual requests
# (typos, vague wording) into clear prompts, looking at the photo when editing.
ASSISTANT = {
    'repo': 'Qwen/Qwen3-VL-2B-Instruct',
    'revision': '89644892e4d85e24eaac8bacfd4f463576704203',
    'folder': WORK / 'prompt-assistant',
}

# Face and hand repair: YOLO detectors (Apache 2.0) that find faces and hands to redraw.
REPAIR = {
    'repo': 'Bingsu/adetailer',
    'revision': '53cc19de382014514d9d4038601d261a7faa9b7b',
    'face': 'face_yolov9c.pt',
    'hand': 'hand_yolov9c.pt',
    'folder': WORK / 'repair-detectors',
}

# Reference faces (step 5 of the realism work): IP-Adapter Plus Face for SDXL (Apache 2.0)
# redraws each face in a picture after a different reference face, so a group stops being
# copies of one face. References come from a pool of generated portraits (see faces.py).
FACE_REFERENCE = {
    'repo': 'h94/IP-Adapter',
    'revision': '018e402774aeeddd60609b4ecdb7e298259dc729',
    'weights': 'sdxl_models/ip-adapter-plus-face_sdxl_vit-h.safetensors',
    'encoder': 'models/image_encoder',
    'folder': WORK / 'face-reference',
    'pool': WORK / 'face-pool',
}

# Image search: EmbeddingGemma 2 (Google, Apache 2.0) puts pictures and typed text into one
# space, so "the picnic with the red umbrella" finds that picture. It needs transformers 5,
# newer than the image models use, so it runs on the CPU in its own environment (search.py).
SEARCH = {
    'repo': 'google/embeddinggemma-2',
    'revision': '914f7f89142e33e77833254d9c9b90c3cef7303b',
    'folder': WORK / 'image-search',
    'python': WORK / 'search-env' / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python'),
    'index': WORK / 'image-search-index',
}

# Realism LoRA for RealVisXL, trained on this laptop from everyday Open Images photos
# (lora_train/). Used when present; its strength is set per image.
REALISM_LORA = WORK / 'realism-lora' / 'final'
REALISM_DEFAULT = 0.6

# Select by description in the editor: the prompt assistant (Qwen3-VL) finds each box,
# SAM 2.1 large (Meta, Apache 2.0; Ultralytics' packaging) outlines what is inside it.
SEGMENT = {
    'repo': 'ultralytics/assets',
    'url': 'https://github.com/ultralytics/assets/releases/download/v8.3.0/sam2.1_l.pt',
    'file': 'sam2.1_l.pt',
    'size': 449239354,
    'folder': WORK / 'segment-model',
}

# The editing brain: Qwen3.5-9B (Apache 2.0), a vision-language model that looks at the photo,
# plans professional edits and checks its own grades (brain.py). 4-bit GGUF served by a pinned
# llama.cpp CUDA build in its own process, which also frees the GPU completely when stopped.
BRAIN = {
    'repo': 'unsloth/Qwen3.5-9B-GGUF',
    'revision': '3885219b6810b007914f3a7950a8d1b469d598a5',
    'model': 'Qwen3.5-9B-Q4_K_M.gguf',
    'mmproj': 'mmproj-F16.gguf',
    'folder': WORK / 'editor-brain',
    'llama_release': 'b11060',
    'llama_assets': ['llama-b11060-bin-win-cuda-12.4-x64.zip', 'cudart-llama-bin-win-cuda-12.4-x64.zip'],
    'server': WORK / 'llama-cpp' / 'b11060' / 'bin' / 'llama-server.exe',
    'port': 7862,
}

# Krita 6 (portable copy) with the AI panel (krita-plugin/), driven from the browser too.
KRITA = WORK / 'krita' / 'krita-x64-6.0.4' / 'bin' / 'krita.exe'
