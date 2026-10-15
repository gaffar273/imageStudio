# The pipeline engine: professional photo editing as deterministic pipelines

The studio edits photos in PhotoCraft the way a professional retoucher does: with named procedures,
each a fixed sequence of tools and settings, applied in a fixed order and checked against the result.
Each procedure is a **pipeline** in code. The language model never edits and never writes a setting.
It reads the request and the photo and **chooses pipelines** from a closed menu, the way a senior
editor tells an assistant which jobs to run.

```
request + photo
      │
      ▼
┌──────────────┐   pipeline ids, slots from closed menus   ┌──────────────────────┐
│ planner role │ ────────────────────────────────────────▶ │ guards (normalize)   │
│ (any model)  │   JSON checked against the schema,        │ numbers must be in   │
└──────────────┘   repaired or asked again                 │ the request, words   │
                                                           │ override directions  │
                                                           └──────────┬───────────┘
                                                                      ▼
                                              workflows expand into procedures
                                                                      ▼
┌──────────────┐  boxes of named things   ┌───────────────┐  measured facts   ┌──────────────┐
│ grounder role│ ───────────────────────▶ │ needs         │ ◀──────────────── │ measure.py   │
│ (any model)  │                          │ (finds,       │  histogram, noise │ (pixels)     │
└──────────────┘                          │  measures)    │  tilt, verticals, │              │
                                          └──────┬────────┘  skin colours     └──────────────┘
                                                 ▼
                         builder: every procedure in stage order → PhotoCraft commands
                                                 ▼
                         PhotoCraft runs them (all pixel work happens in the editor)
                                                 ▼
          measured checks (checks.py, pixels) ── then ── checker role review (labelled fallible)
```

## Why pipelines and not prompts

A 9B vision model judged photos well but wrote numbers erratically: a “centered square” crop of a
1012×813 photo came back as a 1024×1024 rectangle. Free-form recipes ruined grades, and a visual
review called a still-grey mug “green”. Prompting a better model reduces such errors; it does not
remove them, and it cannot explain or reproduce an edit. A pipeline can. The division of labour:

| Job | Done by | Why |
|---|---|---|
| Which jobs the request asks for | the planner model, choosing pipeline ids | language and judgement |
| Where the named things are | the grounder model (boxes), SAM 2.1 (outlines) | grounding is a trained skill |
| What the photo measures | `pipelines/measure.py` | numbers come from pixels |
| Every command and setting | the pipeline's code | exact, repeatable, explainable |
| Whether it worked | `pipelines/checks.py` first, the checker model second | numbers do not flatter |

## What a pipeline is

`backend/image_studio/pipelines/core.py` defines it. Each pipeline declares:

- **id, title, category, summary**: the summary is what the planner reads; it says which slots mean
  what (“aspect like 1:1, 4:5”; “choice = autumn, spring, summer or winter”).
- **stage**: where it runs in the retoucher's order: layer housekeeping → pixel retouching → raw
  development → AI layers → adjustment layers → effects → cut-outs → geometry → text and graphics →
  output. A request listing “add a title, then crop” still crops first, so the title lands on the
  final canvas.
