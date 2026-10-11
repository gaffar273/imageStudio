# Local Image Studio

Generate realistic people and large scenes from text on this laptop's RTX 4060.
The app has three pretrained text-to-image models:

| Mode | Use | Defaults |
| --- | --- | --- |
| Realistic — people and scenes | Portraits, photographs, architecture, landscapes | RealVisXL 5.0, 30 steps, prompt strength 5 |
| Accurate — follows detailed prompts | Exact counts, colors, positions, written text | Z-Image Turbo, 9 steps |
| Turbo — quick drafts | Fast ideas and simple images | SDXL-Turbo, 4 steps, 512 × 512 |

## Open and use

Double-click **Start image generator.bat**. The browser opens
http://127.0.0.1:7860. The server listens only on this laptop.

1. Choose **Realistic — people and scenes**.
2. Describe the subject, setting, lighting, and composition.
3. Select an image format, a **High-detail pass** option, and how many images
   (1–4, made one after another), then click **Generate image**.
4. Download from the image's download button, or find the automatically saved PNG
   in the `images` folder beside this file (**Open images folder** opens it).

**Stop** ends the current render after the current step, including a batch. Click
any picture under **Recent images** to see its settings, then **Use these
settings** to load them again. Settings are also written into each PNG (the
common `parameters` text field), so other image tools can read them.

## Accurate mode (Z-Image Turbo)

RealVisXL and Turbo are SDXL models: they read prompts with CLIP text encoders,
which often miscount objects and attach colors to the wrong object. **Accurate**
uses Z-Image Turbo (Tongyi-MAI, Alibaba; Apache 2.0), which reads the prompt with
the Qwen3-4B language model. Write full sentences; it follows counts, colors,
positions and short written text much more closely. Prompt strength and Things to
avoid do not apply (it is distilled to work without guidance), and Layout sketch,
the high-detail pass, Smart prompt and Vary faces all work with it.

It was chosen after comparing the open-weights models that fit this laptop, using
the Artificial Analysis text-to-image arena (blind human votes, October 2026):

| Model | Arena Elo | License | Why / why not |
| --- | --- | --- | --- |
| Z-Image Turbo (used) | 941 | Apache 2.0 | Best open model that fits 8 GB GPU / 16 GB RAM with quantization |
| FLUX.2 [klein] 9B | 941 | Non-commercial | Same score, larger, non-commercial |
| FLUX.2 [klein] 4B | 863 | Apache 2.0 | Smaller and faster, clearly lower quality |
| FLUX.1 [dev] | 841 | Non-commercial | Lower score, 12B |
| FLUX.1 [schnell] | 803 | Apache 2.0 | Lowest of these |
| Qwen-Image 20B | 889 | Apache 2.0 | Too large for 16 GB system RAM |

**Download accurate model.bat** downloads it (about 13.8 GB, stored as about 10 GB).
Memory on this laptop: the official transformer is 24.6 GB in float32, so the app
uses a 5-bit GGUF conversion of the same weights (unsloth, Q5_K_M, 5.6 GB). The
Qwen3-4B text encoder is converted once to 8-bit storage with a scale per weight
row (4.4 GB instead of 8 GB); it is loaded straight onto the GPU while your prompt
is read, then freed so the transformer has the GPU.

Measured on this laptop (9 steps, peak GPU allocation 5.77 GiB, 6.3 GiB reserved):
37–53 s at 1344 × 768, about 60 s at 1024 × 1024 and 832 × 1216, plus about 20 s
to load the model for the first image. On "exactly three objects: red cube, blue
sphere, yellow pyramid, left to right" and a longer studio version it was right in all 3 tests from the words
alone, and it spelled a three-word sign correctly. The 1.5× high-detail pass works
but fills the GPU (7.9 GiB reserved) and took 146 s in total, so switching to
Accurate turns it off; its images are already sharp at normal size.

## Face and hand repair

Faces and hands that are small in the picture get few pixels and often come out soft
or malformed. With **🩹 Face and hand repair** ticked (the default, Realistic and
Accurate), after the image (and any high-detail pass) is drawn:

