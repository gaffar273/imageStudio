# PhotoCraft assistant: how a sentence becomes a layered edit

The PhotoCraft studio turns a plain-language request such as

> Crop to a 4:5 portrait keeping the cat in frame, make the cat's fur slightly warmer, blur the
> background a bit, add the title 'Home Sweet Home' at the bottom in white, and increase vibrance by 12.
> Keep the dog unchanged.

into a PhotoCraft document where every change is its own named, masked, editable layer, then measures
the result against each part of the request.

## Why not let the model write commands?

The first integration asked the 9B vision model (Qwen3.5-9B, local) to write PhotoCraft commands and
their parameters directly. It understood requests well but wrote numbers badly. For example, "crop to a
centered square" on a 1012×813 photo became a 1024×1024 crop at x=12, leaving a black band. The new
design splits the work:

| Job | Who does it | Why |
|---|---|---|
| Understand the request and split it into edits | Vision model, constrained to a JSON schema of enums | Models are good at language and judgement |
| Find named things ("the red mug", "her shirt") | Vision model gives boxes on its trained 0–1000 grid; PhotoCraft's Object Selection outlines them | Grounding is a trained skill; outlines need pixels |
| Every number sent to the engine | Deterministic Python (`photocraft_intents.py`) | Crops, rotations, text placement and colour maths must be exact |
| Things only knowable while running (new layer IDs, rendered text width) | `studio.*` steps that inspect the live document (`photocraft_macros.py`) | IDs change when layers convert; fonts render at unknown widths |
| Did it work? | Pixel measurements first, the vision model's review second | The model said "done" for a mug that was still grey |

## The edit language

The planner fills one record per requested change. Every field is a choice from a menu, except the
person's exact words:

```json
{"quote": "make the red mug green", "action": "recolor", "target": "object", "object": "the red mug",
 "direction": "none", "strength": "moderate", "value": null, "text": "", "color": "green",
 "position": "", "size": "", "aspect": "", "choice": ""}
```

There are about 60 actions: geometry, raw development, adjustment layers, looks, filters, cut-outs,
text and graphics, layer housekeeping, `other` (any registry command, with settings checked against
its spec) and `generate` (new content painted by FLUX.1 Kontext). The guards are:

- **Numbers.** A `value` is kept only if that number appears in the request. Otherwise the strength
  word decides ("slightly" is subtle, "very" is strong).
- **Words.** Title text is restored to the person's exact quoted words and letter case.
- **Directions.** Words in the request override the model ("deepen the blues" means more saturation).
- **Coverage.** Any sentence of the request that no edit or keep-note accounts for is reported as
  "Not understood", never silently dropped.
- **Layer edits.** Layer actions are only accepted when the request talks about layers. Otherwise the
  clause becomes a keep-unchanged note.

## Compiling

`Compiler` orders edits the way a retoucher works: layer changes, pixel retouching, raw development,
AI layers, adjustments, effects and cut-outs while every object is still whole in the frame, then
geometry, then text and graphics on the final canvas, where colour changes cannot tint them. Masks are
cropped along with their layers. Selecting first matters: when a square crop ran first, it left half a
shirt in the frame, and Object Selection picked the wrong piece. Boxes are kept in original coordinates
for the plan overlay, and they are moved through every crop, rotation, resize and border for the measured
checks. An object that ends up outside the final crop is reported.

Two safety rules came from real failures:

- Every object selection is followed by a check that something was selected. An empty selection would
  otherwise let an adjustment hit the whole picture, as happened when a recolour turned a whole portrait blue.
- Objects removed earlier in a plan no longer count as foreground, so "remove the mug, make the background
  black and white" leaves no coloured patch where the mug was.

- Crops: the largest rectangle of the asked shape, centred on what must stay in frame.
- Straightening: the largest same-shaped rectangle inside the rotated picture (no black corners).
- Raw development: all global Camera Raw requests merge into one editable smart filter on the photo.
- Local edits: an adjustment layer whose mask is the selection, or a masked copy of the photo that carries
  the filter, so the original stays untouched.
- Text: created, measured, shrunk if it does not fit inside 5% margins, moved so its measured box sits
  exactly at the asked position, coloured for readability (with a soft shadow on busy backgrounds) when
  no colour was named.
- Removal: small blemishes use PhotoCraft's content-aware fill. Objects of 1.5% of the frame or more are
  rebuilt by Kontext and pasted back as a masked layer. The step measures whether the area now blends
  with its surroundings. On the first try Kontext painted a yellow mug where the blue one had been, so
  the step retries with a prompt that describes the empty background and keeps the better attempt.