- **finds**: what must be located before it can be built (“the main subject”, “each person's face”).
- **measures**: the analyses it reads (exposure statistics, noise, levels, horizon tilt, verticals,
  skin and tooth colours).
- **options**: the closed menu for its `choice` slot, when it has one.
- **build** (a *procedure*) or **expand** (a *workflow*).

Procedures build PhotoCraft commands. Workflows are a professional job made of procedures; they
never build steps themselves. `product_marketplace` expands into `remove_background` (pure white),
`drop_shadow`, `product_frame` (the product filling 85% of a square) and `resize` (2000×2000 for
Amazon). Each part is ordered with everything else in the request and checked on its own. A part
that does not apply to a given photo (no vertical edges to straighten, an exposure already
balanced) is marked optional and becomes a note instead of stopping the plan. When the person also
asks for one of a workflow's parts in their own words (“…and much more color”), their edit replaces
the workflow's version.

The full list is generated from the registry into [pipelines.md](pipelines.md)
(`python scripts/pipeline_catalog.py`): 123 pipelines, 24 of them workflows, in 14 categories.

### How a pipeline is written

```python
@procedure('graduated_filter', 'Graduated filter', 'light', 'adjust',
           'a graduated (ND) filter: darken one edge of the frame, usually the sky at the top '
           '(position = the edge; strength)')
def graduated_filter(b, index, edit):
    edge = (edit['position'] or 'top').split()[-1]
    b.add(index, 'studio.select_insert', {}, 'Choose where the layer goes')
    soft_band(b, index, edge)                      # a feathered band fading toward the middle
    stops = round(-0.9 * min(lang.LEVEL[edit['strength']], 1.6), 2)
    b.add(index, 'layer.newAdjustmentLayer.exposure', {'exposure': stops, 'gamma': 0.95}, ...)
```

`b` is the builder (`photocraft_intents.Compiler`): it tracks the canvas through every crop and
rotation, turns targets into selections (SAM outlines, colour ranges, soft bands), merges Camera Raw
settings for the same area into one editable layer, and records which boxes each requirement is
checked on. A new capability is a new function in `pipelines/library/`; nothing else changes.

### Lessons the real engine taught

Every pipeline was run in PhotoCraft on test photos and compared before and after. Several first
versions were wrong in ways no unit test could see, and the fixes are now part of the pipelines:

| Pipeline | First version | What happened | Now |
|---|---|---|---|
| `window_pull` | Camera Raw highlights + dehaze on a highlight mask | a bright ring around a cat in front of a lit wall (local operators near a dark edge) | a Curves layer on the luminosity mask: a global operation cannot halo |
| `exposure_fix` | highlight recovery whenever ≥1% clipped | a lamp in shot pulled every highlight down and greyed the wall | recovery only for ≥4% clipped; a “bright” target for interiors |
| `graduated_filter` | Camera Raw −0.45 EV copy | barely visible | an Exposure layer (−0.9 EV) on a soft band |
| `light_leak` | a full-frame linear gradient, Screen | the whole picture turned orange | a feathered pool of light at the corner |
| `polaroid`, borders, fit | canvas extension in a colour | margins rendered black: the extension only colours a locked Background, the photo is a smart object | a solid fill layer behind the picture |
| `landscape_enhance` | deepen the sky through a sky selection | an arc drawn across the sea | a graduated filter, no segmentation |
| `split_tone` | colour offsets at the colour's own strength | teal shadows moved 8 of 100: invisible | offsets normalised to the asked strength |
| `compose` | — | never asked for the subject to be found | declares its finds; a test now checks this for every framing pipeline |
| `photo_correction` | fixed amounts: exposure to a 45% middle tone, Auto Color levels, vibrance, clarity, sharpen | on nine photos given camera faults it moved them *further* from the originals (colour difference 15.4 → 17.1) and turned a neon sign green | the measured camera develop below (15.4 → 7.9) |

### Developing a camera photo

“Develop this raw”, “I shot this on my DSLR, refine it”, “fix this photo” and “enhance it” all reach
the `photo_correction` workflow, which develops the photo the way a retoucher develops a camera file
(`pipelines/library/camera_develop.py`). It reads the photo once (`camera_develop.read`) and each
step either sets its part of one editable Camera Raw filter or leaves a note saying what it
measured and why it did nothing:

| Step | Reads | Sets |
|---|---|---|
| White balance | the light's colour three ways: the greyest midtones, the brightest near-neutrals, the white patch | per-channel point curves (exact gains, as a white-balance dropper); less when the readings disagree; 40% of a warm cast kept as the light's mood, a green or magenta cast removed in full |
| Tones | the 0.5th and 99.5th percentiles and the middle tone, after the white balance | a point curve putting the black and white points at the ends (never stretching more than 1.8×) and lifting dark midtones to about 40% (a night shot stays dark); highlight recovery when over 2% clips; contrast if still flat |
| Colour | the coloured parts' saturation, after the white balance and curve, on a 256 px copy | vibrance |
| Noise | the grain in the flat areas | luminance and colour noise reduction in proportion |
| Sharpening | the grain | capture sharpening 40, masked 40 to 80 so the grain is not sharpened |
| Sky | the top quarter against the rest | a soft graduated filter |
| Horizon | the strongest family of near-horizontal lines | straightened when 0.5° to 4° off |
| Vignette | the frame's edge after the curve | corners 10 darker; none on a plain backdrop |

What the measurements showed (PhotoCraft, 2026-10-15), and what each changed:

- **The Whites slider barely reaches a flat photo**: +40 moved the group photo's brightest tones
  from 0.694 to 0.697. Camera Raw's point curve is exact ([[40, 0], [175, 255]] put the 98th
  percentile at the 0.96 computed) and runs after exposure, so the tones are set with it.