1. YOLO detectors (Bingsu/adetailer `face_yolov9c` and `hand_yolov9c`, Apache 2.0,
   run on the CPU in about 0.4 s) find up to 12 faces and hands.
2. Each is cropped as a square with surroundings, enlarged to 1024 × 1024, redrawn
   by the same model with a face- or hand-specific prompt plus your prompt at
   **Repair strength** (default 0.3 for faces; hands get 0.1 more), shrunk back and
   blended in with a soft edge. Faces already larger than about 820 pixels are left
   alone, unless they get a reference face (below).

Every face gets its own prompt and its own seed. Before, every face was redrawn with
the same seed, the same polished face prompt ("sharp detailed eyes") and the whole
group's description, at 0.4; that pulled the faces in a group toward one face. Now
each face's prompt names only that person: their Vary faces description when the
people were listed left to right and the number of faces found matches, otherwise a
face shape and one detail picked for that face (no heritage, sex or age, so they
cannot contradict the face).

The JSON beside each image lists every face and hand found and how much each was
enlarged. Measured: about 10–20 s per face or hand with Realistic and about 25 s with
Accurate. In a wide Realistic picnic photo, a child's face with a melted nose and
mouth came out as a normal face, and the other four faces became sharper; Accurate's
faces were already good, so the gain there was small. It does not count fingers, so
an extra finger can survive.

**Download repair models.bat** downloads the detectors (about 100 MB). They need the
`ultralytics` package (AGPL-3.0, installed in the project environment); its usage
reporting is switched off.

## Photo style and photo finish: less of the "AI look"

Image models are tuned on pictures people rated as beautiful, so by default they draw
airbrushed skin, studio light, blurred backgrounds and rich colors, which is exactly what
makes a picture read as AI. Two options in the Create tab work against it:

- **Photo style** (`style.py`). **Natural photo** (the default) asks for what an
  ordinary camera records: an unretouched candid photo, skin with pores, true-to-life
  colors, the background in focus. RealVisXL and Turbo get a short prefix (SDXL reads
  only the first 77 tokens) and "airbrushed, retouched, beauty filter, glamour,
  oversaturated, HDR, heavy bokeh, perfect symmetry, studio lighting" added to Things to
  avoid; Z-Image gets the same as a full sentence. **Polished** is the old behavior.
  Smart prompt no longer adds lens and "cinematic" wording, and is told to prefer
  everyday details over glamorous ones.
- **Photo finish** (`finish.py`). **Light** (the default) adds what real cameras add:
  fine grain strongest in the midtones, slightly muted colors and lifted blacks, a faint
  vignette and a sub-pixel color fringe toward the edges. **Film** is about twice as
  strong. It takes about 0.25 s and is seeded, so a seed still reproduces the image.

## Realism LoRA (trained on this laptop)

**📷 Realism LoRA** (default 0.6, 0 turns it off) adds a LoRA trained here on 800
ordinary photographs, so RealVisXL draws what real cameras record instead of stock-photo
polish. It applies to Realistic mode and to the RealVisXL finish in Accurate mode (also
its face repair and detail pass). With strength 0 the picture is identical to before.

Measured on 5 prompts × 2 seeds (woman on a park bench, five friends on a beach, a man
cooking at home, a street market, an old man reading in a cafe), same seeds at 0, 0.6
and 1.0: without it, pictures look like staged stock photos (a fashion-shoot pose, six
near-identical women waving, a dramatic pendant lamp, a blurred-background portrait in
the market). At 0.6 they look like everyday photos: ordinary-looking people, cluttered
real kitchens, crowds and backgrounds in focus, plain light, and more varied faces. At
1.0 they look most like snapshots, but small faces lose some detail and one beach figure
was malformed; 0.6 kept the detail. It does not fix written text (newspapers are still
gibberish) or counts.

How it was made (`training/lora/`, reproducible):

1. `prepare_data.py`: 800 photos from the Open Images validation set (Flickr photos
   listed as CC BY 2.0; `../../work/lora-data/credits.csv` lists the author, licence and
   source of each): 500 with people and 300 everyday scenes, picked by human-verified
   labels. Dropped: drawings, text, black and white, small (under 640 px), blurry, and
   photos where a face is taller than 22% of the picture (143 of them), so the LoRA
   learns how ordinary photos look, not who is in them.
