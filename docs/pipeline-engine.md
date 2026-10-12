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
(`python scripts/pipeline_catalog.py`): 115 pipelines, 24 of them workflows, in 14 categories.

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
local grounder, for example. Settings live in the studio settings file; API keys are read from
environment variables and are never stored. The API exposes it as `GET/PUT /api/photocraft/models`.

```python
from image_studio.pipelines import models
models.connect('planner', preset='ollama', model='qwen2.5vl:7b', save=True)
models.connect('grounder', preset='gemini', model='<model id>')   # its [ymin, xmin, ymax, xmax] boxes are reordered
```

### The contract keeps weak models honest

Models differ in how well they follow a schema, so no answer is trusted as it arrives
(`models/contract.py`):

1. **Portable schemas.** Constraints some providers reject (item counts, ranges, lengths) are
   removed from what is sent and enforced locally instead.
2. **Spelled-out schemas.** A model without a JSON mode gets the schema in its instructions.
3. **Extraction.** The JSON is found inside prose and code fences; trailing commas are tolerated.
4. **Repair without guessing.** A menu choice in other letter case or with spaces for underscores
   (“Blur Background” → `blur_background`), a number written as text, a missing optional field and a
   list that is too long are fixed. A choice that is not on the menu is not guessed.
5. **Asking again.** Anything that cannot be repaired is listed back to the model (“answer.edits[0].
   action must be one of the menu values, not "sharpen it"”), up to three times.
6. **Engine guards.** Whatever still slips through meets the edit language's own guards: an unknown
   pipeline becomes `other`, a number that is not in the request is dropped, direction words in the
   request override the model, and every sentence no edit covers is reported as “Not understood”.

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
effect. Only then does the checker model review the result, and its verdicts are labelled fallible.

## Evaluation

- `tests/test_pipelines.py`: every pipeline builds on a sample document; every workflow expands into
  registered procedures; framing pipelines ask for their subject; the contract repairs and rejects as
  described; adapters send images and schemas in each provider's format.
- `scripts/planner_bench.py`: 175 requests a working editor gets (the original 138 plus 37 that only the
  new workflows and techniques answer), run through the real planner with the local Qwen3.5-9B model.
- Real-engine runs of the new pipelines on the bench photos, judged by before/after sheets and the
  measured checks.

| Measurement (2026-10-12, local Qwen3.5-9B, RTX 4060 8 GB) | Result |
|---|---|
| The original 138 plans recompiled through the pipeline registry | 138/138 send exactly the same engine commands as before the refactor |
| Benchmark, first live run with the 115-pipeline menu | 155/175 |
| … after the fit check with re-asking, workflow coverage and positions from words | 175/175 (portrait 21/21, colour 18/18, workflows 23/23, techniques 14/14) |
| New pipelines and workflows run in PhotoCraft | 22 of 22 run; every measured check passes after the fixes in the table above |
| Unit and integration tests | `tests/test_pipelines.py` plus the existing PhotoCraft, API and desktop suites |

The 20 first-run misses: 7 were the model choosing a newer, more specific pipeline (“teal and orange
grade” → `split_tone`, “too dark” → `exposure_fix`), so those expectations were widened; 6 were a bug
(a workflow's parts did not count as covering the person's sentence, so it was reported “Not
understood”); 4 were wrong choices now caught by the fit check and re-asked (a darker beard as a
shadow tint, turquoise water and vivid sunset colours as colour splash, god rays as a light leak);
2 were pipelines that did not declare what to find (the eyes for an eye colour, the subject for a
composition crop; the composition case also moved to a photo whose subject is small enough to
recompose); and 1 was a position the model left out (“move the yellow mug to the left”).