- **A middle-tone aim darkens white backdrops**: aiming every photo at 45% pulled the puppy on
  white down 0.8 EV. Midtones are now only ever lifted.
- **The light's colour**: of six ways to read it, each single one misread some originals' own
  colours (warm skin, beach sand) as a cast by up to 16°. The three combined, correcting less
  when they disagree, left 1.65° of cast on average against 2.49° for the greyest midtones alone,
  and misread no original by more than 2.3°. Splitting the correction into temperature and tint
  stopped a green cast being read as warm and only 60% corrected.
- **Grain looks like colour**: chroma noise made washed-out photos read as saturated, so colour
  is judged on a 256 px copy. The grain measure itself moved only in steps of 1.48 (a median of
  whole levels); it is now a trimmed mean deviation, continuous.
- **Sharpening raises grain unless masked**: amount 80 took a noisy photo's grain from 2.97 to
  4.45; with masking 50 the edges gained as much and the grain did not rise.
- **Camera Raw's vignette is strong**: −25 darkened the corners by 29% and the ring halfway out
  by 23%; the develop uses −10 at midpoint 25 (corners about 13% darker, the middle untouched).
  On the puppy and the mugs it showed as a spotlight on the backdrop, so a plain border (tones
  spread under 0.15 after the curve; real scenes measured 0.24 and up) gets none.

Each step has a measured check against the photo with only the develop's other steps applied
(`camera_develop.preview`), so a vignette is judged on the corners it darkened, not on the
brightening the curve gave the whole picture. Results on the nine bench photos, each given a
camera file's faults of known size (0.6 EV under, flattened to 7–88%, a warm, cool or green cast,
30% less colour, a 0.8 px blur, grain):

| Photo | Faults | Colour difference from the original (CIELAB ΔE) | | |
|---|---|---|---|---|
| | | faulty | old workflow | **develop** |
| man | warm | 17.4 | 18.8 | **9.3** |
| woman | cool | 14.2 | 11.8 | **7.8** |
| group | green | 16.8 | 18.0 | **10.3** |
| mugs | warm | 16.0 | 7.5 | **6.2** |
| puppy | cool | 20.9 | 19.1 | **9.1** |
| town | green | 14.0 | 21.1 | **7.6** |
| room | warm | 17.2 | 11.4 | **10.1** |
| neon | cool | 10.0 | 34.1 | **4.7** |
| street | green | 12.1 | 11.7 | **6.0** |
| mean | | 15.4 | 17.1 | **7.9** |

46 of the 47 checks that applied pass. The one that does not is the grainiest photo (the puppy):
its noise reduction and masked sharpening nearly cancel, and its edges end only 1% crisper. A
develop takes 1.1 to 1.7 s in PhotoCraft, its checks included. The faults are synthetic so that
the original is known; real camera files have not been benchmarked this way.

## Talking to any model

`backend/image_studio/pipelines/models/` makes the engine independent of the model. The engine asks
three kinds of question, each a **role**:

| Role | Question | Answer schema |
|---|---|---|
| `planner` | which pipelines does this request need, with which slots? | `{"edits": [{"action": <pipeline id>, "target": <menu>, ...}], "preserve": [...], "questions": [...]}` |
| `grounder` | where is “the red mug”? | `{"boxes": [[x1, y1, x2, y2], ...]}` on a 0–1000 grid |
| `checker` | for each requirement: done, partly, not done, unclear? | `{"verdicts": [{"verdict": <menu>, "note": ...}]}` |

Each role is connected to one model through an **adapter**:

- `local`: the bundled Qwen3.5-9B vision model on llama.cpp (the default; schemas are enforced as a
  grammar, so answers always parse).
- `openai`: anything speaking the OpenAI chat-completions protocol: Ollama, LM Studio, vLLM, a remote
  llama.cpp server, OpenAI, Google Gemini's OpenAI-compatible endpoint, OpenRouter, Groq, Together.