2. `caption.py`: Qwen3-VL describes what each photo shows (people, action, setting,
   light) and never its style, so the LoRA learns the look that all captions leave out.
3. `train_lora.py`: latents and text embeddings are cached once (388 MB); then a rank-16
   LoRA on RealVisXL's attention layers trains for 2,400 steps (3 passes) at learning
   rate 1e-4 with min-SNR weighting, 10% empty captions and SDXL's size conditioning
   (the photos are at most 1024 px, and SDXL is told their real size so it does not
   learn small or soft pictures). Measured: 1.05 s per step, 45 minutes, 5.8 GiB peak
   GPU memory. Checkpoints every 400 steps are in `../../work/realism-lora`.
4. `evaluate.py`: the comparison above.

To retrain, for example with your own photos added to `../../work/lora-data/images`
(only photos you took or have the right to use), stop the image generator and run
`prepare_data.py` (optional), `caption.py`, then `train_lora.py`. The app uses
`../../work/realism-lora/final`.

## Finish with RealVisXL (Accurate mode)

Z-Image Turbo follows the request best (counts, positions, a different look for each
person), and RealVisXL draws the most photographic skin and texture. With **🧬 Finish
with RealVisXL** ticked (the default in Accurate mode):

1. Z-Image makes the picture, and Check and retry checks it as before.
2. Z-Image is unloaded and RealVisXL redraws the chosen picture lightly (Detail pass
   strength, default 0.35; at 1.5× size when the high-detail pass is on), from the
   scene without the list of people.
3. The faces of the Z-Image picture are blended back over that redraw, and face and
   hand repair (with reference faces) then gives them RealVisXL's skin; then the
   photo finish.

Step 3 is there because a whole-picture RealVisXL pass, even at 0.25, recast a small
Italian woman's face in a Z-Image group photo as East Asian, while redrawing her face
enlarged in face repair kept her as she was. The gallery shows the Z-Image picture and
the final one. With several images, every Z-Image picture is made first and RealVisXL
then finishes them, so each model loads once. Measured on this laptop (1216 × 832, four
people): Z-Image picture 62–94 s including loading; RealVisXL stage 143–156 s including
loading, the texture pass and repair of 4 faces (with references) and 2 hands; peak
GPU memory 7.5 GiB. A full run through the app (Smart prompt, two checked Z-Image
attempts, RealVisXL finish, three people) took 5 min 44 s.

## Check and retry

With **🔍 Check and retry** ticked (the default), every image is inspected before
you get it:

1. The prompt assistant (Qwen3-VL) turns your request into a checklist of small
   questions: each object and its color, each count ("How many apples?"),
   each position, the setting and lighting, and any quoted text.
2. It looks at the finished image and answers each one. Yes/no questions are scored
   by how sure it is; counts must match exactly; quoted text is read back and must
   be spelled exactly (case and punctuation may differ).
3. If anything fails, it rewrites the prompt to stress what was missed and tries
   again with a new seed. If counts or positions still fail halfway through the
   attempts, it also plans and draws a layout sketch and uses it from then on.
4. It stops at the first image that passes every check, or after **Most attempts per
   image** (default 4), and shows every attempt with its match score, the best one
   selected. **Prompt check** lists each check, and each image's JSON keeps them.

Checking takes about 10 s to load the assistant plus about 2.5 s per image. Measured:

- On 11 saved images of "exactly three objects: red cube, blue sphere, yellow
  pyramid" whose right answer was known, its pass/fail matched in all 11, including
  an image whose only fault was a tiny extra ball.
- Realistic, same prompt: attempt 1 (red sphere, two blue spheres) 36%, attempt 2
  (six objects) 50%, attempt 3 with the automatic layout sketch passed.
- Accurate, "exactly five red apples..., a green pear on the far right, a note that
  says "Buy more fruit"": attempt 1 had four apples and was caught; attempt 2 passed.

It is a 2-billion-parameter vision model: it checks what is visible, not taste, and
it can miss subtle anatomy problems such as an extra finger. It counts reliably only
when asked "How many ...?", so yes/no count questions ("Are there three people?") are
turned into counts; asked as yes/no, it passed a picture with five people for three.