- Colour ranges ("deepen the blues"): Hue/Saturation's own per-colour ranges, with blues including
  cyans. A selected "blues" range missed a turquoise sea completely (measured 0.383 → 0.383).

## Checking

After applying, the workspace records:

1. **Measured checks**: aspect ratio, exact size, the text layer reads exactly the asked words and sits
   in the asked ninth of the frame, the recoloured object's hue, the share of the background without
   colour, the direction of brightness, warmth and saturation changes, and the backdrop colour.
2. **AI visual review**: the model compares before and after for each requirement and each "keep
   unchanged" note. Conflicts show up, such as a crop that removes the dog the person asked to keep.

Failed batches never advance history. Every revision keeps its native `.pcraft` file, and the workspace
can jump to any revision.

## The interface

The studio is a full-height editor with a tool rail. Every panel speaks the same edit language as the
planner, so a slider and a sentence go through the same compiler.

- **Assistant**: plan cards with the person's words, what will happen, found objects outlined on the canvas,
  keep-notes, open questions, "apply the understood parts", and the result check.
- **Adjust**: light, colour, presence and detail sliders, applied to the whole image, the subject, the background or the sky.
- **Looks**: graded looks, black and white, toned, sepia and duotone.
- **Crop**: shapes kept on the centre, the subject or a named object; rotate, flip, straighten, resize, border.
- **Select**: cut-out on a colour or transparency, background blur, object removal and recolouring, AI-painted layers.
- **Text**: installed fonts, sizes or exact points, position grid, readable colour, bold, italic, shadow, outline, glow.
- **Filters** and **All tools**: real controls generated from each command's parameter specification for
  all 858 registry commands (`photocraft_specs.py`).
- **Inspector**: layers with visibility, opacity, blend mode, rename, delete and smart-filter toggles, plus clickable history.

## Evaluation

`tests/test_photocraft_intents.py` (31 tests) covers the guards, the geometry, the ordering, the safety
rules, the measurements and a real headless-engine run. `frontend/tests/photocraft-studio.spec.ts` checks
the interface. These end-to-end requests ran through the live API with the local planner on an RTX 4060
Laptop GPU (8 GB). Each row is the final run, after the fixes its earlier runs prompted.

| Request | Final result | What earlier runs exposed |
|---|---|---|
| 4:5 crop keeping the cat, warmer fur, background blur, exact title, vibrance +12, keep the dog | All measured checks pass; the review flags that a 4:5 crop around the cat cannot keep the dog | Main subject boxed both animals; the crop ignored “keeping the cat in frame” |
| Recolor the red mug green, remove the second mug from the right, background black and white, mugs keep colour | Hue 130° against green's 131°, area matches its surroundings, background 100% without colour | The review said “done” for a mug left grey; Kontext painted a yellow mug instead of removing; the removed mug's spot stayed coloured |
| Square crop centred on her face, shirt light blue | 1024×1024; the visible shirt measures 223° against light blue's 224° | An empty selection turned the whole portrait blue; the shirt measurement first sampled skin |
| Deeper sea blues, add a small white sailboat, “Amalfi” bottom right | Blues saturation measured higher; sailboat painted by AI, only changed pixels kept | A selected “blues” range missed a turquoise sea; “add” without a reference object was blocked |
| Cut out the puppy onto pastel pink, “Adopt Me” bottom centre, navy, 64 pt | Backdrop measured as exactly the asked colour | “Pastel pink” first came out white |
| Dramatic sunset sky, brighten the friends a little, 16:9, bold white serif title with shadow, faces natural | Sky deeper with no halo; an invented 32 pt text size was refused | PhotoCraft's sky selection left a halo around people; the generic dramatic look greyed a sunset |
| Noise reduction, sharpen the sign, exposure +0.5 EV, resize to 1080×1350 | All applied; cropped to 4:5 first so nothing stretches | — |

The AI visual review was wrong several times in these runs, in both directions. It called a grey mug
green and claimed a sailboat that was never painted, and it repeatedly said a square crop was still a
portrait. The interface labels it as fallible and lists the measured checks first.

Known limits: the planner is a 9B model running locally, so very long or unusual requests may be split
imperfectly. The plan review is there so a person can see what was understood before anything changes.
A planner pass takes 10–30 s, and Kontext edits take two to six minutes on an 8 GB GPU.