- `anthropic`: Claude through the official Anthropic SDK, with structured outputs.

Presets fill in the details (`models.PRESETS`), and a role can mix them: a hosted planner with the
local grounder, for example. Settings live in the studio settings file; API keys come from an
environment variable or Settings → Providers (sealed for the Windows account), never from the
settings file. The API exposes it as `GET/PUT /api/photocraft/models`.

```python
from image_studio.pipelines import models
models.connect('planner', preset='ollama', model='qwen3-vl:8b', save=True)
models.connect('grounder', preset='gemini', model='<model id>')   # its [ymin, xmin, ymax, xmax] boxes are reordered
```

**What a model can do is declared, not assumed.** Finding things on the 0–1000 grid is a trained
skill: Qwen3-VL and Gemini have it (their presets and model names say so, `models.can_ground`);
most chat models were never measured at it, and Qwen2.5-VL answers in pixels of the picture it saw.
So when Settings → Providers points the assistant at Claude or GPT, the planner and the checker
move and the grounder stays on the bundled model while it is installed; without it, the grounder
follows the assistant and the Providers page says object selections may miss
(`models.warnings`). A model marked `vision: false` is never used as the grounder or the checker.
A hosted server's rate limit (429) or server error (5xx) is asked again, waiting as it asks; a
refused key or a server that is not running is not.

**A menu that stays short.** With `planner_menu: "categories"` in the settings (or
`IMAGE_STUDIO_PLANNER_MENU`), the planner first names the kinds of edit the request needs, then
chooses from those categories' pipelines only: the menu it reads drops from 18,600 characters to
about 8,000 for a two-category request, however many pipelines the studio grows. The default stays
`"full"` until the benchmark says otherwise (see Evaluation).

**Each pipeline's own choices.** A pipeline with a `choice` slot declares its options (the seasons,
the looks, the artistic filters). A choice in other spelling is mapped to the option; a choice that
names nothing on the menu (“fall” for the season) is asked again with that pipeline's menu alone,
or falls back to the pipeline's default with a note. Pipelines that take several options at once
(a portrait retouch's jobs) say `many=True`.

### The contract keeps weak models honest

Models differ in how well they follow a schema, so no answer is trusted as it arrives
(`models/contract.py`):

1. **Portable schemas.** Constraints some providers reject (item counts, ranges, lengths, patterns)
   are removed from what is sent and checked locally instead: a box coordinate outside 0–1000, a box
   with two numbers, a too-short answer is a problem the model is asked about.
2. **Spelled-out schemas.** A model without a JSON mode gets the schema in its instructions.
3. **Extraction.** The JSON is found inside prose and code fences; trailing commas are tolerated.
4. **Repair without guessing.** A menu choice in other letter case, with spaces for underscores or
   a plural “s” (“Blur Background” → `blur_background`, “vignettes” → `vignette`), a number written
   as text, a missing free-text field and a list that is too long are fixed. A near spelling is not a
   match: “desaturation” is not `saturation` and “unsharpen” is not `sharpen`, though both are 85%
   alike. A missing or empty menu choice is never filled with the menu's first value (a missing
   review verdict once read as “done” and a missing pipeline as `brightness`); it is asked again.
5. **Asking again.** Anything that cannot be repaired is listed back to the model (“answer.edits[0].
   action must be one of the menu values, not "sharpen it"”), up to three times.
6. **Engine guards.** Whatever still slips through meets the edit language's own guards: an edit
   with no pipeline is left out and its words reported as “Not understood”; an unknown pipeline
   becomes `other`; a number counts only when it is written in that edit's own words (“crop to 4:5
   and boost vibrance” has no vibrance amount); and direction words in the request override the
   model for the amount pipelines (light, warmth, colour, punch, haze). Direction words are read as
   phrases (`photocraft_intents.direction_from_words`): “less dark” and “too dark” are brighter,
   “reduce the warmth” is cooler, “brighten the darker areas” is led by its verb, “recover the blown
   out sky” lowers the highlights. Earlier the guard read any “less” or “darker” as decrease and
   overruled correct answers; for pipelines where direction is not an amount (“add a soft shadow”,
   “remove the dog”) the words now never overrule the model.

The last resort, `other`, lets the model pick up to three PhotoCraft commands for something no
pipeline covers; they run with their own default settings, never with numbers the model wrote.