## Layout sketch: exact objects, colors and positions

From words alone, SDXL often miscounts objects, swaps colors (a red sphere instead of
a red cube) and ignores left/right. **Layout sketch** in the Create tab fixes that:

1. Describe the picture, including where each object goes.
2. Open **📐 Layout sketch** and click **Sketch the layout from my description**. The
   prompt assistant plans each object's shape, color and place and draws simple
   shaded shapes. Or draw colored shapes yourself with the brush, or upload a sketch.
3. Fix the sketch if needed, then click **Generate image**. RealVisXL starts from the
   sketch instead of noise, so the objects, colors and positions come from it.

**Freedom from the sketch** (default 0.65) is how much the model may redraw it.
Measured on "exactly three objects: red cube, blue sphere, yellow pyramid, left to
right": at 0.6–0.65, five of six images were exactly right and one had a tiny extra
ball; at 0.75, both images added an extra ball and one turned the cube into a
sphere. Lower it if objects change or appear; raise it if the result looks too
much like the sketch. Clear the sketch (bin icon) to create from words only.
Layout sketches work with Realistic and Accurate.

## Vary faces

Realistic models tend to draw the same face for "a woman" whatever the seed. With
**🎭 Vary faces** ticked (the default), each image gets a heritage, a first name, a
face shape and one distinct detail, picked from its seed, placed where the
prompt first names the person. A new seed gives a different person; the same seed
gives the same one. A heritage you wrote ("Indian fisherman") is kept, and a prompt
that already describes the face (face, eyes, nose, freckles, "named ...") is left
unchanged. The JSON beside each image records the prompt actually used.

"A family restaurant", "a family car" and similar phrases no longer count as a family
(before, "four friends in a family restaurant" were all given one shared heritage).

## Reference faces: a different face for each person

Words only go so far: RealVisXL reads at most 77 tokens through CLIP and still drifts
to its usual faces, so five friends can come out as five similar men. With **👥 A
different reference face for each person** ticked (the default once set up), face
repair with RealVisXL redraws each face after a reference face:

1. A pool of 192 generated portraits of invented people covers every heritage in Vary
   faces, both sexes and four age groups (children, 19–28, 32–50, 60–80).
2. For each face in the picture, the CLIP image encoder measures how alike it is to
   every pool face (on the face alone). Its most alike labelled pool faces decide its
   sex (majority) and age (median). The reference is picked from the seed among the 5
   most alike pool faces of that sex, within 12 years, and at most 0.08 less alike
   than the best match, preferring the heritage the request gave that person (Vary
   faces). No two faces in a picture share a reference.
3. A face whose best likeness is under 0.57 gets no reference and is repaired as
   usual. Measured: the encoder matched faces correctly when they scored 0.595 or more;
   two white men in warm restaurant light scored 0.54 and were matched to East Asian
   and Ghanaian faces, which recast them. The JSON says which faces were skipped.
4. IP-Adapter Plus Face (h94/IP-Adapter, Apache 2.0) redraws the face at strength 0.42
   with the reference at 0.45 influence. Large faces in portraits are redrawn too (at up
   to 1280 pixels), since a portrait is where the usual face shows most.

It works with Realistic and with Accurate when **Finish with RealVisXL** is on (Z-Image
cannot use the adapter). The JSON beside each image lists each face's reference and
the sex and age it was taken to have.

Setup, once: **Download face variety model.bat** (about 3.4 GB), then with the image
generator stopped, **Build face pool.bat** (about 40 minutes). You can add photos to
`../../work/face-pool` (largest face used), but only of yourself or of people who agreed
to it. They have no sex or age label, so they are only picked for faces they are among
the 7 most alike to.

## Edit a photo

The **Edit a photo** tab changes your own photos from a written instruction, using
FLUX.1 Kontext [dev] running on this laptop:

1. Drag in a photo, paste one, or use the webcam. Crop and resize are in the photo
   toolbar; **Rotate left**, **Rotate right** and **Flip** are below it.
2. Describe the change, for example *"Change the background to a beach at sunset.
   Keep the person, face and pose exactly the same."*
