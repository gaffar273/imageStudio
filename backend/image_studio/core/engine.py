"""Local RealVisXL, Z-Image Turbo and SDXL-Turbo inference for an 8 GB NVIDIA GPU."""

import argparse
import gc
import json
import math
import os
import secrets
import threading
import time
from pathlib import Path
from PIL import Image
from image_studio.core.catalog import (
    ROOT,
    WORK,
    MODELS,
    SIZES,
    DEFAULT_NEGATIVE,
    KONTEXT,
    EDIT_QUALITY,
    REALISM_LORA,
)

# The personal style LoRA, trained from the Library's favorites (services/personal.py).
PERSONAL_LORA = WORK / 'personal-lora' / 'final'

os.environ.setdefault('HF_HOME', str(WORK / 'huggingface'))
os.environ.setdefault('HF_HUB_DISABLE_TELEMETRY', '1')
os.environ.setdefault('HF_HUB_DOWNLOAD_TIMEOUT', '120')


def new_output(seed, folder=None):
    folder = ROOT / 'images' if folder is None else Path(folder)
    folder.mkdir(exist_ok=True)
    return folder / (time.strftime('%Y%m%d-%H%M%S') + f'-{seed}-{time.time_ns() % 1000000:06d}.png')


def keep_faces(source, textured):
    """The textured picture with the source picture's faces blended back in.

    A whole-picture RealVisXL pass, even at 0.25, recast a small Italian woman's face in a
    Z-Image group photo as East Asian (RealVisXL's own leaning, and the other people's
    heritages early in its prompt), while redrawing that face enlarged in face repair kept
    her. So the texture pass keeps the faces it was given; face repair adds their texture.
    Returns the picture and how many faces were kept."""
    from image_studio.services import repair
    from PIL import ImageDraw, ImageFilter

    if not repair.available():
        return textured, 0
    found = [item for item in repair.detect(source) if item['kind'] == 'face']
    if not found:
        return textured, 0
    scale = textured.width / source.width
    mask = Image.new('L', textured.size, 0)
    draw = ImageDraw.Draw(mask)
    sizes = []
    for item in found:
        x0, y0, x1, y1 = (value * scale for value in item['box'])
        size = max(x1 - x0, y1 - y0)
        sizes.append(size)
        grow = 0.1 * size
        draw.rounded_rectangle([x0 - grow, y0 - grow, x1 + grow, y1 + grow], radius=0.3 * size, fill=255)
    mask = mask.filter(ImageFilter.GaussianBlur(max(2.0, 0.06 * sorted(sizes)[len(sizes) // 2])))
    return Image.composite(source.resize(textured.size, Image.LANCZOS), textured, mask), len(found)


def texture_source(path):
    """What the saved settings say about the image RealVisXL added texture to."""
    path = Path(path)
    try:
        details = json.loads(path.with_suffix('.json').read_text(encoding='utf-8'))
    except (OSError, ValueError):
        details = {}
    return dict(
        image=path.name, model=details.get('model'), seed=details.get('seed'), steps=details.get('steps')
    )


def save(image, output, details, sampler):
    from PIL.PngImagePlugin import PngInfo

    info = PngInfo()
    info.add_text('parameters', png_parameters(details, sampler))
    image.save(output, pnginfo=info)
    output.with_suffix('.json').write_text(json.dumps(details, indent=2, allow_nan=False), encoding='utf-8')


def json_safe(value):
    """Schedulers can contain infinities; preserve them as strings in strict JSON."""
    if isinstance(value, float) and not math.isfinite(value):
        return str(value)
    if isinstance(value, dict):
        return {key: json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(item) for item in value]
    return value


class Cancelled(Exception):
    """Raised when a Stop request interrupts generation."""


def png_parameters(details, sampler):
    """Settings in the widely read 'parameters' PNG text format."""
    text = details['prompt']
    if details['negative_prompt']:
        text += f'\nNegative prompt: {details["negative_prompt"]}'
    return text + (
        f'\nSteps: {details["steps"]}, Sampler: {sampler}, CFG scale: {details["guidance"]}, '
        f'Seed: {details["seed"]}, Size: {details["base_width"]}x{details["base_height"]}, '
        f'Model: {details["model"].split("/")[-1]}'
        + (
            f', Hires resize: {details["width"]}x{details["height"]}, '
            f'Denoising strength: {details["detail_pass"]["strength"]}'
            if isinstance(details.get('detail_pass'), dict)
            else ''
        )
    )


# High-detail pass: enlarge the first image, then let the model redraw it lightly
# at the larger size. Up to DETAIL_MAX_PIXELS it runs in one pass; larger images
# (or a single pass that runs out of GPU memory) are redrawn as overlapping tiles,
# one after another, and blended back together.
DETAIL_SCALES = {'Off': None, '1.5× size': 1.5, '2× size': 2.0}
DETAIL_DEFAULT = '1.5× size'
DETAIL_MAX_PIXELS = 1536 * 1536
DETAIL_STRENGTH = 0.35
TILE = 1024
TILE_OVERLAP = 192

# Layout sketch: the first image starts from the sketch instead of noise. Strength is
# how much the model may redraw it; lower follows the sketch more closely.
LAYOUT_STRENGTH = 0.65


def detail_size(width, height, scale):
    return round(width * scale / 64) * 64, round(height * scale / 64) * 64


def tile_starts(length, tile=TILE, overlap=TILE_OVERLAP):
    """Evenly spread tile offsets that cover the length with at least `overlap` shared pixels."""
    if length <= tile:
        return [0]
    count = math.ceil((length - overlap) / (tile - overlap))
    step = (length - tile) / (count - 1)
    return [round(index * step) for index in range(count)]


def tile_weights(size, start, length, overlap=TILE_OVERLAP):
    """1 in the middle, ramping down across the overlap except at the image border."""
    import numpy as np

    weights = np.ones(size, dtype=np.float32)
    ramp = np.linspace(1 / overlap, 1, overlap, dtype=np.float32)
    if start > 0:
        weights[:overlap] = ramp
    if start + size < length:
        weights[-overlap:] = ramp[::-1]
    return weights


# Face and hand repair: how much of each enlarged face is redrawn (hands get a little more).
# 0.4 pulled faces toward one look; 0.3 fixes them while keeping who they are.
REPAIR_STRENGTH = 0.3

# Z-Image Turbo is distilled for 8 transformer passes (9 scheduler steps) without guidance.
ACCURATE_STEPS = 9
DEFAULT_STEPS = {'realistic': 30, 'accurate': ACCURATE_STEPS, 'turbo': 4}

# Instruction-based editing with FLUX.1 Kontext.
EDIT_STEPS = 24
EDIT_GUIDANCE = 2.5
EDIT_MAX_SIDE = 4096


def soft_mask(mask):
    """A painted or selected area grown slightly and feathered, so edits blend in."""
    from PIL import ImageFilter

    mask = mask.convert('L').point(lambda value: 255 if value > 0 else 0)
    edge = max(3, round(min(mask.size) / 128))
    return mask.filter(ImageFilter.MaxFilter(edge * 2 + 1)).filter(ImageFilter.GaussianBlur(edge))


def fit_area(width, height, area, multiple=16):
    """Same aspect ratio, about `area` pixels, sides divisible by `multiple`."""
    scale = math.sqrt(area / (width * height))
    return (
        max(multiple, round(width * scale / multiple) * multiple),
        max(multiple, round(height * scale / multiple) * multiple),
    )


def _gated_ff_forward(self, hidden_states):
    # The transformers version casts activations to the storage dtype of wo, which
    # would be float8 here; the layerwise-casting hook already computes in bfloat16.
    hidden_states = self.act(self.wi_0(hidden_states)) * self.wi_1(hidden_states)
    return self.wo(self.dropout(hidden_states))


def load_t5_fp8(folder, device='cpu'):
    """T5-XXL with float8 linear weights, computed in bfloat16 (see download_model.py).
    Loading with device='cuda' streams the weights from disk straight to the GPU."""
    import types
    import torch
    from accelerate import init_empty_weights
    from diffusers.hooks import apply_layerwise_casting
    from safetensors.torch import load_file
    from transformers import T5Config, T5EncoderModel

    with init_empty_weights():
        model = T5EncoderModel(T5Config.from_pretrained(folder / 'text_encoder_2'))
    model.load_state_dict(
        load_file(str(folder / 'text_encoder_2' / 'model-fp8.safetensors'), device=str(device)),
        strict=False,
        assign=True,
    )
    # Full-precision position table for installs converted before it was kept in bfloat16.
    bias = folder / 'text_encoder_2' / 'position-bias-bf16.safetensors'
    if bias.exists():
        model.load_state_dict(load_file(str(bias), device=str(device)), strict=False, assign=True)
    if any(
        param.dtype == torch.float8_e4m3fn
        for name, param in model.named_parameters()
        if 'relative_attention_bias' in name
    ):
        raise RuntimeError('The editing model text encoder needs a repair. Run Download editing model.bat.')
    if any(param.is_meta for param in model.parameters()):
        raise RuntimeError('The editing model text encoder is incomplete. Run Download editing model.bat.')
    for block in model.encoder.block:
        feed_forward = block.layer[-1].DenseReluDense
        feed_forward.forward = types.MethodType(_gated_ff_forward, feed_forward)
    apply_layerwise_casting(
        model,
        storage_dtype=torch.float8_e4m3fn,
        compute_dtype=torch.bfloat16,
        skip_modules_pattern=('norm', 'shared', 'embed_tokens', 'relative_attention_bias'),
    )
    return model.eval()


def scaled_fp8_linear():
    """The layer class is built on first use so that importing engine stays free of torch."""
    import torch

    class ScaledFP8Linear(torch.nn.Module):
        """A linear layer stored as float8 with one scale per output row (see
        convert_qwen_to_fp8 in download_model.py), expanded to bfloat16 when used."""

        def __init__(self, weight, scale):
            super().__init__()
            self.register_buffer('weight', weight)
            self.register_buffer('scale', scale)

        def forward(self, x):
            return torch.nn.functional.linear(x, self.weight.to(x.dtype) * self.scale.to(x.dtype))

    return ScaledFP8Linear


def load_qwen_fp8(folder, device='cuda'):
    """Z-Image's Qwen3-4B text encoder from its 8-bit file, loaded straight to `device`."""
    import torch
    from accelerate import init_empty_weights
    from safetensors.torch import load_file
    from transformers import Qwen3Config, Qwen3Model

    with init_empty_weights():
        model = Qwen3Model(Qwen3Config.from_pretrained(folder / 'text_encoder'))
    state = {
        key.removeprefix('model.'): tensor
        for key, tensor in load_file(
            str(folder / 'text_encoder' / 'model-fp8.safetensors'), device=str(device)
        ).items()
    }
    linear = scaled_fp8_linear()
    for name, module in list(model.named_modules()):
        for child_name, child in list(module.named_children()):
            if isinstance(child, torch.nn.Linear):
                key = f'{name}.{child_name}' if name else child_name
                setattr(module, child_name, linear(state.pop(f'{key}.weight'), state.pop(f'{key}.scale')))
    model.load_state_dict(state, strict=False, assign=True)
    if any(param.is_meta for param in model.parameters()):
        raise RuntimeError('The accurate model text encoder is incomplete. Run Download accurate model.bat.')
    return model.to(device).eval()


class ImageEngine:
    def __init__(self):
        self.pipe = None
        self.refiner = None
        self.offloaded = None
        self.model_key = None
        self.cancelled = threading.Event()
        self.edit_prompt_cache = None
        self.prompt_cache = {}
        self.lora = None  # the realism LoRA's folder while it is loaded into RealVisXL
        self.personal_lora = None  # the personal style LoRA's folder while it is loaded
        self.personal = 0.0  # its strength for the next RealVisXL image (set per request)

    def unload(self):
        import torch

        if self.pipe is not None:
            self.pipe.remove_all_hooks()
            self.pipe = None
        self.refiner = self.offloaded = self.edit_prompt_cache = self.lora = self.personal_lora = None
        self.prompt_cache = {}
        self.model_key = None
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()

    def load(self, model='realistic', status=print):
        from image_studio.services import assistant

        # The prompt assistant may be kept on the GPU between editor commands.
        assistant.release()
        if self.pipe is not None and self.model_key == model:
            return
        import torch
        from diffusers import (
            AutoPipelineForImage2Image,
            AutoPipelineForText2Image,
            DPMSolverMultistepScheduler,
            ZImageImg2ImgPipeline,
        )

        if not torch.cuda.is_available():
            raise RuntimeError(
                'The NVIDIA GPU is unavailable. Check the driver and CUDA-enabled PyTorch installation.'
            )
        entry = KONTEXT if model == 'kontext' else MODELS[model]
        if not (entry['folder'] / 'download-complete.json').exists():
            raise RuntimeError(
                'The editing model is not downloaded yet. Run Download editing model.bat first.'
                if model == 'kontext'
                else 'The accurate model is not downloaded yet. Run Download accurate model.bat first.'
                if model == 'accurate'
                else 'The model download is incomplete. Run Download model.bat first.'
            )
        self.unload()
        status('Loading the model into memory. The first image takes longer...')
        torch.set_num_threads(4)
        if model == 'kontext':
            pipeline = self.load_kontext()
            # The 6.9 GB transformer plus its activations overflow an 8 GB GPU, and
            # Windows then pages GPU memory through system RAM (minutes per step).
            # Stream it through the GPU one block at a time instead, prefetching the
            # next block on a side stream while the current one computes.
            pipeline.transformer.enable_group_offload(
                onload_device=torch.device('cuda'),
                offload_device=torch.device('cpu'),
                offload_type='block_level',
                num_blocks_per_group=1,
                use_stream=True,
                low_cpu_mem_usage=True,
            )
            pipeline.text_encoder.to('cuda')
            pipeline.vae.to('cuda')
            self.pipe = self.offloaded = pipeline
            self.model_key = model
            return
        if model == 'accurate':
            pipeline = self.load_zimage()
            # Shares the same weights; used for the detail pass and layout sketches. (from_pipe
            # would try to cast the quantized transformer, which GGUF weights do not allow.)
            self.refiner = ZImageImg2ImgPipeline(**pipeline.components)
            pipeline.vae.enable_tiling()
            self.pipe, self.model_key = pipeline, model
            self.use(pipeline)
            return
        pipeline = AutoPipelineForText2Image.from_pretrained(
            str(entry['folder']),
            torch_dtype=torch.float16,
            variant='fp16',
            use_safetensors=True,
            local_files_only=True,
        )
        if model == 'realistic':
            pipeline.scheduler = DPMSolverMultistepScheduler.from_config(
                pipeline.scheduler.config,
                algorithm_type='sde-dpmsolver++',
                solver_order=2,
                use_karras_sigmas=True,
            )
            # Shares the same weights; no extra memory.
            self.refiner = AutoPipelineForImage2Image.from_pipe(pipeline)
            if (REALISM_LORA / 'pytorch_lora_weights.safetensors').exists():
                # Loaded once (about 90 MB); each image sets its strength (see set_realism).
                pipeline.load_lora_weights(str(REALISM_LORA), adapter_name='realism')
                pipeline.disable_lora()
                self.lora = REALISM_LORA
            if (PERSONAL_LORA / 'pytorch_lora_weights.safetensors').exists():
                pipeline.load_lora_weights(str(PERSONAL_LORA), adapter_name='personal')
                pipeline.disable_lora()
                self.personal_lora = PERSONAL_LORA
        pipeline.vae.enable_tiling()
        self.pipe, self.model_key = pipeline, model
        self.use(pipeline)

    @staticmethod
    def load_kontext():
        import torch
        from diffusers import (
            AutoencoderKL,
            FlowMatchEulerDiscreteScheduler,
            FluxKontextPipeline,
            FluxTransformer2DModel,
            GGUFQuantizationConfig,
        )
        from transformers import CLIPTextModel, CLIPTokenizer, T5TokenizerFast

        folder = KONTEXT['folder']
        transformer = FluxTransformer2DModel.from_single_file(
            str(folder / KONTEXT['gguf_file']),
            config=str(folder),
            subfolder='transformer',
            quantization_config=GGUFQuantizationConfig(compute_dtype=torch.bfloat16),
            torch_dtype=torch.bfloat16,
        )
        return FluxKontextPipeline(
            scheduler=FlowMatchEulerDiscreteScheduler.from_pretrained(folder, subfolder='scheduler'),
            vae=AutoencoderKL.from_pretrained(folder, subfolder='vae', torch_dtype=torch.bfloat16),
            text_encoder=CLIPTextModel.from_pretrained(
                folder, subfolder='text_encoder', torch_dtype=torch.bfloat16
            ),
            tokenizer=CLIPTokenizer.from_pretrained(folder, subfolder='tokenizer'),
            # T5 is loaded only while an instruction is encoded; see encode_edit_prompt.
            text_encoder_2=None,
            tokenizer_2=T5TokenizerFast.from_pretrained(folder, subfolder='tokenizer_2'),
            transformer=transformer,
        )

    @staticmethod
    def load_zimage():
        import torch
        from diffusers import (
            AutoencoderKL,
            FlowMatchEulerDiscreteScheduler,
            GGUFQuantizationConfig,
            ZImagePipeline,
            ZImageTransformer2DModel,
        )
        from transformers import AutoTokenizer

        entry = MODELS['accurate']
        folder = entry['folder']
        transformer = ZImageTransformer2DModel.from_single_file(
            str(folder / entry['gguf_file']),
            config=str(folder),
            subfolder='transformer',
            quantization_config=GGUFQuantizationConfig(compute_dtype=torch.bfloat16),
            torch_dtype=torch.bfloat16,
        )
        return ZImagePipeline(
            scheduler=FlowMatchEulerDiscreteScheduler.from_pretrained(folder, subfolder='scheduler'),
            vae=AutoencoderKL.from_pretrained(folder, subfolder='vae', torch_dtype=torch.bfloat16),
            # Qwen3 is loaded only while a prompt is read; see encode_zimage_prompt.
            text_encoder=None,
            tokenizer=AutoTokenizer.from_pretrained(folder, subfolder='tokenizer'),
            transformer=transformer,
        )

    def encode_zimage_prompt(self, prompt, status):
        """Load the 8-bit Qwen3 encoder straight onto the GPU, read the prompt, and free
        it, so the GPU holds either the encoder or the transformer. Recent results are reused."""
        import torch

        if prompt in self.prompt_cache:
            return self.prompt_cache[prompt]
        status('Reading your prompt...')
        # Nothing else may sit on the GPU while the 4.4 GB encoder is there.
        self.offloaded.maybe_free_model_hooks()
        self.pipe.text_encoder = self.refiner.text_encoder = load_qwen_fp8(MODELS['accurate']['folder'])
        try:
            with torch.inference_mode():
                embeds, _ = self.pipe.encode_prompt(
                    prompt=prompt, device=torch.device('cuda'), do_classifier_free_guidance=False
                )
        finally:
            self.pipe.text_encoder = self.refiner.text_encoder = None
            gc.collect()
            torch.cuda.empty_cache()
        self.prompt_cache[prompt] = embeds
        while len(self.prompt_cache) > 6:
            self.prompt_cache.pop(next(iter(self.prompt_cache)))
        return embeds

    def repair_pass(
        self,
        image,
        scene,
        model,
        seed,
        steps,
        guidance,
        negative_prompt,
        strength,
        status,
        people=None,
        references=False,
    ):
        """Find faces and hands and redraw each one enlarged (see repair.py). Each face gets
        its own description (`people`, left to right, when they match the faces found) and
        seed, and with `references` (RealVisXL) its own reference face (see faces.py).
        Returns the picture and what was done, for the saved settings."""
        import torch
        from image_studio.services import repair
        from image_studio.services import variety

        if not repair.available():
            return image, 'skipped: run Download repair models.bat'
        items = repair.detect(image)
        if not items:
            return image, dict(strength=strength, items=[])
        hands = [item for item in items if item['kind'] == 'hand']
        found = repair.left_to_right([item for item in items if item['kind'] == 'face'])
        people = people if people and len(people) == len(found) else None
        faces = [
            dict(
                item,
                slot=index,
                person=variety.for_repair(people[index]) if people else variety.face_details(seed, index),
            )
            for index, item in enumerate(found)
        ]
        embeds = {}
        if references and model == 'realistic' and faces:
            from image_studio.services import faces as reference_faces

            if not reference_faces.available():
                references = 'skipped: run Download face variety model.bat and Build face pool.bat'
            else:
                status('Choosing a reference face for each person...')
                self.offloaded.maybe_free_model_hooks()
                heritages = [variety.heritage_of(person) for person in people] if people else None
                chosen = reference_faces.references(
                    image, [face['box'] for face in faces], seed, heritages, status
                )
                for index, (name, decision, embed) in enumerate(chosen):
                    if name is None:
                        faces[index]['reference'] = decision
                        continue
                    # A large face is redrawn too: otherwise a portrait keeps the model's usual face.
                    faces[index].update(reference=name, seen_as=decision, always=True)
                    embeds[index] = embed

        def check(pipe, step, timestep, callback_kwargs):
            if self.cancelled.is_set():
                raise Cancelled()
            return callback_kwargs

        def redraw(crop, item, index):
            if item['kind'] == 'face':
                text = f'{repair.PROMPTS["face"]}, {item["person"]}, {scene}'
                face = item['slot']
                amount = max(strength, reference_faces.STRENGTH) if face in embeds else strength
            else:
                text, face = f'{repair.PROMPTS["hand"]}, {scene}', None
                amount = min(strength + repair.HAND_EXTRA, 0.6)
            if model == 'accurate':
                # Image-to-image runs `strength` of the steps; keep at least 6 for the few-step model.
                settings = dict(
                    prompt_embeds=self.encode_zimage_prompt(text, status),
                    guidance_scale=0.0,
                    num_inference_steps=max(steps, math.ceil(6 / amount)),
                )
            else:
                settings = dict(
                    prompt=text,
                    negative_prompt=negative_prompt,
                    guidance_scale=guidance,
                    num_inference_steps=steps,
                )
                if face in embeds:
                    settings['ip_adapter_image_embeds'] = [embeds[face].to('cuda')]
            self.use(self.refiner)
            with torch.inference_mode():
                return self.refiner(
                    image=crop,
                    strength=amount,
                    callback_on_step_end=check,
                    # A different seed for every face and hand.
                    generator=torch.Generator(device='cpu').manual_seed(seed + 101 + index),
                    **settings,
                ).images[0]

        # Everything without a reference first: once the adapter is loaded, every redraw needs one.
        plain = hands + [face for face in faces if face['slot'] not in embeds]
        referenced = [face for face in faces if face['slot'] in embeds]
        total = len(plain) + len(referenced)
        adapter = False
        face_notes = []
        try:
            image, notes = repair.repair(image, plain, redraw, status, 0, total)
            if referenced:
                from image_studio.core.catalog import FACE_REFERENCE

                status('Loading the reference-face adapter...')
                self.refiner.load_ip_adapter(
                    str(FACE_REFERENCE['folder']),
                    subfolder='sdxl_models',
                    weight_name=FACE_REFERENCE['weights'].split('/')[-1],
                    image_encoder_folder=None,
                    local_files_only=True,
                )
                adapter = True
                self.refiner.set_ip_adapter_scale(reference_faces.SCALE)
                image, face_notes = repair.repair(image, referenced, redraw, status, len(plain), total)
        except torch.cuda.OutOfMemoryError:
            self.offloaded.maybe_free_model_hooks()
            gc.collect()
            torch.cuda.empty_cache()
            return image, 'skipped: the GPU ran out of memory'
        finally:
            # The text-to-image pipeline shares the UNet, which must not keep the adapter.
            if adapter:
                self.refiner.unload_ip_adapter()
        result = dict(strength=strength, items=notes + face_notes)
        if embeds:
            result['reference_scale'] = reference_faces.SCALE
            result['reference_strength'] = max(strength, reference_faces.STRENGTH)
        elif isinstance(references, str):
            result['references'] = references
        return image, result

    def encode_edit_prompt(self, prompt, status):
        """Load T5 straight onto the GPU, encode, and free it, so system RAM only
        has to hold the editing transformer. The last result is reused."""
        import torch

        if self.edit_prompt_cache and self.edit_prompt_cache[0] == prompt:
            return self.edit_prompt_cache[1]
        status('Reading your instruction...')
        # Nothing else may sit on the GPU while the 4.8 GB encoder is there.
        self.pipe.maybe_free_model_hooks()
        self.pipe.text_encoder_2 = load_t5_fp8(KONTEXT['folder'], device='cuda')
        try:
            with torch.inference_mode():
                prompt_embeds, pooled_embeds, _ = self.pipe.encode_prompt(
                    prompt=prompt, prompt_2=None, device=torch.device('cuda'), max_sequence_length=512
                )
        finally:
            self.pipe.text_encoder_2 = None
            gc.collect()
            torch.cuda.empty_cache()
        self.edit_prompt_cache = (prompt, (prompt_embeds, pooled_embeds))
        return prompt_embeds, pooled_embeds

    def set_realism(self, strength):
        """Realism LoRA strength for the next RealVisXL image (0 turns it off). The text-to-image
        and image-to-image pipelines share the UNet, so this sets both. The personal style LoRA,
        when trained, is mixed in at `self.personal`. Returns the realism strength used."""
        import torch

        if self.model_key != 'realistic' or (self.lora is None and self.personal_lora is None):
            return 0.0
        strength = strength if self.lora is not None else 0.0
        personal = self.personal if self.personal_lora is not None else 0.0
        names = [name for name, value in (('realism', strength), ('personal', personal)) if value > 0]
        # After a render, the offload hooks have made the LoRA weights inference tensors, which
        # may only be switched on and off inside inference mode.
        with torch.inference_mode():
            if names:
                self.pipe.enable_lora()
                self.pipe.set_adapters(names, [strength if name == 'realism' else personal for name in names])
                return strength
            self.pipe.disable_lora()
        return 0.0

    def use(self, pipeline):
        """Both pipelines share modules, so only one may hold the offload hooks."""
        if self.offloaded is not pipeline:
            pipeline.enable_model_cpu_offload()
            self.offloaded = pipeline

    @staticmethod
    def validate(
        prompt,
        seed,
        steps,
        model,
        size,
        guidance,
        negative_prompt,
        detail,
        detail_strength,
        layout=None,
        layout_strength=LAYOUT_STRENGTH,
    ):
        if model not in MODELS:
            raise ValueError('Choose Realistic, Accurate or Turbo.')
        prompt = prompt.strip()
        if not prompt:
            raise ValueError('Describe the image you want first.')
        if len(prompt) > 1000:
            raise ValueError('Please keep the description under 1,000 characters.')
        if size not in SIZES:
            raise ValueError('Choose one of the listed image formats.')
        if steps is None:
            steps = DEFAULT_STEPS[model]
        if model == 'realistic' and (not isinstance(steps, int) or not 20 <= steps <= 50):
            raise ValueError('Realistic mode uses 20 to 50 steps.')
        if model == 'accurate' and (not isinstance(steps, int) or not 6 <= steps <= 16):
            raise ValueError('Accurate mode uses 6 to 16 steps.')
        if model == 'turbo' and steps not in (1, 2, 3, 4):
            raise ValueError('Turbo mode uses 1 to 4 steps.')
        if not 1 <= guidance <= 9:
            raise ValueError('Prompt strength must be between 1 and 9.')
        if len(negative_prompt) > 1000:
            raise ValueError('Keep the negative prompt under 1,000 characters.')
        if detail not in DETAIL_SCALES:
            raise ValueError('Choose one of the listed detail options.')
        if not 0.1 <= detail_strength <= 0.6:
            raise ValueError('Detail strength must be between 0.1 and 0.6.')
        if layout is not None and model == 'turbo':
            raise ValueError(
                'Layout sketches work with Realistic and Accurate. Choose one of them or clear the sketch.'
            )
        if not 0.3 <= layout_strength <= 0.95:
            raise ValueError('Sketch freedom must be between 0.3 and 0.95.')
        seed = secrets.randbelow(2**31) if seed is None else int(seed)
        if not 0 <= seed < 2**32:
            raise ValueError('Seed must be between 0 and 4294967295.')
        width, height = SIZES[size] if model != 'turbo' else (512, 512)
        return prompt, seed, steps, width, height

    def refine_tiled(self, image, seed, settings, status, start_tile):
        """Redraw a large image as overlapping TILE-sized pieces and blend them."""
        import numpy as np
        import torch

        width, height = image.size
        xs, ys = tile_starts(width), tile_starts(height)
        total = len(xs) * len(ys)
        result = np.zeros((height, width, 3), dtype=np.float32)
        weight = np.zeros((height, width, 1), dtype=np.float32)
        for row, top in enumerate(ys):
            for col, left in enumerate(xs):
                index = row * len(xs) + col
                tile_w, tile_h = min(TILE, width), min(TILE, height)
                start_tile(index, total)
                status(f'Adding fine detail: part {index + 1} of {total}...')
                tile = image.crop((left, top, left + tile_w, top + tile_h))
                tile = self.refiner(
                    image=tile, generator=torch.Generator(device='cpu').manual_seed(seed + index), **settings
                ).images[0]
                mask = np.outer(tile_weights(tile_h, top, height), tile_weights(tile_w, left, width))[
                    ..., None
                ]
                result[top : top + tile_h, left : left + tile_w] += np.asarray(tile, dtype=np.float32) * mask
                weight[top : top + tile_h, left : left + tile_w] += mask
        return Image.fromarray(np.clip(result / weight + 0.5, 0, 255).astype(np.uint8)), total

    def generate(
        self,
        prompt,
        seed=None,
        steps=None,
        status=print,
        *,
        model='realistic',
        size='Square · 1024 × 1024',
        guidance=5.0,
        negative_prompt=DEFAULT_NEGATIVE,
        detail=DETAIL_DEFAULT,
        detail_strength=DETAIL_STRENGTH,
        on_step=None,
        request=None,
        layout=None,
        layout_strength=LAYOUT_STRENGTH,
        repair=False,
        repair_strength=REPAIR_STRENGTH,
        style='Polished',
        finish='Off',
        people=None,
        scene=None,
        references=False,
        source=None,
        folder=None,
        realism=0.0,
    ):
        """Make and save one image. `style` and `finish` are style.py and finish.py options;
        `people` and `scene` describe each person and the picture for face repair, and
        `references` gives each face a reference face. With `source` (an Accurate image's
        path), RealVisXL redraws that image lightly for real-photo texture instead of
        starting from noise ("Finish with RealVisXL")."""
        from image_studio.services import finish as photo_finish
        from image_studio.services import style as photo_style

        prompt, seed, steps, width, height = self.validate(
            prompt,
            seed,
            steps,
            model,
            size,
            guidance,
            negative_prompt,
            detail,
            detail_strength,
            layout,
            layout_strength,
        )
        if style not in photo_style.STYLES:
            raise ValueError('Choose one of the listed photo styles.')
        if finish not in photo_finish.FINISHES:
            raise ValueError('Choose one of the listed photo finishes.')
        if source is not None and model != 'realistic':
            raise ValueError('Only RealVisXL can add texture to another image.')
        source_image = Image.open(source).convert('RGB') if source is not None else None
        if source_image is not None:
            width, height = source_image.size
        model_prompt = photo_style.apply(prompt, model, style)
        negative_prompt = (
            photo_style.negative(negative_prompt, style) if model != 'accurate' else negative_prompt
        )
        # Image-to-image from a sketch runs only the last `layout_strength` share of the steps.
        first_steps = (
            0
            if source_image is not None
            else min(int(steps * layout_strength), steps)
            if layout is not None
            else steps
        )
        scale = DETAIL_SCALES[detail] if model != 'turbo' else None
        if source_image is not None:
            # The texture pass is the detail pass, at the same size when the detail pass is off.
            scale = scale or 1.0
        target = detail_size(width, height, scale) if scale else None
        tiled = bool(target) and target[0] * target[1] > DETAIL_MAX_PIXELS
        detail_steps = min(int(steps * detail_strength), steps) if scale else 0

        def pieces():
            return len(tile_starts(target[0])) * len(tile_starts(target[1])) if tiled else 1

        import torch

        total_started = time.perf_counter()
        if self.cancelled.is_set():
            raise Cancelled()
        self.load(model, status)
        realism = self.set_realism(realism)
        torch.cuda.reset_peak_memory_stats()
        started = time.perf_counter()
        # `done` counts finished steps; the total grows if a single pass falls back to tiles.
        state = dict(done=0, total=first_steps + detail_steps * pieces(), floor=0)

        def progress(pipe, step, timestep, callback_kwargs):
            if self.cancelled.is_set():
                raise Cancelled()
            state['done'] = min(max(state['done'] + 1, state['floor']), state['total'])
            phase = (
                'Adding real-photo texture'
                if source_image is not None
                else 'Adding fine detail'
                if state['done'] > first_steps
                else 'Creating your image'
            )
            status(f'{phase}: step {state["done"]} of {state["total"]}...')
            if on_step:
                on_step(state['done'], state['total'])
            return callback_kwargs

        def start_tile(index, total):
            state['done'] = state['floor'] = first_steps + index * detail_steps
            state['total'] = first_steps + total * detail_steps

        common = dict(
            prompt=model_prompt,
            num_inference_steps=steps,
            guidance_scale=guidance if model == 'realistic' else 0.0,
            negative_prompt=negative_prompt if model == 'realistic' else None,
            callback_on_step_end=progress,
        )
        failed_memory, detail_note, tiles, repair_note, kept_faces = False, None, 0, None, 0
        try:
            if model == 'accurate':
                # Distilled without guidance, so no negative prompt.
                common = dict(
                    prompt_embeds=self.encode_zimage_prompt(model_prompt, status),
                    num_inference_steps=steps,
                    guidance_scale=0.0,
                    callback_on_step_end=progress,
                )
            with torch.inference_mode():
                if source_image is not None:
                    image = source_image
                elif layout is None:
                    self.use(self.pipe)
                    image = self.pipe(
                        width=width,
                        height=height,
                        generator=torch.Generator(device='cpu').manual_seed(seed),
                        **common,
                    ).images[0]
                else:
                    self.use(self.refiner)
                    image = self.refiner(
                        image=layout.convert('RGB').resize((width, height), Image.LANCZOS),
                        strength=layout_strength,
                        generator=torch.Generator(device='cpu').manual_seed(seed),
                        **common,
                    ).images[0]
                if scale:
                    base_image, enlarged = image, image.resize(target, Image.LANCZOS)
                    self.use(self.refiner)
                    settings = dict(common, strength=detail_strength)
                    if not tiled:
                        status(
                            f'{"Adding real-photo texture" if source_image is not None else "Adding fine detail"} '
                            f'at {target[0]} × {target[1]}...'
                        )
                        try:
                            image = self.refiner(
                                image=enlarged,
                                generator=torch.Generator(device='cpu').manual_seed(seed),
                                **settings,
                            ).images[0]
                            tiles = 1
                        except torch.cuda.OutOfMemoryError:
                            tiled = True
                        if tiled:
                            # Too big for one pass on this GPU: redo it in tiles.
                            self.refiner.maybe_free_model_hooks()
                            gc.collect()
                            torch.cuda.empty_cache()
                    if tiled:
                        try:
                            image, tiles = self.refine_tiled(enlarged, seed, settings, status, start_tile)
                        except torch.cuda.OutOfMemoryError:
                            detail_note = 'skipped: the GPU ran out of memory'
                        if detail_note:
                            # Keep the finished first image rather than losing the render.
                            image = base_image
                            self.refiner.maybe_free_model_hooks()
                            gc.collect()
                            torch.cuda.empty_cache()
            if source_image is not None:
                image, kept_faces = keep_faces(source_image, image)
            if repair and model != 'turbo':
                image, repair_note = self.repair_pass(
                    image,
                    scene or prompt,
                    model,
                    seed,
                    steps,
                    guidance,
                    negative_prompt,
                    repair_strength,
                    status,
                    people,
                    references,
                )
            image = photo_finish.finish(image, finish, seed)
        except torch.cuda.OutOfMemoryError:
            failed_memory = True
        except Cancelled:
            # Move every component back to RAM so the next image starts clean.
            self.offloaded.maybe_free_model_hooks()
            status('Stopped.')
            raise
        # Leave the exception handler before freeing tensors held by its traceback.
        if failed_memory:
            self.unload()
            raise RuntimeError(
                'The GPU ran out of memory. Close other GPU apps or choose Smaller (768 × 768), then retry.'
            )
        torch.cuda.synchronize()
        elapsed = round(time.perf_counter() - started, 2)
        output = new_output(seed, folder)
        manifest = json.loads((MODELS[model]['folder'] / 'download-complete.json').read_text())
        details = dict(
            prompt=prompt,
            request=request or prompt,
            seed=seed,
            steps=steps,
            width=image.width,
            height=image.height,
            style=style,
            finish=finish,
            **(
                dict(realism_lora=dict(strength=realism, weights=str(self.lora.relative_to(WORK))))
                if realism
                else {}
            ),
            **(
                dict(personal_lora=dict(strength=self.personal))
                if self.personal_lora is not None and self.personal > 0 and self.model_key == 'realistic'
                else {}
            ),
            **(dict(model_prompt=model_prompt) if model_prompt != prompt else {}),
            **(
                dict(texture_from=dict(texture_source(source), faces_kept=kept_faces))
                if source is not None
                else {}
            ),
            base_width=width,
            base_height=height,
            detail_pass=(
                detail_note or dict(option=detail, strength=detail_strength, steps=detail_steps, tiles=tiles)
            )
            if scale
            else None,
            layout=dict(strength=layout_strength) if layout is not None else None,
            repair=repair_note,
            model=MODELS[model]['repo'],
            revision=manifest.get('revision'),
            seconds=elapsed,
            total_seconds=round(time.perf_counter() - total_started, 2),
            guidance=guidance if model == 'realistic' else 0.0,
            negative_prompt=negative_prompt if model == 'realistic' else '',
            **(dict(weights=MODELS[model]['gguf_file']) if model == 'accurate' else {}),
            scheduler=type(self.pipe.scheduler).__name__,
            scheduler_config=json_safe(dict(self.pipe.scheduler.config)),
            peak_allocated_gib=round(torch.cuda.max_memory_allocated() / 2**30, 2),
            peak_reserved_gib=round(torch.cuda.max_memory_reserved() / 2**30, 2),
        )
        save(image, output, details, 'DPM++ 2M SDE Karras' if model == 'realistic' else details['scheduler'])
        status(
            f'Done in {elapsed}s. Saved to images. Seed: {seed}'
            + (f'. Detail pass {detail_note}.' if detail_note else '')
        )
        return output, details

    def edit(
        self,
        image,
        prompt,
        seed=None,
        steps=EDIT_STEPS,
        guidance=EDIT_GUIDANCE,
        *,
        mask=None,
        quality=next(iter(EDIT_QUALITY)),
        status=print,
        on_step=None,
        request=None,
    ):
        """Change a photo by instruction. With a mask, only the painted area changes."""
        if image is None:
            raise ValueError('Add a photo first.')
        prompt = prompt.strip()
        if not prompt:
            raise ValueError('Describe the change you want.')
        if len(prompt) > 1000:
            raise ValueError('Please keep the instruction under 1,000 characters.')
        if not isinstance(steps, int) or not 10 <= steps <= 50:
            raise ValueError('Editing uses 10 to 50 steps.')
        if not 1 <= guidance <= 6:
            raise ValueError('Instruction strength must be between 1 and 6.')
        if quality not in EDIT_QUALITY:
            raise ValueError('Choose one of the listed quality options.')
        seed = secrets.randbelow(2**31) if seed is None else int(seed)
        if not 0 <= seed < 2**32:
            raise ValueError('Seed must be between 0 and 4294967295.')
        image = image.convert('RGB')
        if max(image.size) > EDIT_MAX_SIDE:
            image.thumbnail((EDIT_MAX_SIDE, EDIT_MAX_SIDE), Image.LANCZOS)
        if mask is not None:
            mask = mask.convert('L').resize(image.size, Image.NEAREST)
            mask = mask.point(lambda value: 255 if value > 0 else 0)
            if mask.getbbox() is None:
                mask = None
        width, height = fit_area(*image.size, EDIT_QUALITY[quality])
        import torch

        total_started = time.perf_counter()
        if self.cancelled.is_set():
            raise Cancelled()
        self.load('kontext', status)
        torch.cuda.reset_peak_memory_stats()
        started = time.perf_counter()

        def progress(pipe, step, timestep, callback_kwargs):
            if self.cancelled.is_set():
                raise Cancelled()
            status(f'Editing your photo: step {step + 1} of {steps}...')
            if on_step:
                on_step(step + 1, steps)
            return callback_kwargs

        failed_memory = False
        try:
            prompt_embeds, pooled_embeds = self.encode_edit_prompt(prompt, status)
            if self.cancelled.is_set():
                raise Cancelled()
            with torch.inference_mode():
                result = self.pipe(
                    image=image.resize((width, height), Image.LANCZOS),
                    prompt_embeds=prompt_embeds,
                    pooled_prompt_embeds=pooled_embeds,
                    width=width,
                    height=height,
                    _auto_resize=False,
                    max_area=width * height,
                    guidance_scale=guidance,
                    num_inference_steps=steps,
                    generator=torch.Generator(device='cpu').manual_seed(seed),
                    callback_on_step_end=progress,
                ).images[0]
        except torch.cuda.OutOfMemoryError:
            failed_memory = True
        except Cancelled:
            self.pipe.maybe_free_model_hooks()
            status('Stopped.')
            raise
        if failed_memory:
            self.unload()
            raise RuntimeError(
                'The GPU ran out of memory. Close other GPU apps or choose Faster, then retry.'
            )
        torch.cuda.synchronize()
        if mask is not None:
            # Keep everything outside the painted area exactly as it was, with a soft edge.
            result = Image.composite(result.resize(image.size, Image.LANCZOS), image, soft_mask(mask))
        elapsed = round(time.perf_counter() - started, 2)
        output = new_output(seed)
        manifest = json.loads((KONTEXT['folder'] / 'download-complete.json').read_text())
        details = dict(
            prompt=prompt,
            request=request or prompt,
            seed=seed,
            steps=steps,
            width=result.width,
            height=result.height,
            base_width=width,
            base_height=height,
            mode='edit',
            painted_area=mask is not None,
            source_width=image.width,
            source_height=image.height,
            quality=quality,
            detail_pass=None,
            model=KONTEXT['repo'],
            weights=KONTEXT['gguf_file'],
            revision=manifest.get('revision'),
            seconds=elapsed,
            total_seconds=round(time.perf_counter() - total_started, 2),
            guidance=guidance,
            negative_prompt='',
            scheduler=type(self.pipe.scheduler).__name__,
            peak_allocated_gib=round(torch.cuda.max_memory_allocated() / 2**30, 2),
            peak_reserved_gib=round(torch.cuda.max_memory_reserved() / 2**30, 2),
        )
        save(result, output, details, 'Euler')
        status(f'Done in {elapsed}s. Saved to images. Seed: {seed}')
        return output, details


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Generate an image locally from a text prompt.')
    parser.add_argument('prompt')
    parser.add_argument('--seed', type=int)
    parser.add_argument('--steps', type=int)
    parser.add_argument('--model', choices=MODELS, default='realistic')
    parser.add_argument('--size', choices=SIZES, default='Square · 1024 × 1024')
    parser.add_argument('--guidance', type=float, default=5.0)
    parser.add_argument('--negative-prompt', default=DEFAULT_NEGATIVE)
    parser.add_argument(
        '--detail',
        choices=DETAIL_SCALES,
        default=DETAIL_DEFAULT,
        help='High-detail second pass (Realistic only).',
    )
    parser.add_argument('--detail-strength', type=float, default=DETAIL_STRENGTH)
    parser.add_argument('--layout', help='Layout sketch image to start from (Realistic only).')
    parser.add_argument('--layout-strength', type=float, default=LAYOUT_STRENGTH)
    parser.add_argument('--repair', action='store_true', help='Redraw faces and hands enlarged.')
    parser.add_argument('--repair-strength', type=float, default=REPAIR_STRENGTH)
    parser.add_argument(
        '--references',
        action='store_true',
        help='A different reference face for each face during repair (Realistic; see faces.py).',
    )
    parser.add_argument('--style', choices=['Natural photo', 'Polished'], default='Natural photo')
    parser.add_argument('--finish', choices=['Off', 'Light', 'Film'], default='Light')
    parser.add_argument('--source', help='Add RealVisXL texture to this image (an Accurate result).')
    parser.add_argument('--realism', type=float, default=0.0, help='Realism LoRA strength (RealVisXL).')
    args = parser.parse_args()
    result, metadata = ImageEngine().generate(
        args.prompt,
        args.seed,
        args.steps,
        model=args.model,
        size=args.size,
        guidance=args.guidance,
        negative_prompt=args.negative_prompt,
        detail=args.detail,
        detail_strength=args.detail_strength,
        layout=Image.open(args.layout) if args.layout else None,
        layout_strength=args.layout_strength,
        repair=args.repair,
        repair_strength=args.repair_strength,
        references=args.references,
        style=args.style,
        finish=args.finish,
        source=args.source,
        realism=args.realism,
    )
    print(result)