## Checking

After PhotoCraft runs a plan, `photocraft_intents.measure` and `pipelines/checks.py` compare the
before and after renders for each requirement: the asked aspect and size, the recoloured object's
hue, the background without colour, the backdrop colour, that only the asked colour kept its
saturation, that the graduated edge darkened more than the opposite edge, that the brightest 3% came
down, that the subject's centre sits on a thirds line, that the product fills the asked share of a
square frame, that the bars are black. A global check (brightness, saturation, warmth) is skipped
when another edit in the same plan also moves that quantity, so one step cannot fail for another's
effect. Detail, noise, grain, blur, tilt-shift, vignette, tint, hue, posterize, threshold, invert,
flip, colour filter and overlay, duotone and texture have measured checks too: about 54 of the 91
procedures now have one (layer housekeeping, text and AI content are judged by the review). Only then
does the checker model review the result, and its verdicts are labelled fallible: a verdict it
leaves out or writes off the menu reads “unclear”, and items it skipped are listed as unchecked.

**Checks steer, once.** A failed check says whether the change went the asked way but not far
enough (`weak`). When every failed check of an edit is weak, the person wrote no number, the edit
is not already strong and the plan has no AI layer, `apply` builds the plan again with that edit one
strength step up (the boxes found the first time are reused, so no model is asked anything), runs it
on the same starting revision, and keeps whichever result fails fewer checks, with a note saying so.
Measured in PhotoCraft (2026-10-13): a subtle brightening re-run at moderate went 0.588 → 0.642
mean brightness, against 0.620 the first time; the discarded attempt's files are deleted.

## A session of requests

Editing is a conversation of several requests, and the engine keeps it tidy the way a retoucher
keeps a layer stack tidy.

**A follow-up revises the last request instead of stacking on it**
(`integrations/photocraft_followup.py`). The plan that made the photo on screen is kept with its
revisions; a follow-up rebuilds it with the change, from the photo as it was before it, with the
boxes it found the first time (no model is asked to find them again), and replaces its result:

| After “make it warmer and add a vignette” | What happens |
|---|---|
| “too much”, “tone it down”, “subtler” | every part one strength step down (a measured develop applies 60% of its correction) |
| “more”, “not enough”, “push it” | one step up |
| “without the vignette”, “drop the grain” | rebuilt without that part; taking out every part says that Undo does it |
| “less warm” | the warming turned down a step instead of a cooling layer above it; on a subtle edit, removed |
| “less warm and add a title” | the warming turned down, the title added, one result |

A written number is the person's exact amount and is never stepped; another target is another
edit. Measured in PhotoCraft on the coastal town (2026-10-15): red−blue warmth 32.7 → 42.5 for
“make it warmer”, 38.7 after “too much”, 42.5 after “more”, 38.7 after “less warm”, the history at
two revisions throughout.

**A long request runs stage by stage.** Three or more edits over two or more stages run as one
revision per stage (clean-up, develop, AI content, adjustments, effects and cut-outs, then framing,
text and output), each checked against the stage before it, so a check before a crop compares the
same frame. When a stage fails, the stages before it are kept and the message says which one
failed. The model's review runs once on the whole result, and the last stage carries every check.
“Develop this photo, crop it to 4:5 and add SUMMER at the top” ran as three steps in 4.8 s, all 9
checks passing; a “too much” afterwards replaced all three.

## Speed

Measured end to end on the bundled model and PhotoCraft (RTX 4060 laptop, 8 GB, 2026-10-15). The
engine's own Python (planning, building, measuring, checking) is 1 to 3 s of a request; the time
goes to the models.

| | Before | Now | What changed |
|---|---|---|---|
| “retouch this portrait” | 421 s | 26 s | blemishes healed with Spot Healing on measured spots instead of FLUX Kontext (374 s) |
| Outlining a face or object | 7 to 22 s on the CPU | 0.1 s on the GPU | SAM 2.1 tiny beside the editing brain (569 MB at most) instead of large on the CPU; kept loaded; one trace per plan |
| First request of a session | +37 s loading the brain | loaded while the photo is open | `POST /api/photocraft/warm`, only on an idle GPU |
| A full camera develop | — | 1.1 to 1.7 s | eight measured steps in one Camera Raw filter |