3. Optional: paint over an area with the brush. Only that area changes; everything
   outside it is kept exactly as it was, at the photo's full resolution.
4. Click **Edit photo**. **Keep editing this result** feeds the output back in for
   the next change, and **Compare before and after** shows a slider.

Tips: say what should stay the same ("keep the face and pose"), name one change
at a time, and raise **Instruction strength** if the change is too weak. Whole-photo
edits come out at about one megapixel in the photo's aspect ratio. **Edit this
image** under Recent images sends any saved picture to the editor.

The editing model is a 4-bit GGUF conversion (Q4_K_M) of FLUX.1 Kontext [dev]; its
T5 text encoder is stored with 8-bit weights so everything fits 16 GB of RAM and
an 8 GB GPU: the text encoder is loaded straight onto the GPU only while your
instruction is read, and the editing model is streamed through the GPU one block
at a time. Measured on this laptop: about 4 min 40 s per edit at Standard
(5.5–6 GB peak GPU memory, 9–10 GB RAM) and
about 3 min 10 s at Faster, plus about 20 s to load the model for the first edit.
Switching between Create and Edit unloads one model and loads the other. FLUX.1 Kontext [dev] is licensed for non-commercial use only.

## Krita: a professional editor driven by prompts

Krita 6.0.4 (free, open source, portable copy in `../../work/krita`) is connected to
Image Studio in both directions. Type what you want, in Krita's **AI** panel or in the
browser's **Krita** tab, and it is done with Krita's own tools and this laptop's AI
models, each change as its own layer that you can hide, adjust, mask or delete.

### Start

Double-click **Start Krita with AI.bat**: it starts Image Studio, opens the browser and
starts Krita with the AI panel (installed automatically). Or, from the browser:

- **Open in Krita** under a created image, an edited photo, or a picture selected in the
  Library opens that picture in Krita (Krita starts if it is closed).
- **Krita** tab → **Open Krita**.

The Krita tab shows what Krita has open, live: the picture, its layers, and the steps of
the current request. **Save to library** puts the picture (all layers merged) in the
Library with the list of what was done; **Undo** is Krita's Ctrl+Z.

### What you can ask

Requests can be combined ("crop to square, make it warmer and add a vignette").

