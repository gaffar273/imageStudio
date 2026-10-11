# A better editing model: research (October 2026)

The current editing model, FLUX.1 Kontext [dev] (4-bit GGUF), works on this laptop (RTX 4060,
8 GB; 16 GB RAM) but takes about 5 minutes per edit, and its license allows **non-commercial use
only**. That conflicts with an open-source studio that anyone may use for anything.

## Candidates

| Model | License | Size | Fits 8 GB / 16 GB RAM? | Notes |
| --- | --- | --- | --- | --- |
| **FLUX.2 [klein] 4B** | **Apache 2.0** | 4B | Model card says ~13 GB VRAM; the distilled version is reported near 8.4 GB. With 4-bit GGUF and CPU offload (as Kontext is run now) it should fit, **untested** | Text-to-image and multi-reference editing in one model; distilled version needs only 4 steps. Ranked below Kontext-class models on detail and text. `Flux2KleinPipeline` is in the installed diffusers 0.37.1 |
| Qwen-Image-Edit-2511 | **Apache 2.0** | 20B | Only at Q2/Q3 quantization on 8 GB (reported "usable but softer"); 20B weights strain 16 GB RAM | Strong editor. `QwenImageEditPlusPipeline` is in diffusers 0.37.1 |
| FLUX.2 [klein] 9B | Non-commercial | 9B | No | Better than 4B, same license problem as Kontext |
| Qwen-Image-2.1 | Qwen Research License (non-commercial) | 7B + 8B encoder | No (about 16 GB at INT8) | Top open-weights editor on Artificial Analysis, but not open for commercial use |
| HunyuanImage 3.0 Instruct | Tencent Community License | very large | No (about 24 GB offloaded) | Strong, too large |
| Boogu-Image-0.1-Edit | Apache 2.0 | — | Reported 12–80 GB | Too large |

## Recommendation

1. **Try FLUX.2 [klein] 4B (distilled) first**, as a second editing engine beside Kontext:
   Apache 2.0, small, few steps, and already supported by the installed diffusers. Measure on
   this laptop: peak GPU memory, seconds per edit, and the same edit requests used for Kontext
   (remove an object, change the weather, recolor clothing, keep a face unchanged).
2. If its quality is close enough, make it the default and keep Kontext as an optional
   "high quality, non-commercial" download. An open-source release then ships with an Apache
   2.0 editor by default.
3. Qwen-Image-Edit-2511 is the Apache 2.0 fallback for machines with more memory (16 GB GPU or
   more), not for 8 GB laptops.

Leaderboards and VRAM figures here come from secondary sources and change quickly; verify on
each model card before downloading, and check the license of any third-party GGUF conversion.

## Sources

- FLUX.2 [klein] 4B model card (Apache 2.0, ~13 GB, `Flux2KleinPipeline`): https://huggingface.co/black-forest-labs/FLUX.2-klein-4B
- FLUX.2 [klein] 4B GGUF: https://huggingface.co/unsloth/FLUX.2-klein-4B-GGUF
- ComfyUI on klein 4B/9B editing: https://blog.comfy.org/p/flux2-klein-4b-fast-local-image-editing
- Klein 4B near 8 GB: https://hackernoon.com/the-8gb-vram-image-model-that-feels-instant-meet-flux2-klein-4b
- Qwen-Image-Edit-2511 model card (Apache 2.0, 20B): https://huggingface.co/Qwen/Qwen-Image-Edit-2511
- Qwen Image Edit on low VRAM: https://aistudynow.com/comfyui-qwen-image-edit-low-vram-workflow-gguf-vs-fp8/
- Open-weights editing leaderboard: https://artificialanalysis.ai/image/leaderboard/editing/open-weights
- Qwen-Image-2.1 license: https://www.eesel.ai/blog/qwen-image-2-1
- Kontext vs klein 9B arena: https://lumenfall.ai/arena/compare/flux.1-kontext-pro/flux.2-klein-9b
