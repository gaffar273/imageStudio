"""Train the realism LoRA for RealVisXL on an 8 GB GPU.

1. Cache: every photo is encoded once by the VAE (also mirrored) at its own size (up to
   1024 x 1024, sides divisible by 64, centre-cropped), and every caption once by both
   text encoders. Then the encoders are freed, so training holds only the UNet.
2. Train: a rank-16 LoRA on the UNet's attention layers, UNet weights in bfloat16 with
   gradient checkpointing, LoRA weights and AdamW in float32, min-SNR (gamma 5) loss
   weighting, a small noise offset, and 10% empty captions. SDXL is told each photo's
   real size and crop (its size conditioning), so 1024-pixel photos do not teach it to
   draw small or soft pictures.

Usage (from the app folder, with the image generator stopped):
  python training/lora\\train_lora.py --steps 1600
Checkpoints go to ../../work/realism-lora/step-XXXX; the last one also to ../../work/realism-lora/final.
"""

import argparse
import gc
import json
import math
import random
import sys
import time
from pathlib import Path

import torch
from PIL import Image, ImageOps

APP = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(APP / 'backend'))
WORK = APP.parent.parent / 'work'
DATA = WORK / 'lora-data'
IMAGES = DATA / 'images'
CACHE = DATA / 'cache'
OUT = WORK / 'realism-lora'
DATA_NOTE = 'Open Images validation (CC BY 2.0), see credits.csv'
MAX_AREA = 1024 * 1024


def use_folders(data, out, note):
    """Train from other photos into another folder (the personal style LoRA uses this)."""
    global DATA, IMAGES, CACHE, OUT, DATA_NOTE
    DATA, OUT, DATA_NOTE = Path(data), Path(out), note
    IMAGES, CACHE = DATA / 'images', DATA / 'cache'