| Kind | Examples | How it is done |
| --- | --- | --- |
| Light and color | brighter, darker, more contrast, warmer, cooler, more vivid, black and white, sepia, auto fix the colors, hue, tint, posterize, invert | Adjustment (filter) layers: Levels, HSV, Color Balance, Desaturate... Change them later in Layer Properties |
| Effects | blur, motion blur, lens blur, sharpen, reduce noise, film grain, vignette, pixelate, oil paint, emboss, edges, rounded corners | Filter layers, or a layer with the effect (grain, vignette) |
| Only one part | blur the background, make the sky bluer, brighten the subject, sharpen the cat | Selects it by description (below), adjusts inside the selection, deselects |
| Canvas | crop to 16:9, crop around the cat, resize to 50%, rotate 90, flip | Krita's crop, scale, rotate and mirror |
| Layers | duplicate the layer and set it to multiply at 40%, hide layer Text, merge down, flatten, new layer | Krita's layer commands |
| Text and color | write "SUMMER" at the top in white, fill the selection with red | Text layer (vector, editable with Krita's text tool), fill layer |
| Change what is in the picture | remove the dog, replace the sky with a sunset, make the car red, put a hat on the dog, make it winter, turn it into a watercolor | FLUX.1 Kontext (about 5 minutes), only inside the selected area when there is one |
| Cut out | remove the background, cut out the person | A transparency mask from the subject's outline, so nothing is erased |
| New content | paint a hot air balloon in the selection, new canvas | Z-Image / RealVisXL into the selection or a new canvas |
| Quality | enhance, upscale 2x, fix the faces | RealVisXL redraw with real-photo detail and face and hand repair (1.5x or 2x enlarges) |
| Questions | what animals are in this picture? | The vision assistant looks and answers |

Anything you select by hand in Krita (lasso, brush selection, magic wand...) limits the
next request to that area, as in the old panel.

### How a request is understood

1. **Instant rules** handle common phrasings ("make it brighter", "crop to 16:9", "blur
   the background", "write X at the top") with no AI at all: about 1–3 seconds.
2. Otherwise **Qwen3-4B** plans the steps: the same language model Z-Image reads prompts
   with, used as a chat model from the same 8-bit file (no extra download). It chooses
   from the list of steps in `agent.py` and every step and value is checked before it
   reaches Krita; it cannot delete, merge or flatten layers unless the request says so.
   About 10 seconds to load and 5–20 seconds to plan.
3. **Questions** about the picture go to the vision assistant (Qwen3-VL-2B), which looks at it.
4. If nothing fits, the whole request becomes one Kontext edit.

Measured with the 2B vision assistant as planner first: it answered "add a small bird on
the chair" with a text layer and "make it look like night" with nine unrelated filters,
so planning moved to Qwen3-4B, which got these and 20 of 24 test requests right (the
rest are fixed by the checks: for example "select the chair and delete it" no longer
deletes the layer).

### Selecting by description

"the dog", "the woman on the left", "her shirt", "sky", "background": the vision assistant
finds each match and gives its box, then **SAM 2.1** (Meta, Apache 2.0) outlines what is
inside, so the selection follows the real edge (hair, raised hands). "background" is
everything except the main subjects. Measured: 5–9 seconds with the assistant loaded,
about 35 seconds including loading it; a dog, the background around a cat and a dog, a
sky between raised arms and a shirt were all outlined correctly.
**Download selection model.bat** downloads SAM 2.1 (450 MB). Without it, selections are
rectangles.

### How it is connected

```
Browser (Krita tab) ──► Image Studio app.py ◄──► bridge.py (127.0.0.1:7861) ◄──► Krita AI plugin
                         GPU: planner, selection,                         Krita's tools: filters,
                         Kontext, Z-Image, RealVisXL                      layers, selections, text
```

Krita's plugin (`krita-plugin/ai_prompt`) keeps a connection open to the bridge: it
receives commands from the browser, sends what it has open (and a preview while the
Krita tab is watching), and sends each GPU job (planning, selecting, editing, new
pictures, enhancing) to Image Studio, which runs them in the same queue as the browser.
Scripts can drive Krita the same way: `POST /krita/command {"kind": "prompt", "text":
"..."}` and `GET /krita/view` (see `bridge.py`).

Errors inside Krita are written to `%APPDATA%\krita\ai_prompt.log`. Image Studio installs
the panel each time it starts while Krita is closed; `install_krita_plugin.py` does it by
hand.

## Smart prompt

With **Smart prompt** ticked (the default, in both tabs), a small vision-language
model (Qwen3-VL-2B-Instruct, Apache 2.0) reads your request first, the way chat
assistants do before calling an image model. When editing, it also looks at the
photo. It fixes typos and casual wording, makes the request specific, and for
edits names what must stay the same. **What the AI understood** shows the prompt
actually used; the JSON beside each image keeps both your words (request) and the
prompt. Untick it to send your exact words. It adds about 5–10 seconds (about 25
seconds the first time) and only occupies the GPU while it runs.
**Download prompt assistant.bat** downloads it (about 4.3 GB).

It keeps counts, positions and lighting direction from your request. If its rewrite
drops one of them (for example "exactly three" or "left"), your exact words are used
instead and **What the AI understood** says so.

It is a small model: it can miss what you really meant, for example keeping a
loose shirt when you ask for a different body shape. Read **What the AI
understood**, and if it missed, say it more directly or untick Smart prompt.

## High-detail pass

SDXL draws at about one megapixel, so small faces, hands, hair and textures can
look soft. The high-detail pass enlarges the finished image and has RealVisXL
redraw it lightly at the larger size, keeping the composition the same.

| Option | Result from 1024 × 1024 | Extra time measured on this laptop |
| --- | --- | --- |
| Off | 1024 × 1024 | none (52 s total) |
| 1.5× size (default) | 1536 × 1536, one pass | about 40 s (92 s total) |
| 2× size | 2048 × 2048, 9 tiles | about 3.5 min (256 s total) |

Images up to 1536 × 1536 pixels are redrawn in one pass. Anything larger is
split into overlapping 1024-pixel tiles that are redrawn one after another and
blended back together with soft edges, so GPU memory stays the same as a normal
image (about 7.6 GB measured). A one-pass redraw that runs out of GPU memory also
switches to tiles automatically. **Detail pass strength** (default 0.35) sets how
much new detail is drawn; higher values can alter faces or add stray objects,
especially with tiles.

The first image and switching models include loading time. Only one model is
loaded at a time to fit the laptop's 16 GB system RAM.

Double-click **Stop image generator.bat** when finished. Closing a browser tab
alone does not stop the app or free the loaded model's system memory.

## Image formats

The format menu includes square, portrait, landscape, widescreen, and smaller
options. These are native generation sizes, not enlarged 512-pixel images.
Turbo remains fixed at 512 × 512. One image is generated at a time.

| Format | Resolution |
| --- | --- |
| Square | 1024 × 1024 |
| Portrait | 832 × 1216 |
| Landscape | 1216 × 832 |
| Widescreen | 1344 × 768 |
| Large portrait | 1024 × 1536 |
| Large landscape | 1536 × 1024 |
| Smaller | 768 × 768 |

Measured on this laptop: the 1536 × 1024 scene took 66.75 seconds to render
(80.03 seconds including loading), with a sampled total peak of 7601 MiB
(7.42 GiB). The 1344 × 768 scene took 41.16 seconds. These are example timings,
not guarantees; prompts, settings, other apps, and laptop power settings matter.

## Fine-tune your image

- **Rendering steps:** 30 is the Realistic default; 20–50 is available. More steps
  take longer and may improve detail, but do not guarantee a better picture.
- **Prompt strength:** start at 5. Very high values can make images look harsh.
- **Detail pass strength:** 0.35 is the default; 0.2–0.5 is available.
- **Things to avoid:** a negative prompt. Remove `illustration`, `cartoon`, or
  `CGI` if you intentionally want those styles.
- **Seed:** leave blank for a new variation, or use a saved seed with exactly the
  same prompt, model, resolution, and settings to reproduce a result on this setup.
  With several images, each uses the next seed (seed, seed + 1, ...).

RealVisXL uses an SDE DPM++ multistep scheduler with Karras sigmas, half-precision
weights, CPU model offloading, PyTorch's default memory-efficient attention, and
tiled VAE decoding. Inactive components move to RAM while the active network runs
on the GPU.

The status reports PyTorch's peak tensor allocation in **GiB**. Windows' total
GPU memory can be higher because of the driver, desktop, and other programs.
The JSON beside each image records peak reserved memory, dimensions, scheduler
configuration, model revision, and timing. Render time excludes model loading;
total time includes it. `verification.json` contains tests on this laptop and
sampled total GPU memory from NVIDIA's driver; sampling may miss brief spikes.

If another GPU app is using memory, close it or select **Smaller**. Filling every
last byte of VRAM is not itself a quality improvement. There is no automatic
resolution reduction if memory is insufficient.

Hands, small faces in crowds, legible signs, and complicated spatial instructions
can still be wrong. Try another seed or a clearer composition. Larger canvases
can also introduce repeated subjects or compositional mistakes.

## Image search (EmbeddingGemma 2)

Above **Recent images**, type what you remember about a picture ("the picnic with the
red umbrella", "old man by the sea", "glowing sign at night") and press Enter or
**🔎 Search**: the 12 best matches replace the recent images. Select one and **Find
similar images** shows the pictures most like it. **Use these settings** and **Edit this
image** work on search results as usual; **Show recent** goes back.

It uses EmbeddingGemma 2 (Google DeepMind, October 2026, Apache 2.0), which turns
pictures and text into 768 numbers in one shared space, so a search matches what is
in the picture, not only the words of its prompt (an edited photo is found by what the
edit added). It needs transformers 5 while the image models use 4.57, so it runs in
its own CPU-only environment (`../../work/search-env`) as a separate process; the GPU
stays free. The process starts when needed and closes after 5 idle minutes (about
1.3 GB of RAM while open).

Measured on this laptop's CPU: reading a picture takes about 5 s. Each new picture is
read in the background right after it is saved (4 threads, so generation is not
slowed), so a search itself takes about 0.1 s; reading the first 74 pictures took 5½
minutes once. On 32 test searches across these 74 pictures (16 broad ones like "a wild
animal in the snow", 16 about details like "red suitcase" or "astronaut helmet") the
first result was right in all 32. Reading pictures at a quarter of the detail was 7×
faster but missed small objects ("green pear"), so full detail is kept.

**Download image search model.bat** sets up the environment (about 1.1 GB of
libraries, `requirements-search.txt`) and downloads the model (1.5 GB).

## Code and model folders

The React migration moved Python source into `backend/image_studio/`, download shortcuts into
`scripts/windows/`, the Krita plugin into `integrations/krita-plugin/`, and training scripts into
`training/lora/`. See the root README for the current folder map and setup commands.

The models, Python environments, LoRA data, and caches still live in `../../work/`.
Original PNG images and their JSON settings still live in `images/`. Keep `outputs/` and `work/`
together when moving this installation. This guide describes the model features and measurements;
references to the old Gradio tabs are historical. The React workspace exposes these settings in
Create image, Edit image, My library, Krita canvas, and Studio settings.

## Command line (from this folder)

```powershell
& ..\..\work\image-env\Scripts\python.exe -m image_studio.core.engine "An editorial portrait of a man beside a cafe window, natural light" --seed 42 --steps 30
& ..\..\work\image-env\Scripts\python.exe -m image_studio.core.engine "A rainy bus stop at night" --detail "2× size"
& ..\..\work\image-env\Scripts\python.exe -m image_studio.core.engine "A forest cabin at sunrise" --model turbo --seed 42
& ..\..\work\image-env\Scripts\python.exe -m image_studio.core.engine "Exactly three objects: a red cube, a blue sphere and a yellow pyramid, left to right" --model accurate
& ..\..\work\image-env\Scripts\python.exe -m image_studio.core.engine "A red cube, a blue sphere and a yellow pyramid" --layout sketch.png --layout-strength 0.65
& ..\..\work\image-env\Scripts\python.exe -m image_studio.core.engine "Four friends at a picnic" --repair --references --style "Natural photo" --finish Film
& ..\..\work\image-env\Scripts\python.exe -m image_studio.core.engine "Four friends at a picnic" --source images\<an Accurate image>.png --repair --references
& ..\..\work\image-env\Scripts\python.exe -m image_studio.services.faces build
& ..\..\work\image-env\Scripts\python.exe -m image_studio.cli.download_model --model realistic
& ..\..\work\image-env\Scripts\python.exe -m image_studio.cli.download_model --model kontext
& ..\..\work\image-env\Scripts\python.exe -m image_studio.cli.download_model --model accurate
```

## Model references and licenses

- RealVisXL: https://huggingface.co/SG161222/RealVisXL_V5.0
- SDXL-Turbo: https://huggingface.co/stabilityai/sdxl-turbo
- Z-Image Turbo: https://huggingface.co/Tongyi-MAI/Z-Image-Turbo
  (5-bit GGUF: https://huggingface.co/unsloth/Z-Image-Turbo-GGUF)
- Arena results: https://artificialanalysis.ai/image/leaderboard/text-to-image?open-weights=true
- FLUX.1 Kontext [dev]: https://huggingface.co/black-forest-labs/FLUX.1-Kontext-dev
  (4-bit GGUF: https://huggingface.co/QuantStack/FLUX.1-Kontext-dev-GGUF)
- IP-Adapter Plus Face (SDXL, Apache 2.0): https://huggingface.co/h94/IP-Adapter
- Open Images (realism LoRA photos; images listed as CC BY 2.0): https://storage.googleapis.com/openimages/web/index.html
- EmbeddingGemma 2 (image search, Apache 2.0): https://huggingface.co/google/embeddinggemma-2
- Scheduler: https://huggingface.co/docs/diffusers/api/schedulers/multistep_dpm_solver
- Memory: https://huggingface.co/docs/diffusers/main/en/optimization/memory

Each model remains governed by its publisher's license. This app uses pretrained
models; it does not train these models from scratch.