What a call to the bundled model costs: reading the photo 2.8 s at 1024 px (1.4 s at 768, 0.7 s
at 512), text at about 1,600 tokens a second, answers at about 39 tokens a second; the planner's
4,800-token menu is cached between requests. Reading the photo at 768 px for planning lost three
bench requests (228/233 against 232/233), so the planner stays at 1024 px. SAM tiny agreed with
large at a median IoU of 0.98 on 15 faces, people and objects; where they differed, on small faces
in a group, large was the one that missed.

## Scope

The pipeline engine plans and checks PhotoCraft edits. The Krita assistant (`services/retoucher.py`,
`services/agent.py`) is an older, separate path: Krita's Python API cannot apply curves or
per-channel levels, so its grades are computed in Python and sent as pixel layers, and its edits are
not registry pipelines. Its model calls go through the same roles (`planner` for the plan, `checker`
for the review, `grounder` for finding things), so it runs on whichever model is connected, but it is
outside the claims and measurements on this page. Pipelines emit PhotoCraft commands directly; an
editor-neutral step list that Krita could also run is future work, not something the engine has.

## Evaluation

- `tests/test_pipelines.py`: every pipeline builds on a sample document; every workflow expands into
  registered procedures; framing pipelines ask for their subject; the contract repairs and rejects as
  described; adapters send images and schemas in each provider's format.
- `scripts/planner_bench.py`: 175 requests a working editor gets (the original 138 plus 37 that only the
  new workflows and techniques answer), run through the real planner with the local Qwen3.5-9B model.
  `--set holdout` runs 40 requests written after every fix and never tuned on (a fix made because of
  one moves it into the main set and a fresh request replaces it); `--set direction` runs 18 requests
  scored on whether the edit goes up or down. Every set also counts edits nobody asked for and how
  often `other` fired. `--planner anthropic:claude-opus-5-5` (or `ollama:qwen3-vl:8b`, `openai:<model>`,
  …) runs it on another model, `--menu categories` with the two-step menu, and `--export-photos` /
  `--photos` make the nine photos portable so anyone can reproduce a run.
- Real-engine runs of the new pipelines on the bench photos, judged by before/after sheets and the
  measured checks.

| Measurement (2026-10-12, local Qwen3.5-9B, RTX 4060 8 GB) | Result |
|---|---|
| The original 138 plans recompiled through the pipeline registry | 138/138 send exactly the same engine commands as before the refactor |
| Benchmark, first live run with the 115-pipeline menu | 155/175 |
| … after the fit check with re-asking, workflow coverage and positions from words | 175/175 (portrait 21/21, colour 18/18, workflows 23/23, techniques 14/14) |
| New pipelines and workflows run in PhotoCraft | 22 of 22 run; every measured check passes after the fixes in the table above |
| Unit and integration tests | `tests/test_pipelines.py` plus the existing PhotoCraft, API and desktop suites |

| Measurement (2026-10-13, local Qwen3.5-9B, RTX 4060 8 GB) | Result |
|---|---|
| Main set with the new direction reading, contract and scoring | 175/175, none with an unrequested edit, `other` 0 times |
| Held-out set (never tuned on) | 39/40; the miss planned correctly but found no visible teeth to whiten on that portrait |
| Direction set, old guards on the same model answers | 14/18: four correct answers flipped (“less dark”, “less cold”, “less washed out”, “the lower half brighter”) |
| Direction set, new guards | 18/18 |
| New effect checks on real PhotoCraft output | 15 of 15 pass on the edit and fail on the untouched photo |
| Other models | not yet measured: no hosted key or local server was connected on the test PC |

The 20 first-run misses: 7 were the model choosing a newer, more specific pipeline (“teal and orange
grade” → `split_tone`, “too dark” → `exposure_fix`), so those expectations were widened; 6 were a bug
(a workflow's parts did not count as covering the person's sentence, so it was reported “Not
understood”); 4 were wrong choices now caught by the fit check and re-asked (a darker beard as a
shadow tint, turquoise water and vivid sunset colours as colour splash, god rays as a light leak);
2 were pipelines that did not declare what to find (the eyes for an eye colour, the subject for a
composition crop; the composition case also moved to a photo whose subject is small enough to
recompose); and 1 was a position the model left out (“move the yellow mug to the left”).