def bucket(width, height):
    """Training size for a photo: no enlarging, at most MAX_AREA, sides divisible by 64."""
    scale = min(1.0, math.sqrt(MAX_AREA / (width * height)))
    return max(64, int(width * scale) // 64 * 64), max(64, int(height * scale) // 64 * 64), scale


def build_cache():
    """Latents and text embeddings for every photo, saved to CACHE."""
    from diffusers import StableDiffusionXLPipeline
    from image_studio.core.catalog import MODELS

    CACHE.mkdir(parents=True, exist_ok=True)
    photos = [path for path in sorted(IMAGES.glob('*.jpg')) if path.with_suffix('.txt').exists()]
    todo = [path for path in photos if not (CACHE / f'{path.stem}.pt').exists()]
    print(f'{len(photos)} captioned photos, {len(todo)} to cache', flush=True)
    if todo or not (CACHE / 'empty.pt').exists():
        pipe = StableDiffusionXLPipeline.from_pretrained(
            str(MODELS['realistic']['folder']),
            torch_dtype=torch.float16,
            variant='fp16',
            use_safetensors=True,
            local_files_only=True,
            unet=None,
        )
        pipe.text_encoder.to('cuda')
        pipe.text_encoder_2.to('cuda')
        # The SDXL VAE overflows in float16; encode in float32.
        vae = pipe.vae.to('cuda', torch.float32)

        def encode_text(text):
            with torch.inference_mode():
                embeds, _, pooled, _ = pipe.encode_prompt(
                    text, device=torch.device('cuda'), do_classifier_free_guidance=False
                )
            return embeds[0].cpu(), pooled[0].cpu()

        embeds, pooled = encode_text('')
        torch.save(dict(embeds=embeds, pooled=pooled), CACHE / 'empty.pt')
        for index, path in enumerate(todo):
            image = ImageOps.exif_transpose(Image.open(path)).convert('RGB')
            width, height, scale = bucket(*image.size)
            resized = image.resize((round(image.width * scale), round(image.height * scale)), Image.LANCZOS)
            left, top = (resized.width - width) // 2, (resized.height - height) // 2
            crop = resized.crop((left, top, left + width, top + height))
            latents = []
            for picture in (crop, ImageOps.mirror(crop)):
                pixels = torch.from_numpy(__import__('numpy').asarray(picture, dtype='float32') / 127.5 - 1)
                pixels = pixels.permute(2, 0, 1)[None].to('cuda')
                with torch.inference_mode():
                    latent = vae.encode(pixels).latent_dist.sample() * vae.config.scaling_factor
                latents.append(latent[0].to(torch.float16).cpu())
            embeds, pooled = encode_text(path.with_suffix('.txt').read_text(encoding='utf-8'))
            torch.save(
                dict(
                    latents=latents,
                    embeds=embeds,
                    pooled=pooled,
                    # SDXL size conditioning: (height, width) before cropping, crop corner, target.
                    original=(resized.height, resized.width),
                    crop=(top, left),
                    target=(height, width),
                ),
                CACHE / f'{path.stem}.pt',
            )
            if index % 100 == 0:
                print(f'cached {index + 1}/{len(todo)}: {width} x {height}', flush=True)
        del pipe, vae
        gc.collect()
        torch.cuda.empty_cache()
    return [CACHE / f'{path.stem}.pt' for path in photos]


def train(items, steps, rank, learning_rate, save_every, seed):
    from diffusers import DDPMScheduler, StableDiffusionXLPipeline, UNet2DConditionModel
    from diffusers.utils import convert_state_dict_to_diffusers
    from peft import LoraConfig
    from peft.utils import get_peft_model_state_dict
    from image_studio.core.catalog import MODELS

    folder = str(MODELS['realistic']['folder'])
    random.seed(seed)
    torch.manual_seed(seed)
    unet = UNet2DConditionModel.from_pretrained(
        folder,
        subfolder='unet',
        variant='fp16',
        torch_dtype=torch.bfloat16,
        use_safetensors=True,
        local_files_only=True,
    )
    unet.requires_grad_(False)
    unet.add_adapter(
        LoraConfig(
            r=rank,
            lora_alpha=rank,
            init_lora_weights='gaussian',
            target_modules=['to_k', 'to_q', 'to_v', 'to_out.0'],
        )
    )
    trainable = [param for param in unet.parameters() if param.requires_grad]
    for param in trainable:
        param.data = param.data.float()
    unet.enable_gradient_checkpointing()
    unet.to('cuda')
    unet.train()
    print(f'LoRA parameters: {sum(param.numel() for param in trainable) / 1e6:.1f} M', flush=True)
    scheduler = DDPMScheduler.from_pretrained(folder, subfolder='scheduler')
    alphas = scheduler.alphas_cumprod.to('cuda')
    snr = alphas / (1 - alphas)
    optimizer = torch.optim.AdamW(trainable, lr=learning_rate, weight_decay=1e-2)
    warmup = min(100, steps // 10)
    lr_lambda = lambda step: (
        min(1.0, (step + 1) / warmup) * 0.5 * (1 + math.cos(math.pi * min(step, steps) / steps))
    )
    schedule = torch.optim.lr_scheduler.LambdaLR(optimizer, lr_lambda)
    empty = torch.load(CACHE / 'empty.pt')
    order, losses, started = [], [], time.time()
    OUT.mkdir(parents=True, exist_ok=True)

    def save(name):
        state = convert_state_dict_to_diffusers(get_peft_model_state_dict(unet))
        StableDiffusionXLPipeline.save_lora_weights(str(OUT / name), unet_lora_layers=state)
        (OUT / name / 'training.json').write_text(
            json.dumps(
                dict(
                    base=MODELS['realistic']['repo'],
                    photos=len(items),
                    step=step + 1,
                    steps=steps,
                    rank=rank,
                    learning_rate=learning_rate,
                    seed=seed,
                    data=DATA_NOTE,
                ),
                indent=2,
            ),
            encoding='utf-8',
        )

    for step in range(steps):
        if not order:
            order = list(items)
            random.shuffle(order)
        item = torch.load(order.pop())
        latents = random.choice(item['latents'])[None].to('cuda', torch.float32)
        text = empty if random.random() < 0.1 else item
        embeds = text['embeds'][None].to('cuda', torch.bfloat16)
        pooled = text['pooled'][None].to('cuda', torch.bfloat16)
        time_ids = torch.tensor(
            [[*item['original'], *item['crop'], *item['target']]], device='cuda', dtype=torch.bfloat16
        )
        noise = torch.randn_like(latents) + 0.0357 * torch.randn(1, latents.shape[1], 1, 1, device='cuda')
        timesteps = torch.randint(0, scheduler.config.num_train_timesteps, (1,), device='cuda')
        noisy = scheduler.add_noise(latents, noise, timesteps)
        with torch.autocast('cuda', dtype=torch.bfloat16):
            prediction = unet(
                noisy.to(torch.bfloat16),
                timesteps,
                encoder_hidden_states=embeds,
                added_cond_kwargs=dict(text_embeds=pooled, time_ids=time_ids),
            ).sample
        loss = torch.nn.functional.mse_loss(prediction.float(), noise, reduction='none').mean()
        # Min-SNR weighting (epsilon prediction): fewer wasted steps on nearly clean timesteps.
        weight = torch.clamp(snr[timesteps], max=5.0) / snr[timesteps]
        (loss * weight).mean().backward()
        torch.nn.utils.clip_grad_norm_(trainable, 1.0)
        optimizer.step()
        schedule.step()
        optimizer.zero_grad(set_to_none=True)
        losses.append(loss.item())
        if (step + 1) % 25 == 0:
            rate = (time.time() - started) / (step + 1)
            print(
                f'step {step + 1}/{steps} loss {sum(losses[-25:]) / 25:.4f} lr {schedule.get_last_lr()[0]:.2e} '
                f'{rate:.2f} s/step, {rate * (steps - step - 1) / 60:.0f} min left, '
                f'peak {torch.cuda.max_memory_allocated() / 2**30:.2f} GiB',
                flush=True,
            )
        if (step + 1) % save_every == 0 and step + 1 < steps:
            save(f'step-{step + 1:04d}')
    save('final')
    print(f'Done in {(time.time() - started) / 60:.0f} min. Saved to {OUT / "final"}', flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--steps', type=int, default=1600)
    parser.add_argument('--rank', type=int, default=16)
    parser.add_argument('--lr', type=float, default=1e-4)
    parser.add_argument('--save-every', type=int, default=400)
    parser.add_argument('--seed', type=int, default=7)
    parser.add_argument('--cache-only', action='store_true')
    parser.add_argument('--data', help='folder with images/ (photos and .txt captions); default lora-data')
    parser.add_argument('--out', help='folder for the checkpoints; default realism-lora')
    args = parser.parse_args()
    if args.data or args.out:
        use_folders(args.data or DATA, args.out or OUT, f'Photos in {args.data or DATA}')
    items = build_cache()
    if not args.cache_only:
        train(items, args.steps, args.rank, args.lr, args.save_every, args.seed)


if __name__ == '__main__':
    main()
